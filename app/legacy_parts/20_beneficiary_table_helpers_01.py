# Auto-split from app/legacy.py lines 3906-4168. Loaded by app.legacy.
def build_query_string(args_dict):
    parts = []
    for k, v in args_dict.items():
        if v not in (None, ""):
            parts.append(f"{k}={v}")
    return "&".join(parts)


def beneficiary_sort_link(args_dict, column):
    current_sort = clean_csv_value(args_dict.get("sort_by", "id"))
    current_order = clean_csv_value(args_dict.get("sort_order", "desc"))
    next_order = "asc" if current_sort != column or current_order == "desc" else "desc"
    query = build_query_string({**args_dict, "sort_by": column, "sort_order": next_order, "page": 1})
    return f"?{query}" if query else ""


def format_modal_fields(data=None, action="", scope_id="beneficiary-form", submit_label="حفظ", show_type_selector=True, fixed_user_type=None):
    data = data or {}
    selected_type = clean_csv_value(fixed_user_type or data.get("user_type", "tawjihi")) or "tawjihi"
    years_html = "".join([f'<option value="{y}" {"selected" if safe(data.get("tawjihi_year", "")) == y else ""}>{y}</option>' for y in TAWJIHI_YEARS])
    branches_html = "".join([f'<option value="{b}" {"selected" if safe(data.get("tawjihi_branch", "")) == b else ""}>{b}</option>' for b in TAWJIHI_BRANCHES])
    freelancer_schedule_html = "".join([f'<option value="{x}" {"selected" if safe(data.get("freelancer_schedule_type", "")) == x else ""}>{x}</option>' for x in FREELANCER_SCHEDULE_OPTIONS])
    time_mode_f_html = "".join([f'<option value="{x}" {"selected" if safe(data.get("freelancer_time_mode", "")) == x else ""}>{x}</option>' for x in TIME_MODE_OPTIONS])
    internet_f_html = "".join([f'<option value="{x}" {"selected" if safe(data.get("freelancer_internet_method", "")) == x else ""}>{x}</option>' for x in INTERNET_ACCESS_METHOD_OPTIONS])
    universities_html = "".join([f'<option value="{x}" {"selected" if safe(data.get("university_name", "")) == x else ""}>{x}</option>' for x in UNIVERSITIES_GAZA])
    days_html = "".join([f'<option value="{x}" {"selected" if safe(data.get("university_days", "")) == x else ""}>{x}</option>' for x in UNIVERSITY_DAYS_OPTIONS])
    time_mode_u_html = "".join([f'<option value="{x}" {"selected" if safe(data.get("university_time_mode", "")) == x else ""}>{x}</option>' for x in TIME_MODE_OPTIONS])
    internet_u_html = "".join([f'<option value="{x}" {"selected" if safe(data.get("university_internet_method", "")) == x else ""}>{x}</option>' for x in INTERNET_ACCESS_METHOD_OPTIONS])

    if show_type_selector:
        type_selector_html = f"""
        <div>
          <label>النوع</label>
          <select name="user_type" required onchange="toggleBeneficiarySections(this, '{scope_id}')">
            <option value="tawjihi" {"selected" if selected_type == "tawjihi" else ""}>توجيهي</option>
            <option value="university" {"selected" if selected_type == "university" else ""}>جامعة</option>
            <option value="freelancer" {"selected" if selected_type == "freelancer" else ""}>فري لانسر</option>
          </select>
        </div>
        """
    else:
        type_selector_html = f"""
        <div>
          <label>النوع</label>
          <input value="{get_type_label(selected_type)}" disabled>
          <input type="hidden" name="user_type" value="{selected_type}">
        </div>
        """

    return f"""
    <form method="POST" action="{action}">
      <div id="{scope_id}" data-beneficiary-scope="1">
        <div class="row">
          {type_selector_html}
          <div><label>الاسم الأول</label><input name="first_name" value="{safe(data.get('first_name', ''))}" required></div>
          <div><label>الاسم الثاني</label><input name="second_name" value="{safe(data.get('second_name', ''))}"></div>
          <div><label>الاسم الثالث</label><input name="third_name" value="{safe(data.get('third_name', ''))}"></div>
          <div><label>الاسم الرابع</label><input name="fourth_name" value="{safe(data.get('fourth_name', ''))}"></div>
          <div><label>الجوال</label><input name="phone" value="{safe(data.get('phone', ''))}" maxlength="10" inputmode="numeric" placeholder="0599123456"></div>
        </div>

        <div class="form-section section-tawjihi {'active' if selected_type == 'tawjihi' else ''}">
          <div class="section-title">بيانات التوجيهي</div>
          <div class="row">
            <div><label>سنة التوجيهي</label><select name="tawjihi_year"><option value="">اختر السنة</option>{years_html}</select></div>
            <div><label>فرع التوجيهي</label><select name="tawjihi_branch"><option value="">اختر الفرع</option>{branches_html}</select></div>
          </div>
        </div>

        <div class="form-section section-freelancer {'active' if selected_type == 'freelancer' else ''}">
          <div class="section-title">بيانات الفري لانسر</div>
          <div class="row">
            <div><label>التخصص</label><input name="freelancer_specialization" value="{safe(data.get('freelancer_specialization', ''))}"></div>
            <div><label>الشركة</label><input name="freelancer_company" value="{safe(data.get('freelancer_company', ''))}"></div>
            <div><label>نوع الدوام</label><select name="freelancer_schedule_type"><option value="">اختر نوع الدوام</option>{freelancer_schedule_html}</select></div>
            <div><label>طريقة الاتصال</label><select name="freelancer_internet_method"><option value="">اختر الطريقة</option>{internet_f_html}</select></div>
            <div><label>وضع الوقت</label><select name="freelancer_time_mode"><option value="">اختر وضع الوقت</option>{time_mode_f_html}</select></div>
            <div><label>من ساعة</label><input type="time" name="freelancer_time_from" value="{safe(data.get('freelancer_time_from', ''))}"></div>
            <div><label>إلى ساعة</label><input type="time" name="freelancer_time_to" value="{safe(data.get('freelancer_time_to', ''))}"></div>
          </div>
        </div>

        <div class="form-section section-university {'active' if selected_type == 'university' else ''}">
          <div class="section-title">بيانات الطالب الجامعي</div>
          <div class="row">
            <div><label>الجامعة</label><select name="university_name"><option value="">اختر الجامعة</option>{universities_html}</select></div>
            <div><label>الرقم الجامعي</label><input name="university_number" value="{safe(data.get('university_number', ''))}" inputmode="numeric"></div>
            <div><label>الكلية</label><input name="university_college" value="{safe(data.get('university_college', ''))}"></div>
            <div><label>التخصص</label><input name="university_specialization" value="{safe(data.get('university_specialization', ''))}"></div>
            <div><label>أيام الجامعة</label><select name="university_days"><option value="">اختر الأيام</option>{days_html}</select></div>
            <div><label>طريقة الاتصال</label><select name="university_internet_method"><option value="">اختر الطريقة</option>{internet_u_html}</select></div>
            <div><label>وضع الوقت</label><select name="university_time_mode"><option value="">اختر وضع الوقت</option>{time_mode_u_html}</select></div>
            <div><label>من ساعة</label><input type="time" name="university_time_from" value="{safe(data.get('university_time_from', ''))}"></div>
            <div><label>إلى ساعة</label><input type="time" name="university_time_to" value="{safe(data.get('university_time_to', ''))}"></div>
          </div>
        </div>

        <div class="section-title">ملاحظات</div>
        <div><textarea class="notes-box" name="notes" placeholder="اكتب أي ملاحظة تخص المستفيد">{safe(data.get('notes', ''))}</textarea></div>
      </div>

      <div class="actions" style="margin-top:4px">
        <button class="btn btn-primary" type="submit"><i class="fa-solid fa-floppy-disk"></i> {submit_label}</button>
        <a class="btn btn-soft" href="{url_for('beneficiaries_page')}">رجوع</a>
      </div>
    </form>
    """
def build_request_args_dict():
    return {
        "q": clean_csv_value(request.args.get("q", "")).strip(),
        "user_type": clean_csv_value(request.args.get("user_type", "")).strip(),
        "tawjihi_year": clean_csv_value(request.args.get("tawjihi_year", "")).strip(),
        "tawjihi_branch": clean_csv_value(request.args.get("tawjihi_branch", "")).strip(),
        "university_name": clean_csv_value(request.args.get("university_name", "")).strip(),
        "university_college": clean_csv_value(request.args.get("university_college", "")).strip(),
        "university_specialization": clean_csv_value(request.args.get("university_specialization", "")).strip(),
        "freelancer_specialization": clean_csv_value(request.args.get("freelancer_specialization", "")).strip(),
        "freelancer_company": clean_csv_value(request.args.get("freelancer_company", "")).strip(),
        "internet_method": clean_csv_value(request.args.get("internet_method", "")).strip(),
        "segment": clean_csv_value(request.args.get("segment", "")).strip(),
        "sort_by": clean_csv_value(request.args.get("sort_by", "id")).strip() or "id",
        "sort_order": clean_csv_value(request.args.get("sort_order", "desc")).strip() or "desc",
    }
