# 48o_admin_forms_v2.py
# إعادة تصميم 4 صفحات admin:
#   - /beneficiaries/add  → admin/beneficiaries/form.html
#   - /beneficiaries/edit/<id> → admin/beneficiaries/form.html
#   - /accounts/add → admin/accounts/form.html
#   - /accounts/edit/<id> → admin/accounts/form.html

from flask import render_template, request, redirect, url_for, flash, session


def _ensure_permission_rows():
    """Keep the lookup table synced after adding new permission keys."""
    for perm in PERMISSIONS:
        try:
            execute_sql(
                "INSERT INTO permissions (name) VALUES (%s) ON CONFLICT(name) DO NOTHING",
                [perm],
            )
        except Exception:
            try:
                execute_sql("INSERT OR IGNORE INTO permissions (name) VALUES (%s)", [perm])
            except Exception:
                pass


# ════════════════════════════════════════════════════════════════
# /beneficiaries/add
# ════════════════════════════════════════════════════════════════
def _add_beneficiary_v2():
    """صفحة إضافة مستفيد بالتصميم الجديد."""
    if request.method == "POST":
        # نستخدم نفس collect_beneficiary_form القديم لجمع البيانات
        data = collect_beneficiary_form()
        if not is_valid_new_phone(data.get("phone", "")):
            flash("رقم الجوال يجب أن يكون 10 أرقام بالضبط ويبدأ بـ 0.", "error")
            return render_template(
                "admin/beneficiaries/form.html",
                data=data, is_edit=False,
                form_title="إضافة مستفيد جديد",
            )
        duplicate = find_duplicate_phone(data.get("phone"))
        if duplicate:
            flash(f"رقم الجوال مستخدم مسبقًا للمستفيد: {duplicate.get('full_name')}", "error")
            return render_template(
                "admin/beneficiaries/form.html",
                data=data, is_edit=False,
                form_title="إضافة مستفيد جديد",
            )
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
            flash("تعذّر حفظ المستفيد. ربما رقم الجوال مكرّر.", "error")
            return redirect(url_for("add_beneficiary_page"))
        new_id = row["id"] if row else None
        log_action("add", "beneficiary", new_id, f"إضافة مستفيد: {data['full_name']}")
        try:
            from app.services.notification_service import notify_beneficiary_created
            notify_beneficiary_created(int(new_id), session.get("username") or "") if new_id else None
        except Exception:
            pass
        flash(f"تمت إضافة {data['full_name']} بنجاح ✓", "success")
        return redirect(url_for("beneficiaries_page"))

    # GET — اعرض النموذج فارغًا
    initial_type = clean_csv_value(request.args.get("user_type", "tawjihi")) or "tawjihi"
    return render_template(
        "admin/beneficiaries/form.html",
        data={"user_type": initial_type},
        is_edit=False,
        form_title="إضافة مستفيد جديد",
    )


# ════════════════════════════════════════════════════════════════
# /beneficiaries/edit/<id>
# ════════════════════════════════════════════════════════════════
def _edit_beneficiary_v2(beneficiary_id):
    row = query_one("SELECT * FROM beneficiaries WHERE id=%s", [beneficiary_id])
    if not row:
        flash("المستفيد غير موجود.", "error")
        return redirect(url_for("beneficiaries_page"))

    if request.method == "POST":
        data = collect_beneficiary_form()
        data["id"] = beneficiary_id
        if not is_phone_change_allowed(data.get("phone", ""), row.get("phone")):
            flash("رقم الجوال يجب أن يكون 10 أرقام بالضبط.", "error")
            data["id"] = beneficiary_id
            return render_template(
                "admin/beneficiaries/form.html",
                data=data, is_edit=True,
                form_title="تعديل المستفيد",
            )
        duplicate = find_duplicate_phone(data.get("phone"), exclude_id=beneficiary_id)
        if duplicate:
            flash(f"رقم الجوال مستخدم مسبقًا للمستفيد: {duplicate.get('full_name')}", "error")
            return render_template(
                "admin/beneficiaries/form.html",
                data=data, is_edit=True,
                form_title="تعديل المستفيد",
            )
        execute_sql(
            """
            UPDATE beneficiaries SET
                user_type=%(user_type)s,
                first_name=%(first_name)s, second_name=%(second_name)s,
                third_name=%(third_name)s, fourth_name=%(fourth_name)s,
                full_name=%(full_name)s, search_name=%(search_name)s,
                phone=%(phone)s,
                tawjihi_year=%(tawjihi_year)s, tawjihi_branch=%(tawjihi_branch)s,
                freelancer_specialization=%(freelancer_specialization)s,
                freelancer_company=%(freelancer_company)s,
                freelancer_schedule_type=%(freelancer_schedule_type)s,
                freelancer_internet_method=%(freelancer_internet_method)s,
                freelancer_time_mode=%(freelancer_time_mode)s,
                freelancer_time_from=%(freelancer_time_from)s,
                freelancer_time_to=%(freelancer_time_to)s,
                university_name=%(university_name)s,
                university_number=%(university_number)s,
                university_college=%(university_college)s,
                university_specialization=%(university_specialization)s,
                university_days=%(university_days)s,
                university_internet_method=%(university_internet_method)s,
                university_time_mode=%(university_time_mode)s,
                university_time_from=%(university_time_from)s,
                university_time_to=%(university_time_to)s,
                notes=%(notes)s
            WHERE id=%(id)s
            """,
            data,
        )
        log_action("edit", "beneficiary", beneficiary_id, f"تعديل مستفيد: {data['full_name']}")
        try:
            from app.services.notification_service import notify_beneficiary_profile_updated
            notify_beneficiary_profile_updated(
                beneficiary_id,
                session.get("username") or "",
                "راجع ملفك للتأكد من صحة البيانات.",
            )
        except Exception:
            pass
        flash("تم حفظ التعديلات ✓", "success")
        return redirect(url_for("beneficiaries_page"))

    # GET
    return render_template(
        "admin/beneficiaries/form.html",
        data=row,
        is_edit=True,
        form_title=f"تعديل: {row.get('full_name') or 'مستفيد'}",
    )


# ════════════════════════════════════════════════════════════════
# /accounts/add
# ════════════════════════════════════════════════════════════════
def _add_account_v2():
    _ensure_permission_rows()
    if request.method == "POST":
        username = clean_csv_value(request.form.get("username"))
        password = clean_csv_value(request.form.get("password"))
        full_name = clean_csv_value(request.form.get("full_name"))
        perms = request.form.getlist("permissions")

        if not username or not password:
            flash("اسم المستخدم وكلمة المرور مطلوبان.", "error")
            return render_template(
                "admin/accounts/form.html",
                data={"username": username, "full_name": full_name},
                assigned=set(perms),
                is_edit=False,
                form_title="إضافة مدير جديد",
                permissions=PERMISSIONS,
                permission_groups=PERMISSION_GROUPS,
                permission_label=permission_label,
                permission_descriptions=PERMISSION_DESCRIPTIONS,
            )
        try:
            row = execute_sql(
                """
                INSERT INTO app_accounts (username, password_hash, full_name, is_active)
                VALUES (%s,%s,%s,TRUE)
                RETURNING id
                """,
                [username, admin_password_hash(password), full_name],
                fetchone=True,
            )
        except Exception:
            flash("اسم المستخدم مستخدم مسبقًا أو يوجد خطأ في قاعدة البيانات.", "error")
            return redirect(url_for("add_account"))
        aid = row["id"]
        for p in perms:
            execute_sql(
                """
                INSERT INTO account_permissions (account_id, permission_id)
                SELECT %s, id FROM permissions WHERE name=%s
                ON CONFLICT DO NOTHING
                """,
                [aid, p],
            )
        log_action("add_account", "account", aid, f"إنشاء حساب {username}")
        flash(f"تم إنشاء الحساب {username} بنجاح ✓", "success")
        return redirect(url_for("accounts_page"))

    return render_template(
        "admin/accounts/form.html",
        data={},
        assigned=set(),
        is_edit=False,
        form_title="إضافة مدير جديد",
        permissions=PERMISSIONS,
        permission_groups=PERMISSION_GROUPS,
        permission_label=permission_label,
        permission_descriptions=PERMISSION_DESCRIPTIONS,
    )


# ════════════════════════════════════════════════════════════════
# /accounts/edit/<id>
# ════════════════════════════════════════════════════════════════
def _edit_account_v2(account_id):
    _ensure_permission_rows()
    row = query_one("SELECT * FROM app_accounts WHERE id=%s", [account_id])
    if not row:
        flash("الحساب غير موجود.", "error")
        return redirect(url_for("accounts_page"))
    assigned_rows = query_all(
        """
        SELECT p.name FROM account_permissions ap
        JOIN permissions p ON p.id = ap.permission_id
        WHERE ap.account_id=%s
        """,
        [account_id],
    )
    assigned = set(x["name"] for x in (assigned_rows or []))

    if request.method == "POST":
        username = clean_csv_value(request.form.get("username"))
        full_name = clean_csv_value(request.form.get("full_name"))
        password = clean_csv_value(request.form.get("password"))
        perms = request.form.getlist("permissions")
        try:
            execute_sql(
                "UPDATE app_accounts SET username=%s, full_name=%s WHERE id=%s",
                [username, full_name, account_id],
            )
        except Exception:
            flash("تعذّر تحديث الحساب. ربما اسم المستخدم مكرّر.", "error")
            return redirect(url_for("edit_account", account_id=account_id))
        if password:
            execute_sql(
                "UPDATE app_accounts SET password_hash=%s WHERE id=%s",
                [admin_password_hash(password), account_id],
            )
        execute_sql("DELETE FROM account_permissions WHERE account_id=%s", [account_id])
        for p in perms:
            execute_sql(
                """
                INSERT INTO account_permissions (account_id, permission_id)
                SELECT %s, id FROM permissions WHERE name=%s
                ON CONFLICT DO NOTHING
                """,
                [account_id, p],
            )
        if session.get("account_id") == account_id:
            session["username"] = username
            session["full_name"] = full_name
            try:
                refresh_session_permissions(account_id)
            except Exception:
                pass
        log_action("edit_account", "account", account_id, f"تعديل حساب {username}")
        flash("تم حفظ التعديلات ✓", "success")
        return redirect(url_for("accounts_page"))

    return render_template(
        "admin/accounts/form.html",
        data=row,
        assigned=assigned,
        is_edit=True,
        form_title=f"تعديل: {row.get('username')}",
        permissions=PERMISSIONS,
        permission_groups=PERMISSION_GROUPS,
        permission_label=permission_label,
        permission_descriptions=PERMISSION_DESCRIPTIONS,
    )


# ════════════════════════════════════════════════════════════════
# استبدال الـ view functions
# ════════════════════════════════════════════════════════════════
if "add_beneficiary_page" in app.view_functions:
    @login_required
    @permission_required("add")
    def _new_add_beneficiary():
        return _add_beneficiary_v2()
    app.view_functions["add_beneficiary_page"] = _new_add_beneficiary

if "edit_beneficiary_page" in app.view_functions:
    @login_required
    @permission_required("edit")
    def _new_edit_beneficiary(beneficiary_id):
        return _edit_beneficiary_v2(beneficiary_id)
    app.view_functions["edit_beneficiary_page"] = _new_edit_beneficiary

if "add_account" in app.view_functions:
    @login_required
    @permission_required("manage_accounts")
    def _new_add_account():
        return _add_account_v2()
    app.view_functions["add_account"] = _new_add_account

if "edit_account" in app.view_functions:
    @login_required
    @permission_required("manage_accounts")
    def _new_edit_account(account_id):
        return _edit_account_v2(account_id)
    app.view_functions["edit_account"] = _new_edit_account
