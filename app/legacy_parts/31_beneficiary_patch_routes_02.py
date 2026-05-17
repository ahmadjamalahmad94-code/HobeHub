# Continued split from 31_beneficiary_patch_routes.py lines 139-248. Loaded by app.legacy.


def _patched_add_beneficiary_page():
    page_title_map = {
        'tawjihi': 'إضافة طالب توجيهي',
        'university': 'إضافة طالب جامعي',
        'freelancer': 'إضافة فري لانسر',
    }
    if request.method == 'POST':
        data = collect_beneficiary_form()
        duplicate = find_duplicate_phone(data.get('phone'))
        if duplicate:
            message = f"رقم الجوال مستخدم مسبقًا للمستفيد: {safe(duplicate.get('full_name'))}."
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'ok': False, 'message': message, 'category': 'error'}), 400
            flash(message, 'error')
            return render_page('إضافة مستفيد', beneficiary_form_html(data, action=url_for('add_beneficiary_page'), title=page_title_map.get(data.get('user_type') or clean_csv_value(request.args.get('user_type', 'tawjihi')) or 'tawjihi', 'إضافة مستفيد')))
        data['added_by_account_id'] = session.get('account_id')
        data['added_by_username'] = session.get('username')
        row = execute_sql("""
            INSERT INTO beneficiaries (
                user_type, first_name, second_name, third_name, fourth_name, full_name, search_name, phone,
                tawjihi_year, tawjihi_branch, freelancer_specialization, freelancer_company,
                freelancer_schedule_type, freelancer_internet_method, freelancer_time_mode,
                freelancer_time_from, freelancer_time_to, university_name, university_number, university_college,
                university_specialization, university_days, university_internet_method,
                university_time_mode, university_time_from, university_time_to,
                weekly_usage_count, weekly_usage_week_start, notes, added_by_account_id, added_by_username
            ) VALUES (
                %(user_type)s, %(first_name)s, %(second_name)s, %(third_name)s, %(fourth_name)s, %(full_name)s, %(search_name)s, %(phone)s,
                %(tawjihi_year)s, %(tawjihi_branch)s, %(freelancer_specialization)s, %(freelancer_company)s,
                %(freelancer_schedule_type)s, %(freelancer_internet_method)s, %(freelancer_time_mode)s,
                %(freelancer_time_from)s, %(freelancer_time_to)s, %(university_name)s, %(university_number)s, %(university_college)s,
                %(university_specialization)s, %(university_days)s, %(university_internet_method)s,
                %(university_time_mode)s, %(university_time_from)s, %(university_time_to)s,
                0, %(weekly_usage_week_start)s, %(notes)s, %(added_by_account_id)s, %(added_by_username)s
            ) RETURNING id
        """, data, fetchone=True)
        new_id = row['id'] if row else None
        log_action('add', 'beneficiary', new_id, f"إضافة مستفيد: {data['full_name']}")
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            inserted_row = query_one('SELECT * FROM beneficiaries WHERE id=%s', [new_id]) if new_id else None
            current_type = clean_csv_value(request.args.get('current_user_type', ''))
            args_dict = build_request_args_dict()
            row_html, modal_html = ('', '')
            if inserted_row and (not current_type or current_type == inserted_row.get('user_type')):
                row_html, modal_html = build_beneficiary_row_html(inserted_row, current_type, args_dict, page=1)
            return jsonify({'ok': True, 'row_html': row_html, 'modal_html': modal_html, 'message': 'تمت إضافة المستفيد.', 'category': 'success', 'reset_form_modal': build_add_beneficiary_modal(current_type or (inserted_row.get('user_type') if inserted_row else 'tawjihi'))})
        flash('تمت إضافة المستفيد.', 'success')
        return redirect(url_for('beneficiaries_page', user_type=data['user_type']))
    page_user_type = clean_csv_value(request.args.get('user_type', 'tawjihi')) or 'tawjihi'
    return render_page('إضافة مستفيد', beneficiary_form_html(action=url_for('add_beneficiary_page'), title=page_title_map.get(page_user_type, 'إضافة مستفيد')))


def _patched_reset_weekly_usage():
    reset_start = get_week_start()
    execute_sql("UPDATE beneficiaries SET weekly_usage_count = 0, weekly_usage_week_start = %s", [reset_start])
    log_action('reset_weekly_usage', 'beneficiary', None, f'تصفير يدوي لكل البطاقات - week_start={reset_start}')
    message = 'تم تجديد جميع البطاقات يدويًا بنجاح.'
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'ok': True, 'message': message, 'category': 'success'})
    flash(message, 'success')
    return redirect(request.referrer or url_for('beneficiaries_page'))


# monkey-patch flask endpoints
app.view_functions['add_beneficiary_page'] = login_required(permission_required('add')(_patched_add_beneficiary_page))
app.view_functions['reset_weekly_usage'] = login_required(permission_required('reset_weekly_usage')(_patched_reset_weekly_usage))



@app.route("/beneficiaries/bulk-delete", methods=["POST"])
@login_required
@permission_required("delete")
def bulk_delete_beneficiaries():
    ids_raw = clean_csv_value(request.form.get("ids", ""))
    ids = [int(x) for x in ids_raw.split(',') if x.strip().isdigit()]
    if not ids:
        flash("لم يتم تحديد أي مستفيد.", "error")
        return redirect(request.referrer or url_for("beneficiaries_page"))
    execute_sql("DELETE FROM beneficiaries WHERE id = ANY(%s)", [ids])
    log_action("bulk_delete", "beneficiary", None, f"حذف جماعي لعدد {len(ids)} مستفيد")
    flash(f"تم حذف {len(ids)} مستفيد بنجاح.", "success")
    return redirect(request.referrer or url_for("beneficiaries_page"))


@app.route("/beneficiaries/export-selected", methods=["POST"])
@login_required
@permission_required("export")
def export_selected_beneficiaries():
    ids_raw = clean_csv_value(request.form.get("ids", ""))
    ids = [int(x) for x in ids_raw.split(',') if x.strip().isdigit()]
    if not ids:
        flash("لم يتم تحديد أي مستفيد.", "error")
        return redirect(request.referrer or url_for("beneficiaries_page"))
    rows = query_all("SELECT * FROM beneficiaries WHERE id = ANY(%s) ORDER BY id DESC", [ids])
    wb = Workbook()
    ws = wb.active
    ws.title = "Selected Beneficiaries"
    headers = ["ID","النوع","الاسم الكامل","الجوال","سنة التوجيهي","فرع التوجيهي","الرقم الجامعي","الجامعة","الكلية","التخصص الجامعي","تخصص الفري لانسر","شركة الفري لانسر","الاستخدام","أضيف بواسطة","التاريخ","ملاحظات"]
    ws.append(headers)
    for r in rows:
        usage_label, _, _ = get_usage_label(r)
        ws.append([r.get("id"), get_type_label(r.get("user_type")), r.get("full_name"), r.get("phone"), r.get("tawjihi_year"), r.get("tawjihi_branch"), r.get("university_number"), r.get("university_name"), r.get("university_college"), r.get("university_specialization"), r.get("freelancer_specialization"), r.get("freelancer_company"), usage_label, r.get("added_by_username"), format_dt_short(r.get("created_at")), r.get("notes")])
    out = io.BytesIO()
    wb.save(out)
    out.seek(0)
    response = Response(out.getvalue(), mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response.headers["Content-Disposition"] = "attachment; filename=selected_beneficiaries.xlsx"
    return response
