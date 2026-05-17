# 48w_quick_edit_api.py — JSON API لتعديل المستفيد كاملًا من modal

from flask import jsonify, request, session


# ════════════════════════════════════════════════
# GET/POST /admin/beneficiaries/<id>/quick-edit
# ════════════════════════════════════════════════
@app.route("/admin/beneficiaries/<int:beneficiary_id>/quick-edit", methods=["GET", "POST"])
@login_required
@permission_required("edit")
def admin_beneficiary_quick_edit(beneficiary_id):
    row = query_one("SELECT * FROM beneficiaries WHERE id=%s", [beneficiary_id])
    if not row:
        return jsonify({"ok": False, "message": "المستفيد غير موجود."}), 404

    if request.method == "GET":
        # كل الحقول
        return jsonify({
            "ok": True,
            "data": {
                "id": row["id"],
                "user_type": row.get("user_type"),
                "first_name": row.get("first_name") or "",
                "second_name": row.get("second_name") or "",
                "third_name": row.get("third_name") or "",
                "fourth_name": row.get("fourth_name") or "",
                "phone": row.get("phone") or "",
                "tawjihi_year": row.get("tawjihi_year") or "",
                "tawjihi_branch": row.get("tawjihi_branch") or "",
                "university_name": row.get("university_name") or "",
                "university_number": row.get("university_number") or "",
                "university_college": row.get("university_college") or "",
                "university_specialization": row.get("university_specialization") or "",
                "university_days": row.get("university_days") or "",
                "university_internet_method": row.get("university_internet_method") or "",
                "freelancer_specialization": row.get("freelancer_specialization") or "",
                "freelancer_company": row.get("freelancer_company") or "",
                "freelancer_schedule_type": row.get("freelancer_schedule_type") or "",
                "freelancer_internet_method": row.get("freelancer_internet_method") or "",
                "notes": row.get("notes") or "",
                "full_name": row.get("full_name") or "",
            }
        })

    # POST — تطبيق التعديل
    f = request.form
    first_name = clean_csv_value(f.get("first_name"))
    second_name = clean_csv_value(f.get("second_name"))
    third_name = clean_csv_value(f.get("third_name"))
    fourth_name = clean_csv_value(f.get("fourth_name"))
    phone = normalize_phone(f.get("phone"))
    notes = clean_csv_value(f.get("notes", row.get("notes") or ""))

    # validate phone
    if phone and len(phone) != 10:
        return jsonify({"ok": False, "message": "رقم الجوال يجب أن يكون 10 أرقام."}), 400
    if phone and phone != (row.get("phone") or ""):
        dup = find_duplicate_phone(phone, exclude_id=beneficiary_id)
        if dup:
            return jsonify({"ok": False, "message": f"رقم الجوال مستخدم: {dup.get('full_name')}"}), 400

    full_name = full_name_from_parts(first_name, second_name, third_name, fourth_name) or row.get("full_name")
    search_name = normalize_search_ar(full_name)
    # نسمح بتغيير user_type (مثلاً توجيهي ← جامعي بعد التخرج)
    ut_raw = clean_csv_value(f.get("user_type") or "") or (row.get("user_type") or "")
    ut = (ut_raw or "").lower()
    if ut not in ("tawjihi", "university", "freelancer"):
        ut = (row.get("user_type") or "").lower()

    # Fields per user_type
    tawjihi_year = clean_csv_value(f.get("tawjihi_year", row.get("tawjihi_year") or "")) if ut == "tawjihi" else (row.get("tawjihi_year") or "")
    tawjihi_branch = clean_csv_value(f.get("tawjihi_branch", row.get("tawjihi_branch") or "")) if ut == "tawjihi" else (row.get("tawjihi_branch") or "")

    if ut == "university":
        university_name = clean_csv_value(f.get("university_name", row.get("university_name") or ""))
        university_number = clean_csv_value(f.get("university_number", row.get("university_number") or ""))
        university_college = clean_csv_value(f.get("university_college", row.get("university_college") or ""))
        university_specialization = clean_csv_value(f.get("university_specialization", row.get("university_specialization") or ""))
        university_days = clean_csv_value(f.get("university_days", row.get("university_days") or ""))
        university_internet_method = clean_csv_value(f.get("university_internet_method", row.get("university_internet_method") or ""))
    else:
        university_name = row.get("university_name") or ""
        university_number = row.get("university_number") or ""
        university_college = row.get("university_college") or ""
        university_specialization = row.get("university_specialization") or ""
        university_days = row.get("university_days") or ""
        university_internet_method = row.get("university_internet_method") or ""

    if ut == "freelancer":
        freelancer_specialization = clean_csv_value(f.get("freelancer_specialization", row.get("freelancer_specialization") or ""))
        freelancer_company = clean_csv_value(f.get("freelancer_company", row.get("freelancer_company") or ""))
        freelancer_schedule_type = clean_csv_value(f.get("freelancer_schedule_type", row.get("freelancer_schedule_type") or ""))
        freelancer_internet_method = clean_csv_value(f.get("freelancer_internet_method", row.get("freelancer_internet_method") or ""))
    else:
        freelancer_specialization = row.get("freelancer_specialization") or ""
        freelancer_company = row.get("freelancer_company") or ""
        freelancer_schedule_type = row.get("freelancer_schedule_type") or ""
        freelancer_internet_method = row.get("freelancer_internet_method") or ""

    execute_sql(
        """
        UPDATE beneficiaries SET
            user_type=%s,
            first_name=%s, second_name=%s, third_name=%s, fourth_name=%s,
            full_name=%s, search_name=%s, phone=%s,
            tawjihi_year=%s, tawjihi_branch=%s,
            university_name=%s, university_number=%s, university_college=%s,
            university_specialization=%s, university_days=%s, university_internet_method=%s,
            freelancer_specialization=%s, freelancer_company=%s,
            freelancer_schedule_type=%s, freelancer_internet_method=%s,
            notes=%s
        WHERE id=%s
        """,
        [ut,
         first_name, second_name, third_name, fourth_name,
         full_name, search_name, phone,
         tawjihi_year, tawjihi_branch,
         university_name, university_number, university_college,
         university_specialization, university_days, university_internet_method,
         freelancer_specialization, freelancer_company,
         freelancer_schedule_type, freelancer_internet_method,
         notes, beneficiary_id],
    )
    old_ut = (row.get("user_type") or "").lower()
    if ut != old_ut:
        log_action("type_change", "beneficiary", beneficiary_id, f"تغيير النوع: {old_ut or '—'} ← {ut}")
    log_action("quick_edit_full", "beneficiary", beneficiary_id, f"تعديل كامل: {full_name}")
    try:
        from app.services.notification_service import notify_beneficiary_profile_updated
        notify_beneficiary_profile_updated(
            beneficiary_id,
            session.get("username") or "",
            "راجع ملفك للتأكد من صحة البيانات.",
        )
    except Exception:
        pass

    return jsonify({
        "ok": True,
        "message": "تم حفظ التعديلات.",
        "data": {
            "id": beneficiary_id,
            "first_name": first_name, "second_name": second_name,
            "third_name": third_name, "fourth_name": fourth_name,
            "phone": phone, "full_name": full_name,
        }
    })


# ════════════════════════════════════════════════
# POST /admin/beneficiaries/<id>/delete-ajax — حذف JSON
# ════════════════════════════════════════════════
@app.route("/admin/beneficiaries/<int:beneficiary_id>/delete-ajax", methods=["POST"])
@login_required
@permission_required("delete")
def admin_beneficiary_delete_ajax(beneficiary_id):
    row = query_one("SELECT full_name FROM beneficiaries WHERE id=%s", [beneficiary_id])
    if not row:
        return jsonify({"ok": False, "message": "المستفيد غير موجود."}), 404
    execute_sql("DELETE FROM beneficiaries WHERE id=%s", [beneficiary_id])
    log_action("delete_beneficiary_ajax", "beneficiary", beneficiary_id, f"حذف: {row.get('full_name')}")
    return jsonify({"ok": True, "message": f"تم حذف {row.get('full_name')}"})


# ════════════════════════════════════════════════
# POST /admin/beneficiaries/bulk-action — عمليات جماعية
# ════════════════════════════════════════════════
@app.route("/admin/beneficiaries/bulk-action", methods=["POST"])
@login_required
@permission_required("edit")
def admin_beneficiary_bulk_action():
    action = clean_csv_value(request.form.get("action"))
    ids_raw = request.form.getlist("ids[]") or request.form.getlist("ids")
    ids = []
    for v in ids_raw:
        try:
            ids.append(int(v))
        except (TypeError, ValueError):
            continue
    if not ids:
        return jsonify({"ok": False, "message": "لم يتم اختيار أي مستفيد."}), 400

    placeholders = ",".join(["%s"] * len(ids))

    if action == "delete":
        if not has_permission("delete"):
            return jsonify({"ok": False, "message": "ليس لديك صلاحية حذف."}), 403
        count_row = query_one(f"SELECT COUNT(*) AS c FROM beneficiaries WHERE id IN ({placeholders})", ids) or {}
        n = int(count_row.get("c") or 0)
        execute_sql(f"DELETE FROM beneficiaries WHERE id IN ({placeholders})", ids)
        log_action("bulk_delete", "beneficiary", 0, f"حذف جماعي ({n})، ids={ids}")
        return jsonify({"ok": True, "message": f"تم حذف {n} مستفيد."})

    if action == "reset_weekly":
        execute_sql(f"UPDATE beneficiaries SET weekly_usage_count=0 WHERE id IN ({placeholders})", ids)
        log_action("bulk_reset_weekly", "beneficiary", 0, f"تصفير عداد ({len(ids)})")
        return jsonify({"ok": True, "message": f"تم تصفير عداد الأسبوع لـ {len(ids)} مستفيد."})

    if action == "switch_to_cards":
        execute_sql(
            f"""
            UPDATE beneficiaries SET
                university_internet_method=CASE WHEN user_type='university' THEN 'نظام البطاقات' ELSE university_internet_method END,
                freelancer_internet_method=CASE WHEN user_type='freelancer' THEN 'نظام البطاقات' ELSE freelancer_internet_method END
            WHERE id IN ({placeholders})
            """,
            ids,
        )
        log_action("bulk_switch_cards", "beneficiary", 0, f"تحويل لبطاقات ({len(ids)})")
        return jsonify({"ok": True, "message": f"تم تحويل {len(ids)} لنظام البطاقات."})

    if action == "switch_to_username":
        execute_sql(
            f"""
            UPDATE beneficiaries SET
                university_internet_method=CASE WHEN user_type='university' THEN 'يوزر إنترنت' ELSE university_internet_method END,
                freelancer_internet_method=CASE WHEN user_type='freelancer' THEN 'يوزر إنترنت' ELSE freelancer_internet_method END
            WHERE id IN ({placeholders}) AND user_type IN ('university','freelancer')
            """,
            ids,
        )
        log_action("bulk_switch_username", "beneficiary", 0, f"تحويل ليوزر ({len(ids)})")
        return jsonify({"ok": True, "message": f"تم تحويل المؤهَّلين منهم إلى يوزر إنترنت."})

    return jsonify({"ok": False, "message": "إجراء غير معروف."}), 400


# ════════════════════════════════════════════════
# POST /admin/beneficiaries/add-ajax — إضافة عبر modal
# ════════════════════════════════════════════════
@app.route("/admin/beneficiaries/add-ajax", methods=["POST"])
@login_required
@permission_required("add")
def admin_beneficiary_add_ajax():
    data = collect_beneficiary_form()
    if not is_valid_new_phone(data.get("phone", "")):
        return jsonify({"ok": False, "message": "رقم الجوال يجب أن يكون 10 أرقام بالضبط ويبدأ بـ 0."}), 400
    duplicate = find_duplicate_phone(data.get("phone"))
    if duplicate:
        return jsonify({"ok": False, "message": f"رقم الجوال مستخدم: {duplicate.get('full_name')}"}), 400
    data["added_by_account_id"] = session.get("account_id")
    data["added_by_username"] = session.get("username")
    try:
        row = execute_sql(
            """
            INSERT INTO beneficiaries (
                user_type, first_name, second_name, third_name, fourth_name,
                full_name, search_name, phone,
                tawjihi_year, tawjihi_branch,
                freelancer_specialization, freelancer_company,
                freelancer_schedule_type, freelancer_internet_method,
                freelancer_time_mode, freelancer_time_from, freelancer_time_to,
                university_name, university_number, university_college,
                university_specialization, university_days,
                university_internet_method, university_time_mode,
                university_time_from, university_time_to,
                weekly_usage_count, weekly_usage_week_start, notes,
                added_by_account_id, added_by_username
            ) VALUES (
                %(user_type)s, %(first_name)s, %(second_name)s, %(third_name)s, %(fourth_name)s,
                %(full_name)s, %(search_name)s, %(phone)s,
                %(tawjihi_year)s, %(tawjihi_branch)s,
                %(freelancer_specialization)s, %(freelancer_company)s,
                %(freelancer_schedule_type)s, %(freelancer_internet_method)s,
                %(freelancer_time_mode)s, %(freelancer_time_from)s, %(freelancer_time_to)s,
                %(university_name)s, %(university_number)s, %(university_college)s,
                %(university_specialization)s, %(university_days)s,
                %(university_internet_method)s, %(university_time_mode)s,
                %(university_time_from)s, %(university_time_to)s,
                0, %(weekly_usage_week_start)s, %(notes)s,
                %(added_by_account_id)s, %(added_by_username)s
            ) RETURNING id
            """,
            data,
            fetchone=True,
        )
    except Exception:
        return jsonify({"ok": False, "message": "تعذّر حفظ المستفيد. ربما رقم الجوال مكرّر."}), 400
    new_id = row["id"] if row else None
    log_action("add_ajax", "beneficiary", new_id, f"إضافة مستفيد (modal): {data.get('full_name')}")
    try:
        from app.services.notification_service import notify_beneficiary_created
        notify_beneficiary_created(int(new_id), session.get("username") or "") if new_id else None
    except Exception:
        pass
    return jsonify({"ok": True, "message": f"تمت إضافة {data.get('full_name')} بنجاح ✓", "id": new_id})


# ════════════════════════════════════════════════
# GET /admin/beneficiaries/rows-ajax — تحميل صفوف القائمة دون reload
# ════════════════════════════════════════════════
from flask import render_template


@app.route("/admin/beneficiaries/rows-ajax")
@login_required
def admin_beneficiaries_rows_ajax():
    # نستخدم نفس مرشحات الصفحة الأصلية
    args_dict = build_request_args_dict() if 'build_request_args_dict' in globals() else dict(request.args)
    filter_clauses, params = build_beneficiary_filters(args_dict)
    where_clause = " AND ".join(filter_clauses) if filter_clauses else "1=1"
    try:
        page = max(1, int(args_dict.get("page") or 1))
    except (TypeError, ValueError):
        page = 1
    per_page = 25
    offset = (page - 1) * per_page

    count_row = query_one(f"SELECT COUNT(*) AS c FROM beneficiaries WHERE {where_clause}", params) or {}
    total = int(count_row.get("c") or 0)
    pages = max(1, (total + per_page - 1) // per_page)

    rows = query_all(
        f"""
        SELECT b.*,
               pa.id AS portal_account_id,
               pa.username AS portal_username,
               pa.is_active AS portal_is_active,
               pa.must_set_password AS portal_must_set_password,
               pa.last_login_at AS portal_last_login_at
        FROM beneficiaries b
        LEFT JOIN beneficiary_portal_accounts pa ON pa.beneficiary_id = b.id
        WHERE {where_clause}
        ORDER BY b.id DESC
        LIMIT %s OFFSET %s
        """,
        params + [per_page, offset],
    )
    if "_enrich_beneficiary_rows" in globals():
        rows = _enrich_beneficiary_rows(rows)

    # KPIs (لتحديث العداد بالتابز)
    kpi_total = (query_one("SELECT COUNT(*) AS c FROM beneficiaries") or {}).get("c") or 0
    kpi_taw = (query_one("SELECT COUNT(*) AS c FROM beneficiaries WHERE user_type='tawjihi'") or {}).get("c") or 0
    kpi_uni = (query_one("SELECT COUNT(*) AS c FROM beneficiaries WHERE user_type='university'") or {}).get("c") or 0
    kpi_free = (query_one("SELECT COUNT(*) AS c FROM beneficiaries WHERE user_type='freelancer'") or {}).get("c") or 0
    kpi_cards = (query_one("""
        SELECT COUNT(*) AS c FROM beneficiaries
        WHERE user_type='tawjihi'
           OR (user_type='university' AND COALESCE(university_internet_method, '') NOT IN ('يوزر إنترنت', 'يمتلك اسم مستخدم', 'username'))
           OR (user_type='freelancer' AND COALESCE(freelancer_internet_method, '') NOT IN ('يوزر إنترنت', 'يمتلك اسم مستخدم', 'username'))
    """) or {}).get("c") or 0
    kpi_username = (query_one("""
        SELECT COUNT(*) AS c FROM beneficiaries
        WHERE (user_type='university' AND COALESCE(university_internet_method, '') IN ('يوزر إنترنت', 'يمتلك اسم مستخدم', 'username'))
           OR (user_type='freelancer' AND COALESCE(freelancer_internet_method, '') IN ('يوزر إنترنت', 'يمتلك اسم مستخدم', 'username'))
    """) or {}).get("c") or 0

    tbody_html = render_template(
        "admin/beneficiaries/_rows_partial.html",
        beneficiaries=rows,
        format_dt_short=format_dt_short,
    )

    return jsonify({
        "ok": True,
        "tbody_html": tbody_html,
        "total": total,
        "page": page,
        "pages": pages,
        "kpis": {
            "total": int(kpi_total or 0),
            "tawjihi": int(kpi_taw or 0),
            "university": int(kpi_uni or 0),
            "freelancer": int(kpi_free or 0),
            "username": int(kpi_username or 0),
            "cards": int(kpi_cards or 0),
        },
    })
