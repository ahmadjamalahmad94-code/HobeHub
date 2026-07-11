"""
ApiV1RadiusClient — عميل RADIUS يتحدث بروتوكول radius-module الحديث (/api/v1).

على خلاف ``LiveRadiusClient`` (الذي يخاطب الـ API القديم ``{base}/app_ad2/<method>``
بترويسات ``X-Api-Key + adv_auth_ad`` وردود متعدّدة الأشكال)، هذا العميل يخاطب
واجهة REST الحديثة في radius-module:

    Base URL : http://HOST/api/v1
    Auth     : إمّا مفتاح API عبر ``Authorization: Bearer <token>`` (+ ``X-API-Key``)
               وإمّا اعتماد أدمن عبر HTTP Basic (يوزر/باس). يختار المالك أحدهما من
               صفحة الإعدادات: إن مُلئ «مفتاح الربط» يُستخدم كتوكن Bearer، وإلّا
               يُستخدم «اسم مستخدم/كلمة مرور الخدمة» كاعتماد Basic.
    Envelope : كل رد بالشكل {"ok": bool, "data": {...}, "error": {code,message,...}}.

تُبقي هذه الطبقة **نفس أشكال الإرجاع** التي يتوقّعها بقيّة التطبيق من
``LiveRadiusClient`` (قوائم/قواميس عاديّة لا DTOs مجمّدة) كي تكون بديلًا حرفيًّا
دون كسر أي مستهلك (radius_match / subscriber_radius_status / card_status /
radius_dashboard / صفحة اختبار الـ API). فقط البروتوكول تحته اختلف.

الأعلام (read_enabled / write_enabled) و verify_ssl تُقرأ من نفس مُحلِّل الاتصال
(radius_config) المستخدَم للعميل القديم، فالتبديل يتم من /admin/radius/settings
بلا إعادة نشر.
"""
from __future__ import annotations

from typing import Any

from .base import RadiusClient, RadiusClientError, RadiusClientNotImplemented
from .dtos import Result
from ..radius_config import resolve_radius_connection


_REQUEST_TIMEOUT = 15


# ─── helpers (تطبيع مستقل، دفاعي مع تعدّد أسماء الحقول) ────────────────────
def _int_or_zero(value: Any) -> int:
    try:
        return int(float(value if value not in (None, "") else 0))
    except (TypeError, ValueError):
        return 0


def _ident(value: Any) -> str:
    """يستخرج المُعرِّف (اسم المستخدم غالبًا) من نص أو قاموس.

    مسارات الـ API الحديثة للحسابات مفهرسة بـ **اسم المستخدم**، بينما توقيع
    ABC يمرّر ``user_external_id``. بعض المستدعين القدامى يمرّرون قاموسًا
    ({"username": ...}). نطبّع الحالتين لاسم مستخدم نصّي."""
    if isinstance(value, dict):
        for k in ("username", "user", "login", "user_id", "id", "external_id"):
            v = value.get(k)
            if v not in (None, ""):
                return str(v).strip()
        return ""
    return str(value or "").strip()


def _as_bool(value: Any) -> bool:
    token = str(value).strip().lower()
    return token in ("1", "true", "yes", "on", "active", "enabled", "t")


def _pick(raw: dict, *keys: str) -> str:
    for k in keys:
        v = raw.get(k)
        if v not in (None, ""):
            return str(v).strip()
    return ""


def _normalize_profile(raw: dict) -> dict:
    """يوحّد خطّة/باقة قادمة من /api/v1/profiles إلى قاموس بمفاتيح تطابق
    الـ Profile DTO **مع** إبقاء الحقول الأصلية للمستهلكين المتساهلين."""
    speed_down = _int_or_zero(raw.get("speed_down_kbps"))
    speed_up = _int_or_zero(raw.get("speed_up_kbps"))
    duration_min = _int_or_zero(raw.get("duration_minutes"))
    quota_mb = _int_or_zero(
        raw.get("quota_total_mb")
        if raw.get("quota_total_mb") not in (None, "")
        else raw.get("monthly_combined_quota_mb")
    )
    ext = _pick(raw, "id", "profile_id", "code") or ""
    out = dict(raw)  # إبقاء كل شيء
    out.update({
        "external_id": ext,
        "id": raw.get("id"),
        "profile_id": raw.get("id"),
        "name": _pick(raw, "name", "code") or ext,
        "speed_up_kbps": speed_up,
        "speed_down_kbps": speed_down,
        "duration_minutes": duration_min,
        "quota_mb": quota_mb,
    })
    return out


def _profile_to_offer(p: dict) -> dict:
    """يحوّل خطّة مطبّعة إلى شكل «عرض» للـ marketplace
    (external_id/name/duration_label/speed/price/active)."""
    down = _int_or_zero(p.get("speed_down_kbps"))
    up = _int_or_zero(p.get("speed_up_kbps"))
    speed = ""
    if down or up:
        speed = f"{down or '?'}/{up or '?'} Kbps"
    mins = _int_or_zero(p.get("duration_minutes"))
    duration_label = f"{mins} دقيقة" if mins else ""
    price = _pick(p, "price", "price_card", "price_bulk")
    enabled = p.get("enabled")
    active = _as_bool(enabled) if enabled is not None else True
    return {
        "external_id": str(p.get("external_id") or p.get("id") or ""),
        "name": p.get("name") or str(p.get("external_id") or ""),
        "duration_label": duration_label,
        "speed": speed,
        "price": price,
        "active": active,
    }


def _normalize_session(raw: dict) -> dict:
    """يوحّد جلسة قادمة من /api/v1/sessions/online كي تجد فيها طبقات الحالة
    مفاتيحها المتوقّعة (running_seconds/framed_ip/calling_station_id...)."""
    out = dict(raw)
    running = _int_or_zero(
        raw.get("session_time")
        if raw.get("session_time") not in (None, "")
        else raw.get("running_seconds")
    )
    framed = _pick(raw, "framed_ip", "framed_ip_address", "framedipaddress")
    mac = _pick(raw, "calling_station_id", "mac_address", "mac")
    nas = _pick(raw, "nas_ip_address", "nas_address", "nas_ip")
    out.setdefault("username", raw.get("username") or "")
    out["running_seconds"] = running
    out["framed_ip"] = framed
    out["framedipaddress"] = framed
    out["calling_station_id"] = mac
    out["mac"] = mac
    out["nas_ip"] = nas
    out["session_id"] = _pick(raw, "session_id", "acctsessionid") or out.get("session_id", "")
    return out


def _normalize_usage(username: str, data: dict) -> dict:
    """يوحّد رد /api/v1/accounts/<u>/usage إلى قاموس بمفاتيح يفهمها
    ``subscriber_radius_status`` (total_seconds/total_bytes_*/last_seen_at)
    مع إبقاء المفاتيح الأصلية."""
    used_seconds = _int_or_zero(data.get("used_seconds"))
    bytes_in = _int_or_zero(data.get("used_bytes_in"))
    bytes_out = _int_or_zero(data.get("used_bytes_out"))
    last_seen = data.get("last_seen_at")
    out = dict(data)
    out.update({
        "username": data.get("username") or username,
        "total_seconds": used_seconds,
        "used_seconds": used_seconds,
        "total_bytes_in": bytes_in,
        "bytes_in": bytes_in,
        "total_bytes_out": bytes_out,
        "bytes_out": bytes_out,
        "last_session_at": last_seen,
        "last_seen_at": last_seen,
    })
    return out


class ApiV1RadiusClient(RadiusClient):
    """عميل يخاطب radius-module عبر /api/v1. بديل حرفي لـ LiveRadiusClient."""

    def __init__(self, cfg: Any = None):
        # cfg قابل للحقن في الاختبارات؛ وإلّا يُحلّ من قاعدة البيانات/البيئة.
        cfg = cfg or resolve_radius_connection()
        self.base_url = (getattr(cfg, "base_url", "") or "").rstrip("/")
        self.master_key = getattr(cfg, "master_key", "") or ""
        self.username = getattr(cfg, "service_username", "") or ""
        self.password = getattr(cfg, "service_password", "") or ""
        self.verify_ssl = bool(getattr(cfg, "verify_ssl", True))
        self._read_enabled = bool(getattr(cfg, "read_enabled", False))
        self._write_enabled = bool(getattr(cfg, "write_enabled", False))

    @property
    def mode(self) -> str:
        return "live"

    # ─── الحُرّاس ─────────────────────────────────────────────────────────
    def _guard_read(self):
        if not self._read_enabled:
            raise RadiusClientNotImplemented(
                "🚧 قراءة RADIUS API غير مفعّلة. فعّل «تفعيل القراءة» في الإعدادات."
            )

    def _guard_write(self):
        if not self._read_enabled:
            raise RadiusClientNotImplemented("🚧 RADIUS API غير مفعّل.")
        if not self._write_enabled:
            raise RadiusClientNotImplemented(
                "🚧 عمليات الكتابة على RADIUS ما زالت موقوفة. "
                "فعّل «تفعيل الكتابة» في الإعدادات بعد اختبار كامل."
            )

    # ─── طبقة HTTP ───────────────────────────────────────────────────────
    def _url(self, path: str) -> str:
        if not self.base_url:
            raise RadiusClientError("RADIUS API Base URL غير محدّد.")
        return f"{self.base_url}/{path.lstrip('/')}"

    def _headers(self, *, auth: bool = True) -> dict:
        h = {"Accept": "application/json"}
        if auth and self.master_key:
            h["Authorization"] = f"Bearer {self.master_key}"
            h["X-API-Key"] = self.master_key
        return h

    def _basic_auth(self, *, auth: bool = True):
        """يُرجع (user, pass) لاعتماد Basic حين لا يوجد مفتاح API — وإلّا None."""
        if auth and not self.master_key and self.username and self.password:
            return (self.username, self.password)
        return None

    def _request(self, method: str, path: str, *, params: dict | None = None,
                 json_body: dict | None = None, auth: bool = True) -> dict:
        """طلب عام يُرجع دائمًا قاموسًا. عند خطأ النقل يضع __transport_error__."""
        try:
            import requests
        except ImportError:
            return {"__transport_error__": "مكتبة requests غير مثبتة", "ok": False}
        try:
            url = self._url(path)
        except RadiusClientError as exc:
            return {"__transport_error__": str(exc), "ok": False}
        try:
            r = requests.request(
                method.upper(), url,
                params=params or None,
                json=json_body if json_body is not None else None,
                headers=self._headers(auth=auth),
                auth=self._basic_auth(auth=auth),
                timeout=_REQUEST_TIMEOUT,
                verify=self.verify_ssl,
            )
        except Exception as exc:  # noqa: BLE001 — أي خطأ نقل = فشل ناعم
            return {"__transport_error__": str(exc), "__url__": url, "ok": False}

        out: dict = {"__http_status__": r.status_code, "__url__": url}
        try:
            body = r.json()
        except ValueError:
            out["__raw__"] = (r.text or "")[:500]
            out["ok"] = False
            out["__error_message__"] = "الرد ليس JSON صالحًا"
            return out
        if isinstance(body, dict):
            out.update(body)
        else:
            out["ok"] = False
            out["__error_message__"] = "شكل رد غير متوقّع"
        return out

    @staticmethod
    def _envelope(body: dict) -> tuple[bool, Any, str]:
        """يفكّك مغلّف ok/fail. يُرجع (ok, data, error_message)."""
        if body.get("__transport_error__"):
            return False, None, str(body.get("__transport_error__"))
        if body.get("ok") is True:
            return True, body.get("data", {}), ""
        err = ""
        e = body.get("error")
        if isinstance(e, dict):
            err = str(e.get("message") or e.get("code") or "")
        err = err or body.get("__error_message__") or f"HTTP {body.get('__http_status__')}"
        return False, body.get("data"), err

    def _get_data(self, path: str, *, params: dict | None = None, auth: bool = True):
        body = self._request("GET", path, params=params, auth=auth)
        return self._envelope(body)

    # ═══════════════════════════════════════════════════════════════════
    # الصحّة / الاتصال
    # ═══════════════════════════════════════════════════════════════════
    def ping(self) -> dict:
        """اختبار اتصال آمن بلا auth عبر /health — يخدم زر «اختبار الاتصال»."""
        if not self.base_url:
            return {"ok": False, "mode": "live", "error": "Base URL غير محدّد."}
        ok, data, err = self._get_data("health", auth=False)
        if not ok:
            return {"ok": False, "mode": "live", "error": err or "تعذّر الاتصال"}
        return {"ok": True, "mode": "live", "data": data or {}}

    def health_check(self) -> dict:
        ok, data, err = self._get_data("health", auth=False)
        if not ok:
            return {"ok": False, "mode": "live", "error": err or "تعذّر الاتصال"}
        d = data or {}
        # توحيد مفتاح النسخة كي يلتقطه العرض (release → version).
        if "version" not in d and d.get("release"):
            d = {**d, "version": d.get("release")}
        return {"ok": True, "mode": "live", "data": d}

    def get_server_status(self) -> dict:
        try:
            self._guard_read()
        except RadiusClientNotImplemented as exc:
            return {"ok": False, "error": str(exc)}
        ok, data, err = self._get_data("version")
        if not ok:
            return {"ok": False, "error": err}
        return {"ok": True, "data": data or {}}

    def get_my_permissions(self) -> dict:
        """المكافئ الحديث لـ «صلاحياتي» في /api/v1 هو عقد منح المزوّد
        (GET /api/v1/provider/grants): يتطلّب مصادقة صحيحة ويُرجع الترخيص +
        الخدمات + السقوف. نجاحه دليلٌ مباشر أنّ الربط والمصادقة (مفتاح API
        أو اعتماد اليوزر/الباس) سليمان — وهو المقصود من اختبار «تسجيل الدخول
        وقراءة الصلاحيات»."""
        try:
            self._guard_read()
        except RadiusClientNotImplemented as exc:
            return {"ok": False, "error": str(exc)}
        ok, data, err = self._get_data("provider/grants")
        if not ok:
            return {"ok": False, "error": err or "تعذّرت قراءة الصلاحيات."}
        return {"ok": True, "data": data or {}}

    def get_my_balance(self) -> dict:
        # لا مفهوم «رصيد» لحساب الأدمن في /api/v1 (الرصيد مفهوم لوحة HobeHub
        # نفسها، لا طبقة الأدمن في الراديوس). تدهور ناعم صريح بلا انهيار.
        return {"ok": False, "error": "غير متاح في /api/v1 (لا نقطة رصيد مكافئة)."}

    # ═══════════════════════════════════════════════════════════════════
    # مؤشّرات اللوحة (KPIs) — تُبنى من نقاط /api/v1 المتاحة
    # ═══════════════════════════════════════════════════════════════════
    def quick_stats(self) -> dict:
        """KPIs لحظية: المتصلون الآن + عدد الباقات.

        لا نقطة «إحصاء واحدة» مكافئة في الـ API الحديث، فنبنيها من نقاط
        القراءة المتاحة (sessions/online + profiles). تُستدعى في «الاختبار
        الكامل»؛ غيابها سابقًا كان يرمي AttributeError = صفحة 500."""
        try:
            self._guard_read()
        except RadiusClientNotImplemented as exc:
            return {"ok": False, "error": str(exc)}
        online = self.get_online_users()
        profiles = self.get_profiles()
        total = self._accounts_total()
        return {
            "ok": True,
            "data": {
                "online_now": len(online),
                "online_users": len(online),        # اسم قديم يقرأه قالب اللوحة
                "profiles_count": len(profiles),
                "total_users": total,               # إجمالي المشتركين (None لو تعذّر)
            },
        }

    def _accounts_total(self):
        """إجمالي حسابات المشتركين (best-effort) من ميتا /api/v1/accounts.
        يُرجع int أو None بلا رمي — لملء بطاقة «مستخدمو RADIUS» بقيمة حيّة."""
        try:
            body = self._request("GET", "accounts", params={"limit": 1, "offset": 0})
        except Exception:  # noqa: BLE001
            return None
        if not isinstance(body, dict):
            return None
        for container in (body.get("meta"), body.get("data"), body):
            if isinstance(container, dict):
                for k in ("total", "count", "total_count"):
                    v = container.get(k)
                    if isinstance(v, (int, float)):
                        return int(v)
        return None

    def get_dashboard_metrics(self) -> dict:
        """مقاييس اللوحة الحديثة: المتصلون الآن + الباقات + أعلام التشغيل.

        بديلٌ حرفيٌّ لدالّة العميل القديم كي لا يرمي «الاختبار الكامل» أو
        اختبار «مؤشرات اللوحة» AttributeError (=500)."""
        try:
            self._guard_read()
        except RadiusClientNotImplemented as exc:
            return {"ok": False, "error": str(exc)}
        online = self.get_online_users()
        profiles = self.get_profiles()
        total = self._accounts_total()
        return {
            "ok": True,
            "data": {
                "online_now": len(online),
                "online_users": len(online),
                "profiles_count": len(profiles),
                "total_users": total,
                "read_enabled": self._read_enabled,
                "write_enabled": self._write_enabled,
                "mode": self.mode,
            },
        }

    # ═══════════════════════════════════════════════════════════════════
    # إجراءات/قراءات إضافية تستغلّ نقاط /api/v1 غير المستعملة سابقًا
    # ═══════════════════════════════════════════════════════════════════
    def disable_account(self, user_external_id: Any, *, requested_by: str = "") -> Result:
        """تعطيل مباشر عبر POST /accounts/<u>/disable (أنظف من PATCH status)."""
        self._guard_write()
        uname = _ident(user_external_id)
        if not uname:
            return Result.failure("اسم المستخدم مطلوب.")
        resp = self._request("POST", f"accounts/{uname}/disable", json_body={})
        ok, _data, err = self._envelope(resp)
        if not ok:
            return Result.failure(err or "تعذّر تعطيل المشترك.")
        return Result.success("تم تعطيل المشترك.", username=uname,
                              api_endpoint=f"/api/v1/accounts/{uname}/disable")

    def enable_account(self, user_external_id: Any, *, requested_by: str = "") -> Result:
        """تفعيل مباشر عبر POST /accounts/<u>/enable."""
        self._guard_write()
        uname = _ident(user_external_id)
        if not uname:
            return Result.failure("اسم المستخدم مطلوب.")
        resp = self._request("POST", f"accounts/{uname}/enable", json_body={})
        ok, _data, err = self._envelope(resp)
        if not ok:
            return Result.failure(err or "تعذّر تفعيل المشترك.")
        return Result.success("تم تفعيل المشترك.", username=uname,
                              api_endpoint=f"/api/v1/accounts/{uname}/enable")

    def get_account_360(self, user_external_id: Any) -> dict | None:
        """لقطة 360 لمشترك (هوية+استهلاك+جلسات) عبر GET /accounts/<u>/360."""
        try:
            self._guard_read()
        except RadiusClientNotImplemented:
            return None
        uname = _ident(user_external_id)
        if not uname:
            return None
        ok, data, _err = self._get_data(f"accounts/{uname}/360")
        return data if ok and isinstance(data, dict) else None

    def get_accounting_usage(self, user_external_id: Any, *, params: dict | None = None) -> dict | None:
        """سجل الاستهلاك التاريخيّ للمشترك عبر GET /accounting/usage/subscribers/<u>
        (بخلاف get_user_usage اللحظيّ) — لتقارير الاستهلاك الشهريّة الحقيقيّة."""
        try:
            self._guard_read()
        except RadiusClientNotImplemented:
            return None
        uname = _ident(user_external_id)
        if not uname:
            return None
        ok, data, _err = self._get_data(
            f"accounting/usage/subscribers/{uname}", params=params or None)
        return data if ok and isinstance(data, dict) else None

    def get_accounting_history(self, user_external_id: Any, *, limit: int = 20) -> list:
        """الجلسات المنتهية (تاريخ) عبر GET /api/v1/accounting?username=<u>."""
        try:
            self._guard_read()
        except RadiusClientNotImplemented:
            return []
        uname = _ident(user_external_id)
        if not uname:
            return []
        ok, data, _err = self._get_data(
            "accounting", params={"username": uname, "limit": int(limit or 20)})
        if not ok:
            return []
        items = (data or {}).get("items") if isinstance(data, dict) else data
        return items if isinstance(items, list) else []

    def get_nas_list(self) -> list:
        """قائمة الـNAS/الراوترات عبر GET /api/v1/nas — قواميس كما ترد."""
        try:
            self._guard_read()
        except RadiusClientNotImplemented:
            return []
        ok, data, _err = self._get_data("nas")
        if not ok:
            return []
        items = (data or {}).get("items") if isinstance(data, dict) else data
        return items if isinstance(items, list) else []

    def lock_session_mac(self, user_external_id: Any, *, mac: str = "",
                         session_id: str = "", requested_by: str = "") -> Result:
        """قفل جلسة المشترك على MAC الحاليّ عبر POST /sessions/lock-mac
        (منع مشاركة الحساب) — يستغلّ نقطة متاحة غير مستعملة."""
        self._guard_write()
        uname = _ident(user_external_id)
        if not uname:
            return Result.failure("اسم المستخدم مطلوب.")
        body: dict[str, Any] = {"username": uname}
        if mac:
            body["mac"] = str(mac).strip()
        if session_id:
            body["session_id"] = str(session_id).strip()
        resp = self._request("POST", "sessions/lock-mac", json_body=body)
        ok, _data, err = self._envelope(resp)
        if not ok:
            return Result.failure(err or "تعذّر قفل MAC.")
        return Result.success("تم قفل MAC للجلسة.", username=uname,
                              api_endpoint="/api/v1/sessions/lock-mac")

    def set_temp_speed(self, user_external_id: Any, *, down_kbps: int, up_kbps: int,
                       minutes: int = 60, session_id: str = "", requested_by: str = "") -> Result:
        """رفع سرعة مؤقّت عبر POST /sessions/temp-speed (يتطلّب جلسة نشطة)."""
        self._guard_write()
        uname = _ident(user_external_id)
        if not uname:
            return Result.failure("اسم المستخدم مطلوب.")
        body = {"username": uname, "down_kbps": _int_or_zero(down_kbps),
                "up_kbps": _int_or_zero(up_kbps),
                "duration_minutes": _int_or_zero(minutes) or 60}
        if session_id:
            body["session_id"] = str(session_id).strip()
        resp = self._request("POST", "sessions/temp-speed", json_body=body)
        ok, _data, err = self._envelope(resp)
        if not ok:
            return Result.failure(err or "تعذّر رفع السرعة المؤقّت.")
        return Result.success("تم رفع السرعة مؤقتًا.", username=uname,
                              api_endpoint="/api/v1/sessions/temp-speed")

    def cancel_temp_speed(self, user_external_id: Any, *, requested_by: str = "") -> Result:
        """إلغاء رفع السرعة المؤقّت عبر POST /sessions/temp-speed/cancel."""
        self._guard_write()
        uname = _ident(user_external_id)
        if not uname:
            return Result.failure("اسم المستخدم مطلوب.")
        resp = self._request("POST", "sessions/temp-speed/cancel",
                             json_body={"username": uname})
        ok, _data, err = self._envelope(resp)
        if not ok:
            return Result.failure(err or "تعذّر إلغاء رفع السرعة.")
        return Result.success("تم إلغاء رفع السرعة.", username=uname)

    # ═══════════════════════════════════════════════════════════════════
    # قراءات
    # ═══════════════════════════════════════════════════════════════════
    def search_users(self, query: str = "", limit: int = 50) -> dict:
        """بحث المشتركين (اسم/جوال/يوزر). يُرجع {"ok", "data": [قواميس]} كما
        يتوقّع محرّك المطابقة. فارغ = سرد كل المشتركين ضمن السقف."""
        try:
            self._guard_read()
        except RadiusClientNotImplemented as exc:
            return {"ok": False, "error": str(exc), "data": []}
        params = {"limit": int(limit or 50), "offset": 0}
        q = (query or "").strip()
        if q:
            params["search"] = q
        ok, data, err = self._get_data("accounts", params=params)
        if not ok:
            return {"ok": False, "error": err, "data": []}
        items = (data or {}).get("items") if isinstance(data, dict) else data
        return {"ok": True, "data": items if isinstance(items, list) else []}

    def get_online_users(self, *args, **kwargs) -> list:
        """قائمة الجلسات المتصلة الآن — قواميس مطبّعة."""
        try:
            self._guard_read()
        except RadiusClientNotImplemented:
            return []
        ok, data, _err = self._get_data("sessions/online")
        if not ok:
            return []
        items = (data or {}).get("items") if isinstance(data, dict) else data
        if not isinstance(items, list):
            return []
        return [_normalize_session(s) for s in items if isinstance(s, dict)]

    def get_profiles(self, *args, **kwargs) -> list:
        """قائمة الباقات/الخطط — قواميس مطبّعة بمفاتيح Profile DTO."""
        try:
            self._guard_read()
        except RadiusClientNotImplemented:
            return []
        ok, data, _err = self._get_data("profiles", params={"limit": 500, "offset": 0})
        if not ok:
            return []
        items = (data or {}).get("items") if isinstance(data, dict) else data
        if not isinstance(items, list):
            return []
        return [_normalize_profile(p) for p in items if isinstance(p, dict)]

    def list_offers(self) -> list:
        """عروض الـ marketplace القابلة للربط. مصدرها الخطط (plans) لأن توليد
        الكروت الحديث يحتاج ``plan_id`` = external_id للعرض."""
        try:
            profiles = self.get_profiles()
        except (RadiusClientError, RadiusClientNotImplemented):
            return []
        offers = []
        for p in profiles:
            offer = _profile_to_offer(p)
            if offer["external_id"]:
                offers.append(offer)
        return offers

    def get_marketplace_offers(self) -> list:
        """عروض السوق الإلكترونيّ المنشورة فقط (لا كل الباقات) عبر
        GET /api/v1/card-marketplace/packages. كل عرض يُشكَّل للربط مع
        ``external_id = plan_id`` كي يتوافق مع توليد البطاقات داخل العرض."""
        try:
            self._guard_read()
        except RadiusClientNotImplemented:
            return []
        ok, data, _err = self._get_data(
            "card-marketplace/packages", params={"active": "1", "limit": 500})
        if not ok:
            return []
        items = (data or {}).get("items") if isinstance(data, dict) else data
        if not isinstance(items, list):
            return []
        offers = []
        for p in items:
            if not isinstance(p, dict):
                continue
            plan_id = _pick(p, "plan_id", "planid")
            ext = str(plan_id or p.get("id") or "")
            if not ext:
                continue
            down = _int_or_zero(p.get("display_speed_down_kbps") or p.get("speed_down_kbps"))
            up = _int_or_zero(p.get("display_speed_up_kbps") or p.get("speed_up_kbps"))
            speed = f"{down or '?'}/{up or '?'} Kbps" if (down or up) else ""
            mins = _int_or_zero(p.get("display_duration_minutes") or p.get("duration_minutes"))
            duration_label = f"{mins} دقيقة" if mins else ""
            enabled = p.get("active")
            offers.append({
                "external_id": ext,  # = plan_id للتوليد داخل العرض
                "name": p.get("name") or p.get("plan_name") or ext,
                "duration_label": duration_label,
                "speed": speed,
                "price": _pick(p, "price", "price_card", "price_bulk"),
                "active": _as_bool(enabled) if enabled is not None else True,
            })
        return offers

    def get_user_usage(self, user_external_id: Any) -> dict | None:
        """ملخّص استخدام مشترك عبر /accounts/<username>/usage. قاموس أو None."""
        try:
            self._guard_read()
        except RadiusClientNotImplemented:
            return None
        username = _ident(user_external_id)
        if not username:
            return None
        ok, data, _err = self._get_data(f"accounts/{username}/usage")
        if not ok or not isinstance(data, dict):
            return None
        return _normalize_usage(username, data)

    def get_user_bandwidth(self, user_external_id: Any) -> dict | None:
        """أقرب مكافئ متاح في /api/v1 هو ملخّص الاستخدام (لا نقطة معدّل لحظي
        مستقلّة). تدهور ناعم: نُرجع نفس لقطة الاستخدام."""
        return self.get_user_usage(user_external_id)

    def get_user_sessions(self, user_external_id: Any) -> dict | None:
        """جلسات المستخدم المتصلة الآن (تصفية /sessions/online بالاسم).
        قراءة فقط تستخدمها طبقة حالة البطاقات. (تاريخ الجلسات المغلقة غير
        متاح عبر هذه النقطة — تدهور ناعم لِما هو متصل الآن)."""
        try:
            self._guard_read()
        except RadiusClientNotImplemented:
            return None
        username = _ident(user_external_id)
        if not username:
            return None
        ok, data, _err = self._get_data("sessions/online", params={"q": username})
        if not ok:
            return None
        items = (data or {}).get("items") if isinstance(data, dict) else data
        sessions = [_normalize_session(s) for s in items if isinstance(s, dict)] if isinstance(items, list) else []
        return {"ok": True, "data": sessions}

    # ═══════════════════════════════════════════════════════════════════
    # كتابة — البطاقات
    # ═══════════════════════════════════════════════════════════════════
    def generate_user_cards(self, category_code: str, count: int = 1, *,
                            radius_offer_external_id: str = "",
                            beneficiary_id: int | None = None,
                            requested_by: str = "", notes: str = "") -> Result:
        """يولّد كروتًا من خطّة/عرض عبر POST /api/v1/cards/generate.

        الـ ``radius_offer_external_id`` المربوط = ``plan_id`` في الـ API الحديث.
        عند النجاح يُرجع Result.success يحوي أول كرت (card_username/card_password/
        external_id) ليحفظه card_dispatcher ويسلّمه المشترك."""
        self._guard_write()
        plan_id_raw = str(radius_offer_external_id or "").strip()
        if not plan_id_raw.isdigit():
            return Result.failure(
                "توليد الكروت الحديث يتطلّب plan_id رقميًّا مربوطًا بالعرض. "
                "اربط العرض من صفحة «ربط العروض» بمعرّف خطّة صحيح."
            )
        body = {"plan_id": int(plan_id_raw), "count": int(count or 1)}
        if notes:
            body["notes"] = notes[:300]
        resp = self._request("POST", "cards/generate", json_body=body)
        ok, data, err = self._envelope(resp)
        if not ok:
            return Result.failure(err or "تعذّر توليد الكروت من RADIUS.")
        cards = (data or {}).get("cards") if isinstance(data, dict) else None
        first = cards[0] if isinstance(cards, list) and cards else None
        if not isinstance(first, dict) or not (first.get("username") and first.get("password")):
            return Result.failure("رد RADIUS لا يحتوي على بيانات كرت صالحة.")
        return Result.success(
            "تم توليد الكرت من RADIUS.",
            card_username=str(first.get("username")),
            card_password=str(first.get("password")),
            external_id=str(first.get("id") or ""),
            category_code=category_code,
            duration_minutes=_int_or_zero(first.get("duration_minutes")),
            api_endpoint="/api/v1/cards/generate",
        )

    def validate_card(self, username: str, password: str) -> Result:
        # لا نتحقّق من كلمة المرور عبر /api/v1 (لا نقطة تحقّق كرت بكلمة مرور
        # آمنة للأدمن) — تدهور ناعم؛ الوضع اليدوي يتحقّق محليًّا.
        self._guard_read()
        return Result.failure("التحقّق من الكرت غير مدعوم عبر /api/v1 من طبقة الأدمن.")

    def remove_user_card(self, card_external_id: str, *, requested_by: str = "") -> Result:
        """يُلغي كرتًا عبر POST /api/v1/cards/<id>/revoke (المعرّف رقميّ)."""
        self._guard_write()
        cid = str(card_external_id or "").strip()
        if not cid.isdigit():
            return Result.failure("إلغاء الكرت يتطلّب معرّف كرت رقميًّا (card_id).")
        resp = self._request("POST", f"cards/{int(cid)}/revoke", json_body={})
        ok, _data, err = self._envelope(resp)
        if not ok:
            return Result.failure(err or "تعذّر إلغاء الكرت.")
        return Result.success("تم إلغاء الكرت.", card_id=cid, api_endpoint=f"/api/v1/cards/{cid}/revoke")

    # ═══════════════════════════════════════════════════════════════════
    # كتابة — المشتركون
    # ═══════════════════════════════════════════════════════════════════
    def create_user(self, username: str, password: str, profile_id: str, *,
                    beneficiary_id: int | None = None, requested_by: str = "",
                    **opts: Any) -> Result:
        self._guard_write()
        uname = _ident(username)
        if not uname or not password:
            return Result.failure("username و password مطلوبان.")
        body: dict = {"username": uname, "password": str(password)}
        if str(profile_id or "").strip().isdigit():
            body["plan_id"] = int(profile_id)
        for k, v in (opts or {}).items():
            body.setdefault(k, v)
        resp = self._request("POST", "accounts", json_body=body)
        ok, data, err = self._envelope(resp)
        if not ok:
            return Result.failure(err or "تعذّر إنشاء المشترك.")
        extra = dict(data or {})
        extra.setdefault("username", uname)
        extra.setdefault("api_endpoint", "/api/v1/accounts")
        return Result.success("تم إنشاء المشترك.", **extra)

    def update_user(self, user_external_id: Any, *, beneficiary_id: int | None = None,
                    requested_by: str = "", **changes: Any) -> Result:
        self._guard_write()
        uname = _ident(user_external_id)
        if not uname:
            return Result.failure("اسم المستخدم مطلوب.")
        payload = {k: v for k, v in (changes or {}).items() if k != "username"}
        # profile_id → plan_id (توافق مع الحقل الحديث)
        if "profile_id" in payload and "plan_id" not in payload:
            pid = str(payload.pop("profile_id") or "").strip()
            if pid.isdigit():
                payload["plan_id"] = int(pid)
        if not payload:
            return Result.success("لا تغييرات.", username=uname)
        resp = self._request("PATCH", f"accounts/{uname}", json_body=payload)
        ok, data, err = self._envelope(resp)
        if not ok:
            return Result.failure(err or "تعذّر تحديث المشترك.")
        return Result.success("تم تحديث المشترك.", username=uname,
                              api_endpoint=f"/api/v1/accounts/{uname}")

    def reset_password(self, user_external_id: Any, new_password: str = "", *,
                       beneficiary_id: int | None = None, requested_by: str = "") -> Result:
        self._guard_write()
        uname = _ident(user_external_id)
        pw = str(new_password or "")
        if isinstance(user_external_id, dict) and not pw:
            pw = str(user_external_id.get("new_password") or user_external_id.get("password") or "")
        if not uname or not pw:
            return Result.failure("اسم المستخدم وكلمة المرور الجديدة مطلوبان.")
        resp = self._request("POST", f"accounts/{uname}/reset_password",
                             json_body={"new_password": pw})
        ok, _data, err = self._envelope(resp)
        if not ok:
            return Result.failure(err or "تعذّر إعادة تعيين كلمة المرور.")
        return Result.success("تم إعادة تعيين كلمة المرور.", username=uname,
                              api_endpoint=f"/api/v1/accounts/{uname}/reset_password")

    def add_time(self, user_external_id: Any, *, sel_time: int, add_time: int,
                 beneficiary_id: int | None = None, requested_by: str = "") -> Result:
        self._guard_write()
        uname = _ident(user_external_id)
        minutes = _int_or_zero(add_time)
        if not uname:
            return Result.failure("اسم المستخدم مطلوب.")
        if minutes <= 0:
            return Result.failure("عدد الدقائق يجب أن يكون أكبر من صفر.")
        resp = self._request("POST", f"accounts/{uname}/extend_time",
                             json_body={"minutes": minutes})
        ok, data, err = self._envelope(resp)
        if not ok:
            return Result.failure(err or "تعذّر تمديد الوقت.")
        return Result.success("تم تمديد الوقت.", username=uname,
                              api_endpoint=f"/api/v1/accounts/{uname}/extend_time",
                              **(data or {}))

    def add_quota_mb(self, user_external_id: Any, mb: int, *,
                     beneficiary_id: int | None = None, requested_by: str = "") -> Result:
        # لا توجد نقطة «إضافة كوتا تراكمية» في /api/v1 (PATCH يضبط قيمة مطلقة
        # لا يزيد عليها). تدهور ناعم برسالة واضحة بدل ضبط خاطئ.
        self._guard_write()
        return Result.failure(
            "إضافة كوتا تراكمية غير مدعومة مباشرة عبر /api/v1 "
            "(المتاح ضبط قيمة الكوتا المطلقة عبر تحديث المشترك)."
        )

    def disconnect(self, user_external_id: Any, *, beneficiary_id: int | None = None,
                   requested_by: str = "") -> Result:
        self._guard_write()
        uname = _ident(user_external_id)
        if not uname:
            return Result.failure("اسم المستخدم مطلوب.")
        body: dict = {"username": uname}
        if isinstance(user_external_id, dict) and user_external_id.get("session_id"):
            body["session_id"] = str(user_external_id.get("session_id"))
        resp = self._request("POST", "sessions/disconnect", json_body=body)
        ok, _data, err = self._envelope(resp)
        if not ok:
            return Result.failure(err or "تعذّر فصل الجلسة.")
        return Result.success("تم طلب فصل الجلسة.", username=uname,
                              api_endpoint="/api/v1/sessions/disconnect")

    def set_mac_lock(self, user_external_id: Any, mac: str = "", *, action: str = "set",
                     beneficiary_id: int | None = None, requested_by: str = "") -> Result:
        self._guard_write()
        uname = _ident(user_external_id)
        if not uname:
            return Result.failure("اسم المستخدم مطلوب.")
        clearing = str(action or "set").strip().lower() in ("clear", "unset", "remove", "unlock")
        value = "" if clearing else str(mac or "").strip()
        if not clearing and not value:
            return Result.failure("عنوان MAC مطلوب لتثبيته.")
        resp = self._request("PATCH", f"accounts/{uname}",
                             json_body={"mac_lock": value, "allowed_macs": value})
        ok, _data, err = self._envelope(resp)
        if not ok:
            return Result.failure(err or "تعذّر ضبط قفل MAC.")
        return Result.success(
            "تم تحرير قفل MAC." if clearing else "تم تثبيت MAC.",
            username=uname, mac=value, api_endpoint=f"/api/v1/accounts/{uname}",
        )

    # ═══════════════════════════════════════════════════════════════════
    # إعلانات
    # ═══════════════════════════════════════════════════════════════════
    def broadcast_sms(self, message: str, *, profile_filter_external_id: str = "",
                      requested_by: str = "") -> Result:
        # لا نقطة بثّ SMS بسيطة في /api/v1 من طبقة الأدمن — تدهور ناعم.
        self._guard_write()
        return Result.failure("بثّ SMS غير مدعوم عبر /api/v1 من هذه الطبقة.")

    # ═══════════════════════════════════════════════════════════════════
    # pending actions — مشتركة مع الوضع اليدوي (سجل محلّي)
    # ═══════════════════════════════════════════════════════════════════
    def list_pending_actions(self, *, action_type: str = "", status: str = "pending", limit: int = 50):
        from .manual import ManualRadiusClient
        return ManualRadiusClient().list_pending_actions(
            action_type=action_type, status=status, limit=limit)

    def mark_pending_done(self, action_id, *, executed_by: str = "", api_response=None, notes: str = ""):
        from .manual import ManualRadiusClient
        return ManualRadiusClient().mark_pending_done(
            action_id, executed_by=executed_by, api_response=api_response, notes=notes)

    def mark_pending_failed(self, action_id, *, error_message: str, executed_by: str = ""):
        from .manual import ManualRadiusClient
        return ManualRadiusClient().mark_pending_failed(
            action_id, error_message=error_message, executed_by=executed_by)

    def cancel_pending(self, action_id, *, executed_by: str = "", notes: str = ""):
        from .manual import ManualRadiusClient
        return ManualRadiusClient().cancel_pending(
            action_id, executed_by=executed_by, notes=notes)
