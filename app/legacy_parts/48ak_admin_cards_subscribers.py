# 48ak_admin_cards_subscribers.py
# صفحة "مشتركو البطاقات" — تعرض المشتركين الذين access_mode='cards'.
# تشمل: كل توجيهي + جامعي/عمل حر بطريقة "نظام البطاقات".
# تتيح: تعديل (modal)، عرض الملف، تحويل ليوزر (لمن يحق له)، حذف.

from flask import request, redirect, url_for, render_template, jsonify


# ════════════════════════════════════════════════════════════════
# GET /admin/cards/subscribers — قائمة مشتركي البطاقات
# ════════════════════════════════════════════════════════════════
@app.route("/admin/cards/subscribers", methods=["GET"])
@admin_login_required
def admin_cards_subscribers_page():
    from app.services.access_rules import can_switch_to

    q = clean_csv_value(request.args.get("q")) or ""
    user_type_filter = clean_csv_value(request.args.get("user_type")) or ""

    sql = """
        SELECT b.id, b.full_name, b.phone, b.user_type,
               b.university_internet_method, b.freelancer_internet_method,
               pa.id AS portal_account_id
        FROM beneficiaries b
        LEFT JOIN beneficiary_portal_accounts pa ON pa.beneficiary_id = b.id
             AND COALESCE(pa.portal_membership_active, FALSE)=TRUE
        WHERE (
              b.user_type = 'tawjihi'
           OR (b.user_type='university'
               AND COALESCE(b.university_internet_method,'') NOT IN ('يوزر إنترنت','يمتلك اسم مستخدم','username'))
           OR (b.user_type='freelancer'
               AND COALESCE(b.freelancer_internet_method,'') NOT IN ('يوزر إنترنت','يمتلك اسم مستخدم','username'))
        )
    """
    params = []
    if q:
        sql += " AND (b.full_name LIKE %s OR b.phone LIKE %s)"
        params.extend([f"%{q}%", f"%{q}%"])
    if user_type_filter in ("tawjihi", "university", "freelancer"):
        sql += " AND b.user_type=%s"
        params.append(user_type_filter)
    sql += " ORDER BY b.id DESC LIMIT 300"

    rows = query_all(sql, params) or []

    type_labels = {"tawjihi": "توجيهي", "university": "جامعي", "freelancer": "عمل حر"}

    # نستورد helper الـ access_mode للتطبيق على بيانات لحظية
    try:
        from app.dashboard.services import get_beneficiary_access_mode
    except Exception:
        get_beneficiary_access_mode = None

    subscribers = []
    for r in rows:
        ut = (r.get("user_type") or "").strip().lower()
        # طبقة أمان: استثناء أي مشترك ليس في وضع cards
        if get_beneficiary_access_mode is not None:
            access_mode = get_beneficiary_access_mode(r)
            if access_mode != 'cards':
                continue
        # الإمكانية للتحويل ليوزر — التوجيهي ممنوع، الجامعي/عمل حر مسموح
        can, reason = can_switch_to(ut, 'username')
        subscribers.append({
            "id": r["id"],
            "full_name": r["full_name"],
            "phone": r.get("phone"),
            "user_type": ut,
            "user_type_label": type_labels.get(ut, ut),
            "has_portal_account": bool(r.get("portal_account_id")),
            "can_switch": can,
            "switch_reason": reason,
        })

    # عدّاد KPIs (بعد فلترة Python)
    counts = {
        "total": len(subscribers),
        "tawjihi": sum(1 for s in subscribers if s["user_type"] == "tawjihi"),
        "university": sum(1 for s in subscribers if s["user_type"] == "university"),
        "freelancer": sum(1 for s in subscribers if s["user_type"] == "freelancer"),
    }

    return render_template(
        "admin/cards/subscribers.html",
        subscribers=subscribers,
        counts=counts,
        filters={"q": q, "user_type": user_type_filter},
    )


# ════════════════════════════════════════════════════════════════
# GET /admin/cards/subscribers/data.json — JSON endpoint للبحث AJAX
# ════════════════════════════════════════════════════════════════
@app.route("/admin/cards/subscribers/data.json", methods=["GET"])
@admin_login_required
def admin_cards_subscribers_data_json():
    """يرجع قائمة مشتركي البطاقات + الإحصائيات كـ JSON."""
    from app.services.access_rules import can_switch_to

    q = clean_csv_value(request.args.get("q")) or ""
    user_type_filter = clean_csv_value(request.args.get("user_type")) or ""

    sql = """
        SELECT b.id, b.full_name, b.phone, b.user_type,
               b.university_internet_method, b.freelancer_internet_method,
               pa.id AS portal_account_id
        FROM beneficiaries b
        LEFT JOIN beneficiary_portal_accounts pa ON pa.beneficiary_id = b.id
             AND COALESCE(pa.portal_membership_active, FALSE)=TRUE
        WHERE (
              b.user_type = 'tawjihi'
           OR (b.user_type='university'
               AND COALESCE(b.university_internet_method,'') NOT IN ('يوزر إنترنت','يمتلك اسم مستخدم','username'))
           OR (b.user_type='freelancer'
               AND COALESCE(b.freelancer_internet_method,'') NOT IN ('يوزر إنترنت','يمتلك اسم مستخدم','username'))
        )
    """
    params = []
    if q:
        sql += " AND (b.full_name LIKE %s OR b.phone LIKE %s)"
        params.extend([f"%{q}%", f"%{q}%"])
    if user_type_filter in ("tawjihi", "university", "freelancer"):
        sql += " AND b.user_type=%s"
        params.append(user_type_filter)
    sql += " ORDER BY b.id DESC LIMIT 300"

    rows = query_all(sql, params) or []
    type_labels = {"tawjihi": "توجيهي", "university": "جامعي", "freelancer": "عمل حر"}
    try:
        from app.dashboard.services import get_beneficiary_access_mode
    except Exception:
        get_beneficiary_access_mode = None

    subscribers = []
    for r in rows:
        ut = (r.get("user_type") or "").strip().lower()
        if get_beneficiary_access_mode is not None:
            access_mode = get_beneficiary_access_mode(r)
            if access_mode != 'cards':
                continue
        can, reason = can_switch_to(ut, 'username')
        subscribers.append({
            "id": r["id"],
            "full_name": r["full_name"],
            "phone": r.get("phone") or "",
            "user_type": ut,
            "user_type_label": type_labels.get(ut, ut),
            "has_portal_account": bool(r.get("portal_account_id")),
            "can_switch": bool(can),
            "switch_reason": reason or "",
        })

    counts = {
        "total": len(subscribers),
        "tawjihi": sum(1 for s in subscribers if s["user_type"] == "tawjihi"),
        "university": sum(1 for s in subscribers if s["user_type"] == "university"),
        "freelancer": sum(1 for s in subscribers if s["user_type"] == "freelancer"),
    }
    return jsonify({"ok": True, "subscribers": subscribers, "counts": counts})
