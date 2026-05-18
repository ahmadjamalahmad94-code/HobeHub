# 48as_card_eligibility.py
# ═════════════════════════════════════════════════════════════════════
# Card Eligibility Engine — تحديد فئات البطاقات المسموحة لكل مشترك.
#
# المنطق النهائي المعتمد:
#
#   نوع المشترك   |   tier        |   الفئات المسموحة
#   ──────────────|───────────────|─────────────────────────────────────
#   توجيهي        |   غير موثّق    |   نصف ساعة فقط
#   توجيهي        |   موثّق يدوياً |   نصف + ساعة
#   جامعي/عمل حر  |   default (0) |   نصف + ساعة
#   جامعي/عمل حر  |   معتمد (1)   |   + ساعتين
#   جامعي/عمل حر  |   مؤكد (2)    |   + 3 ساعات
#   جامعي/عمل حر  |   سوبر (3)    |   + 4 ساعات (داخل نافذة الوقت فقط)
#
# طبقتا حماية:
#   1) عرض: get_available_categories_for_beneficiary يخفي ما لا يحق
#   2) خادمي: check_quota / issue_card_from_inventory يرفض الطلب
#
# الـ schema migrations المضافة (idempotent):
#   beneficiaries.tawjihi_verified           BOOLEAN DEFAULT FALSE
#   beneficiaries.four_hour_window_from      TIME    NULL
#   beneficiaries.four_hour_window_until     TIME    NULL
# ═════════════════════════════════════════════════════════════════════

from flask import jsonify, request
from datetime import datetime, time as _time


# ─── 1. Migrations ───────────────────────────────────────────────────
def _ensure_eligibility_columns():
    """يضيف الأعمدة الجديدة على beneficiaries إن لم تكن موجودة."""
    cols = [
        ("tawjihi_verified",       "BOOLEAN DEFAULT FALSE"),
        ("four_hour_window_from",  "TIME NULL"),
        ("four_hour_window_until", "TIME NULL"),
    ]
    for col, ddl in cols:
        try:
            if is_sqlite_database_url():
                # SQLite: TIME → TEXT (يقبل HH:MM)
                ddl_sqlite = ddl.replace("BOOLEAN DEFAULT FALSE", "INTEGER DEFAULT 0").replace("TIME NULL", "TEXT")
                rows = query_all("PRAGMA table_info(beneficiaries)")
                names = {r["name"] for r in (rows or [])}
                if col not in names:
                    execute_sql(f"ALTER TABLE beneficiaries ADD COLUMN {col} {ddl_sqlite}")
            else:
                execute_sql(f"ALTER TABLE beneficiaries ADD COLUMN IF NOT EXISTS {col} {ddl}")
        except Exception:
            pass


try:
    _ensure_eligibility_columns()
except Exception:
    pass


# ─── 2. الـ Engine الرئيسي للأهلية ────────────────────────────────────
TIER_TO_CODES = {
    0: ["half_hour", "one_hour", "two_hours", "three_hours"],                   # افتراضي — الفئات العادية
    1: ["half_hour", "one_hour", "two_hours"],                                  # معتمد — + ساعتين
    2: ["half_hour", "one_hour", "two_hours", "three_hours"],                   # مؤكد — + 3 ساعات
    3: ["half_hour", "one_hour", "two_hours", "three_hours", "four_hours"],     # سوبر — + 4 ساعات
}

TAWJIHI_DEFAULT_CODES  = ["half_hour"]
TAWJIHI_VERIFIED_CODES = ["half_hour", "one_hour"]


def _parse_time(value):
    """يحوّل نص HH:MM أو TIME إلى time object. يرجع None لو فاشل."""
    if value is None or value == "":
        return None
    if isinstance(value, _time):
        return value
    s = str(value).strip()
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(s, fmt).time()
        except (TypeError, ValueError):
            continue
    return None


def _is_inside_four_hour_window(beneficiary_row) -> bool:
    """يحدد لو الوقت الحالي داخل نافذة بطاقة 4 ساعات للمشترك.

    إذا لم تُضبط نافذة → دائماً متاح (نُعتبره غير مقيّد).
    """
    if not beneficiary_row:
        return True
    t_from = _parse_time(beneficiary_row.get("four_hour_window_from"))
    t_until = _parse_time(beneficiary_row.get("four_hour_window_until"))
    # لو واحد من الحقلين فاضي → ما في تقييد
    if not t_from or not t_until:
        return True
    now_t = datetime.now().time()
    if t_from <= t_until:
        # نافذة عادية في نفس اليوم (مثل 14:00 → 22:00)
        return t_from <= now_t <= t_until
    # نافذة تعبر منتصف الليل (مثل 22:00 → 06:00)
    return now_t >= t_from or now_t <= t_until


def get_eligible_card_codes(beneficiary) -> set[str]:
    """يرجع set من أكواد الفئات المسموحة لمشترك معيّن.

    المنطق:
      - تــوجيهي: ينطبق فقط tawjihi_verified
      - جامعي / عمل حر: ينطبق tier من card_quota_policies + نافذة الوقت لـ super
    """
    if not beneficiary:
        return set()

    ut = (beneficiary.get("user_type") or "").strip().lower()

    if ut == "tawjihi":
        # boolean flag بسيط
        verified = beneficiary.get("tawjihi_verified")
        if isinstance(verified, int):
            verified = bool(verified)
        return set(TAWJIHI_VERIFIED_CODES if verified else TAWJIHI_DEFAULT_CODES)

    if ut in ("university", "freelancer"):
        # احصل على tier من نظام التوثيق
        try:
            from app.legacy_parts import _legacy_part  # noqa
        except ImportError:
            pass
        # الـ tier متاح كدالة في النطاق العام (loaded من 48av)
        try:
            tier = get_effective_tier(int(beneficiary.get("id") or 0))
        except Exception:
            tier = 0
        codes = set(TIER_TO_CODES.get(int(tier or 0), TIER_TO_CODES[0]))
        # تطبيق نافذة بطاقة 4 ساعات (super tier فقط)
        if "four_hours" in codes and not _is_inside_four_hour_window(beneficiary):
            codes.discard("four_hours")
        return codes

    # نوع غير معروف → نصف فقط احتياطاً
    return set(TAWJIHI_DEFAULT_CODES)


# ─── 3. Override get_available_categories_for_beneficiary ─────────────
def _new_get_available_categories(beneficiary_id: int) -> list[dict]:
    """نسخة جديدة تطبّق نظام الأهلية الموحَّد.

    تستبدل النسخة في quota_engine.py.
    """
    from app.services.quota_engine import get_active_categories

    bid = int(beneficiary_id or 0)
    if not bid:
        return get_active_categories()

    b = query_one(
        "SELECT id, user_type, tawjihi_verified, four_hour_window_from, four_hour_window_until "
        "FROM beneficiaries WHERE id=%s LIMIT 1",
        [bid],
    )
    if not b:
        return []

    eligible = get_eligible_card_codes(b)
    if not eligible:
        return []

    try:
        base_categories = _original_get_available_categories(bid)
    except Exception:
        base_categories = get_active_categories()
    return [c for c in base_categories if (c.get("code") or "").strip().lower() in eligible]


# Monkey-patch quota_engine.get_available_categories_for_beneficiary
try:
    from app.services import quota_engine as _qe
    _original_get_available_categories = _qe.get_available_categories_for_beneficiary
    _qe.get_available_categories_for_beneficiary = _new_get_available_categories
except Exception:
    pass


# ─── 4. Endpoint: تبديل توثيق التوجيهي ───────────────────────────────
@app.route("/admin/beneficiaries/<int:bid>/toggle-tawjihi-verified", methods=["POST"])
@admin_login_required
def admin_toggle_tawjihi_verified(bid):
    """يقلب tawjihi_verified للمشترك (لو توجيهي)."""
    b = query_one("SELECT id, full_name, user_type, tawjihi_verified FROM beneficiaries WHERE id=%s", [bid])
    if not b:
        return jsonify({"ok": False, "message": "المشترك غير موجود."}), 404
    if (b.get("user_type") or "").strip().lower() != "tawjihi":
        return jsonify({"ok": False, "message": "هذا الإجراء متاح للتوجيهي فقط."}), 400

    current = bool(b.get("tawjihi_verified"))
    new_val = not current
    execute_sql(
        "UPDATE beneficiaries SET tawjihi_verified=%s WHERE id=%s",
        [new_val, bid],
    )
    log_action(
        "toggle_tawjihi_verified", "beneficiary", bid,
        f"{b.get('full_name')}: {current} → {new_val}",
    )
    return jsonify({
        "ok": True,
        "tawjihi_verified": new_val,
        "message": "تم توثيق التوجيهي (يحق له نصف ساعة + ساعة)." if new_val
                   else "تم إلغاء توثيق التوجيهي (نصف ساعة فقط).",
    })


# ─── 5. Endpoint: ضبط نافذة بطاقة 4 ساعات ────────────────────────────
@app.route("/admin/beneficiaries/<int:bid>/set-four-hour-window", methods=["POST"])
@admin_login_required
def admin_set_four_hour_window(bid):
    """يضبط نافذة الوقت لبطاقة 4 ساعات لمشترك سوبر.

    form fields: window_from, window_until (HH:MM أو فارغ للحذف)
    """
    b = query_one("SELECT id, full_name, user_type FROM beneficiaries WHERE id=%s", [bid])
    if not b:
        return jsonify({"ok": False, "message": "المشترك غير موجود."}), 404

    raw_from = (request.form.get("window_from") or "").strip()
    raw_until = (request.form.get("window_until") or "").strip()

    # السماح بحذف النافذة بإرسال قيمة فارغة في كلاهما
    if not raw_from and not raw_until:
        execute_sql(
            "UPDATE beneficiaries SET four_hour_window_from=NULL, four_hour_window_until=NULL WHERE id=%s",
            [bid],
        )
        log_action("clear_four_hour_window", "beneficiary", bid, b.get("full_name") or "")
        return jsonify({"ok": True, "cleared": True, "message": "تم إلغاء نافذة الوقت."})

    t_from = _parse_time(raw_from)
    t_until = _parse_time(raw_until)
    if not t_from or not t_until:
        return jsonify({"ok": False, "message": "صيغة الوقت غير صحيحة (HH:MM)."}), 400

    execute_sql(
        "UPDATE beneficiaries SET four_hour_window_from=%s, four_hour_window_until=%s WHERE id=%s",
        [t_from.strftime("%H:%M:%S"), t_until.strftime("%H:%M:%S"), bid],
    )
    log_action(
        "set_four_hour_window", "beneficiary", bid,
        f"{b.get('full_name')}: {raw_from} → {raw_until}",
    )
    return jsonify({
        "ok": True,
        "window_from": t_from.strftime("%H:%M"),
        "window_until": t_until.strftime("%H:%M"),
        "message": f"تم ضبط نافذة بطاقة 4 ساعات: {raw_from} → {raw_until}.",
    })


# ─── 6. Defense: aug check_quota برفض الفئات غير المسموحة ─────────────
def _check_eligibility_in_quota(beneficiary_id: int, category_code: str):
    """يرجع None إن كان مسموح، أو QuotaDecision(fail) إن كان ممنوع."""
    from app.services.quota_engine import QuotaDecision

    bid = int(beneficiary_id or 0)
    if not bid or not category_code:
        return None

    b = query_one(
        "SELECT id, user_type, tawjihi_verified, four_hour_window_from, four_hour_window_until "
        "FROM beneficiaries WHERE id=%s LIMIT 1",
        [bid],
    )
    if not b:
        return None
    eligible = get_eligible_card_codes(b)
    code = (category_code or "").strip().lower()
    if code not in eligible:
        # رسائل خطأ موضّحة حسب السبب
        ut = (b.get("user_type") or "").strip().lower()
        if ut == "tawjihi":
            if code == "one_hour":
                msg = "بطاقة الساعة متاحة فقط للتوجيهي الموثّق. راجع الإدارة للتوثيق."
            else:
                msg = "هذه الفئة غير متاحة للتوجيهي (متاح: نصف ساعة فقط)."
        elif code == "four_hours" and not _is_inside_four_hour_window(b):
            t_from = _parse_time(b.get("four_hour_window_from"))
            t_until = _parse_time(b.get("four_hour_window_until"))
            if t_from and t_until:
                msg = f"بطاقة 4 ساعات متاحة فقط بين {t_from.strftime('%H:%M')} و {t_until.strftime('%H:%M')}."
            else:
                msg = "بطاقة 4 ساعات خارج نافذة الوقت المخصصة لك."
        else:
            msg = f"هذه الفئة ({code}) غير متاحة لمستوى توثيقك الحالي. راجع الإدارة لترقية حسابك."
        return QuotaDecision(allowed=False, reason=msg)
    return None


# Wrap quota_engine.check_quota للفحص بعد المنطق الأصلي
try:
    from app.services import quota_engine as _qe2
    _original_check_quota = _qe2.check_quota

    def _wrapped_check_quota(beneficiary_id, category_code="", *args, **kwargs):
        # طبقة 1: الأهلية الجديدة
        eligibility = _check_eligibility_in_quota(beneficiary_id, category_code)
        if eligibility is not None and not eligibility.allowed:
            return eligibility
        # طبقة 2: المنطق الأصلي (daily_limit, weekly_limit, etc.)
        return _original_check_quota(beneficiary_id, category_code, *args, **kwargs)

    _qe2.check_quota = _wrapped_check_quota
except Exception:
    pass
