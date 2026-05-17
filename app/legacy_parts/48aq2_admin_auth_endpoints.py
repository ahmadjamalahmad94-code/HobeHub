# 48aq2_admin_auth_endpoints.py
# ─────────────────────────────────────────────────────────────────────
# endpoints دخول الإدارة — مقيّدة للمدراء (app_accounts) فقط
# تُستخدم حصراً من بوابة الإدارة الفاخرة: /h0be-vault-9k2x7p/master-gateway
#
# المسارات:
#   POST /admin-auth/check   → يتحقق من وجود حساب الإدمن
#   POST /admin-auth/submit  → يتحقق من كلمة المرور ويفتح الجلسة
#
# /login/check و /login/submit لا تقبل المدراء بعد الآن
# ─────────────────────────────────────────────────────────────────────

import logging
from flask import jsonify, request, session, url_for

_log = logging.getLogger("hobehub.admin_auth")


def _normalize_admin_identifier(raw):
    return (raw or "").strip()


# ────────────────────────────────────────────────────────────────
# POST /admin-auth/check — هل يوجد حساب إدمن بهذا اليوزرنيم؟
# ────────────────────────────────────────────────────────────────
@app.route("/admin-auth/check", methods=["POST"])
def admin_auth_check():
    """يتحقق من وجود حساب الإدمن — لا يكشف أي بيانات مشتركين."""
    ident = _normalize_admin_identifier(
        request.form.get("identifier") or request.form.get("username") or ""
    )
    if not ident:
        return jsonify({"ok": False, "message": "أدخل اسم المستخدم."}), 400

    try:
        admin = query_one(
            "SELECT id, username, full_name, is_active FROM app_accounts WHERE username=%s LIMIT 1",
            [ident],
        )
    except Exception as e:
        _log.exception("admin_auth_check db error")
        return jsonify({"ok": False, "message": "خطأ في الاتصال. حاول مرة أخرى."}), 500

    if not admin:
        # لا نكشف إن كان السبب عدم الوجود أم خطأ في الإدخال
        return jsonify({"ok": False, "message": "بيانات الدخول غير صحيحة."}), 401

    if not admin.get("is_active"):
        return jsonify({"ok": False, "message": "هذا الحساب معطّل. تواصل مع المسؤول."}), 403

    return jsonify({
        "ok": True,
        "type": "admin",
        "state": "active",
        "label": admin.get("full_name") or admin.get("username"),
        "next": "password",
    })


# ────────────────────────────────────────────────────────────────
# POST /admin-auth/submit — كلمة المرور وفتح جلسة الإدارة
# ────────────────────────────────────────────────────────────────
@app.route("/admin-auth/submit", methods=["POST"])
def admin_auth_submit():
    """يتحقق من كلمة مرور الإدمن ويفتح الجلسة الإدارية."""
    ident = _normalize_admin_identifier(
        request.form.get("identifier") or request.form.get("username") or ""
    )
    password = (request.form.get("password") or "").strip()

    if not ident or not password:
        return jsonify({"ok": False, "message": "أدخل بياناتك كاملة."}), 400

    try:
        admin = query_one(
            "SELECT * FROM app_accounts WHERE username=%s AND is_active=TRUE LIMIT 1",
            [ident],
        )
    except Exception:
        _log.exception("admin_auth_submit db error")
        return jsonify({"ok": False, "message": "خطأ في الاتصال. حاول مرة أخرى."}), 500

    if not admin:
        return jsonify({"ok": False, "message": "بيانات الدخول غير صحيحة."}), 401

    failure_key = auth_failure_key("admin", ident)
    if is_auth_limited(failure_key):
        return jsonify({"ok": False, "message": "تم إيقاف المحاولات مؤقتًا. حاول لاحقًا."}), 429

    if not verify_admin_password(admin.get("password_hash"), password):
        register_auth_failure(failure_key)
        _log.warning("admin_auth_submit: wrong password for %s", ident)
        return jsonify({"ok": False, "message": "كلمة المرور غير صحيحة."}), 401

    # كلمة المرور صحيحة — افتح الجلسة
    try:
        maybe_upgrade_admin_password(admin["id"], password, admin.get("password_hash"))
    except Exception:
        pass

    clear_auth_failures(failure_key)
    session.clear()
    session["portal_type"] = "admin"
    session["account_id"] = admin["id"]
    session["username"] = admin["username"]
    session["full_name"] = admin["full_name"]

    try:
        refresh_session_permissions(admin["id"])
    except Exception:
        pass

    try:
        log_action("login", "account", admin["id"], "تسجيل دخول إدمن (بوابة فاخرة)")
    except Exception:
        pass

    _log.info("admin_auth_submit: login success for %s", ident)

    try:
        redirect_url = url_for("dashboard")
    except Exception:
        redirect_url = "/admin/dashboard"

    return jsonify({
        "ok": True,
        "redirect": redirect_url,
        "label": admin.get("full_name") or admin.get("username"),
    })
