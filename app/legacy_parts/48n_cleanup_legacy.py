# 48n_cleanup_legacy.py
# تنظيف جذري:
#   1) login → يوجّه المشترك للبوابة الجديدة (/card أو /user/account) حسب access_mode
#   2) /user/dashboard القديم → redirect للبوابة الجديدة
#   3) كل /user/cards/* → 302 إلى /card/*
#   4) كل /cards/* و /users/* → 302 إلى /card/* و /user/*
#   5) /internet/* → 302 إلى /user/internet/*
#   6) لا تصميم قديم يظهر للمشترك مطلقًا

from flask import redirect, request, session


def _portal_access_mode_for_beneficiary(beneficiary_row):
    try:
        mode = get_beneficiary_access_mode(beneficiary_row)
    except Exception:
        mode = ""
    return (mode or "cards").strip().lower()


def _portal_target_for_beneficiary(beneficiary_id):
    """يحدد البوابة المناسبة للمشترك حسب نوعه وطريقة الاتصال."""
    if not beneficiary_id:
        return "/user/login"
    try:
        ben = query_one(
            """SELECT id, user_type,
                      university_internet_method, freelancer_internet_method
               FROM beneficiaries WHERE id=%s LIMIT 1""",
            [int(beneficiary_id)],
        ) or {}
    except Exception:
        return "/card"

    if _portal_access_mode_for_beneficiary(ben) == "username":
        return "/user/account"
    return "/card"


# ════════════════════════════════════════════════════════════════
# (1) Override user_dashboard → redirect للبوابة المناسبة
# ════════════════════════════════════════════════════════════════
if "user_dashboard" in app.view_functions:
    @user_login_required
    def _redirect_user_dashboard():
        bid = session.get("beneficiary_id")
        target = _portal_target_for_beneficiary(bid)
        return redirect(target, code=302)
    app.view_functions["user_dashboard"] = _redirect_user_dashboard


# ════════════════════════════════════════════════════════════════
# (2) Override user_login POST → بدل ما يروح /user/dashboard
#     يروح للبوابة الجديدة مباشرةً
# ════════════════════════════════════════════════════════════════
_prev_user_login = app.view_functions.get("user_login")


def _redesigned_user_login():
    """تسجيل دخول المشترك — يوجّه للبوابة الجديدة مباشرةً."""
    if session.get("portal_type") == "beneficiary" and session.get("beneficiary_id"):
        return redirect(_portal_target_for_beneficiary(session.get("beneficiary_id")))
    if session.get("portal_type") == "admin" and session.get("account_id"):
        return redirect("/admin/dashboard")

    if request.method == "POST":
        username = normalize_portal_username(request.form.get("username"))
        password = clean_csv_value(request.form.get("password"))
        row = get_beneficiary_portal_account_by_username(username)
        if not row:
            flash("بيانات الدخول غير صحيحة.", "error")
            return redirect(url_for("user_login"))
        if portal_account_is_locked(row):
            flash("تم إيقاف المحاولة مؤقتًا. يرجى المحاولة لاحقًا.", "error")
            return redirect(url_for("user_login"))
        if row.get("must_set_password"):
            flash("الحساب يحتاج تفعيل. استخدم رقم الجوال ورمز التفعيل أولًا.", "error")
            return redirect(url_for("user_activate"))
        if verify_portal_password(row.get("password_hash"), password):
            finalize_beneficiary_portal_login(row)
            log_action(
                "beneficiary_login",
                "beneficiary_portal_account",
                row["id"],
                f"Portal login for beneficiary {row['beneficiary_id']}",
            )
            # ✅ هنا التحوّل الجوهري — نروح للبوابة الجديدة
            return redirect(_portal_target_for_beneficiary(row["beneficiary_id"]))
        register_portal_failed_attempt(row["id"])
        flash("بيانات الدخول غير صحيحة.", "error")
        return redirect(url_for("user_login"))

    # GET — استخدم الـ view الأصلي لعرض النموذج
    if _prev_user_login is not None:
        return _prev_user_login()
    return redirect("/portal")


if "user_login" in app.view_functions:
    app.view_functions["user_login"] = _redesigned_user_login


@app.route("/card/login", methods=["GET", "POST"])
def card_login():
    """Dedicated login entry for card subscribers; auth logic stays shared."""
    return _redesigned_user_login()


@app.route("/card/logout")
@user_login_required
def card_logout():
    """Dedicated logout exit for card subscribers."""
    log_action(
        "beneficiary_logout",
        "beneficiary_portal_account",
        session.get("beneficiary_portal_account_id"),
        f"Card portal logout for beneficiary {session.get('beneficiary_id')}",
    )
    session.clear()
    return redirect("/card/login")


_prev_user_logout = app.view_functions.get("user_logout")


@user_login_required
def _three_layer_user_logout():
    if _prev_user_logout is not None:
        _prev_user_logout()
    else:
        session.clear()
    return redirect("/user/login?mode=user")


if "user_logout" in app.view_functions:
    app.view_functions["user_logout"] = _three_layer_user_logout


def _redirect_with_query(target_url, code=None):
    qs = request.query_string.decode("utf-8", errors="ignore")
    if qs:
        target_url += ("&" if "?" in target_url else "?") + qs
    return redirect(target_url, code=code or (308 if request.method != "GET" else 302))


_STRICT_EXACT_REDIRECTS = {
    "/dashboard": "/admin/dashboard",
    "/accounts": "/admin/accounts",
    "/accounts/add": "/admin/accounts/add",
    "/audit-log": "/admin/audit-log",
    "/beneficiaries": "/admin/beneficiaries",
    "/beneficiaries/add": "/admin/beneficiaries/add",
    "/exports": "/admin/exports",
    "/export_csv": "/admin/exports/csv",
    "/download_template": "/admin/exports/template",
    "/backup_sql": "/admin/backup-sql",
    "/import": "/admin/import",
    "/import_csv": "/admin/import/upload",
    "/profile": "/admin/profile",
    "/timer": "/admin/timer",
    "/usage-logs": "/admin/usage-logs",
    "/usage-archive": "/admin/usage-archive",
    "/admin/archive": "/admin/usage-archive",
    "/admin-control": "/admin/system-cleanup",
    "/cards": "/card",
    "/cards/history": "/card/history",
    "/cards/pending": "/card/pending",
    "/cards/request": "/card/request",
    "/users/account": "/user/account",
    "/users/change-password": "/user/account/change-password",
    "/users/unblock-site": "/user/account/unblock-site",
    "/users/speed-upgrade": "/user/account/speed-upgrade",
    "/users/requests": "/user/account/requests",
    "/users/internet/request": "/user/internet/request",
    "/users/internet/my-requests": "/user/internet/my-requests",
    "/users/internet/my-access": "/user/internet/my-access",
    "/internet/request": "/user/internet/request",
    "/internet/my-requests": "/user/internet/my-requests",
    "/internet/my-access": "/user/internet/my-access",
    "/user/cards": "/card",
    "/user/cards/history": "/card/history",
    "/user/cards/pending": "/card/pending",
    "/user/cards/request": "/card/request",
}


_STRICT_PREFIX_REDIRECTS = [
    ("/accounts/edit/", "/admin/accounts/edit/"),
    ("/accounts/toggle/", "/admin/accounts/toggle/"),
    ("/beneficiaries/edit/", "/admin/beneficiaries/edit/"),
    ("/beneficiaries/delete/", "/admin/beneficiaries/delete/"),
    ("/beneficiaries/add_usage/", "/admin/beneficiaries/add_usage/"),
    ("/beneficiaries/bulk-delete", "/admin/beneficiaries/bulk-delete"),
    ("/beneficiaries/export-selected", "/admin/beneficiaries/export-selected"),
    ("/beneficiaries/reset-weekly-usage", "/admin/beneficiaries/reset-weekly-usage"),
    ("/usage-logs/archive", "/admin/usage-logs/archive"),
    ("/usage-logs/archive-before", "/admin/usage-logs/archive-before"),
    ("/usage-logs/clear", "/admin/usage-logs/clear"),
    ("/usage-logs/clear-before", "/admin/usage-logs/clear-before"),
    ("/usage-archive/export", "/admin/usage-archive/export"),
    ("/usage-archive/restore", "/admin/usage-archive/restore"),
    ("/usage-archive/restore-before", "/admin/usage-archive/restore-before"),
    ("/usage-archive/clear", "/admin/usage-archive/clear"),
]


@app.before_request
def _enforce_three_layer_paths():
    path = request.path.rstrip("/") if request.path != "/" else request.path
    if session.get("portal_type") == "beneficiary" and session.get("beneficiary_id"):
        current_target = _portal_target_for_beneficiary(session.get("beneficiary_id"))
        if current_target == "/user/account" and (path == "/card" or path.startswith("/card/")):
            if path != "/card/logout":
                return _redirect_with_query("/user/account")
        if current_target == "/card" and (path == "/user/account" or path.startswith("/user/account/")):
            return _redirect_with_query("/card")

    target = _STRICT_EXACT_REDIRECTS.get(path)
    if target:
        return _redirect_with_query(target)
    if path.startswith("/import_status/"):
        return _redirect_with_query(f"/admin/import/{path.removeprefix('/import_status/')}/status")
    if path.startswith("/import_progress/"):
        return _redirect_with_query(f"/admin/import/{path.removeprefix('/import_progress/')}/progress")
    for old_prefix, new_prefix in _STRICT_PREFIX_REDIRECTS:
        if path == old_prefix or path.startswith(old_prefix):
            suffix = path[len(old_prefix):]
            return _redirect_with_query(new_prefix + suffix)
    return None


# ════════════════════════════════════════════════════════════════
# (3) Redirect old /user/cards/* → /card/*
# (4) Redirect legacy /users/* and /cards/* → /user/* and /card/*
# (5) Redirect legacy /internet/* → /user/internet/*
# ════════════════════════════════════════════════════════════════
def _make_redirect(target_url, methods):
    """factory لإنشاء view function تعيد redirect لـ target_url مع الحفاظ على query string."""
    def _redirect_view(**kwargs):
        url = target_url
        # عوّض المعلمات الديناميكية مثل <int:request_id>
        if kwargs:
            try:
                url = url.format(**kwargs)
            except (KeyError, IndexError):
                pass
        qs = request.query_string.decode("utf-8", errors="ignore")
        if qs:
            url += ("&" if "?" in url else "?") + qs
        return redirect(url, code=302)
    return _redirect_view


_LEGACY_REDIRECTS = [
    # endpoint                          new_url_template
    ("user_cards_dashboard",            "/card"),
    ("user_cards_request",              "/card/request"),
    ("user_cards_history",              "/card/history"),
    ("user_cards_pending_list",         "/card/pending"),

    ("internet_request_page",           "/user/internet/request"),
    ("internet_my_requests_page",       "/user/internet/my-requests"),
    ("internet_my_access_page",         "/user/internet/my-access"),
]


_CANONICAL_ALIAS_ENDPOINTS = [
    ("_alias__user_cards_dashboard__card", "user_cards_dashboard"),
    ("_alias__user_cards_request__card_request", "user_cards_request"),
    ("_alias__user_cards_history__card_history", "user_cards_history"),
    ("_alias__user_cards_pending_list__card_pending", "user_cards_pending_list"),
]


for alias_endpoint, source_endpoint in _CANONICAL_ALIAS_ENDPOINTS:
    if alias_endpoint in app.view_functions and source_endpoint in app.view_functions:
        app.view_functions[alias_endpoint] = app.view_functions[source_endpoint]


for endpoint, new_url in _LEGACY_REDIRECTS:
    if endpoint in app.view_functions:
        # ملاحظة مهمة: الـ aliases في 48i_url_reorganization تم تسجيلها
        # على الـ NEW urls بـ endpoint مختلف (`_alias__...`), فهي ستبقى تعمل
        # وتستخدم view_func الأصلي. عندما نستبدل الـ original endpoint هنا
        # بـ redirect, تتأثر الـ OLD url فقط.
        app.view_functions[endpoint] = _make_redirect(new_url, methods=("GET", "POST"))


_ALIAS_REDIRECTS = [
    ("_alias__user_cards_dashboard__cards", "/card"),
    ("_alias__user_cards_request__cards_request", "/card/request"),
    ("_alias__user_cards_history__cards_history", "/card/history"),
    ("_alias__user_cards_pending_list__cards_pending", "/card/pending"),
    ("_alias__user_account_dashboard__users_account", "/user/account"),
    ("_alias__user_account_change_password__users_change-password", "/user/account/change-password"),
    ("_alias__user_account_unblock_site__users_unblock-site", "/user/account/unblock-site"),
    ("_alias__user_account_speed_upgrade__users_speed-upgrade", "/user/account/speed-upgrade"),
    ("_alias__user_account_my_requests__users_requests", "/user/account/requests"),
    ("_alias__user_internet_request_page__users_internet_request", "/user/internet/request"),
    ("_alias__user_internet_my_requests_page__users_internet_my-requests", "/user/internet/my-requests"),
    ("_alias__user_internet_my_access_page__users_internet_my-access", "/user/internet/my-access"),
]


for endpoint, new_url in _ALIAS_REDIRECTS:
    if endpoint in app.view_functions:
        app.view_functions[endpoint] = _make_redirect(new_url, methods=("GET", "POST"))
