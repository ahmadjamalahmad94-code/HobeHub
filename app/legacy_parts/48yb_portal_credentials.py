# Portal account credential controls.
from flask import jsonify, request


@app.route("/admin/portal-accounts/<int:portal_id>/set-credentials", methods=["POST"])
@login_required
@permission_required("manage_portal_accounts", "manage_accounts")
def admin_portal_account_set_credentials(portal_id):
    row = query_one("SELECT id, username FROM beneficiary_portal_accounts WHERE id=%s", [portal_id])
    if not row:
        return jsonify({"ok": False, "message": "الحساب غير موجود."}), 404

    new_username = clean_csv_value(request.form.get("username") or "") or row.get("username")
    new_password = clean_csv_value(request.form.get("password") or "")
    is_active = request.form.get("is_active", "1") in ("1", "true", "on")
    access_state = "active" if is_active else "disabled"

    if new_username != row.get("username"):
        dup = query_one(
            "SELECT id FROM beneficiary_portal_accounts WHERE username=%s AND id<>%s",
            [new_username, portal_id],
        )
        if dup:
            return jsonify({"ok": False, "message": "اسم المستخدم مستخدم مسبقًا."}), 400

    if new_password:
        execute_sql(
            """
            UPDATE beneficiary_portal_accounts SET
                username=%s, password_hash=%s, password_plain=%s,
                is_active=%s, portal_access_state=%s, must_set_password=FALSE,
                activation_code_hash=NULL, activation_code_expires_at=NULL,
                updated_at=CURRENT_TIMESTAMP
            WHERE id=%s
            """,
            [new_username, _sha256(new_password), new_password, is_active, access_state, portal_id],
        )
    else:
        execute_sql(
            """
            UPDATE beneficiary_portal_accounts SET
                username=%s, is_active=%s, portal_access_state=%s, updated_at=CURRENT_TIMESTAMP
            WHERE id=%s
            """,
            [new_username, is_active, access_state, portal_id],
        )
    log_action(
        "portal_set_credentials",
        "beneficiary_portal_account",
        portal_id,
        f"تعديل بيانات حساب البوابة {new_username}",
    )
    return jsonify({"ok": True, "message": "تم حفظ التعديلات."})
