# Continued split from 20_beneficiary_table_helpers.py lines 123-264. Loaded by app.legacy.



def build_beneficiary_filters(args_dict):
    filters = ["1=1"]
    params = []
    q = args_dict["q"]
    if q:
        from app.services.smart_search import smart_search_clause
        clause, clause_params = smart_search_clause(
            q,
            text_columns=("search_name", "full_name"),
            phone_columns=("phone",),
            extra_columns=(
                "tawjihi_year",
                "tawjihi_branch",
                "freelancer_specialization",
                "freelancer_company",
                "university_name",
                "university_number",
                "university_college",
                "university_specialization",
            ),
        )
        if clause:
            filters.append(clause)
            params.extend(clause_params)

    if args_dict["user_type"]:
        filters.append("user_type = %s")
        params.append(args_dict["user_type"])
    if args_dict["tawjihi_year"]:
        filters.append("tawjihi_year = %s")
        params.append(args_dict["tawjihi_year"])
    if args_dict["tawjihi_branch"]:
        filters.append("tawjihi_branch = %s")
        params.append(args_dict["tawjihi_branch"])
    if args_dict["university_name"]:
        filters.append("university_name = %s")
        params.append(args_dict["university_name"])
    if args_dict["university_college"]:
        filters.append("university_college ILIKE %s")
        params.append(f"%{args_dict['university_college']}%")
    if args_dict["university_specialization"]:
        filters.append("university_specialization ILIKE %s")
        params.append(f"%{args_dict['university_specialization']}%")
    if args_dict["freelancer_specialization"]:
        filters.append("freelancer_specialization ILIKE %s")
        params.append(f"%{args_dict['freelancer_specialization']}%")
    if args_dict["freelancer_company"]:
        filters.append("freelancer_company ILIKE %s")
        params.append(f"%{args_dict['freelancer_company']}%")

    if args_dict["internet_method"] == "cards":
        filters.append("""
        (
          (user_type='freelancer' AND freelancer_internet_method='نظام البطاقات')
          OR (user_type='university' AND university_internet_method='نظام البطاقات')
        )
        """)
    elif args_dict["internet_method"] == "username":
        filters.append("""
        (
          (user_type='freelancer' AND freelancer_internet_method='يمتلك اسم مستخدم')
          OR (user_type='university' AND university_internet_method='يمتلك اسم مستخدم')
        )
        """)

    seg = (args_dict.get("segment") or "").strip()
    if seg == "cards":
        filters.append("""
        (
          user_type='tawjihi'
          OR (user_type='university' AND COALESCE(university_internet_method,'') NOT IN ('يوزر إنترنت','يمتلك اسم مستخدم','username'))
          OR (user_type='freelancer' AND COALESCE(freelancer_internet_method,'') NOT IN ('يوزر إنترنت','يمتلك اسم مستخدم','username'))
        )
        """)
    elif seg == "username":
        filters.append("""
        (
          (user_type='university' AND COALESCE(university_internet_method,'') IN ('يوزر إنترنت','يمتلك اسم مستخدم','username'))
          OR (user_type='freelancer' AND COALESCE(freelancer_internet_method,'') IN ('يوزر إنترنت','يمتلك اسم مستخدم','username'))
        )
        """)

    return filters, params


def find_duplicate_phone(phone, exclude_id=None):
    phone = normalize_phone(phone)
    if not phone:
        return None
    sql = "SELECT id, full_name FROM beneficiaries WHERE phone=%s"
    params = [phone]
    if exclude_id is not None:
        sql += " AND id<>%s"
        params.append(exclude_id)
    sql += " LIMIT 1"
    return query_one(sql, params)



def build_beneficiary_row_html(r, selected_type, args_dict, page=1, display_index=None):
    usage_label, limited, count = get_usage_label(r)
    current_qs = build_query_string({**args_dict, "page": page})
    row_class = f"row-type-{safe(r.get('user_type'))}"
    if limited and count >= 3:
        row_class += " row-complete"

    edit_modal_id = f"edit-{r['id']}"
    usage_modal_id = f"usage-{r['id']}"
    actions = []
    modal_parts = []

    if has_permission("edit"):
        edit_action = f"{url_for('edit_beneficiary_page', beneficiary_id=r['id'])}?current_user_type={selected_type}"
        modal_body = format_modal_fields(
            r,
            action=edit_action,
            scope_id=f"scope-{r['id']}",
            submit_label="حفظ التعديلات",
            show_type_selector=True,
        )
        edit_onsubmit = f"<form method=\"POST\" onsubmit=\"return submitBeneficiaryEdit(this, {r['id']}, '{edit_modal_id}')\" action=\""
        modal_body = modal_body.replace('<form method="POST" action="', edit_onsubmit, 1)
        modal_parts.append(f"""
        <div id="{edit_modal_id}" class="modal">
          <div class="modal-card">
            <a href="#!" class="modal-close">×</a>
            <div class="hero" style="margin-bottom:8px"><h1>تعديل المستفيد #{r['id']}</h1><p>{safe(r.get('full_name'))}</p></div>
            {modal_body}
          </div>
        </div>
        """)
        actions.append(f"<a class='btn btn-secondary btn-icon' href='#{edit_modal_id}' title='تعديل'><i class='fa-solid fa-pen'></i></a>")

    if has_permission("delete"):
        delete_url = url_for('delete_beneficiary', beneficiary_id=r['id'])
        actions.append(
            f"<form class='inline-form' method='POST' action='{delete_url}' onsubmit=\"return confirm('هل أنت متأكد من الحذف؟')\"><button class='btn btn-danger btn-icon' type='submit' title='حذف'><i class='fa-solid fa-trash'></i></button></form>"
        )

    if has_permission("usage_counter") and limited and count < 3:
        usage_url = f"{url_for('add_usage', beneficiary_id=r['id'])}?{current_qs}"
        actions.append(
            f"<button class='btn btn-accent btn-icon' type='button' onclick=\"return openGlobalUsageModal({r['id']}, '{usage_url}')\" title='+1 بطاقة'><i class='fa-solid fa-plus'></i></button>"
        )

    type_html = f"<span class='type-badge {get_type_css(r.get('user_type'))}'>{get_type_label(r.get('user_type'))}</span>"
    added_by = safe(r.get('added_by_username')) or '-'
    created_at = format_dt_short(r.get('created_at'))
    notes = safe(r.get('notes')) or '-'
    number_cell = safe(display_index if display_index is not None else r['id'])

    if selected_type == "tawjihi":
        row_cells = [number_cell, safe(r['full_name']), safe(r['phone']), safe(r['tawjihi_year']), safe(r['tawjihi_branch']), usage_label, added_by, created_at, notes, " ".join(actions) if actions else "-"]
    elif selected_type == "university":
        row_cells = [number_cell, safe(r['full_name']), safe(r['phone']), safe(r.get('university_number')), safe(r['university_name']), safe(r['university_college']), safe(r['university_specialization']), usage_label, added_by, created_at, notes, " ".join(actions) if actions else "-"]
    elif selected_type == "freelancer":
        row_cells = [number_cell, safe(r['full_name']), safe(r['phone']), safe(r['freelancer_specialization']), safe(r['freelancer_company']), usage_label, added_by, created_at, notes, " ".join(actions) if actions else "-"]
    else:
        row_cells = [number_cell, safe(r['full_name']), safe(r['phone']), type_html, usage_label, added_by, created_at, notes, " ".join(actions) if actions else "-"]

    row_html = f"<tr id='beneficiary-row-{r['id']}' class='{row_class}'>" + ''.join([f"<td class='cell-wrap'>{cell}</td>" for cell in row_cells]) + "</tr>"
    return row_html, "".join(modal_parts)
