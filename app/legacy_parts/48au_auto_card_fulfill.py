# 48au_auto_card_fulfill.py
# تنفيذ تلقائي لطلب بطاقة معلَّق — يسحب أقدم بطاقة من المخزون ويسلّمها مباشرة
# POST /admin/cards/pending/<id>/fulfill-auto  →  JSON

import json
from flask import jsonify, request, session


@app.route("/admin/cards/pending/<int:action_id>/fulfill-auto", methods=["POST"])
@admin_login_required
def admin_cards_pending_fulfill_auto(action_id):
    """
    تنفيذ تلقائي: يبحث عن أقدم بطاقة في المخزون تطابق مدة فئة الطلب،
    ثم يستدعي fulfill_pending_card_action بنفس البيانات.
    """
    from app.services.card_dispatcher import fulfill_pending_card_action
    from app.services.quota_engine import get_category_by_code

    actor = session.get("username") or "admin"
    notes = (request.form.get("notes") or request.get_json(silent=True) or {}).get("notes", "") \
        if not isinstance(request.form.get("notes"), str) else request.form.get("notes", "")
    notes = notes or "تنفيذ تلقائي من المخزون"

    # ── 1. تحميل الطلب المعلَّق ──────────────────────────────────────────
    action = query_one(
        "SELECT * FROM radius_pending_actions WHERE id=%s LIMIT 1",
        [action_id],
    )
    if not action:
        return jsonify({"ok": False, "message": "الطلب غير موجود."}), 404
    if action.get("status") != "pending":
        return jsonify({"ok": False, "message": f"الطلب بحالة «{action.get('status')}» ولا يمكن تنفيذه."}), 409

    # ── 2. استخراج فئة البطاقة ───────────────────────────────────────────
    try:
        payload = json.loads(action.get("payload_json") or "{}") \
            if isinstance(action.get("payload_json"), str) else (action.get("payload_json") or {})
    except (TypeError, ValueError):
        payload = {}

    category_code = payload.get("category_code") or ""
    category = get_category_by_code(category_code)
    if not category:
        return jsonify({"ok": False, "message": "فئة البطاقة في الطلب غير معروفة."}), 422

    duration_minutes = int(category["duration_minutes"])

    # ── 3. سحب أقدم بطاقة من المخزون ────────────────────────────────────
    card = query_one(
        "SELECT * FROM manual_access_cards WHERE duration_minutes=%s ORDER BY id ASC LIMIT 1",
        [duration_minutes],
    )
    if not card:
        label = category.get("label_ar") or f"{duration_minutes} دقيقة"
        return jsonify({
            "ok": False,
            "message": f"لا توجد بطاقات متاحة في المخزون لفئة «{label}».",
        }), 409

    # ── 4. تنفيذ الطلب عبر fulfill_pending_card_action ───────────────────
    result = fulfill_pending_card_action(
        action_id,
        card_username=card["card_username"],
        card_password=card["card_password"],
        actor_username=actor,
        notes=notes,
    )

    if not result.ok:
        return jsonify({"ok": False, "message": result.message}), 422

    # حذف البطاقة من المخزون بعد التسليم الناجح
    try:
        execute_sql(
            "DELETE FROM manual_access_cards WHERE id=%s",
            [card["id"]],
        )
    except Exception:
        pass

    return jsonify({
        "ok": True,
        "message": result.message,
        "card_username": result.card_username,
        "card_password": result.card_password,
        "issued_card_id": result.issued_card_id,
        "duration_label": result.duration_label,
    })
