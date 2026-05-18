# Auto-split from app/legacy.py lines 2442-2517. Loaded by app.legacy.
def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if session.get("portal_type") == "beneficiary":
            flash("هذه الصفحة مخصصة للإدارة فقط.", "error")
            return redirect(url_for("user_dashboard"))
        if not session.get("account_id"):
            return redirect(url_for("login"))
        session["portal_type"] = "admin"
        return view(*args, **kwargs)
    return wrapped


def admin_login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if session.get("portal_type") == "beneficiary":
            flash("هذه الصفحة مخصصة للإدارة فقط.", "error")
            return redirect(url_for("user_dashboard"))
        if not session.get("account_id"):
            return redirect(url_for("login"))
        session["portal_type"] = "admin"
        return view(*args, **kwargs)
    return wrapped


admin_login_required = login_required


def user_login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if session.get("portal_type") == "admin" and session.get("account_id"):
            flash("هذه الصفحة مخصصة للمستفيدين فقط.", "error")
            return redirect("/admin/dashboard")
        if session.get("portal_type") != "beneficiary" or not session.get("beneficiary_id"):
            if session.get("portal_type") == "beneficiary":
                session.clear()
            if request.path.startswith("/card"):
                return redirect("/card/login")
            return redirect(url_for("user_login"))
        if session.get("portal_access_state") == "frozen" and not request.path.startswith("/user/profile"):
            flash("حسابك مجمّد مؤقتًا. يمكنك تحديث ملفك الشخصي ثم مراجعة الإدارة.", "warning")
            return redirect(url_for("user_profile_page"))
        return view(*args, **kwargs)
    return wrapped


def admin_permission_required(permission_name):
    return permission_required(permission_name)


def user_owns_beneficiary(param_name="beneficiary_id"):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            beneficiary_id = kwargs.get(param_name)
            if beneficiary_id is None:
                beneficiary_id = request.view_args.get(param_name) if request.view_args else None
            if int(session.get("beneficiary_id") or 0) != int(beneficiary_id or 0):
                flash("غير مسموح بالوصول إلى بيانات مستفيد آخر.", "error")
                return redirect(url_for("user_dashboard"))
            return view(*args, **kwargs)
        return wrapped
    return decorator


def permission_required(permission_name):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if session.get("portal_type") == "beneficiary":
                flash("هذه الصفحة مخصصة للإدارة فقط.", "error")
                return redirect(url_for("user_dashboard"))
            if not session.get("account_id"):
                return redirect(url_for("login"))
            if not has_permission(permission_name):
                flash("غير مصرح لك بهذه العملية.", "error")
                return redirect(url_for("dashboard"))
            return view(*args, **kwargs)
        return wrapped
    return decorator


def render_page(title, content):
    return render_template_string(BASE_TEMPLATE, title=title, content=content)
