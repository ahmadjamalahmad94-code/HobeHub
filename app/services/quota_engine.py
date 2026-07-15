"""
quota_engine — يحدّد ما إذا كان مشترك يستحق بطاقة الآن.

القاعدة:
  1) ابحث عن أعلى أولوية من card_quota_policies تنطبق على المشترك:
       per-user  >  per-group  >  default
  2) تحقق من اليوم (allowed_days)، الفئة (allowed_category_codes)، النطاق الزمني.
  3) احسب البطاقات المُسلَّمة لهذا المشترك اليوم/الأسبوع من beneficiary_issued_cards.
  4) قارن مع daily_limit / weekly_limit.

الاستخدام:
    from app.services.quota_engine import check_quota, get_effective_policy

    decision = check_quota(beneficiary_id=42, category_code="one_hour")
    if decision.allowed:
        # نفّذ الإصدار
        ...
    else:
        flash(decision.reason)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from app import legacy


STANDARD_CARD_CATEGORY_CODES = ("half_hour", "one_hour", "two_hours", "three_hours")
SPECIAL_CARD_CATEGORY_CODES = ("four_hours",)
OFFICIAL_CARD_CATEGORY_CODES = STANDARD_CARD_CATEGORY_CODES + SPECIAL_CARD_CATEGORY_CODES
DEFAULT_ALLOWED_CATEGORY_CODES = ",".join(STANDARD_CARD_CATEGORY_CODES)


# أسماء الأيام بالأسبوع (يطابق Python's weekday(): 0=Mon...6=Sun)
_WEEKDAY_NAMES = {
    "mon": 0, "monday": 0, "الإثنين": 0, "اثنين": 0,
    "tue": 1, "tuesday": 1, "الثلاثاء": 1, "ثلاثاء": 1,
    "wed": 2, "wednesday": 2, "الأربعاء": 2, "اربعاء": 2,
    "thu": 3, "thursday": 3, "الخميس": 3, "خميس": 3,
    "fri": 4, "friday": 4, "الجمعة": 4, "جمعة": 4,
    "sat": 5, "saturday": 5, "السبت": 5, "سبت": 5,
    "sun": 6, "sunday": 6, "الأحد": 6, "احد": 6,
}


@dataclass
class QuotaDecision:
    """قرار محرّك الحصص لمشترك معين."""
    allowed: bool
    reason: str = ""
    policy_id: int | None = None
    policy_scope: str = ""
    daily_limit: int | None = None
    weekly_limit: int | None = None
    daily_used: int = 0
    weekly_used: int = 0
    daily_remaining: int | None = None
    weekly_remaining: int | None = None
    allowed_categories: list[str] = field(default_factory=list)
    allowed_days_names: list[str] = field(default_factory=list)
    valid_time_from: str = ""
    valid_time_until: str = ""

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


# ─── helpers ─────────────────────────────────────────────────────────
def _csv_split(text: str) -> list[str]:
    if not text:
        return []
    return [t.strip() for t in str(text).split(",") if t.strip()]


def _is_category_allowed(category_code: str, allowed_categories: list[str]) -> bool:
    if not category_code:
        return True
    if category_code in SPECIAL_CARD_CATEGORY_CODES:
        return category_code in allowed_categories
    return not allowed_categories or category_code in allowed_categories


def _parse_allowed_days(value: str) -> set[int]:
    """يحول 'sat,sun,mon' أو 'السبت,الأحد' إلى set من weekday() integers."""
    if not value:
        return set()
    out: set[int] = set()
    for raw in _csv_split(value.lower()):
        # دعم القيم الرقمية (0..6) مباشرةً
        if raw.isdigit():
            n = int(raw)
            if 0 <= n <= 6:
                out.add(n)
            continue
        n = _WEEKDAY_NAMES.get(raw)
        if n is not None:
            out.add(n)
    return out


def _time_to_minutes(value: str | None) -> int | None:
    if not value:
        return None
    try:
        hour_text, minute_text = str(value).strip()[:5].split(":", 1)
        hour, minute = int(hour_text), int(minute_text)
    except (TypeError, ValueError):
        return None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return hour * 60 + minute


def _is_time_in_window(now_dt: datetime, start: str | None, end: str | None) -> bool:
    start_minutes = _time_to_minutes(start)
    end_minutes = _time_to_minutes(end)
    if start_minutes is None or end_minutes is None:
        return True
    current = now_dt.hour * 60 + now_dt.minute
    if start_minutes <= end_minutes:
        return start_minutes <= current <= end_minutes
    return current >= start_minutes or current <= end_minutes


def _today_local() -> date:
    return legacy.today_local()


def _week_start_local(today: date | None = None) -> date:
    return legacy.get_week_start(today)


# ─── public API ──────────────────────────────────────────────────────
def get_beneficiary_group_ids(beneficiary_id: int) -> list[int]:
    """يرجع معرّفات مجموعات هذا المشترك."""
    if not beneficiary_id:
        return []
    rows = legacy.query_all(
        "SELECT group_id FROM beneficiary_group_members WHERE beneficiary_id=%s",
        [beneficiary_id],
    )
    return [int(r["group_id"]) for r in rows if r.get("group_id")]


def get_effective_policy(beneficiary_id: int, *, today: date | None = None) -> dict | None:
    """
    يرجع سياسة الحصص الفعّالة لهذا المشترك (الأعلى أولوية بحسب الترتيب).

    الترتيب: user > group > default.
    داخل كل scope، الأولوية الأعلى (priority الأصغر) تفوز.

    الإرجاع: row من card_quota_policies أو None إن لم توجد.
    """
    today_value = today or _today_local()
    today_iso = today_value.isoformat()

    # 1) per-user
    row = legacy.query_one(
        """
        SELECT * FROM card_quota_policies
        WHERE scope='user'
          AND target_id=%s
          AND is_active=TRUE
          AND (valid_from IS NULL OR valid_from <= %s)
          AND (valid_until IS NULL OR valid_until >= %s)
        ORDER BY priority ASC, id DESC
        LIMIT 1
        """,
        [beneficiary_id, today_iso, today_iso],
    )
    if row:
        return row

    # 2) per-group (أي مجموعة ينتمي إليها المشترك)
    group_ids = get_beneficiary_group_ids(beneficiary_id)
    if group_ids:
        placeholders = ",".join(["%s"] * len(group_ids))
        row = legacy.query_one(
            f"""
            SELECT * FROM card_quota_policies
            WHERE scope='group'
              AND target_id IN ({placeholders})
              AND is_active=TRUE
              AND (valid_from IS NULL OR valid_from <= %s)
              AND (valid_until IS NULL OR valid_until >= %s)
            ORDER BY priority ASC, id DESC
            LIMIT 1
            """,
            [*group_ids, today_iso, today_iso],
        )
        if row:
            return row

    # 3) default
    row = legacy.query_one(
        """
        SELECT * FROM card_quota_policies
        WHERE scope='default'
          AND is_active=TRUE
          AND (valid_from IS NULL OR valid_from <= %s)
          AND (valid_until IS NULL OR valid_until >= %s)
        ORDER BY priority ASC, id DESC
        LIMIT 1
        """,
        [today_iso, today_iso],
    )
    return row


def count_cards_today(beneficiary_id: int, *, on_date: date | None = None) -> int:
    """عدد البطاقات المُسلَّمة لهذا المشترك اليوم."""
    if not beneficiary_id:
        return 0
    target_date = (on_date or _today_local()).isoformat()
    row = legacy.query_one(
        """
        SELECT COUNT(*) AS c FROM beneficiary_issued_cards
        WHERE beneficiary_id=%s
          AND DATE(issued_at) = %s
        """,
        [beneficiary_id, target_date],
    )
    return int((row or {}).get("c") or 0)


def count_cards_week(beneficiary_id: int, *, on_date: date | None = None) -> int:
    """عدد البطاقات المُسلَّمة هذا الأسبوع (من بداية الأسبوع المحلي)."""
    if not beneficiary_id:
        return 0
    week_start = _week_start_local(on_date or _today_local()).isoformat()
    row = legacy.query_one(
        """
        SELECT COUNT(*) AS c FROM beneficiary_issued_cards
        WHERE beneficiary_id=%s
          AND DATE(issued_at) >= %s
        """,
        [beneficiary_id, week_start],
    )
    return int((row or {}).get("c") or 0)


def check_quota(
    beneficiary_id: int,
    category_code: str = "",
    *,
    now: datetime | None = None,
) -> QuotaDecision:
    """
    يحدّد إن كان يجوز للمشترك أخذ بطاقة الآن من فئة معينة.

    إذا category_code فارغ → نتحقق من حدود الحصة فقط (للعرض).
    """
    if not beneficiary_id:
        return QuotaDecision(allowed=False, reason="المشترك غير محدد.")

    now_dt = now or legacy.now_local()
    policy = get_effective_policy(beneficiary_id, today=now_dt.date())
    if not policy:
        return QuotaDecision(allowed=False, reason="لا توجد سياسة حصص مفعّلة. تواصل مع الإدارة.")

    weekday = now_dt.weekday()

    daily_limit = policy.get("daily_limit")
    weekly_limit = policy.get("weekly_limit")
    allowed_days = _parse_allowed_days(policy.get("allowed_days") or "")
    allowed_categories = _csv_split(policy.get("allowed_category_codes") or "")
    valid_time_from = policy.get("valid_time_from") or ""
    valid_time_until = policy.get("valid_time_until") or ""

    daily_used = count_cards_today(beneficiary_id, on_date=now_dt.date())
    weekly_used = count_cards_week(beneficiary_id, on_date=now_dt.date())

    daily_remaining = (
        max(0, int(daily_limit) - daily_used) if daily_limit is not None else None
    )
    weekly_remaining = (
        max(0, int(weekly_limit) - weekly_used) if weekly_limit is not None else None
    )

    decision = QuotaDecision(
        allowed=True,
        policy_id=int(policy["id"]),
        policy_scope=policy.get("scope") or "",
        daily_limit=int(daily_limit) if daily_limit is not None else None,
        weekly_limit=int(weekly_limit) if weekly_limit is not None else None,
        daily_used=daily_used,
        weekly_used=weekly_used,
        daily_remaining=daily_remaining,
        weekly_remaining=weekly_remaining,
        allowed_categories=allowed_categories,
        allowed_days_names=[k for k, v in _WEEKDAY_NAMES.items() if v in allowed_days and len(k) > 3][:7],
        valid_time_from=valid_time_from,
        valid_time_until=valid_time_until,
    )

    # ─── الفحوصات ─────────────────────────────────────────────────
    if allowed_days and weekday not in allowed_days:
        decision.allowed = False
        decision.reason = "اليوم خارج الأيام المسموحة بسياستك."
        return decision

    if not _is_time_in_window(now_dt, valid_time_from, valid_time_until):
        decision.allowed = False
        decision.reason = f"الوقت الحالي خارج ساعات الدوام المسموحة ({valid_time_from} - {valid_time_until})."
        return decision

    if not _is_category_allowed(category_code, allowed_categories):
        decision.allowed = False
        decision.reason = f"فئة البطاقة ({category_code}) غير مسموحة بسياستك."
        return decision

    # قيد وقت الدوام (يغلب دائمًا): لا تُصدَر بطاقة أطول من الوقت المتبقّي حتى
    # نهاية الدوام العامّ. لو انتهى الدوام → لا بطاقة.
    if category_code:
        remaining_min = _remaining_workday_minutes(now_dt)
        if remaining_min is not None:
            if remaining_min <= 0:
                decision.allowed = False
                decision.reason = "انتهى وقت الدوام — لا يمكن إصدار بطاقة الآن."
                return decision
            _cat = get_category_by_code(category_code)
            _dur = int((_cat or {}).get("duration_minutes") or 0)
            if _dur > remaining_min:
                decision.allowed = False
                decision.reason = (
                    f"مدّة البطاقة أطول من المتبقّي للدوام ({remaining_min} دقيقة) — "
                    "اختر بطاقة أقصر."
                )
                return decision

    # قاعدة نوع المشترك (تغلب على السياسة): توجيهي → نصف ساعة فقط
    from app.services.access_rules import (
        is_card_category_allowed_for_user_type,
        USER_TYPE_LABELS,
    )
    b = legacy.query_one(
        "SELECT user_type FROM beneficiaries WHERE id=%s", [beneficiary_id]
    )
    ut = ((b or {}).get("user_type") or "").strip().lower()
    if category_code and ut and not is_card_category_allowed_for_user_type(ut, category_code):
        ut_label = USER_TYPE_LABELS.get(ut, ut)
        decision.allowed = False
        decision.reason = (
            f"المشترك ({ut_label}) لا يحق له هذه الفئة — مسموح فقط بطاقة نصف ساعة."
        )
        return decision

    if daily_limit is not None and daily_used >= int(daily_limit):
        decision.allowed = False
        decision.reason = f"وصلت إلى الحد اليومي ({daily_limit}). تجدّد عند منتصف الليل."
        return decision

    if weekly_limit is not None and weekly_used >= int(weekly_limit):
        decision.allowed = False
        decision.reason = f"وصلت إلى الحد الأسبوعي ({weekly_limit})."
        return decision

    return decision


def get_active_categories() -> list[dict]:
    """قائمة الفئات المتاحة (للداشبورد + الإدارة)."""
    return legacy.query_all(
        """
        SELECT * FROM card_categories
        WHERE is_active=TRUE
          AND code IN ('half_hour','one_hour','two_hours','three_hours','four_hours')
        ORDER BY display_order ASC, duration_minutes ASC
        """
    )


def _remaining_workday_minutes(now=None):
    """الدقائق المتبقّية حتى نهاية الدوام العامّ (من إعدادات البطاقات).
    None إن تعذّر تحديد نهاية الدوام؛ 0 إن انتهى الدوام."""
    try:
        sched = legacy.get_hotspot_workday_settings() or {}
        end = str(sched.get("end_time") or "").strip()
        if not end or ":" not in end:
            return None
        eh, em = [int(x) for x in end.split(":", 1)]
        now_dt = now or legacy.now_local()
        end_dt = now_dt.replace(hour=eh, minute=em, second=0, microsecond=0)
        return max(0, int((end_dt - now_dt).total_seconds() // 60))
    except Exception:  # noqa: BLE001 — لا نكسر العرض إن غابت الإعدادات
        return None


def get_available_categories_for_beneficiary(beneficiary_id: int) -> list[dict]:
    from app.services.access_rules import allowed_card_codes_for_user_type

    categories = get_active_categories()
    policy = get_effective_policy(int(beneficiary_id or 0))
    allowed_categories = _csv_split((policy or {}).get("allowed_category_codes") or "")
    # قيد وقت الدوام: لا نعرض بطاقة أطول من المتبقّي حتى نهاية الدوام.
    remaining_min = _remaining_workday_minutes()

    # طبّق قاعدة نوع المشترك (مثلاً توجيهي → half_hour فقط)
    bid = int(beneficiary_id or 0)
    if bid:
        b = legacy.query_one("SELECT user_type FROM beneficiaries WHERE id=%s", [bid])
        user_type = ((b or {}).get("user_type") or "").strip().lower()
        type_locked_codes = allowed_card_codes_for_user_type(user_type)
    else:
        type_locked_codes = None

    result = []
    for category in categories:
        code = str(category.get("code") or "").strip().lower()
        if not _is_category_allowed(code, allowed_categories):
            continue
        if type_locked_codes is not None and code not in type_locked_codes:
            continue
        # قيد وقت الدوام: أسقِط الفئات الأطول من الوقت المتبقّي (وكلّها إن انتهى).
        if remaining_min is not None and int(category.get("duration_minutes") or 0) > remaining_min:
            continue
        result.append(category)
    return result


def get_category_by_code(code: str) -> dict | None:
    if not code:
        return None
    return legacy.query_one(
        """
        SELECT * FROM card_categories
        WHERE code=%s
          AND is_active=TRUE
          AND code IN ('half_hour','one_hour','two_hours','three_hours','four_hours')
        LIMIT 1
        """,
        [code],
    )
