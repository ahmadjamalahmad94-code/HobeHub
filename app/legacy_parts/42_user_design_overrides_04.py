# Continued split from 42_user_design_overrides.py lines 412-478. Loaded by app.legacy.


def _clean_user_login():
    if session.get("portal_type") == "beneficiary" and session.get("beneficiary_id"):
        return redirect(url_for("user_dashboard"))
    if session.get("portal_type") == "admin" and session.get("account_id"):
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        username = normalize_portal_username(request.form.get("username"))
        password = clean_csv_value(request.form.get("password"))
        row = get_beneficiary_portal_account_by_username(username)
        if not row:
            flash("\u0628\u064a\u0627\u0646\u0627\u062a \u0627\u0644\u062f\u062e\u0648\u0644 \u063a\u064a\u0631 \u0635\u062d\u064a\u062d\u0629.", "error")
            return redirect(url_for("user_login"))
        if portal_account_is_locked(row):
            flash("\u062a\u0645 \u0625\u064a\u0642\u0627\u0641 \u0627\u0644\u0645\u062d\u0627\u0648\u0644\u0629 \u0645\u0624\u0642\u062a\u064b\u0627. \u064a\u0631\u062c\u0649 \u0627\u0644\u0645\u062d\u0627\u0648\u0644\u0629 \u0644\u0627\u062d\u0642\u064b\u0627.", "error")
            return redirect(url_for("user_login"))
        if row.get("must_set_password"):
            flash("\u0627\u0644\u062d\u0633\u0627\u0628 \u064a\u062d\u062a\u0627\u062c \u062a\u0641\u0639\u064a\u0644. \u0627\u0633\u062a\u062e\u062f\u0645 \u0631\u0642\u0645 \u0627\u0644\u062c\u0648\u0627\u0644 \u0648\u0631\u0645\u0632 \u0627\u0644\u062a\u0641\u0639\u064a\u0644 \u0623\u0648\u0644\u064b\u0627.", "error")
            return redirect(url_for("user_activate"))
        if verify_portal_password(row.get("password_hash"), password):
            finalize_beneficiary_portal_login(row)
            log_action("beneficiary_login", "beneficiary_portal_account", row["id"], f"Portal login for beneficiary {row['beneficiary_id']}")
            return redirect(url_for("user_dashboard"))
        register_portal_failed_attempt(row["id"])
        flash("\u0628\u064a\u0627\u0646\u0627\u062a \u0627\u0644\u062f\u062e\u0648\u0644 \u063a\u064a\u0631 \u0635\u062d\u064a\u062d\u0629.", "error")
        return redirect(url_for("user_login"))
    content = """
    <section class="portal-auth-hero">
      <div>
        <span class="badge badge-blue">بوابة المشتركين</span>
        <h1>تسجيل دخول المشترك</h1>
        <p>ادخل برقم الجوال وكلمة المرور بعد تفعيل الحساب، ثم انتقل مباشرة إلى واجهة المشترك المناسبة لنوع خدمتك.</p>
      </div>
      <div class="portal-feature-list">
        <div><i class="fa-solid fa-gauge-high"></i><span>متابعة الحالة والطلبات</span></div>
        <div><i class="fa-solid fa-user-shield"></i><span>واجهة منفصلة عن الإدارة</span></div>
        <div><i class="fa-solid fa-clock"></i><span>مصممة لخدمات الإنترنت المجانية</span></div>
      </div>
    </section>
    <div class="portal-panel portal-auth-panel">
      <form method="POST">
        <div class="grid grid-2">
          <div><label>رقم الجوال</label><input name="username" required></div>
          <div><label>كلمة المرور</label><input type="password" name="password" required></div>
        </div>
        <div class="actions" style="margin-top:16px">
          <button class="btn btn-primary" type="submit">تسجيل الدخول</button>
          <a class="btn btn-soft" href="/user/activate">تفعيل الحساب</a>
          <a class="btn btn-soft" href="/user/register">تسجيل اشتراك</a>
          <a class="btn btn-soft" href="/login">دخول الإدارة</a>
        </div>
      </form>
    </div>
    """
    return render_user_page("تسجيل دخول المشترك", content)


app.view_functions["user_register"] = _clean_user_register
app.view_functions["user_login"] = _clean_user_login
app.view_functions["user_dashboard"] = user_login_required(_designed_user_dashboard)
app.view_functions["user_profile_page"] = user_login_required(_designed_user_profile_page)
app.view_functions["user_internet_access_page"] = user_login_required(_designed_user_internet_access_page)
app.view_functions["user_internet_request_page"] = user_login_required(_designed_user_internet_request_page)
app.view_functions["user_internet_my_requests_page"] = user_login_required(_designed_user_internet_my_requests_page)
app.view_functions["user_internet_my_access_page"] = user_login_required(_designed_user_internet_access_page)
app.view_functions["admin_portal_accounts_page"] = admin_login_required(permission_required("manage_portal_accounts", "manage_accounts")(_patched_admin_portal_accounts_page))
