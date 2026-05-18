# Continued split from 40_user_activation_patch_routes.py lines 210-335. Loaded by app.legacy.


def _patched_admin_portal_accounts_page():
    one_time_code = ""
    one_time_label = ""
    if request.method == "POST":
        action = clean_csv_value(request.form.get("action", "save")) or "save"
        beneficiary_id = int(clean_csv_value(request.form.get("beneficiary_id", "0")) or "0")
        is_active = request.form.get("is_active", "1") == "1"
        beneficiary_row = query_one("SELECT id, full_name, phone FROM beneficiaries WHERE id=%s LIMIT 1", [beneficiary_id]) if beneficiary_id > 0 else None
        username = normalize_portal_username(clean_csv_value(request.form.get("username")) or clean_csv_value((beneficiary_row or {}).get("phone")))
        if beneficiary_id <= 0 or not beneficiary_row or not username:
            flash("المستفيد ورقم الجوال الصحيح حقول مطلوبة.", "error")
            return redirect(url_for("admin_portal_accounts_page"))
        existing = query_one("SELECT * FROM beneficiary_portal_accounts WHERE beneficiary_id=%s LIMIT 1", [beneficiary_id])
        if action == "save":
            if existing:
                execute_sql(
                    """
                    UPDATE beneficiary_portal_accounts
                    SET username=%s, is_active=%s, portal_membership_active=TRUE, portal_access_state='active', must_set_password=TRUE, updated_at=CURRENT_TIMESTAMP
                    WHERE beneficiary_id=%s
                    """,
                    [username, is_active, beneficiary_id],
                )
                portal_id = existing["id"]
                action_label = "update"
            else:
                row = execute_sql(
                    """
                    INSERT INTO beneficiary_portal_accounts (
                        beneficiary_id, username, password_hash, is_active, portal_membership_active, portal_access_state, must_set_password
                    ) VALUES (%s,%s,%s,%s,TRUE,'active',TRUE)
                    RETURNING id
                    """,
                    [beneficiary_id, username, "", is_active],
                    fetchone=True,
                )
                portal_id = row["id"] if row else None
                action_label = "create"
            one_time_code = issue_activation_code_for_portal_account(portal_id)
            one_time_label = "رمز التفعيل"
            log_action("manage_portal_account", "beneficiary_portal_account", portal_id, f"{action_label} portal account for beneficiary {beneficiary_id}")
            flash("تم حفظ الحساب وتوليد رمز تفعيل جديد.", "success")
        elif action in {"regenerate_code", "send_code"}:
            if not existing:
                flash("لا يوجد حساب بوابة لهذا المستفيد بعد.", "error")
                return redirect(url_for("admin_portal_accounts_page"))
            portal_id = existing["id"]
            one_time_code = issue_activation_code_for_portal_account(portal_id)
            one_time_label = "رمز التفعيل"
            if action == "send_code":
                flash("لا يوجد مزود SMS مهيأ حاليًا. تم توليد رمز جديد وعرضه لك مرة واحدة فقط.", "info")
            else:
                flash("تمت إعادة توليد رمز التفعيل.", "success")
            log_action("manage_portal_account", "beneficiary_portal_account", portal_id, f"{action} for beneficiary {beneficiary_id}")
        else:
            flash("الإجراء المطلوب غير معروف.", "error")
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
        f"<option value='{r['id']}'>{safe(r.get('full_name'))} - {safe(normalize_phone(r.get('phone')) or '-')}</option>"
        for r in beneficiaries
    )
    rows_html = ""
    for row in accounts:
        rows_html += f"""
        <tr>
          <td>{row['id']}</td>
          <td>{safe(row.get('full_name'))}</td>
          <td>{safe(row.get('username'))}</td>
          <td>{'نشط' if row.get('is_active') else 'متوقف'}</td>
          <td>{'نعم' if row.get('must_set_password') else 'لا'}</td>
          <td>{format_dt_short(row.get('activated_at'))}</td>
          <td>{format_dt_short(row.get('last_activation_sent_at'))}</td>
          <td>
            <div class='actions'>
              <form method='POST'>
                <input type='hidden' name='action' value='regenerate_code'>
                <input type='hidden' name='beneficiary_id' value='{row['beneficiary_id']}'>
                <input type='hidden' name='username' value='{safe(row.get('username'))}'>
                <input type='hidden' name='is_active' value='{"1" if row.get("is_active") else "0"}'>
                <button class='btn btn-soft' type='submit'>إعادة توليد رمز التفعيل</button>
              </form>
              <form method='POST'>
                <input type='hidden' name='action' value='send_code'>
                <input type='hidden' name='beneficiary_id' value='{row['beneficiary_id']}'>
                <input type='hidden' name='username' value='{safe(row.get('username'))}'>
                <input type='hidden' name='is_active' value='{"1" if row.get("is_active") else "0"}'>
                <button class='btn btn-secondary' type='submit'>إرسال رمز التفعيل</button>
              </form>
            </div>
          </td>
        </tr>
        """
    code_card = f"<div class='flash info'><strong>{safe(one_time_label)}:</strong> <span style='font-size:18px'>{safe(one_time_code)}</span><br><span class='small'>اعرضه للمستفيد الآن، لأنه لن يظهر مرة أخرى.</span></div>" if one_time_code else ""
    content = f"""
    <div class='hero'><div><h1>حسابات بوابة المستفيدين</h1><p>رقم الجوال هو اسم المستخدم الافتراضي، وأول دخول يتم عبر رمز تفعيل ثم تعيين كلمة مرور دائمة.</p></div></div>
    {code_card}
    <div class='card'>
      <form method='POST'>
        <input type='hidden' name='action' value='save'>
        <div class='grid grid-2'>
          <div><label>المستفيد</label><select name='beneficiary_id' required>{options}</select></div>
          <div><label>رقم الجوال</label><input name='username' placeholder='سيُستخدم رقم الجوال افتراضيًا'></div>
          <div><label>الحالة</label><select name='is_active'><option value='1'>نشط</option><option value='0'>متوقف</option></select></div>
        </div>
        <div class='actions' style='margin-top:16px'><button class='btn btn-primary' type='submit'>حفظ الحساب وتوليد رمز تفعيل</button></div>
      </form>
    </div>
    <div class='table-wrap' style='margin-top:16px'>
      <table>
        <thead><tr><th>#</th><th>المستفيد</th><th>اسم المستخدم</th><th>الحالة</th><th>الحساب يحتاج تفعيل</th><th>تاريخ التفعيل</th><th>آخر إرسال</th><th>إجراءات</th></tr></thead>
        <tbody>{rows_html or "<tr><td colspan='8'>لا توجد حسابات حتى الآن.</td></tr>"}</tbody>
      </table>
    </div>
    """
    return render_page("حسابات بوابة المستفيدين", content)
