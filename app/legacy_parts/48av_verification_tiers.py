# 48av_verification_tiers.py
# نظام التوثيق المتدرج — Verification Tiers
#
# أربعة مستويات تفتح فئات بطاقات إضافية:
#   0 = افتراضي  → نصف ساعة + ساعة
#   1 = معتمد    → + ساعتين
#   2 = مؤكد     → + 3 ساعات
#   3 = سوبر     → + 4 ساعات
#
# كل مستوى > 0 يُنشئ per-user policy في card_quota_policies.
# تاريخ انتهاء اختياري + مستوى احتياطي بعد الانتهاء.

from flask import jsonify, request, session
from datetime import date, datetime

# ─── ثوابت المستويات ──────────────────────────────────────────────────────
TIER_CODES = {
    0: [],  # افتراضي — تتحكم السياسة الافتراضية فقط
    1: ["half_hour", "one_hour", "two_hours"],
    2: ["half_hour", "one_hour", "two_hours", "three_hours"],
    3: ["half_hour", "one_hour", "two_hours", "three_hours", "four_hours"],
}

TIER_LABELS = {0: "افتراضي", 1: "معتمد", 2: "مؤكد", 3: "سوبر"}
TIER_COLORS = {0: "muted", 1: "blue", 2: "green", 3: "gold"}


# ─── تصحيح السياسة الافتراضية عند أول تشغيل ──────────────────────────────
def _fix_default_policy():
    """يتأكد أن السياسة الافتراضية = نصف ساعة + ساعة فقط (default tier).

    باقي الفئات (ساعتين/3/4) تفتح فقط لمن يحصل على tier > 0 (per-user policy).
    """
    try:
        execute_sql(
            """
            UPDATE card_quota_policies
               SET allowed_category_codes = 'half_hour,one_hour,two_hours,three_hours',
                   updated_at = CURRENT_TIMESTAMP
             WHERE scope = 'default'
               AND COALESCE(allowed_category_codes,'') <> 'half_hour,one_hour,two_hours,three_hours'
            """,
        )
    except Exception:
        pass


try:
    _fix_default_policy()
except Exception:
    pass


# ─── مساعدات ─────────────────────────────────────────────────────────────
def _codes_to_tier(codes_csv: str) -> int:
    codes = {c.strip().lower() for c in (codes_csv or "").split(",") if c.strip()}
    if "four_hours" in codes:
        return 3
    if "three_hours" in codes:
        return 2
    if "two_hours" in codes:
        return 1
    return 0


def _get_default_limits() -> tuple[int | None, int | None]:
    """يقرأ daily_limit وweekly_limit من السياسة الافتراضية."""
    try:
        row = query_one(
            "SELECT daily_limit, weekly_limit FROM card_quota_policies "
            "WHERE scope='default' AND is_active=TRUE ORDER BY priority ASC LIMIT 1"
        )
        if row:
            return row.get("daily_limit"), row.get("weekly_limit")
    except Exception:
        pass
    return 1, 7


def get_beneficiary_tiers(beneficiary_id: int) -> list[dict]:
    """
    يرجع قائمة per-user policies النشطة للمشترك مرتبةً بالأولوية،
    كل عنصر فيه: id, tier, tier_label, tier_color, valid_until, priority, expired
    """
    today_iso = date.today().isoformat()
    rows = query_all(
        """
        SELECT id, allowed_category_codes, valid_until, priority
          FROM card_quota_policies
         WHERE scope = 'user'
           AND target_id = %s
           AND is_active = TRUE
         ORDER BY priority ASC, id DESC
        """,
        [beneficiary_id],
    )
    result = []
    for row in rows:
        tier = _codes_to_tier(row.get("allowed_category_codes") or "")
        vu = row.get("valid_until")
        expired = bool(vu and vu < today_iso)
        result.append({
            "id": row["id"],
            "tier": tier,
            "tier_label": TIER_LABELS.get(tier, "افتراضي"),
            "tier_color": TIER_COLORS.get(tier, "muted"),
            "valid_until": vu,
            "priority": row["priority"],
            "expired": expired,
        })
    return result


def get_effective_tier(beneficiary_id: int) -> int:
    """المستوى الفعلي النشط الآن (الأعلى بين السياسات غير المنتهية)."""
    today_iso = date.today().isoformat()
    tiers = get_beneficiary_tiers(beneficiary_id)
    active = [t for t in tiers if not t["expired"]]
    return max((t["tier"] for t in active), default=0)


# ─── endpoint: معلومات التوثيق ──────────────────────────────────────────
@app.route("/admin/beneficiaries/<int:bid>/tier-info", methods=["GET"])
@admin_login_required
def admin_beneficiary_tier_info(bid):
    b = query_one("SELECT full_name, user_type FROM beneficiaries WHERE id=%s", [bid])
    if not b:
        return jsonify({"ok": False, "message": "المشترك غير موجود."}), 404

    tiers = get_beneficiary_tiers(bid)
    effective = get_effective_tier(bid)
    return jsonify({
        "ok": True,
        "beneficiary_id": bid,
        "full_name": b.get("full_name") or "",
        "user_type": b.get("user_type") or "",
        "effective_tier": effective,
        "effective_tier_label": TIER_LABELS.get(effective, "افتراضي"),
        "policies": tiers,
        "tier_labels": TIER_LABELS,
        "tier_colors": TIER_COLORS,
    })


# ─── endpoint: تعيين مستوى التوثيق ────────────────────────────────────
@app.route("/admin/beneficiaries/<int:bid>/set-tier", methods=["POST"])
@admin_login_required
def admin_beneficiary_set_tier(bid):
    """
    body (JSON أو form):
      tier         : 0-3
      valid_until  : 'YYYY-MM-DD' أو '' (اختياري)
      fallback_tier: 0-3 (يظهر فقط لو valid_until مضبوط)
    """
    b = query_one("SELECT full_name FROM beneficiaries WHERE id=%s", [bid])
    if not b:
        return jsonify({"ok": False, "message": "المشترك غير موجود."}), 404

    # قراءة البيانات من JSON أو form
    data = request.get_json(silent=True) or {}
    if not data:
        data = {k: request.form.get(k, "") for k in ("tier", "valid_until", "fallback_tier")}

    try:
        tier = int(data.get("tier", 0))
        if tier not in TIER_CODES:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({"ok": False, "message": "مستوى التوثيق غير صالح."}), 422

    valid_until = (data.get("valid_until") or "").strip() or None
    if valid_until:
        try:
            datetime.strptime(valid_until, "%Y-%m-%d")
        except ValueError:
            return jsonify({"ok": False, "message": "تاريخ الانتهاء غير صالح (استخدم YYYY-MM-DD)."}), 422

    fallback_tier = 0
    if valid_until:
        try:
            fallback_tier = int(data.get("fallback_tier", 0))
            if fallback_tier not in TIER_CODES:
                fallback_tier = 0
        except (TypeError, ValueError):
            fallback_tier = 0

    actor = session.get("username") or "admin"
    daily_lim, weekly_lim = _get_default_limits()

    # ── حذف كل per-user policies الحالية لهذا المشترك ─────────────────
    execute_sql(
        "DELETE FROM card_quota_policies WHERE scope='user' AND target_id=%s",
        [bid],
    )

    # ── إنشاء السياسة الرئيسية ────────────────────────────────────────
    if tier > 0:
        codes = ",".join(TIER_CODES[tier])
        until_note = f" حتى {valid_until}" if valid_until else " (دائم)"
        execute_sql(
            """
            INSERT INTO card_quota_policies
              (scope, target_id, allowed_category_codes,
               daily_limit, weekly_limit,
               valid_until, priority, is_active, notes, created_at, updated_at)
            VALUES
              ('user', %s, %s, %s, %s, %s, 1, TRUE, %s,
               CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            [
                bid, codes, daily_lim, weekly_lim, valid_until,
                f"توثيق {TIER_LABELS[tier]}{until_note} — {actor}",
            ],
        )

    # ── إنشاء السياسة الاحتياطية (بعد انتهاء الرئيسية) ───────────────
    if valid_until and fallback_tier > 0:
        fb_codes = ",".join(TIER_CODES[fallback_tier])
        execute_sql(
            """
            INSERT INTO card_quota_policies
              (scope, target_id, allowed_category_codes,
               daily_limit, weekly_limit,
               valid_until, priority, is_active, notes, created_at, updated_at)
            VALUES
              ('user', %s, %s, %s, %s, NULL, 10, TRUE, %s,
               CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            [
                bid, fb_codes, daily_lim, weekly_lim,
                f"توثيق احتياطي {TIER_LABELS[fallback_tier]} (بعد انتهاء المؤقت) — {actor}",
            ],
        )

    # ── تدقيق ─────────────────────────────────────────────────────────
    try:
        insert_audit_log(
            action="beneficiary_tier_set",
            performed_by=session.get("username") or "admin",
            details={
                "beneficiary_id": bid,
                "tier": tier,
                "tier_label": TIER_LABELS[tier],
                "valid_until": valid_until,
                "fallback_tier": fallback_tier,
            },
        )
    except Exception:
        pass

    msg = f"تم تعيين مستوى «{TIER_LABELS[tier]}»"
    if valid_until:
        msg += f" حتى {valid_until}"
        if fallback_tier > 0:
            msg += f"، ثم يرجع لـ «{TIER_LABELS[fallback_tier]}»"
    elif tier == 0:
        msg = "تم إعادة المشترك للمستوى الافتراضي"

    return jsonify({
        "ok": True,
        "message": msg,
        "tier": tier,
        "tier_label": TIER_LABELS[tier],
        "tier_color": TIER_COLORS[tier],
        "valid_until": valid_until,
        "fallback_tier": fallback_tier,
    })
