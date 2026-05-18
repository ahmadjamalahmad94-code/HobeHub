# Auto-split from app/legacy.py lines 7849-7996. Loaded by app.legacy.
@app.route("/admin/beneficiaries")
@admin_login_required
def admin_beneficiaries_alias():
    return beneficiaries_page()


@app.route("/admin/accounts")
@admin_login_required
def admin_accounts_alias():
    return accounts_page()


@app.route("/admin/profile", methods=["GET", "POST"])
@admin_login_required
def admin_profile_alias():
    return profile_page()


@app.route("/admin/audit-log")
@admin_login_required
def admin_audit_log_alias():
    return audit_log_page()


@app.route("/admin/usage-logs")
@admin_login_required
def admin_usage_logs_alias():
    return usage_logs_page()


@app.route("/admin/import")
@admin_login_required
def admin_import_alias():
    return import_page()


@app.route("/admin/exports")
@admin_login_required
def admin_exports_alias():
    return export_center()


@app.route("/admin/archive")
@admin_login_required
def admin_archive_alias():
    return usage_archive_page()


@app.route("/admin/system-cleanup")
@admin_login_required
def admin_cleanup_alias():
    return admin_control_panel()


@app.route("/admin/timer")
@admin_login_required
def admin_timer_alias():
    return power_timer_page()


@app.route("/admin/portal-accounts", methods=["GET", "POST"])
@admin_login_required
@permission_required("manage_accounts")
def admin_portal_accounts_page():
    if request.method == "POST":
        beneficiary_id = int(clean_csv_value(request.form.get("beneficiary_id", "0")) or "0")
        username = clean_csv_value(request.form.get("username"))
        password = clean_csv_value(request.form.get("password"))
        is_active = request.form.get("is_active") == "1"
        if beneficiary_id <= 0 or not username or not password:
            flash("المستفيد واسم المستخدم وكلمة المرور حقول مطلوبة.", "error")
            return redirect(url_for("admin_portal_accounts_page"))
        existing = query_one("SELECT * FROM beneficiary_portal_accounts WHERE beneficiary_id=%s LIMIT 1", [beneficiary_id])
        if existing:
            execute_sql(
                """
                UPDATE beneficiary_portal_accounts
                SET username=%s, password_hash=%s, is_active=%s, portal_membership_active=TRUE, portal_access_state='active', updated_at=CURRENT_TIMESTAMP
                WHERE beneficiary_id=%s
                """,
                [username, sha256_text(password), is_active, beneficiary_id],
            )
            portal_id = existing["id"]
            action_label = "update"
        else:
            row = execute_sql(
                """
                INSERT INTO beneficiary_portal_accounts (beneficiary_id, username, password_hash, is_active, portal_membership_active, portal_access_state)
                VALUES (%s,%s,%s,%s,TRUE,'active')
                RETURNING id
                """,
                [beneficiary_id, username, sha256_text(password), is_active],
                fetchone=True,
            )
            portal_id = row["id"] if row else None
            action_label = "create"
        log_action("manage_portal_account", "beneficiary_portal_account", portal_id, f"{action_label} portal account for beneficiary {beneficiary_id}")
        flash("تم حفظ حساب البوابة للمستفيد.", "success")
        return redirect(url_for("admin_portal_accounts_page"))
    beneficiaries = query_all("SELECT id, full_name, phone FROM beneficiaries ORDER BY id DESC LIMIT 500")
    accounts = query_all(
        """
        SELECT pa.*, b.full_name, b.phone
        FROM beneficiary_portal_accounts pa
        JOIN beneficiaries b ON b.id = pa.beneficiary_id
        ORDER BY pa.id DESC
        """
    )
    options = "".join(
        f"<option value='{r['id']}'>{safe(r.get('full_name'))} - {safe(r.get('phone'))}</option>"
        for r in beneficiaries
    )
    rows_html = ""
    for row in accounts:
        rows_html += f"<tr><td>{row['id']}</td><td>{safe(row.get('full_name'))}</td><td>{safe(row.get('username'))}</td><td>{'نشط' if row.get('is_active') else 'متوقف'}</td><td>{format_dt_short(row.get('last_login_at'))}</td></tr>"
    content = f"""
    <div class='hero'><div><h1>حسابات بوابة المستفيدين</h1><p>إنشاء أو تحديث حسابات دخول المستفيدين بشكل منفصل عن حسابات الإدارة.</p></div></div>
    <div class='card'>
      <form method='POST'>
        <div class='grid grid-2'>
          <div><label>المستفيد</label><select name='beneficiary_id' required>{options}</select></div>
          <div><label>اسم المستخدم</label><input name='username' required></div>
          <div><label>كلمة المرور</label><input type='password' name='password' required></div>
          <div><label>الحالة</label><select name='is_active'><option value='1'>نشط</option><option value='0'>متوقف</option></select></div>
        </div>
        <div class='actions' style='margin-top:16px'><button class='btn btn-primary' type='submit'>حفظ الحساب</button></div>
      </form>
    </div>
    <div class='table-wrap' style='margin-top:16px'>
      <table>
        <thead><tr><th>#</th><th>المستفيد</th><th>اسم المستخدم</th><th>الحالة</th><th>آخر دخول</th></tr></thead>
        <tbody>{rows_html or "<tr><td colspan='5'>لا توجد حسابات حتى الآن.</td></tr>"}</tbody>
      </table>
    </div>
    """
    return render_page("حسابات بوابة المستفيدين", content)
