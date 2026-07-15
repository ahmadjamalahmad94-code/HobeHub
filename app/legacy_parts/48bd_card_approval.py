# 48bd_card_approval.py
# سير موافقة على البطاقات الطويلة (٣/٤ ساعات افتراضيًّا):
#   • القصيرة (نصف/ساعة/ساعتين) تُصدَر فورًا.
#   • الطويلة تُنشئ طلب موافقة معلّق (لا بطاقة) + إشعار للإدارة.
#   • الموافقة → تُولَّد البطاقة بنفس الآليّة (شراء السوق) وتُحقن بصفحة المشترك.
#   • الرفض → إشعار المشترك، ولا يُحتسب أنّه أخذ بطاقة (لا صفّ issued_cards).
# شرط عامّ يُضبط من «إعدادات البطاقات»، مع إعفاء يدويّ لمستفيدين من قائمتهم.

import json

from flask import jsonify, request


_APPROVAL_CODES_DEFAULT = "three_hours,four_hours"


def card_approval_codes() -> set:
    """أكواد الفئات التي تتطلّب موافقة (من الإعدادات). فارغ = الموافقة مُعطّلة."""
    row = get_radius_settings_row() or {}
    raw = row.get("long_card_approval_codes")
    if raw is None:
        raw = _APPROVAL_CODES_DEFAULT
    return {c.strip() for c in str(raw or "").split(",") if c.strip()}


def is_card_approval_exempt(beneficiary_id) -> bool:
    if not beneficiary_id:
        return False
    try:
        row = query_one(
            "SELECT 1 AS x FROM card_approval_exemptions WHERE beneficiary_id=%s LIMIT 1",
            [int(beneficiary_id)],
        )
        return bool(row)
    except Exception:
        return False


def needs_card_approval(beneficiary_id, category_code) -> bool:
    code = (category_code or "").strip()
    if not code or code not in card_approval_codes():
        return False
    return not is_card_approval_exempt(beneficiary_id)


def set_card_approval_exempt(beneficiary_id, exempt: bool) -> None:
    bid = int(beneficiary_id or 0)
    if not bid:
        return
    if exempt:
        try:
            execute_sql(
                "INSERT INTO card_approval_exemptions (beneficiary_id) VALUES (%s) "
                "ON CONFLICT (beneficiary_id) DO NOTHING",
                [bid],
            )
        except Exception:
            # SQLite أقدم بلا ON CONFLICT — تحقّق ثم أدرِج
            if not is_card_approval_exempt(bid):
                try:
                    execute_sql("INSERT INTO card_approval_exemptions (beneficiary_id) VALUES (%s)", [bid])
                except Exception:
                    pass
    else:
        execute_sql("DELETE FROM card_approval_exemptions WHERE beneficiary_id=%s", [bid])


def create_card_approval_request(beneficiary_id, category_code, *, usage_reason="", actor_username=""):
    """ينشئ طلب موافقة معلّق (لا يُصدر بطاقة) ويُشعر الطرفين. يُرجع action_id أو 0."""
    payload = json.dumps(
        {"category_code": category_code, "usage_reason": usage_reason, "needs_approval": True},
        ensure_ascii=False,
    )
    row = execute_sql(
        """
        INSERT INTO radius_pending_actions
            (action_type, target_kind, beneficiary_id, payload_json, status,
             attempted_by_mode, notes, requested_by_username)
        VALUES ('generate_user_cards','user',%s,%s,'pending','live',%s,%s)
        RETURNING id
        """,
        [int(beneficiary_id or 0), payload,
         "بطاقة طويلة — بانتظار موافقة الإدارة", actor_username or ""],
        fetchone=True,
    )
    action_id = int((row or {}).get("id") or 0)
    if action_id:
        try:
            from app.services.notification_service import notify_pending_action_created
            notify_pending_action_created(action_id)
        except Exception:
            pass
    return action_id


def _appr_respond(ok, message, status=200):
    """يردّ JSON لطلبات AJAX، أو flash+تحويل لطلبات النموذج العاديّة (صفحة التفاصيل)."""
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"ok": ok, "message": message}), (200 if ok else status)
    flash(message, "success" if ok else "error")
    return redirect(request.referrer or url_for("admin_request_center", type="card"))


def _approval_payload(action):
    raw = action.get("payload_json")
    if isinstance(raw, dict):
        return raw  # Postgres JSONB يعود قاموسًا جاهزًا
    if isinstance(raw, str):
        try:
            return json.loads(raw or "{}")
        except Exception:
            return {}
    return {}


def _category_label_for(code):
    """اسم الفئة العربيّ من كودها (للإشعارات)."""
    code = (code or "").strip()
    if not code:
        return "بطاقة"
    try:
        from app.services.quota_engine import get_category_by_code
        cat = get_category_by_code(code)
        if cat and cat.get("label_ar"):
            return cat["label_ar"]
    except Exception:
        pass
    return {"half_hour": "نصف ساعة", "one_hour": "ساعة", "two_hours": "ساعتين",
            "three_hours": "ثلاث ساعات", "four_hours": "أربع ساعات"}.get(code, code)


# ─── POST /admin/cards/pending/<id>/approve — موافقة: توليد فوريّ من السوق
@app.route("/admin/cards/pending/<int:action_id>/approve", methods=["POST"])
@admin_login_required
def admin_card_approval_approve(action_id):
    from app.services.card_dispatcher import request_card_via_radius

    action = query_one("SELECT * FROM radius_pending_actions WHERE id=%s LIMIT 1", [action_id])
    if not action:
        return _appr_respond(False, "الطلب غير موجود.", 404)
    if action.get("status") != "pending":
        return _appr_respond(False, f"الطلب بحالة «{action.get('status')}» ولا يمكن الموافقة عليه.", 409)

    bid = int(action.get("beneficiary_id") or 0)
    code = (_approval_payload(action).get("category_code") or "").strip()
    if not (bid and code):
        return _appr_respond(False, "بيانات الطلب ناقصة.", 400)

    disp = request_card_via_radius(
        bid, code,
        actor_username=session.get("username") or "admin",
        skip_quota=True, notes="موافقة الإدارة على بطاقة طويلة",
    )
    if not getattr(disp, "ok", False) or not getattr(disp, "issued_card_id", 0):
        return _appr_respond(False, getattr(disp, "message", "تعذّر توليد البطاقة."), 400)

    execute_sql(
        "UPDATE radius_pending_actions SET status='done', executed_by_username=%s, "
        "executed_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP WHERE id=%s",
        [session.get("username") or "admin", action_id],
    )
    try:
        from app.services.notification_service import create_beneficiary_notification
        create_beneficiary_notification(
            bid,
            title=f"تمت الموافقة — بطاقة {_category_label_for(code)}",
            body=f"تمت الموافقة على طلب بطاقة {_category_label_for(code)} وأُصدرت — تجدها في «سجل بطاقاتي» جاهزة للدخول.",
            event_type="generate_user_cards", status="done",
            source_type="radius_pending_actions", source_id=int(action_id),
            action_url="/card/history",
        )
    except Exception:
        pass
    log_action("approve_long_card", "radius_pending_actions", action_id, f"user={bid} code={code}")
    return _appr_respond(True, "تمت الموافقة وأُصدرت البطاقة للمشترك.")


# ─── POST /admin/cards/pending/<id>/reject — رفض: إشعار بلا احتساب بطاقة
@app.route("/admin/cards/pending/<int:action_id>/reject", methods=["POST"])
@admin_login_required
def admin_card_approval_reject(action_id):
    action = query_one(
        "SELECT beneficiary_id, status, payload_json FROM radius_pending_actions WHERE id=%s LIMIT 1",
        [action_id],
    )
    if not action:
        return _appr_respond(False, "الطلب غير موجود.", 404)
    if action.get("status") != "pending":
        return _appr_respond(False, f"الطلب بحالة «{action.get('status')}».", 409)

    cat_label = _category_label_for(_approval_payload(action).get("category_code"))
    reason = clean_csv_value(request.form.get("reason")) or "لم تتم الموافقة"
    execute_sql(
        "UPDATE radius_pending_actions SET status='cancelled', executed_by_username=%s, "
        "executed_at=CURRENT_TIMESTAMP, error_message=%s, updated_at=CURRENT_TIMESTAMP WHERE id=%s",
        [session.get("username") or "admin", reason, action_id],
    )
    bid = int(action.get("beneficiary_id") or 0)
    if bid:
        try:
            from app.services.notification_service import create_beneficiary_notification
            create_beneficiary_notification(
                bid,
                title=f"تم رفض طلبك — بطاقة {cat_label}",
                body=f"لم تتم الموافقة على طلب بطاقة {cat_label}. ({reason}) يمكنك طلب بطاقة أقصر (نصف/ساعة/ساعتين) فورًا.",
                event_type="generate_user_cards", status="failed",
                source_type="radius_pending_actions", source_id=int(action_id),
                action_url="/card",
            )
        except Exception:
            pass
    log_action("reject_long_card", "radius_pending_actions", action_id, f"user={bid} reason={reason}")
    return _appr_respond(True, "تم رفض الطلب وإشعار المشترك.")
