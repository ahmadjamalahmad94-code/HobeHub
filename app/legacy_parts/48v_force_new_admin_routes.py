# 48v_force_new_admin_routes.py — حل صارم:
# 1) يسجّل endpoints مفقودة تستخدمها templates قديمة (admin_dashboard_alias, ...)
# 2) snapshot للـ canonical view functions
# 3) إعادة ربط view_functions للـ aliases

from flask import redirect, request


_FORCED_ROUTES = [
    ("/dashboard",                                     "dashboard",                  ["GET"]),
    ("/admin/dashboard",                               "dashboard",                  ["GET"]),
    ("/admin/beneficiaries",                           "beneficiaries_page",         ["GET"]),
    ("/admin/beneficiaries/add",                       "add_beneficiary_page",       ["GET", "POST"]),
    ("/admin/beneficiaries/edit/<int:beneficiary_id>", "edit_beneficiary_page",      ["GET", "POST"]),
    ("/admin/accounts",                                "accounts_page",              ["GET"]),
    ("/admin/accounts/add",                            "add_account",                ["GET", "POST"]),
    ("/admin/accounts/edit/<int:account_id>",          "edit_account",               ["GET", "POST"]),
    ("/admin/profile",                                 "profile_page",               ["GET", "POST"]),
    ("/admin/audit-log",                               "audit_log_page",             ["GET"]),
    ("/admin/usage-logs",                              "usage_logs_page",            ["GET"]),
    ("/admin/import",                                  "import_page",                ["GET"]),
    ("/admin/exports",                                 "export_center",              ["GET"]),
    ("/admin/archive",                                 "usage_archive_page",         ["GET"]),
    ("/admin/system-cleanup",                          "admin_control_panel",        ["GET", "POST"]),
    ("/admin/timer",                                   "power_timer_page",           ["GET"]),
]


# Endpoints مفقودة كانت تستخدمها templates قديمة (BASE_TEMPLATE من 30_template_overrides_*)
# لازم نسجّلها حتى url_for() ما ترمي BuildError
_MISSING_ENDPOINTS_BASE = [
    # endpoint_name, fallback_url
    ("admin_dashboard_alias",       "/admin/_compat/dashboard-alias"),
    ("admin_beneficiaries_alias",   "/admin/_compat/beneficiaries-alias"),
    ("admin_accounts_alias",        "/admin/_compat/accounts-alias"),
    ("admin_profile_alias",         "/admin/_compat/profile-alias"),
    ("admin_audit_log_alias",       "/admin/_compat/audit-log-alias"),
    ("admin_usage_logs_alias",      "/admin/_compat/usage-logs-alias"),
    ("admin_import_alias",          "/admin/_compat/import-alias"),
    ("admin_exports_alias",         "/admin/_compat/exports-alias"),
    ("admin_archive_alias",         "/admin/_compat/archive-alias"),
    ("admin_cleanup_alias",         "/admin/_compat/cleanup-alias"),
    ("admin_timer_alias",           "/admin/_compat/timer-alias"),
]


_CANONICAL_SNAPSHOT = {}
for _, canonical_endpoint, _ in _FORCED_ROUTES:
    if canonical_endpoint in app.view_functions:
        _CANONICAL_SNAPSHOT[canonical_endpoint] = app.view_functions[canonical_endpoint]


def _make_static_proxy(canonical_endpoint):
    target = _CANONICAL_SNAPSHOT.get(canonical_endpoint)
    def _proxy(**kwargs):
        if target is None:
            try:
                return _admin_home_view()
            except Exception:
                from flask import abort
                abort(404)
        return target(**kwargs)
    _proxy.__name__ = f"_forced__{canonical_endpoint}"
    return _proxy


def _make_redirect(target_url):
    def _r(**kwargs):
        return redirect(target_url)
    _r.__name__ = f"_redir__{target_url.strip('/').replace('/', '_').replace('-', '_') or 'root'}"
    return _r


# ── الخطوة 1: ضمن وجود endpoint 'dashboard' ──
_existing_endpoints = {r.endpoint for r in app.url_map.iter_rules()}
if "dashboard" not in _existing_endpoints:
    try:
        def _dashboard_view():
            try:
                return _admin_home_view()
            except Exception:
                return redirect("/admin/dashboard")
        _dashboard_view.__name__ = "dashboard"
        app.add_url_rule("/dashboard", endpoint="dashboard", view_func=_dashboard_view, methods=["GET"])
        _CANONICAL_SNAPSHOT["dashboard"] = _dashboard_view
    except Exception:
        pass


# ── الخطوة 2: سجّل endpoints مفقودة (للحفاظ على url_for من ترميات قديمة) ──
# نسجّلها على fallback URLs فريدة، فالـ url_for() يعمل
_existing_endpoints = {r.endpoint for r in app.url_map.iter_rules()}
for endpoint_name, fallback_url in _MISSING_ENDPOINTS_BASE:
    if endpoint_name in _existing_endpoints:
        continue
    try:
        # كل alias يعيد توجيه للـ canonical URL الجديد
        target = {
            "admin_dashboard_alias":     "/admin/dashboard",
            "admin_beneficiaries_alias": "/admin/beneficiaries",
            "admin_accounts_alias":      "/admin/accounts",
            "admin_profile_alias":       "/admin/profile",
            "admin_audit_log_alias":     "/admin/audit-log",
            "admin_usage_logs_alias":    "/admin/usage-logs",
            "admin_import_alias":        "/admin/import",
            "admin_exports_alias":       "/admin/exports",
            "admin_archive_alias":       "/admin/archive",
            "admin_cleanup_alias":       "/admin/system-cleanup",
            "admin_timer_alias":         "/admin/timer",
        }.get(endpoint_name, "/admin/dashboard")
        app.add_url_rule(
            fallback_url,
            endpoint=endpoint_name,
            view_func=_make_redirect(target),
            methods=["GET"],
        )
    except Exception:
        pass


# ── الخطوة 3: أعد ربط view_functions للـ aliases الموجودة ──
for url, canonical_endpoint, methods in _FORCED_ROUTES:
    try:
        existing_rules = [r for r in app.url_map.iter_rules() if r.rule == url]
        if existing_rules:
            for rule in existing_rules:
                if rule.endpoint == canonical_endpoint:
                    continue
                app.view_functions[rule.endpoint] = _make_static_proxy(canonical_endpoint)
        else:
            unique_endpoint = f"forced__{canonical_endpoint}__{url.strip('/').replace('/', '_').replace('<', '').replace('>', '').replace(':', '_')}"
            existing_endpoints = {r.endpoint for r in app.url_map.iter_rules()}
            if unique_endpoint not in existing_endpoints:
                try:
                    app.add_url_rule(
                        url,
                        endpoint=unique_endpoint,
                        view_func=_make_static_proxy(canonical_endpoint),
                        methods=methods,
                    )
                except Exception:
                    pass
    except Exception:
        pass


_PHASE1_CANONICAL_GET_REDIRECTS = {
    "/admin/home": "/admin/dashboard",
    "/admin/cards/overview": "/admin/cards",
    "/admin/cards/policies": "/admin/cards/settings",
    "/admin/quota-groups": "/admin/cards/settings",
    "/admin/users-account/": "/admin/users-account",
    "/admin/users-account/overview": "/admin/users-account",
    "/admin/radius/users-online": "/admin/radius/online",
}


@app.before_request
def _phase1_navigation_redirects():
    if request.method != "GET":
        return None
    target = _PHASE1_CANONICAL_GET_REDIRECTS.get(request.path)
    if not target:
        return None
    query = request.query_string.decode("utf-8", errors="ignore")
    if query:
        target = f"{target}?{query}"
    return redirect(target, code=302)


if "admin_cards_import_v2_handler" in globals() and "admin_cards_import_page" in app.view_functions:
    app.view_functions["admin_cards_import_page"] = admin_cards_import_v2_handler


_CARD_CANONICAL_ALIASES = {
    "_alias__user_cards_dashboard__card": "_new_cards_dashboard",
    "_alias__user_cards_request__card_request": "_new_cards_request",
    "_alias__user_cards_history__card_history": "user_cards_history",
    "_alias__user_cards_pending_list__card_pending": "user_cards_pending_list",
}

for _alias_endpoint, _function_name in _CARD_CANONICAL_ALIASES.items():
    _target = globals().get(_function_name)
    if _target is not None and _alias_endpoint in app.view_functions:
        app.view_functions[_alias_endpoint] = _target
