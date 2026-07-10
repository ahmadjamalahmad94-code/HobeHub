# Continued split from 38_admin_internet_request_routes.py lines 103-262. Loaded by app.legacy.


@app.route("/admin/internet-requests")
@login_required
@permission_required("manage_internet_requests")
def admin_internet_requests_page():
    process_due_speed_restores()
    status_filter = clean_csv_value(request.args.get("status", ""))
    where = []
    params = []
    if status_filter:
        where.append("r.status=%s")
        params.append(status_filter)
    sql = """
    SELECT r.*, b.full_name
    FROM internet_service_requests r
    JOIN beneficiaries b ON b.id = r.beneficiary_id
    """
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY CASE WHEN r.status='pending' THEN 0 WHEN r.status='approved' THEN 1 ELSE 2 END, r.id DESC"
    rows = query_all(sql, params)
    items = ""
    for row in rows:
        items += f"""
        <tr>
          <td>{row['id']}</td>
          <td>{safe(row.get('full_name'))}</td>
          <td>{safe(internet_request_type_label(row.get('request_type')))}</td>
          <td>{internet_request_status_pill(row.get('status'))}</td>
          <td>{safe(row.get('requested_by')) or '-'}</td>
          <td>{format_dt_short(row.get('created_at'))}</td>
          <td><a class='btn btn-soft btn-icon' href='{url_for("admin_internet_request_detail_page", request_id=row["id"])}' title='مراجعة'><i class='fa-solid fa-eye'></i></a></td>
        </tr>
        """
    content = f"""
    <div class='hero'>
      <div><h1>إدارة طلبات الإنترنت</h1><p>مراجعة الطلبات واعتمادها وتنفيذها داخل Hobe Hub.</p></div>
      <div class='actions'>
        <a class='btn btn-soft' href='{url_for("radius_settings_page")}'>إعدادات RADIUS</a>
        <a class='btn btn-secondary' href='{url_for("radius_online_users_page")}'>المستخدمون المتصلون</a>
      </div>
    </div>
    <div class='card'>
      <form method='GET' class='filters'>
        <div>
          <label>الحالة</label>
          <select name='status'>
            <option value=''>الكل</option>
            <option value='pending' {'selected' if status_filter=='pending' else ''}>قيد المراجعة</option>
            <option value='approved' {'selected' if status_filter=='approved' else ''}>تمت الموافقة</option>
            <option value='executed' {'selected' if status_filter=='executed' else ''}>تم التنفيذ</option>
            <option value='failed' {'selected' if status_filter=='failed' else ''}>فشل التنفيذ</option>
            <option value='rejected' {'selected' if status_filter=='rejected' else ''}>مرفوض</option>
          </select>
        </div>
        <div class='actions' style='align-items:end'><button class='btn btn-primary' type='submit'>تحديث</button></div>
      </form>
    </div>
    <div class='table-wrap' style='margin-top:16px'>
      <table>
        <thead><tr><th>#</th><th>المستفيد</th><th>النوع</th><th>الحالة</th><th>أنشأه</th><th>التاريخ</th><th>إجراءات</th></tr></thead>
        <tbody>{items or "<tr><td colspan='7'>لا توجد طلبات.</td></tr>"}</tbody>
      </table>
    </div>
    """
    return render_page("إدارة طلبات الإنترنت", content)


def render_admin_internet_request_detail(request_row: dict):
    requested_payload = json_safe_dict(request_row.get("requested_payload"))
    admin_payload = json_safe_dict(request_row.get("admin_payload"))
    linked_account = get_radius_account(request_row["beneficiary_id"]) or {}
    merged_username = get_request_external_username(request_row, linked_account)
    actions_html = ""
    if request_row.get("status") == "pending" and has_permission("approve_internet_requests"):
        actions_html += f"""
        <div class='card' style='margin-top:16px'>
          <h3>اعتماد / تجهيز الطلب</h3>
          <form method='POST' action='{url_for("admin_internet_request_approve", request_id=request_row["id"])}'>
            <div class='grid grid-2'>
              <div><label>اسم المستخدم الخارجي</label><input name='external_username' value='{safe(merged_username)}'></div>
              <div><label>رقم / اسم البروفايل</label><div class='grid grid-2'><input name='profile_id' value='{safe(admin_payload.get("profile_id") or requested_payload.get("profile_id"))}' placeholder='profile_id'><input name='profile_name' value='{safe(admin_payload.get("profile_name") or requested_payload.get("profile_name"))}' placeholder='profile_name'></div></div>
              <div><label>مدة رفع السرعة بالدقائق</label><input name='duration_minutes' type='number' min='1' value='{safe(admin_payload.get("duration_minutes") or requested_payload.get("duration_minutes") or "60")}'></div>
              <div><label>البروفايل الأصلي</label><input name='original_profile_id' value='{safe(admin_payload.get("original_profile_id") or linked_account.get("current_profile_id"))}'></div>
              <div><label>عدد البطاقات</label><input name='card_count' type='number' min='1' value='{safe(admin_payload.get("card_count") or requested_payload.get("card_count") or "1")}'></div>
              <div><label>إضافة وقت</label><div class='grid grid-2'><input name='time_amount' type='number' min='1' value='{safe(admin_payload.get("time_amount") or requested_payload.get("time_amount"))}'><select name='time_unit'><option value='minutes'>دقائق</option><option value='hours'>ساعات</option><option value='days'>أيام</option></select></div></div>
              <div><label>إضافة كوتة MB</label><input name='quota_amount_mb' type='number' min='1' value='{safe(admin_payload.get("quota_amount_mb") or requested_payload.get("quota_amount_mb"))}'></div>
              <div><label>رفع / تنزيل منفصل</label><div class='grid grid-2'><input name='upload_quota_mb' type='number' min='0' value='{safe(admin_payload.get("upload_quota_mb") or requested_payload.get("upload_quota_mb"))}' placeholder='رفع'><input name='download_quota_mb' type='number' min='0' value='{safe(admin_payload.get("download_quota_mb") or requested_payload.get("download_quota_mb"))}' placeholder='تنزيل'></div></div>
              <div><label>MAC</label><input name='mac_address' value='{safe(admin_payload.get("mac_address") or requested_payload.get("mac_address"))}'></div>
              <div><label>كلمة مرور جديدة</label><input name='new_password' value=''></div>
            </div>
            <div style='margin-top:12px'><label>ملاحظات الإدارة</label><textarea name='notes'>{safe(admin_payload.get("notes") or requested_payload.get("notes"))}</textarea></div>
            <div class='actions' style='margin-top:12px'><button class='btn btn-primary' type='submit'><i class='fa-solid fa-check'></i> اعتماد الطلب</button></div>
          </form>
          <form method='POST' action='{url_for("admin_internet_request_reject", request_id=request_row["id"])}' style='margin-top:12px'>
            <label>سبب الرفض</label><textarea name='reason' placeholder='اكتب سببًا واضحًا للمراجعة'></textarea>
            <div class='actions' style='margin-top:12px'><button class='btn btn-danger' type='submit'><i class='fa-solid fa-ban'></i> رفض الطلب</button></div>
          </form>
        </div>
        """
    if request_row.get("status") in {"approved", "failed"} and has_permission("execute_radius_actions"):
        actions_html += f"""
        <div class='card' style='margin-top:16px'>
          <h3>تنفيذ الطلب خارجيًا</h3>
          <p class='muted'>سيتم استدعاء endpoint المناسب في app_ad مع حفظ النتيجة داخل النظام.</p>
          <form method='POST' action='{url_for("admin_internet_request_execute", request_id=request_row["id"])}'>
            <button class='btn btn-accent' type='submit'><i class='fa-solid fa-play'></i> تنفيذ الطلب</button>
          </form>
        </div>
        """
    api_response = json_safe_dict(request_row.get("api_response"))
    content = f"""
    <div class='hero'>
      <div><h1>مراجعة طلب إنترنت #{request_row['id']}</h1><p>{safe(request_row.get('full_name'))} - {safe(internet_request_type_label(request_row.get('request_type')))}</p></div>
      <div class='actions'><a class='btn btn-soft' href='{url_for("admin_internet_requests_page")}'>رجوع للقائمة</a></div>
    </div>
    <div class='grid grid-2'>
      <div class='card'><h3>ملخص الطلب</h3><div class='grid grid-2'><div><label>الحالة</label><div>{internet_request_status_pill(request_row.get('status'))}</div></div><div><label>أنشأه</label><div>{safe(request_row.get('requested_by')) or '-'}</div></div><div><label>آخر مراجعة</label><div>{safe(request_row.get('reviewed_by')) or '-'} / {format_dt_short(request_row.get('reviewed_at'))}</div></div><div><label>آخر تنفيذ</label><div>{format_dt_short(request_row.get('executed_at'))}</div></div></div></div>
      <div class='card'><h3>الربط الخارجي</h3><div class='grid grid-2'><div><label>اسم المستخدم الخارجي</label><div>{safe(linked_account.get('external_username')) or safe(merged_username) or '-'}</div></div><div><label>البروفايل الحالي</label><div>{safe(linked_account.get('current_profile_name')) or safe(linked_account.get('current_profile_id')) or '-'}</div></div></div></div>
    </div>
    <div class='grid grid-2' style='margin-top:16px'><div class='card'><h3>بيانات الطلب</h3><pre>{safe(json.dumps(requested_payload, ensure_ascii=False, indent=2))}</pre></div><div class='card'><h3>بيانات الإدارة</h3><pre>{safe(json.dumps(admin_payload, ensure_ascii=False, indent=2))}</pre></div></div>
    <div class='card' style='margin-top:16px'><h3>النتيجة الخارجية</h3><div><strong>Endpoint:</strong> {safe(request_row.get('api_endpoint')) or '-'}</div><div style='margin-top:8px'><strong>خطأ:</strong> {safe(request_row.get('error_message')) or '-'}</div><pre style='margin-top:12px'>{safe(json.dumps(api_response, ensure_ascii=False, indent=2)) if api_response else '-'}</pre></div>
    {actions_html}
    """
    return render_page("مراجعة طلب إنترنت", content)


@app.route("/admin/internet-requests/<int:request_id>")
@login_required
@permission_required("manage_internet_requests")
def admin_internet_request_detail_page(request_id):
    process_due_speed_restores()
    row = get_internet_request_row(request_id)
    if not row:
        flash("الطلب غير موجود.", "error")
        return redirect(url_for("admin_internet_requests_page"))
    return render_admin_internet_request_detail(row)


@app.route("/admin/internet-requests/<int:request_id>/approve", methods=["POST"])
@login_required
@permission_required("approve_internet_requests")
def admin_internet_request_approve(request_id):
    row = get_internet_request_row(request_id)
    if not row:
        flash("الطلب غير موجود.", "error")
        return redirect(url_for("admin_internet_requests_page"))
    admin_payload = normalize_admin_request_form(request.form)
    update_internet_service_request(
        request_id,
        status="approved",
        admin_payload=admin_payload,
        reviewed_by=session.get("username", ""),
        reviewed_at=now_local(),
        error_message="",
    )
    log_action("approve_internet_request", "internet_request", request_id, f"Approve {row.get('request_type')}")
    # ── ربط الريديوس: اعتماد طلب «إنشاء يوزر» يُزوِّده فعليًّا على الريديوس ──
    radius_note = ""
    if clean_csv_value(row.get("request_type")) == "create_user":
        try:
            acct = query_one(
                "SELECT external_username, plain_password, current_profile_id "
                "FROM beneficiary_radius_accounts WHERE beneficiary_id=%s LIMIT 1",
                [row.get("beneficiary_id")]) or {}
            ru = clean_csv_value(acct.get("external_username"))
            rp = acct.get("plain_password") or ""
            if ru and rp:
                from app.services.radius_provisioning import provision_subscriber
                pr = provision_subscriber(
                    beneficiary_id=row.get("beneficiary_id"), username=ru, password=rp,
                    profile_id=clean_csv_value(acct.get("current_profile_id")) or "",
                    requested_by=session.get("username") or "admin")
                if pr.get("ok") and pr.get("live"):
                    execute_sql(
                        "UPDATE beneficiary_radius_accounts SET status='active', "
                        "updated_at=CURRENT_TIMESTAMP WHERE beneficiary_id=%s",
                        [row.get("beneficiary_id")])
                    radius_note = " وأُنشئ اليوزر على الريديوس."
                elif not pr.get("ok"):
                    radius_note = f" (تنبيه ريديوس: {pr.get('message')})"
        except Exception:
            pass
    try:
        from app.services.notification_service import notify_internet_request_status
        notify_internet_request_status(request_id, "approved", actor_name=session.get("username", ""))
    except Exception:
        pass
    flash("تمت الموافقة على الطلب وتجهيزه للتنفيذ." + radius_note, "success")
    return redirect(url_for("admin_request_center_detail", source="internet", request_id=request_id))
