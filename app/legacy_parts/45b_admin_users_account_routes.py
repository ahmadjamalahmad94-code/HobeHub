from flask import flash, jsonify, redirect, render_template, request, session, url_for

_USERNAME_USER_TYPES = ('university', 'freelancer')
_USERNAME_METHODS = ("يوزر إنترنت", "يمتلك اسم مستخدم", "username")

_USER_ACTION_TYPES = {
    "reset_password": "إعادة كلمة المرور",
    "unblock_site":   "فتح موقع",
    "speed_upgrade":  "رفع السرعة",
    "create_user":    "إنشاء حساب",
    "update_user":    "تعديل بيانات",
    "add_time":       "إضافة وقت",
    "add_quota_mb":   "إضافة كوتة",
    "disconnect":     "فصل جلسة",
}


def _user_type_label(ut):
    from app.services.access_rules import USER_TYPE_LABELS
    return USER_TYPE_LABELS.get((ut or '').strip().lower(), ut or '—')


def _beneficiary_access_mode(row):
    """يرجع 'cards' أو 'username' حسب internet_method الموجود."""
    if not row:
        return 'cards'
    ut = (row.get("user_type") or "").strip().lower()
    if ut == "university":
        method = (row.get("university_internet_method") or "").strip()
    elif ut == "freelancer":
        method = (row.get("freelancer_internet_method") or "").strip()
    else:
        return 'cards'
    return 'username' if method in _USERNAME_METHODS else 'cards'


def _load_username_subscribers(q="", user_type_filter="", limit=None):
    """يبني قائمة مشتركي حساب الإنترنت من نفس مصدر الجدول والعدادات."""
    from app.services.access_rules import can_switch_to

    sql = """
        SELECT b.id, b.full_name, b.phone, b.user_type, b.weekly_usage_count,
               b.university_internet_method, b.freelancer_internet_method,
               pa.id AS portal_account_id,
               pa.username AS portal_username,
               ra.external_username    AS radius_username,
               ra.plain_password       AS radius_password,
               ra.current_profile_name AS radius_offer_name,
               ra.current_profile_id   AS radius_offer_id
        FROM beneficiaries b
        LEFT JOIN beneficiary_portal_accounts pa ON pa.beneficiary_id = b.id
             AND COALESCE(pa.portal_membership_active, FALSE)=TRUE
        LEFT JOIN beneficiary_radius_accounts  ra ON ra.beneficiary_id = b.id
        WHERE b.user_type IN ('university','freelancer')
    """
    params = []
    if q:
        from app.services.smart_search import smart_search_clause
        clause, clause_params = smart_search_clause(
            q,
            text_columns=("b.search_name", "b.full_name"),
            phone_columns=("b.phone", "pa.username", "ra.external_username"),
            extra_columns=(
                "b.university_name", "b.university_number", "b.university_college",
                "b.university_specialization", "b.freelancer_specialization", "b.freelancer_company",
            ),
        )
        if clause:
            sql += " AND " + clause
            params.extend(clause_params)
    if user_type_filter in _USERNAME_USER_TYPES:
        sql += " AND b.user_type=%s"
        params.append(user_type_filter)
    sql += " ORDER BY b.id DESC"

    users = []
    seen_ids = set()
    for r in query_all(sql, params):
        # منع التكرار: قد يملك المستفيد أكثر من صفّ radius_accounts فيتضاعف
        # بسبب LEFT JOIN — نُبقي أوّل ظهور فقط (صفّ واحد لكل مستفيد).
        if r["id"] in seen_ids:
            continue
        seen_ids.add(r["id"])
        ut = (r.get("user_type") or "").strip().lower()
        access_mode = _beneficiary_access_mode(r)
        if access_mode != 'username':
            continue
        can, reason = can_switch_to(ut, 'cards')
        radius_user = r.get("radius_username") or r.get("portal_username") or r.get("phone") or ""
        radius_pwd = r.get("radius_password") or ""
        users.append({
            "id": r["id"],
            "full_name": r["full_name"],
            "phone": r.get("phone") or "",
            "user_type": ut,
            "user_type_label": _user_type_label(ut),
            "access_mode": access_mode,
            "has_portal_account": bool(r.get("portal_account_id")),
            "portal_account_id": r.get("portal_account_id"),
            "portal_username": radius_user,
            "portal_password": radius_pwd,
            "offer_name": (r.get("radius_offer_name") or "").strip(),
            "offer_id": (r.get("radius_offer_id") or ""),
            "weekly_usage_count": int(r.get("weekly_usage_count") or 0),
            "can_switch": bool(can),
            "switch_reason": reason or "",
        })
        if limit and len(users) >= limit:
            break
    return users


def _active_speed_upgrades_count():
    row = query_one(
        "SELECT COUNT(*) AS c FROM temporary_speed_upgrades WHERE status IN ('pending','active')"
    ) or {}
    return int(row.get("c") or 0)

# /admin/users-account — overview
@app.route("/admin/users-account", methods=["GET"])
@app.route("/admin/users-account/", methods=["GET"])
@app.route("/admin/users-account/overview", methods=["GET"])
@admin_login_required
def admin_users_account_overview():
    """صفحة موحّدة: KPIs + أنواع الطلبات + قائمة المشتركين الكاملة مع الفلترة."""
    from app.services.radius_client import get_radius_client

    client = get_radius_client()
    user_action_types = list(_USER_ACTION_TYPES.keys())
    placeholders = ",".join(["%s"] * len(user_action_types))
    pending_row = query_one(
        f"SELECT COUNT(*) AS c FROM radius_pending_actions WHERE status='pending' AND action_type IN ({placeholders})",
        user_action_types,
    ) or {}
    user_requests_count = int(pending_row.get("c") or 0)

    counts = {}
    for t in user_action_types:
        r = query_one(
            "SELECT COUNT(*) AS c FROM radius_pending_actions WHERE status='pending' AND action_type=%s",
            [t],
        ) or {}
        counts[t] = int(r.get("c") or 0)

    # ─── قائمة مشتركي اليوزر فقط (access_mode='username') ───
    q = clean_csv_value(request.args.get("q")) or ""
    user_type_filter = clean_csv_value(request.args.get("user_type")) or ""
    all_username_users = _load_username_subscribers()
    filtered_username_users = _load_username_subscribers(q, user_type_filter)
    users_count = len(all_username_users)
    filtered_users_count = len(filtered_username_users)
    users = filtered_username_users[:300]

    # ─ بيانات RADIUS API ─
    from app.services.radius_dashboard import (
        get_radius_kpis,
        get_radius_online_users,
        get_radius_profiles,
    )
    api_kpis = get_radius_kpis()
    api_online = get_radius_online_users(limit=20)
    api_profiles = get_radius_profiles()

    return render_template(
        "admin/users_account/overview.html",
        users_count=users_count,
        filtered_users_count=filtered_users_count,
        user_requests_count=user_requests_count,
        speed_upgrades_count=_active_speed_upgrades_count(),
        counts=counts,
        users=users,
        filters={"q": q, "user_type": user_type_filter},
        api_kpis=api_kpis,
        api_online=api_online,
        api_profiles=api_profiles,
    )

# /admin/users-account/list — مدموجة في الـ overview، تحويل للحفاظ على الروابط القديمة
@app.route("/admin/users-account/list", methods=["GET"])
@admin_login_required
def admin_users_account_list():
    return admin_users_account_overview()

# /admin/users-account/data.json — JSON endpoint للبحث الـ AJAX
@app.route("/admin/users-account/data.json", methods=["GET"])
@admin_login_required
def admin_users_account_data_json():
    """يرجع قائمة مشتركي حساب الإنترنت كـ JSON — نفس الفلترة والاستعلام كـ overview."""
    q = clean_csv_value(request.args.get("q")) or ""
    user_type_filter = clean_csv_value(request.args.get("user_type")) or ""
    users = _load_username_subscribers(q, user_type_filter)
    return jsonify({"ok": True, "users": users[:300], "count": len(users)})
# /admin/users-account/requests
@app.route("/admin/users-account/create", methods=["POST"])
@admin_login_required
def admin_users_account_create():
    user_type = clean_csv_value(request.form.get("user_type"))
    if user_type not in _USERNAME_USER_TYPES:
        return jsonify({"ok": False, "message": "حسابات الإنترنت متاحة فقط للجامعة والعمل الحر."}), 400

    password = clean_csv_value(request.form.get("password"))
    if len(password) < 6:
        return jsonify({"ok": False, "message": "كلمة المرور يجب أن تكون 6 أحرف أو أرقام على الأقل."}), 400

    data = {col: clean_csv_value(request.form.get(col, "")) for col in CSV_IMPORT_COLUMNS}
    full_name = clean_csv_value(request.form.get("full_name"))
    if full_name and not clean_csv_value(data.get("first_name")):
        data["first_name"], data["second_name"], data["third_name"], data["fourth_name"] = split_full_name(full_name)
    data["user_type"] = user_type
    data["phone"] = normalize_phone(data.get("phone"))
    data["full_name"] = full_name_from_parts(
        data.get("first_name"),
        data.get("second_name"),
        data.get("third_name"),
        data.get("fourth_name"),
    )
    data["search_name"] = normalize_search_ar(data["full_name"])
    data["weekly_usage_week_start"] = get_week_start()
    data["added_by_account_id"] = session.get("account_id")
    data["added_by_username"] = session.get("username")

    if not data["full_name"]:
        return jsonify({"ok": False, "message": "أدخل اسم المشترك."}), 400
    if not is_valid_new_phone(data.get("phone", "")):
        return jsonify({"ok": False, "message": "رقم الجوال يجب أن يكون 10 أرقام ويبدأ بـ 0."}), 400
    duplicate = find_duplicate_phone(data.get("phone"))
    if duplicate:
        return jsonify({"ok": False, "message": f"رقم الجوال مستخدم لدى: {duplicate.get('full_name')}"}), 400

    username = normalize_portal_username(data["phone"])
    if query_one("SELECT id FROM beneficiary_portal_accounts WHERE username=%s LIMIT 1", [username]):
        return jsonify({"ok": False, "message": "رقم الجوال مستخدم كاسم دخول لحساب آخر."}), 400

    if user_type == "university":
        data["university_internet_method"] = "يوزر إنترنت"
    else:
        data["freelancer_internet_method"] = "يوزر إنترنت"

    beneficiary_id = None
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
        beneficiary_id = int(row["id"]) if row and row.get("id") else None
        if not beneficiary_id:
            raise ValueError("missing beneficiary id")

        portal_row = execute_sql(
            """
            INSERT INTO beneficiary_portal_accounts (
                beneficiary_id, username, password_hash, password_plain,
                is_active, portal_membership_active, portal_access_state, must_set_password, activated_at
            ) VALUES (%s,%s,'',NULL,TRUE,TRUE,'active',TRUE,NULL)
            RETURNING id
            """,
            [beneficiary_id, username],
            fetchone=True,
        )
        portal_id = int(portal_row["id"]) if portal_row and portal_row.get("id") else None
        activation_code = issue_activation_code_for_portal_account(portal_id) if portal_id else ""

        import hashlib as _hashlib
        password_md5 = _hashlib.md5(password.encode("utf-8")).hexdigest()
        existing_radius = query_one(
            "SELECT id FROM beneficiary_radius_accounts WHERE beneficiary_id=%s LIMIT 1",
            [beneficiary_id],
        )
        if existing_radius:
            execute_sql(
                """
                UPDATE beneficiary_radius_accounts
                SET external_username=%s,
                    plain_password=%s,
                    password_md5=%s,
                    status='pending',
                    updated_at=CURRENT_TIMESTAMP
                WHERE beneficiary_id=%s
                """,
                [username, password, password_md5, beneficiary_id],
            )
        else:
            execute_sql(
                """
                INSERT INTO beneficiary_radius_accounts
                    (beneficiary_id, external_username, plain_password, password_md5, status)
                VALUES (%s,%s,%s,%s,'pending')
                """,
                [beneficiary_id, username, password, password_md5],
            )
        execute_sql(
            """
            INSERT INTO radius_pending_actions (
                action_type, target_kind, beneficiary_id, payload_json,
                requested_by_account_id, requested_by_username, notes, attempted_by_mode
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,'manual')
            """,
            [
                "create_user",
                "user",
                beneficiary_id,
                Json({"username": username, "password": password, "profile_id": "", "source": "admin_users_account_create"}),
                session.get("account_id"),
                session.get("username") or "",
                "إنشاء حساب إنترنت من لوحة الإدارة",
            ],
        )
        # ── ربط الريديوس: محاولة إنشاء اليوزر مباشرةً (إضافيّ؛ الطابور أعلاه هو
        #    المسار الاحتياطيّ عند إقفال الكتابة/الوضع غير المباشر) ──
        try:
            from app.services.radius_provisioning import provision_subscriber
            _pr = provision_subscriber(
                beneficiary_id=beneficiary_id, username=username, password=password,
                profile_id="", requested_by=session.get("username") or "admin",
            )
            if _pr.get("ok") and _pr.get("live"):
                execute_sql(
                    "UPDATE beneficiary_radius_accounts SET status='active', "
                    "updated_at=CURRENT_TIMESTAMP WHERE beneficiary_id=%s",
                    [beneficiary_id],
                )
        except Exception:
            pass
    except Exception:
        if beneficiary_id:
            try:
                execute_sql("DELETE FROM beneficiaries WHERE id=%s", [beneficiary_id])
            except Exception:
                pass
        return jsonify({"ok": False, "message": "تعذّر إنشاء حساب الإنترنت. راجع البيانات وحاول مرة أخرى."}), 400

    log_action("create_user_account", "beneficiary", beneficiary_id, f"إنشاء مشترك حساب إنترنت: {data['full_name']}")
    try:
        from app.services.notification_service import notify_beneficiary_created
        notify_beneficiary_created(beneficiary_id, session.get("username") or "")
    except Exception:
        pass
    return jsonify({
        "ok": True,
        "message": f"تم إنشاء مشترك حساب الإنترنت لـ {data['full_name']}. كلمة مرور حساب الإنترنت محفوظة للربط، وكلمة مرور البوابة سيعينها المشترك برمز التفعيل.",
        "id": beneficiary_id,
        "username": username,
        "activation_code": activation_code,
    })


@app.route("/admin/users-account/requests", methods=["GET"])
@admin_login_required
def admin_users_account_requests():
    filter_type = clean_csv_value(request.args.get("type")) or ""
    filter_status = clean_csv_value(request.args.get("status")) or "pending"
    beneficiary_filter = clean_csv_value(request.args.get("beneficiary_id")) or ""

    user_types_csv = ",".join(f"'{t}'" for t in _USER_ACTION_TYPES.keys())
    sql = f"SELECT * FROM radius_pending_actions WHERE action_type IN ({user_types_csv})"
    params = []
    if filter_type and filter_type in _USER_ACTION_TYPES:
        sql += " AND action_type=%s"
        params.append(filter_type)
    if filter_status:
        sql += " AND status=%s"
        params.append(filter_status)
    if beneficiary_filter.isdigit():
        sql += " AND beneficiary_id=%s"
        params.append(int(beneficiary_filter))
    sql += " ORDER BY id DESC LIMIT 200"

    raw = query_all(sql, params)
    items = []
    import json as _json
    for a in raw:
        beneficiary = None
        if a.get("beneficiary_id"):
            beneficiary = query_one(
                "SELECT full_name, phone FROM beneficiaries WHERE id=%s LIMIT 1",
                [a["beneficiary_id"]],
            )
        payload = a.get("payload_json")
        if isinstance(payload, str):
            try:
                payload = _json.loads(payload)
            except Exception:
                payload = {}
        items.append({
            "id": a["id"],
            "action_type": a["action_type"],
            "type_label": _USER_ACTION_TYPES.get(a["action_type"], a["action_type"]),
            "beneficiary_name": (beneficiary or {}).get("full_name"),
            "beneficiary_phone": (beneficiary or {}).get("phone"),
            "payload": payload or {},
            "notes": a.get("notes") or "",
            "requested_at": a.get("requested_at"),
            "status": a.get("status"),
        })

    return render_template(
        "admin/users_account/requests.html",
        items=items,
        filter_type=filter_type,
        filter_status=filter_status,
        beneficiary_filter=beneficiary_filter,
        user_requests_count=sum(1 for x in items if x["status"] == "pending"),
    )


@app.route("/admin/users-account/requests/<int:action_id>/done", methods=["POST"])
@admin_login_required
def admin_user_request_done(action_id):
    from app.services.radius_client import get_radius_client
    notes = clean_csv_value(request.form.get("notes")) or "تم التنفيذ يدويًا"
    client = get_radius_client()
    client.mark_pending_done(action_id, executed_by=session.get("username") or "admin", notes=notes)
    log_action("user_action_done", "radius_pending_actions", action_id, notes)
    flash("تم وضع علامة منفّذ.", "success")
    return redirect(request.referrer or url_for("admin_request_center", type="user"))


@app.route("/admin/users-account/requests/<int:action_id>/cancel", methods=["POST"])
@admin_login_required
def admin_user_request_cancel(action_id):
    from app.services.radius_client import get_radius_client
    notes = clean_csv_value(request.form.get("notes")) or "أُلغي من الإدارة"
    client = get_radius_client()
    client.cancel_pending(action_id, executed_by=session.get("username") or "admin", notes=notes)
    log_action("user_action_cancel", "radius_pending_actions", action_id, notes)
    flash("تم إلغاء الطلب.", "success")
    return redirect(request.referrer or url_for("admin_request_center", type="user"))
def _upsert_radius_account(beneficiary_id, username, password, profile_id, profile_name,
                           expire_at, schedule_days="", schedule_from="", schedule_to=""):
    """يخزّن/يحدّث بيانات حساب الريديوس محليًّا (المصدر للمزامنة)."""
    exists = query_one(
        "SELECT id FROM beneficiary_radius_accounts WHERE beneficiary_id=%s LIMIT 1",
        [beneficiary_id],
    )
    if exists:
        execute_sql(
            "UPDATE beneficiary_radius_accounts SET external_username=%s, plain_password=%s, "
            "current_profile_id=%s, current_profile_name=COALESCE(%s, current_profile_name), "
            "expires_at=%s, schedule_days=%s, schedule_from=%s, schedule_to=%s, "
            "status='active', updated_at=CURRENT_TIMESTAMP WHERE beneficiary_id=%s",
            [username, password, profile_id or None, profile_name or None,
             expire_at or None, schedule_days or "", schedule_from or "", schedule_to or "",
             beneficiary_id],
        )
    else:
        execute_sql(
            "INSERT INTO beneficiary_radius_accounts "
            "(beneficiary_id, external_username, plain_password, current_profile_id, "
            "current_profile_name, expires_at, schedule_days, schedule_from, schedule_to, status) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'active')",
            [beneficiary_id, username, password, profile_id or None,
             profile_name or None, expire_at or None,
             schedule_days or "", schedule_from or "", schedule_to or ""],
        )


# /admin/radius/profiles.json — باقات الريديوس لقوائم الاختيار (نافذة التحويل)
@app.route("/admin/radius/profiles.json")
@admin_login_required
def admin_radius_profiles_json():
    items = []
    try:
        from app.services.radius_dashboard import get_radius_profiles
        res = get_radius_profiles()
        items = (res.get("data") if isinstance(res, dict) else res) or []
    except Exception:
        items = []
    out = []
    for p in items:
        if not isinstance(p, dict):
            continue
        pid = p.get("profile_id") or p.get("external_id") or p.get("id")
        if pid in (None, ""):
            continue
        out.append({"id": str(pid), "name": p.get("name") or str(pid), "speed": p.get("speed") or ""})
    return jsonify({"ok": True, "profiles": out})


def _beneficiary_remark(ben):
    """ملاحظة الريديوس من بيانات المستفيد: جامعة/شركة + كليّة + تخصص/مجال."""
    t = (ben.get("user_type") or "").strip().lower()
    parts = []
    if t == "university":
        if ben.get("university_name"): parts.append("الجامعة: " + str(ben["university_name"]))
        if ben.get("university_college"): parts.append("الكلية: " + str(ben["university_college"]))
        if ben.get("university_specialization"): parts.append("التخصص: " + str(ben["university_specialization"]))
    elif t == "freelancer":
        if ben.get("freelancer_company"): parts.append("الشركة: " + str(ben["freelancer_company"]))
        if ben.get("freelancer_specialization"): parts.append("المجال: " + str(ben["freelancer_specialization"]))
    elif t == "tawjihi":
        if ben.get("tawjihi_year"): parts.append("السنة: " + str(ben["tawjihi_year"]))
        if ben.get("tawjihi_branch"): parts.append("الفرع: " + str(ben["tawjihi_branch"]))
    return " · ".join(parts)


# /admin/beneficiary/<id>/convert-access — تحويل المشترك (cards ↔ username)
@app.route("/admin/beneficiary/<int:beneficiary_id>/convert-access", methods=["POST"])
@admin_login_required
def admin_beneficiary_convert_access(beneficiary_id):
    from app.services.access_rules import can_switch_to, ACCESS_LABELS

    target_mode = clean_csv_value(request.form.get("target_mode"))
    if target_mode not in {"cards", "username"}:
        flash("نوع الوصول غير صالح.", "error")
        return redirect(url_for("admin_users_account_list"))

    if clean_csv_value(request.form.get("confirm_convert")) != "1":
        flash("يجب تأكيد التحويل قبل التنفيذ.", "error")
        return redirect(url_for("admin_users_account_list"))

    ben = query_one(
        "SELECT id, full_name, user_type, university_name, university_college, "
        "university_specialization, freelancer_company, freelancer_specialization, "
        "tawjihi_year, tawjihi_branch FROM beneficiaries WHERE id=%s LIMIT 1",
        [beneficiary_id],
    )
    if not ben:
        flash("المشترك غير موجود.", "error")
        return redirect(url_for("admin_users_account_list"))
    _ben_full_name = clean_csv_value(ben.get("full_name"))
    _ben_remark = _beneficiary_remark(ben)

    ut = (ben.get("user_type") or "").strip().lower()
    ok, reason = can_switch_to(ut, target_mode)
    if not ok:
        flash(reason, "error")
        return redirect(url_for("admin_users_account_list"))

    # نطبّق التحويل: نحدّث internet_method في الحقل المناسب
    method_value = "يوزر إنترنت" if target_mode == "username" else "نظام البطاقات"
    if ut == "university":
        execute_sql(
            "UPDATE beneficiaries SET university_internet_method=%s WHERE id=%s",
            [method_value, beneficiary_id],
        )
    elif ut == "freelancer":
        execute_sql(
            "UPDATE beneficiaries SET freelancer_internet_method=%s WHERE id=%s",
            [method_value, beneficiary_id],
        )
    # tawjihi لا يحتاج (مقفل على cards)

    # ── ربط الريديوس: التحويل إلى «يوزر إنترنت» ⇒ إنشاء اليوزر فعليًّا على الريديوس ──
    # تُقرأ البيانات الناقصة (اسم المستخدم/كلمة المرور/الباقة/الانتهاء) من نافذة
    # التحويل إن أُرسلت، وإلا نسقط للقيم المخزّنة، ثم لجوّال المشترك واسمٍ آمن.
    radius_note = ""
    actor = session.get("username") or "admin"
    acct = query_one(
        "SELECT external_username, plain_password, current_profile_id, status "
        "FROM beneficiary_radius_accounts WHERE beneficiary_id=%s LIMIT 1",
        [beneficiary_id],
    ) or {}
    prior_user = clean_csv_value(acct.get("external_username"))
    # «موجود على الريديوس» = له اسم مستخدم وحالته سبق أن جُهّزت (لا pending أوّليّة).
    already_live = bool(prior_user) and clean_csv_value(acct.get("status")) in ("active", "disabled")

    if target_mode == "username":
        ben_phone = clean_csv_value(
            (query_one("SELECT phone FROM beneficiaries WHERE id=%s", [beneficiary_id]) or {}).get("phone"))
        f_user = clean_csv_value(request.form.get("username"))
        f_pass = (request.form.get("password") or "").strip()
        f_profile = clean_csv_value(request.form.get("profile_id"))
        f_profile_name = clean_csv_value(request.form.get("profile_name"))
        f_expire = clean_csv_value(request.form.get("expire_at"))
        r_profile = f_profile or clean_csv_value(acct.get("current_profile_id")) or ""
        # جدولة الأيّام/الساعات (اختياريّة، مبسّطة)
        _days = [clean_csv_value(d) for d in request.form.getlist("schedule_days") if clean_csv_value(d)]
        f_days = ",".join(_days)
        f_from = clean_csv_value(request.form.get("schedule_from"))
        f_to = clean_csv_value(request.form.get("schedule_to"))

        if already_live:
            # إعادة تحويل: الحساب موجود مسبقًا → فحص وإعادة تفعيل فقط (لا إنشاء جديد).
            r_user = prior_user
            _upsert_radius_account(
                beneficiary_id, r_user, f_pass or (acct.get("plain_password") or ""),
                r_profile, f_profile_name, f_expire, f_days, f_from, f_to)
            from app.services.radius_provisioning import set_subscriber_enabled, update_subscriber_attrs
            er = set_subscriber_enabled(username=r_user, enabled=True,
                                        beneficiary_id=beneficiary_id, requested_by=actor)
            # زامن الاسم/الملاحظات/الجدولة على الحساب الموجود أيضًا.
            import json as _json
            _cs = ""
            if f_days or f_from or f_to:
                _cs = _json.dumps({"windows": [{"days": f_days.split(",") if f_days else [],
                                                "from": f_from, "to": f_to}]})
            update_subscriber_attrs(
                username=r_user, requested_by=actor,
                full_name=_ben_full_name, remark=_ben_remark,
                working_days=f_days, connection_schedule=_cs)
            execute_sql(
                "UPDATE beneficiary_radius_accounts SET status='active', "
                "updated_at=CURRENT_TIMESTAMP WHERE beneficiary_id=%s", [beneficiary_id])
            if er.get("ok") and er.get("live"):
                radius_note = f" وأُعيد تفعيل حسابه الموجود على الريديوس (المستخدم: {r_user})."
            elif not er.get("ok"):
                radius_note = f" (تنبيه ريديوس: {er.get('message')})"
            else:
                radius_note = " (سُجِّل محليًّا؛ سيُعاد تفعيله عند تفعيل الكتابة/المزامنة)."
        else:
            # إنشاء أوّل مرّة.
            r_user = f_user or prior_user or ben_phone
            r_pass = f_pass or (acct.get("plain_password") or "")
            if r_user and not r_pass:
                import secrets as _secrets
                r_pass = _secrets.token_urlsafe(6)  # كلمة مرور آمنة افتراضيّة إن لم تُعطَ
            if r_user and r_pass:
                _upsert_radius_account(beneficiary_id, r_user, r_pass, r_profile,
                                       f_profile_name, f_expire, f_days, f_from, f_to)
                from app.services.radius_provisioning import provision_subscriber
                pr = provision_subscriber(
                    beneficiary_id=beneficiary_id, username=r_user, password=r_pass,
                    profile_id=r_profile, expire_at=f_expire,
                    schedule_days=f_days, schedule_from=f_from, schedule_to=f_to,
                    full_name=_ben_full_name, remark=_ben_remark, requested_by=actor)
                if pr.get("ok") and pr.get("live"):
                    execute_sql(
                        "UPDATE beneficiary_radius_accounts SET status='active', "
                        "updated_at=CURRENT_TIMESTAMP WHERE beneficiary_id=%s", [beneficiary_id])
                    radius_note = f" وأُنشئ حسابه على الريديوس (المستخدم: {r_user})."
                elif not pr.get("ok"):
                    radius_note = f" (تنبيه ريديوس: {pr.get('message')})"
                else:
                    radius_note = " (سُجِّل محليًّا؛ سيُنشأ على الريديوس عند تفعيل الكتابة/المزامنة)."
            else:
                radius_note = " (تعذّر تحديد اسم مستخدم — أضِف جوّالًا للمشترك أو عيّنه في النافذة)."

    elif target_mode == "cards" and prior_user:
        # التحويل إلى البطاقات يُعطّل حساب الريديوس المُنشأ (لا يُحذف — يُعاد تفعيله لاحقًا).
        from app.services.radius_provisioning import set_subscriber_enabled
        dr = set_subscriber_enabled(username=prior_user, enabled=False,
                                    beneficiary_id=beneficiary_id, requested_by=actor)
        execute_sql(
            "UPDATE beneficiary_radius_accounts SET status='disabled', "
            "updated_at=CURRENT_TIMESTAMP WHERE beneficiary_id=%s", [beneficiary_id])
        if dr.get("ok") and dr.get("live"):
            radius_note = f" وعُطِّل حسابه على الريديوس (المستخدم: {prior_user})."
        elif not dr.get("ok"):
            radius_note = f" (تنبيه ريديوس: {dr.get('message')})"
        else:
            radius_note = " (سُجِّل محليًّا؛ سيُعطَّل عند تفعيل الكتابة/المزامنة)."

    log_action(
        "convert_access_mode",
        "beneficiary",
        beneficiary_id,
        f"تحويل إلى {ACCESS_LABELS.get(target_mode, target_mode)}",
    )
    try:
        from app.services.notification_service import notify_access_mode_changed
        notify_access_mode_changed(
            beneficiary_id,
            ACCESS_LABELS.get(target_mode, target_mode),
            session.get("username") or "admin",
        )
    except Exception:
        pass
    msg = f"تم تحويل {ben['full_name']} إلى {ACCESS_LABELS.get(target_mode, target_mode)}.{radius_note}"
    # AJAX response
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"ok": True, "message": msg})
    flash(msg, "success")
    # redirect back to referrer if available, else fallback
    referrer = request.form.get("_referrer") or request.referrer or ""
    if referrer and "/admin/" in referrer:
        return redirect(referrer)
    return redirect(url_for("admin_users_account_list"))
