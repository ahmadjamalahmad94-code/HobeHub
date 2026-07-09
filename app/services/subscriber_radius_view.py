"""
subscriber_radius_view.py — يبني view-model نظيف للقراءات الحية من RADIUS
لصفحة المشترك (يوزر) الشخصية «/user/account».

كل عمليات الجلب والتحليل والتنسيق تتم هنا، والقالب يعرض النتيجة فقط
(التزامًا بالقاعدة المعمارية 9: لا business logic في القوالب).

المصادر (عبر RadiusClient فقط — لا اتصال مباشر بـ radius-module):
    - get_user_usage      → ملخص الاستخدام (جلسات/بايتات/ثوانٍ)
    - get_user_bandwidth  → استخدام لحظي / سرعة
    - get_user_sessions   → جلسات المستخدم
    - get_profiles        → لمطابقة سرعة الباقة (speed_up_kbps / speed_down_kbps)

الحقول المطلوبة والمتاح منها فعلًا من الـ API الحالي:
    ✅ متاح : العرض/الباقة، سرعة الرفع، سرعة التنزيل، الجلسات،
              كمية التحميل/الاستهلاك، مدة الاتصال.
    ⚠️ غير متاح حاليًا (لا ترجعها الـ DTOs الحالية — تظهر كـ «غير متاح حاليًا»):
              المدة اليومية، وقت الدوام (أيام/ساعات)، الساعات المسحوبة والمتبقية.
              تُقرأ دفاعيًا لو ظهرت في الرد الخام مستقبلًا، وإلا تبقى placeholder.
"""
from __future__ import annotations

from typing import Any

UNAVAILABLE_LABEL = "غير متاح حاليًا"


# ═══════════════════════════════════════════════════════════════════════
# دوال مساعدة نقية (stdlib فقط — لا تعتمد على تطبيق Flask، قابلة للاختبار معزولة)
# ═══════════════════════════════════════════════════════════════════════
def _first(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def _get(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return default


def _num(value: Any) -> float | None:
    """يرجع الرقم أو None (يفرّق بين 0 الحقيقي والغياب)."""
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _usage_data(payload: Any) -> dict:
    """يفكّ غلاف {ok, data:{...}} أو يرجع الـ dict كما هو."""
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, dict):
            return data
        return payload
    return {}


def _as_list(payload: Any) -> list:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("data", "sessions", "__list__", "rows"):
            val = payload.get(key)
            if isinstance(val, list):
                return val
    return []


def fmt_speed_kbps(kbps: Any) -> str:
    """kbps صحيح → «20 Mbps» أو «512 Kbps»."""
    k = _num(kbps)
    if k is None or k <= 0:
        return ""
    if k >= 1000:
        mbps = k / 1000.0
        return f"{mbps:g} Mbps"
    return f"{k:g} Kbps"


def fmt_speed_value(value: Any) -> str:
    """
    سرعة قد تصل كنص جاهز («20M»/«20 Mbps»/«20480/20480») أو كرقم kbps.
    - نص غير رقمي بحت → نثق به كما هو.
    - رقم بحت → نعامله كـ kbps وننسّقه.
    """
    if value in (None, ""):
        return ""
    text = str(value).strip()
    if not text:
        return ""
    # رقم بحت (kbps)
    if text.replace(".", "", 1).isdigit():
        return fmt_speed_kbps(text)
    return text


def fmt_bytes(total: Any) -> str:
    """بايتات → «1.5 GB» / «320 MB»."""
    total_i = max(_int(total), 0)
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(total_i)
    unit = units[0]
    for unit in units:
        if value < 1024 or unit == units[-1]:
            break
        value /= 1024
    if unit in {"B", "KB"}:
        return f"{value:.0f} {unit}"
    return f"{value:.1f} {unit}"


def fmt_duration_seconds(seconds: Any) -> str:
    """ثوانٍ → «3س 20د» (ساعات + دقائق)."""
    total = max(_int(seconds), 0)
    hours = total // 3600
    minutes = (total % 3600) // 60
    if hours and minutes:
        return f"{hours}س {minutes}د"
    if hours:
        return f"{hours}س"
    if minutes:
        return f"{minutes}د"
    return "أقل من دقيقة" if total > 0 else "0د"


def fmt_duration_minutes(minutes: Any) -> str:
    m = _num(minutes)
    if m is None:
        return ""
    return fmt_duration_seconds(int(m) * 60)


def _field(key: str, label: str, value: Any, *, icon: str = "") -> dict:
    """عنصر view-model واحد. value فارغ ⇒ غير متاح."""
    text = "" if value in (None, "") else str(value).strip()
    available = bool(text)
    return {
        "key": key,
        "label": label,
        "value": text if available else UNAVAILABLE_LABEL,
        "available": available,
        "icon": icon,
    }


# ═══════════════════════════════════════════════════════════════════════
# مطابقة الباقة لاستخراج السرعة (Profile.speed_up_kbps / speed_down_kbps)
# ═══════════════════════════════════════════════════════════════════════
def _match_profile(profiles: list, profile_id: Any, profile_name: Any) -> Any:
    pid = str(profile_id or "").strip()
    pname = str(profile_name or "").strip().lower()
    for prof in profiles or []:
        ext = str(_first(_get(prof, "external_id"), _get(prof, "id")) or "").strip()
        name = str(_get(prof, "name") or "").strip().lower()
        if pid and ext and pid == ext:
            return prof
        if pname and name and pname == name:
            return prof
    return None


# ═══════════════════════════════════════════════════════════════════════
# بناء الحقول من الحمولات المُحلَّلة (نقي — لا استدعاءات API)
# ═══════════════════════════════════════════════════════════════════════
def _build_fields(usage: dict, bandwidth: dict, sessions: list,
                  profile: Any, local: dict) -> list[dict]:
    usage = usage or {}
    bandwidth = bandwidth or {}
    local = local or {}
    blob = {**usage, **bandwidth}  # merge للبحث الدفاعي عن المفاتيح

    # ── العرض / الباقة ─────────────────────────────────────────────
    plan_name = _first(
        blob.get("profile_name"),
        blob.get("groupname"),
        _get(profile, "name"),
        local.get("current_profile_name"),
    )

    # ── سرعة الرفع / التنزيل ───────────────────────────────────────
    up_speed = fmt_speed_value(_first(
        blob.get("up_speed"), blob.get("upload_speed"), blob.get("speed_up")
    ))
    if not up_speed and profile is not None:
        up_speed = fmt_speed_kbps(_get(profile, "speed_up_kbps"))

    down_speed = fmt_speed_value(_first(
        blob.get("down_speed"), blob.get("download_speed"), blob.get("speed_down")
    ))
    if not down_speed and profile is not None:
        down_speed = fmt_speed_kbps(_get(profile, "speed_down_kbps"))

    # ── الجلسات ────────────────────────────────────────────────────
    sessions_count = _first(
        blob.get("total_sessions"), blob.get("session_count"),
        blob.get("num_sessions"), blob.get("sessions"),
    )
    if _num(sessions_count) is None and sessions:
        sessions_count = len(sessions)
    sessions_val = "" if _num(sessions_count) is None else str(_int(sessions_count))

    # ── كمية التحميل / الاستهلاك ───────────────────────────────────
    bytes_in = _num(_first(blob.get("total_bytes_in"), blob.get("bytes_in"), blob.get("download_bytes")))
    bytes_out = _num(_first(blob.get("total_bytes_out"), blob.get("bytes_out"), blob.get("upload_bytes")))
    if bytes_in is not None or bytes_out is not None:
        total_bytes = int(bytes_in or 0) + int(bytes_out or 0)
        consumption = fmt_bytes(total_bytes)
    else:
        alt = _num(_first(blob.get("val_usage_qouta"), blob.get("usage_bytes"), blob.get("total_usage")))
        consumption = fmt_bytes(alt) if alt is not None else ""

    # ── مدة الاتصال ────────────────────────────────────────────────
    total_seconds = _num(_first(
        blob.get("total_seconds"), blob.get("used_seconds"),
        blob.get("acctsessiontime"), blob.get("time_used_seconds"),
        blob.get("running_seconds"),
    ))
    conn_time = fmt_duration_seconds(total_seconds) if total_seconds is not None else ""

    # ── المدة اليومية (⚠️ غير موجودة في DTOs — دفاعي) ──────────────
    daily_raw = _first(
        blob.get("daily_limit_minutes"), blob.get("daily_quota_minutes"),
        blob.get("daily_minutes"), blob.get("daily_time_limit"),
    )
    daily_duration = fmt_duration_minutes(daily_raw) if _num(daily_raw) is not None else ""

    # ── وقت الدوام (أيام/ساعات) (⚠️ غير موجود في DTOs — دفاعي) ─────
    work_schedule = str(_first(
        blob.get("connection_schedule"), blob.get("work_schedule"),
        blob.get("schedule"),
    ) or "").strip()
    if not work_schedule:
        days = str(_first(blob.get("arr_days"), blob.get("active_days")) or "").strip()
        frm = str(_first(blob.get("limit_from"), blob.get("time_from")) or "").strip()
        to = str(_first(blob.get("limit_to"), blob.get("time_to")) or "").strip()
        parts = []
        if days:
            parts.append(f"أيام: {days}")
        if frm and to:
            parts.append(f"ساعات: {frm} - {to}")
        work_schedule = "، ".join(parts)

    # ── الساعات المسحوبة والمتبقية (⚠️ غير موجود في DTOs — دفاعي) ─
    hours_used = _num(_first(blob.get("hours_used"), blob.get("time_used_hours"), blob.get("used_hours")))
    hours_rem = _num(_first(blob.get("hours_remaining"), blob.get("time_remaining_hours"), blob.get("remaining_hours")))
    if hours_used is not None or hours_rem is not None:
        u = f"{hours_used:g}" if hours_used is not None else "؟"
        r = f"{hours_rem:g}" if hours_rem is not None else "؟"
        hours_used_remaining = f"مسحوب {u} س / متبقٍ {r} س"
    else:
        hours_used_remaining = ""

    return [
        _field("plan", "العرض/الباقة", plan_name, icon="fa-box"),
        _field("speed_down", "سرعة التنزيل", down_speed, icon="fa-arrow-down"),
        _field("speed_up", "سرعة الرفع", up_speed, icon="fa-arrow-up"),
        _field("sessions", "الجلسات", sessions_val, icon="fa-list-ol"),
        _field("consumption", "كمية التحميل/الاستهلاك", consumption, icon="fa-chart-simple"),
        _field("connection_time", "مدة الاتصال", conn_time, icon="fa-clock"),
        _field("daily_duration", "المدة اليومية", daily_duration, icon="fa-hourglass-half"),
        _field("work_schedule", "وقت الدوام (أيام وساعات)", work_schedule, icon="fa-calendar-week"),
        _field("hours_used_remaining", "الساعات المسحوبة والمتبقية", hours_used_remaining, icon="fa-battery-half"),
    ]


def _empty_view(state: str, state_label: str, message: str,
                username: str = "", external_id: str = "",
                local: dict | None = None) -> dict:
    """view-model آمن عند عدم توفر قراءة حية — يعرض placeholders دون تعطّل."""
    fields = _build_fields({}, {}, [], None, local or {})
    return {
        "state": state,
        "state_label": state_label,
        "is_live": False,
        "message": message,
        "username": username,
        "external_id": external_id,
        "fields": fields,
    }


# ═══════════════════════════════════════════════════════════════════════
# الواجهة العامة
# ═══════════════════════════════════════════════════════════════════════
def build_subscriber_radius_view(
    beneficiary_id: int,
    username: str = "",
    external_id: str = "",
    *,
    client: Any = None,
    local_account: dict | None = None,
    under_development: bool | None = None,
) -> dict:
    """
    يبني view-model القراءات الحية لمشترك اليوزر على صفحته الشخصية.

    المعاملات القابلة للحقن (client / local_account / under_development)
    موجودة للاختبار المعزول؛ في الإنتاج تُشتق من التطبيق تلقائيًا.

    يرجع dict فيه:
        state            : live | under_development | unlinked | no_data
        state_label      : وسم عربي جاهز للعرض
        is_live          : هل البيانات قراءة حية فعلية؟
        message          : رسالة توضيحية
        username / external_id
        fields           : قائمة حقول [{key,label,value,available,icon}]
    """
    beneficiary_id = _int(beneficiary_id)

    # ── حلّ الحساب المحلي والمعرّفات (lazy imports كي يبقى الملف قابلًا للاستيراد معزولًا) ──
    if local_account is None:
        try:
            from app import legacy
            local_account = legacy.query_one(
                "SELECT * FROM beneficiary_radius_accounts WHERE beneficiary_id=%s LIMIT 1",
                [beneficiary_id],
            ) or {}
        except Exception:
            local_account = {}
    local = local_account or {}

    radius_username = str(_first(
        username, local.get("external_username"), local.get("external_user_id")
    ) or "").strip()
    ext_id = str(_first(
        external_id, local.get("external_user_id"), local.get("current_profile_id") and None,
    ) or "").strip()
    if not ext_id:
        ext_id = radius_username

    # ── لا معرّف مرتبط → حالة «غير مرتبط» ──
    if not radius_username and not ext_id:
        return _empty_view(
            "unlinked", "غير مرتبط",
            "لا يوجد حساب RADIUS مرتبط بهذا المشترك بعد.",
            local=local,
        )

    # ── تحديد وضع التطوير / الإطفاء ──
    if under_development is None:
        try:
            from app.services.radius_client import is_api_under_development
            from app.services.radius_kill_switch import is_radius_offline
            under_development = bool(is_api_under_development() or is_radius_offline())
        except Exception:
            under_development = True

    if under_development:
        return _empty_view(
            "under_development", "قيد التطوير",
            "القراءة الحية من RADIUS قيد التطوير. تُعرض البيانات المتاحة محليًا فقط.",
            username=radius_username, external_id=ext_id, local=local,
        )

    # ── قراءات حية ──
    if client is None:
        try:
            from app.services.radius_client import get_radius_client
            client = get_radius_client()
        except Exception:
            return _empty_view(
                "under_development", "قيد التطوير",
                "تعذّر تهيئة عميل RADIUS.",
                username=radius_username, external_id=ext_id, local=local,
            )

    lookup = ext_id or radius_username

    def _safe(method_name: str, *args):
        method = getattr(client, method_name, None)
        if not callable(method):
            return None
        try:
            return method(*args)
        except Exception:
            return None

    usage = _usage_data(_safe("get_user_usage", lookup))
    bandwidth = _usage_data(_safe("get_user_bandwidth", lookup))
    sessions = _as_list(_safe("get_user_sessions", lookup))
    profiles = _safe("get_profiles")
    profiles = profiles if isinstance(profiles, list) else []

    profile = _match_profile(
        profiles,
        _first(usage.get("profile_id"), bandwidth.get("profile_id"), local.get("current_profile_id")),
        _first(usage.get("profile_name"), bandwidth.get("profile_name"), local.get("current_profile_name")),
    )

    fields = _build_fields(usage, bandwidth, sessions, profile, local)
    has_any = any(f["available"] for f in fields)

    return {
        "state": "live" if has_any else "no_data",
        "state_label": "قراءة حية" if has_any else "لا توجد بيانات",
        "is_live": True,
        "message": "" if has_any else "لم ترجع RADIUS بيانات لهذا المشترك بعد.",
        "username": radius_username,
        "external_id": ext_id,
        "fields": fields,
    }
