# Portal account access state controls: active, frozen, disabled.
from flask import jsonify, request


@app.route("/admin/portal-accounts/<int:portal_id>/access-state", methods=["POST"])
@admin_login_required
def admin_portal_account_access_state(portal_id):
    row = query_one(
        "SELECT id, username, beneficiary_id FROM beneficiary_portal_accounts WHERE id=%s",
        [portal_id],
    )
    if not row:
        return jsonify({"ok": False, "message": "الحساب غير موجود."}), 404

    state = clean_csv_value(request.form.get("state") or "")
    if state not in {"active", "frozen", "disabled"}:
        return jsonify({"ok": False, "message": "اختر حالة صحيحة: تفعيل، تجميد، أو تعطيل."}), 400

    is_active = state != "disabled"
    execute_sql(
        """
        UPDATE beneficiary_portal_accounts
           SET is_active=%s,
               portal_access_state=%s,
               portal_membership_active=TRUE,
               updated_at=CURRENT_TIMESTAMP
         WHERE id=%s
        """,
        [is_active, state, portal_id],
    )
    labels = {
        "active": "تم تفعيل حساب البوابة.",
        "frozen": "تم تجميد الحساب مؤقتًا. يستطيع المشترك الدخول لتحديث ملفه فقط.",
        "disabled": "تم تعطيل حساب البوابة. سيطلب من المشترك مراجعة الإدارة.",
    }
    try:
        log_action(
            "portal_access_state",
            "beneficiary_portal_account",
            portal_id,
            f"{row.get('username')} -> {state}",
        )
    except Exception:
        pass
    return jsonify({"ok": True, "message": labels[state], "state": state, "is_active": is_active})
