# Auto-split from app/legacy.py lines 10882-11008. Loaded by app.legacy.
def _clean_admin_cards_import_page():
    if request.method == "POST":
        duration_minutes = int(clean_csv_value(request.form.get("duration_minutes")) or "0")
        upload = request.files.get("cards_file")
        if duration_minutes not in {30, 60, 120, 180, 240} or not upload or not clean_csv_value(upload.filename):
            flash("مدة البطاقات وملف الاستيراد حقول مطلوبة.", "error")
            return redirect(url_for("admin_cards_import_page"))
        try:
            inserted = import_manual_access_cards(duration_minutes, upload, clean_csv_value(upload.filename), session.get("username", "admin"))
            log_action("import_manual_cards", "manual_access_cards", 0, f"Imported {inserted} cards for {duration_minutes} minutes")
            flash(f"تم استيراد {inserted} بطاقة لقسم {card_duration_label(duration_minutes)}.", "success")
            return redirect(url_for("admin_cards_inventory_page"))
        except Exception as exc:
            flash(f"تعذر استيراد البطاقات: {exc}", "error")
            return redirect(url_for("admin_cards_import_page"))
    options_html = "".join([f"<option value='{item['minutes']}'>{item['label']}</option>" for item in CARD_DURATION_OPTIONS])
    content = f"""
    <div class="hero">
      <div><h1>بطاقات هوت سبوت</h1><p>استيراد مخزون البطاقات يدويًا من ملفات CSV أو Excel لاستخدامه داخل البوابة.</p></div>
    </div>
    <div class="portal-panel">
      <div class="section-heading"><div><h3>استيراد ملف جديد</h3><p>الملف يجب أن يحتوي اسم المستخدم وكلمة المرور لكل بطاقة.</p></div></div>
      <form method="POST" enctype="multipart/form-data">
        <div class="grid grid-2">
          <div><label>قسم البطاقات</label><select name="duration_minutes" required><option value="">اختر القسم</option>{options_html}</select></div>
          <div><label>ملف البطاقات</label><input type="file" name="cards_file" accept=".csv,.xlsx,.xlsm" required></div>
        </div>
        <div class="actions" style="margin-top:16px">
          <button class="btn btn-primary" type="submit">استيراد البطاقات</button>
          <a class="btn btn-soft" href="{url_for('admin_cards_inventory_page')}">فتح الجرد</a>
        </div>
      </form>
    </div>
    """
    return render_page("بطاقات هوت سبوت", content)


def _clean_admin_cards_inventory_page():
    counts = get_manual_cards_inventory_counts()
    workday = portal_workday_context()
    rows = "".join([f"<tr><td>{item['label']}</td><td>{item['available']}</td></tr>" for item in counts]) or "<tr><td colspan='2'>لا يوجد مخزون بطاقات حاليًا.</td></tr>"
    cards = "".join([f"<div class='summary-card'><div class='label'>{item['label']}</div><div class='value'>{item['available']}</div><div class='note'>بطاقات متاحة الآن</div></div>" for item in counts])
    content = f"""
    <div class="hero">
      <div><h1>بطاقات هوت سبوت</h1><p>إدارة مخزون البطاقات، وقت الدوام، واستيراد الملفات الخاصة بالبطاقات المجانية.</p></div>
    </div>
    <div class="grid">
      {cards}
      <div class='summary-card'><div class='label'>الدوام الحالي</div><div class='value'>{workday['start_time']} - {workday['end_time']}</div><div class='note'>ينعكس مباشرة على المدد المسموحة للمشترك</div></div>
    </div>
    <div class="portal-panel" style="margin-top:18px">
      <div class="actions" style="margin-bottom:14px">
        <a class="btn btn-primary" href="{url_for('admin_cards_import_page')}">استيراد ملف جديد</a>
        <a class="btn btn-soft" href="{url_for('admin_cards_settings_page')}">إعدادات بطاقات هوت سبوت</a>
      </div>
      <div class="table-wrap">
        <table>
          <thead><tr><th>القسم</th><th>المتوفر</th></tr></thead>
          <tbody>{rows}</tbody>
        </table>
      </div>
    </div>
    """
    return render_page("بطاقات هوت سبوت", content)


def _clean_admin_cards_settings_page():
    settings_row = get_radius_settings_row() or {}
    schedule = get_hotspot_workday_settings()
    if request.method == "POST":
        router_login_url = clean_csv_value(request.form.get("router_login_url"))
        workday_start_time = clean_csv_value(request.form.get("workday_start_time")) or "08:00"
        workday_end_time = clean_csv_value(request.form.get("workday_end_time")) or "16:00"
        try:
            sh, sm = [int(part) for part in workday_start_time.split(":", 1)]
            eh, em = [int(part) for part in workday_end_time.split(":", 1)]
            workday_start_time = f"{sh:02d}:{sm:02d}"
            workday_end_time = f"{eh:02d}:{em:02d}"
        except Exception:
            flash("يرجى إدخال وقت بداية ونهاية صالح بصيغة HH:MM.", "error")
            return redirect(url_for("admin_cards_settings_page"))
        execute_sql(
            "UPDATE radius_api_settings SET router_login_url=%s, workday_start_time=%s, workday_end_time=%s, updated_at=CURRENT_TIMESTAMP WHERE id=1",
            [router_login_url, workday_start_time, workday_end_time],
        )

        # ── الأساس العامّ (السياسة الافتراضية scope='default') — يُورَّث للكلّ ──
        def _int_or_none(v):
            v = clean_csv_value(v)
            return int(v) if v and v.lstrip("-").isdigit() else None
        base_daily = _int_or_none(request.form.get("base_daily_limit"))
        base_weekly = _int_or_none(request.form.get("base_weekly_limit"))
        base_categories = clean_csv_value(request.form.get("base_allowed_category_codes"))
        _existing_default = query_one(
            "SELECT id FROM card_quota_policies WHERE scope='default' ORDER BY priority ASC, id DESC LIMIT 1"
        )
        if _existing_default:
            execute_sql(
                "UPDATE card_quota_policies SET daily_limit=%s, weekly_limit=%s, "
                "allowed_category_codes=%s, is_active=TRUE, updated_at=CURRENT_TIMESTAMP WHERE id=%s",
                [base_daily, base_weekly, base_categories, _existing_default["id"]],
            )
        else:
            execute_sql(
                "INSERT INTO card_quota_policies (scope, daily_limit, weekly_limit, "
                "allowed_days, allowed_category_codes, priority, is_active, notes) "
                "VALUES ('default',%s,%s,'',%s,1000,TRUE,'القاعدة الأساسية لكل المشتركين')",
                [base_daily, base_weekly, base_categories],
            )

        log_action("update_hotspot_cards_settings", "radius_api_settings", 1,
                   f"router={router_login_url}, workday={workday_start_time}-{workday_end_time}, "
                   f"base_daily={base_daily}, base_weekly={base_weekly}, base_cats={base_categories or '*'}")
        flash("تم تحديث إعدادات البطاقات والقاعدة الأساسية للمشتركين.", "success")
        return redirect(url_for("admin_cards_settings_page"))

    current_url = settings_row.get("router_login_url") or get_router_login_url() or ""
    default_policy = query_one(
        "SELECT daily_limit, weekly_limit, allowed_category_codes FROM card_quota_policies "
        "WHERE scope='default' ORDER BY priority ASC, id DESC LIMIT 1"
    ) or {}
    base_categories = query_all(
        "SELECT code, label_ar FROM card_categories WHERE is_active=TRUE ORDER BY duration_minutes ASC"
    ) or []
    return render_template(
        "admin/cards/settings.html",
        current_url=current_url,
        start_time=schedule["start_time"],
        end_time=schedule["end_time"],
        base_daily=default_policy.get("daily_limit"),
        base_weekly=default_policy.get("weekly_limit"),
        base_selected_codes=(default_policy.get("allowed_category_codes") or ""),
        base_categories=base_categories,
    )


portal_access_type_copy = _clean_portal_access_type_copy
app.view_functions["user_dashboard"] = user_login_required(_clean_user_dashboard)
app.view_functions["user_profile_page"] = user_login_required(_clean_user_profile_page)
app.view_functions["user_internet_my_requests_page"] = user_login_required(_clean_user_internet_my_requests_page)
app.view_functions["user_internet_access_page"] = user_login_required(_manual_cards_user_access_page)
app.view_functions["user_internet_my_access_page"] = user_login_required(_manual_cards_user_access_page)
app.view_functions["user_internet_request_page"] = user_login_required(_manual_cards_user_request_page)
app.view_functions["advradius_app_test_route"] = login_required(permission_required("manage_radius_settings")(_clean_advradius_app_test_route))
app.view_functions["admin_cards_import_page"] = admin_login_required(_clean_admin_cards_import_page)
app.view_functions["admin_cards_inventory_page"] = admin_login_required(_clean_admin_cards_inventory_page)
app.view_functions["admin_cards_settings_page"] = admin_login_required(_clean_admin_cards_settings_page)


app.view_functions["user_internet_access_page"] = user_login_required(_manual_cards_user_access_page)
app.view_functions["user_internet_my_access_page"] = user_login_required(_manual_cards_user_access_page)
app.view_functions["user_internet_request_page"] = user_login_required(_manual_cards_user_request_page)
