# 48bc_subscriber_card_policy.py
# سياسة بطاقات خاصّة بمشترك (scope='user') — عرض/حفظ/تصفير من صفحة المشترك.
# السياسة الافتراضية تُطبَّق وتُورَّث للجميع؛ هذه تُنشئ استثناءً لمشترك بعينه
# (يتجاوز محرّك الحصص الافتراضيّةَ لأنّه يستعلم scope='user' أوّلًا).

import datetime as _sp_dt

from flask import jsonify, request


def _sp_jsonable(row):
    """يحوّل صفّ السياسة إلى قاموس آمن للـJSON: التواريخ/الأوقات → ISO نصّيّ
    (كي يعمل .slice في الواجهة بثبات عبر SQLite وPostgres)."""
    if not row:
        return None
    out = {}
    for k, v in dict(row).items():
        if isinstance(v, (_sp_dt.datetime, _sp_dt.date)):
            out[k] = v.isoformat()
        elif isinstance(v, _sp_dt.time):
            out[k] = v.strftime("%H:%M")
        else:
            out[k] = v
    return out


_SP_DAY_NAMES = [
    ("sat", "السبت"), ("sun", "الأحد"), ("mon", "الإثنين"), ("tue", "الثلاثاء"),
    ("wed", "الأربعاء"), ("thu", "الخميس"), ("fri", "الجمعة"),
]


def _sp_intornone(v):
    v = clean_csv_value(v)
    return int(v) if v and v.lstrip("-").isdigit() else None


def _sp_time_or_none(v):
    value = clean_csv_value(v)
    if not value:
        return None
    parts = value.split(":", 1)
    if len(parts) != 2:
        raise ValueError
    hour, minute = int(parts[0]), int(parts[1])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError
    return f"{hour:02d}:{minute:02d}"


# ─── GET: بيانات المحرّر (السياسة الخاصّة الحالية + الفئات + المُطبّق فعليًّا)
@app.route("/admin/users/<int:bid>/card-policy", methods=["GET"])
@admin_login_required
def subscriber_card_policy_get(bid):
    ben = query_one("SELECT id, full_name FROM beneficiaries WHERE id=%s LIMIT 1", [bid])
    if not ben:
        return jsonify({"ok": False, "message": "المشترك غير موجود."}), 404

    override = query_one(
        "SELECT * FROM card_quota_policies WHERE scope='user' AND target_id=%s "
        "ORDER BY priority ASC, id DESC LIMIT 1",
        [bid],
    )
    cats = query_all(
        "SELECT code, label_ar FROM card_categories WHERE is_active=TRUE "
        "ORDER BY duration_minutes ASC"
    ) or []

    effective = None
    try:
        from app.services.quota_engine import get_effective_policy
        effective = get_effective_policy(bid)
    except Exception:  # noqa: BLE001 — العرض لا يكسر إن تعذّر الحساب
        effective = None

    return jsonify({
        "ok": True,
        "beneficiary": {"id": ben["id"], "full_name": ben.get("full_name") or ""},
        "override": _sp_jsonable(override),
        "effective": _sp_jsonable(effective),
        "effective_scope": (effective or {}).get("scope") if effective else None,
        "categories": [{"code": c["code"], "label_ar": c["label_ar"]} for c in cats],
        "day_names": [{"code": d[0], "label": d[1]} for d in _SP_DAY_NAMES],
    })


# ─── POST: حفظ/تحديث السياسة الخاصّة (upsert scope='user')
@app.route("/admin/users/<int:bid>/card-policy", methods=["POST"])
@admin_login_required
def subscriber_card_policy_save(bid):
    ben = query_one("SELECT id FROM beneficiaries WHERE id=%s LIMIT 1", [bid])
    if not ben:
        return jsonify({"ok": False, "message": "المشترك غير موجود."}), 404

    try:
        daily = _sp_intornone(request.form.get("daily_limit"))
        weekly = _sp_intornone(request.form.get("weekly_limit"))
        priority = int(clean_csv_value(request.form.get("priority") or "50"))
        valid_time_from = _sp_time_or_none(request.form.get("valid_time_from"))
        valid_time_until = _sp_time_or_none(request.form.get("valid_time_until"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "message": "قيمة غير صالحة في الحدود أو الأولوية أو ساعات الدوام."}), 400
    if bool(valid_time_from) ^ bool(valid_time_until):
        return jsonify({"ok": False, "message": "حدد بداية ونهاية ساعات الدوام معًا، أو اتركهما فارغتين."}), 400

    allowed_days = clean_csv_value(request.form.get("allowed_days"))
    allowed_categories = clean_csv_value(request.form.get("allowed_category_codes"))
    valid_from = clean_csv_value(request.form.get("valid_from")) or None
    valid_until = clean_csv_value(request.form.get("valid_until")) or None
    notes = clean_csv_value(request.form.get("notes"))

    existing = query_one(
        "SELECT id FROM card_quota_policies WHERE scope='user' AND target_id=%s LIMIT 1", [bid]
    )
    if existing:
        execute_sql(
            """
            UPDATE card_quota_policies SET
                daily_limit=%s, weekly_limit=%s, allowed_days=%s, allowed_category_codes=%s,
                priority=%s, valid_from=%s, valid_until=%s, valid_time_from=%s, valid_time_until=%s,
                notes=%s, is_active=TRUE, updated_at=CURRENT_TIMESTAMP
            WHERE id=%s
            """,
            [daily, weekly, allowed_days, allowed_categories, priority, valid_from,
             valid_until, valid_time_from, valid_time_until, notes, existing["id"]],
        )
    else:
        execute_sql(
            """
            INSERT INTO card_quota_policies
                (scope, target_id, daily_limit, weekly_limit, allowed_days, allowed_category_codes,
                 priority, valid_from, valid_until, valid_time_from, valid_time_until, notes,
                 is_active, created_by_account_id)
            VALUES ('user',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,TRUE,%s)
            """,
            [bid, daily, weekly, allowed_days, allowed_categories, priority, valid_from,
             valid_until, valid_time_from, valid_time_until, notes, session.get("account_id")],
        )
    log_action("save_subscriber_card_policy", "card_quota_policies", bid,
               f"user={bid} daily={daily} weekly={weekly} cats={allowed_categories or '*'}")
    return jsonify({"ok": True, "message": "تم حفظ السياسة الخاصّة بالمشترك."})


# ─── POST: تصفير — حذف السياسة الخاصّة فيرث المشترك الافتراضية
@app.route("/admin/users/<int:bid>/card-policy/reset", methods=["POST"])
@admin_login_required
def subscriber_card_policy_reset(bid):
    execute_sql("DELETE FROM card_quota_policies WHERE scope='user' AND target_id=%s", [bid])
    log_action("reset_subscriber_card_policy", "card_quota_policies", bid, f"user={bid}")
    return jsonify({"ok": True, "message": "أُلغيت السياسة الخاصّة — يرث المشترك السياسة الافتراضية."})
