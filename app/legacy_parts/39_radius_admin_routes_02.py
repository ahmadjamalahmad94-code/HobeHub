# Continued split from 39_radius_admin_routes.py lines 136-222. Loaded by app.legacy.


@app.route("/admin/radius/users-online")
@login_required
@permission_required("view_radius_status")
def radius_online_users_page():
    rows = []
    error_text = ""
    try:
        rows_data = get_radius_client().get_online_users({})
        if isinstance(rows_data, dict):
            rows = rows_data.get("data") or rows_data.get("users") or rows_data.get("rows") or []
    except Exception as exc:
        error_text = str(exc)
    rows_html = ""
    for row in rows[:200]:
        username = safe(row.get("username") or row.get("user_name") or row.get("name") or "-")
        ip_address = safe(row.get("ip") or row.get("framedipaddress") or "-")
        session_time = safe(row.get("session_time") or row.get("uptime") or "-")
        disconnect_btn = ""
        if has_permission("disconnect_radius_user") and username != "-":
            disconnect_btn = f"""
            <form method='POST' action='{url_for("radius_disconnect_user_page")}' onsubmit="return confirm('هل تريد فصل هذا المستخدم؟')">
              <input type='hidden' name='username' value='{username}'>
              <button class='btn btn-danger btn-icon' type='submit' title='فصل'><i class='fa-solid fa-plug-circle-xmark'></i></button>
            </form>
            """
        rows_html += f"<tr><td>{username}</td><td>{ip_address}</td><td>{session_time}</td><td>{disconnect_btn or '-'}</td></tr>"
    content = f"""
    <div class='hero'><div><h1>المستخدمون المتصلون</h1><p>عرض مراقبة فقط مع إمكانية الفصل لمن يملك الصلاحية المناسبة.</p></div><div class='actions'><a class='btn btn-soft' href='{url_for("radius_user_lookup_page")}'>بحث مستخدم</a></div></div>
    {f"<div class='flash error'>{safe(error_text)}</div>" if error_text else ""}
    <div class='table-wrap'><table><thead><tr><th>اسم المستخدم</th><th>IP</th><th>مدة الجلسة</th><th>فصل</th></tr></thead><tbody>{rows_html or "<tr><td colspan='4'>لا توجد بيانات متاحة حاليًا.</td></tr>"}</tbody></table></div>
    """
    return render_page("المستخدمون المتصلون", content)


@app.route("/admin/radius/disconnect", methods=["POST"])
@login_required
@permission_required("disconnect_radius_user")
def radius_disconnect_user_page():
    username = clean_csv_value(request.form.get("username"))
    if not username:
        flash("اسم المستخدم مطلوب.", "error")
        return redirect(url_for("radius_online_users_page"))
    from app.services.radius_provisioning import disconnect_subscriber
    res = disconnect_subscriber(username=username, requested_by=session.get("username") or "admin")
    if res.get("ok"):
        log_action("disconnect_radius_user", "radius_user", None,
                   f"Disconnect {username} live={res.get('live')}")
        flash("تم إرسال أمر الفصل بنجاح." if res.get("live")
              else "سُجِّل أمر الفصل (سيُنفَّذ عند تفعيل الكتابة/المزامنة).", "success")
    else:
        log_action("disconnect_radius_user_failed", "radius_user", None,
                   f"{username}: {res.get('message')}")
        flash(f"تعذر فصل المستخدم: {safe(str(res.get('message')))}", "error")
    return redirect(request.referrer or url_for("radius_online_users_page"))


@app.route("/admin/radius/lock-mac", methods=["POST"])
@login_required
@permission_required("disconnect_radius_user")
def radius_lock_mac_page():
    username = clean_csv_value(request.form.get("username"))
    mac = clean_csv_value(request.form.get("mac"))
    if not username:
        flash("اسم المستخدم مطلوب.", "error")
        return redirect(request.referrer or url_for("radius_online_users_page"))
    from app.services.radius_provisioning import lock_session_mac
    res = lock_session_mac(username=username, mac=mac,
                           requested_by=session.get("username") or "admin")
    if res.get("ok"):
        flash("تم قفل MAC للجلسة." if res.get("live")
              else "سُجِّل طلب قفل MAC (سيُنفَّذ عند تفعيل الكتابة/المزامنة).", "success")
    else:
        flash(f"تعذّر قفل MAC: {safe(str(res.get('message')))}", "error")
    return redirect(request.referrer or url_for("radius_online_users_page"))


@app.route("/admin/radius/temp-speed", methods=["POST"])
@login_required
@permission_required("disconnect_radius_user")
def radius_temp_speed_page():
    username = clean_csv_value(request.form.get("username"))
    if not username:
        flash("اسم المستخدم مطلوب.", "error")
        return redirect(request.referrer or url_for("radius_online_users_page"))

    def _to_int(v):
        try:
            return int(v)
        except (TypeError, ValueError):
            return 0
    down = _to_int(request.form.get("down_kbps"))
    up = _to_int(request.form.get("up_kbps"))
    minutes = _to_int(request.form.get("minutes")) or 60
    if down <= 0 and up <= 0:
        flash("حدّد سرعة تنزيل أو رفع.", "error")
        return redirect(request.referrer or url_for("radius_online_users_page"))
    from app.services.radius_client import get_radius_client as _mrc
    from app.services.radius_client import is_api_under_development
    if is_api_under_development():
        flash("واجهة الريديوس غير مفعّلة.", "error")
        return redirect(request.referrer or url_for("radius_online_users_page"))
    try:
        client = _mrc()
        if not hasattr(client, "set_temp_speed"):
            flash("رفع السرعة غير مدعوم في هذا الوضع.", "error")
            return redirect(request.referrer or url_for("radius_online_users_page"))
        sid = clean_csv_value(request.form.get("session_id"))
        res = client.set_temp_speed(username, down_kbps=down, up_kbps=up, minutes=minutes,
                                    session_id=sid, requested_by=session.get("username") or "admin")
        if bool(getattr(res, "ok", False)):
            flash(f"تم رفع السرعة مؤقتًا لـ{minutes} دقيقة.", "success")
        else:
            flash(f"تعذّر رفع السرعة: {safe(str(getattr(res, 'message', '') or ''))}", "error")
    except Exception as exc:
        flash(f"تعذّر رفع السرعة: {safe(str(exc))}", "error")
    return redirect(request.referrer or url_for("radius_online_users_page"))


@app.route("/admin/radius/extend-time", methods=["POST"])
@login_required
@permission_required("disconnect_radius_user")
def radius_extend_time_page():
    username = clean_csv_value(request.form.get("username"))
    try:
        minutes = int(request.form.get("minutes") or 0)
    except (TypeError, ValueError):
        minutes = 0
    if not username or minutes <= 0:
        flash("اسم المستخدم وعدد الدقائق مطلوبان.", "error")
        return redirect(request.referrer or url_for("radius_online_users_page"))
    from app.services.radius_client import get_radius_client as _mrc
    from app.services.radius_client import is_api_under_development
    if is_api_under_development():
        flash("واجهة الريديوس غير مفعّلة.", "error")
        return redirect(request.referrer or url_for("radius_online_users_page"))
    try:
        client = _mrc()
        res = client.add_time(username, sel_time=0, add_time=minutes,
                              requested_by=session.get("username") or "admin")
        if bool(getattr(res, "ok", False)):
            flash(f"تم تمديد الوقت {minutes} دقيقة.", "success")
        else:
            flash(f"تعذّر التمديد: {safe(str(getattr(res, 'message', '') or ''))}", "error")
    except Exception as exc:
        flash(f"تعذّر التمديد: {safe(str(exc))}", "error")
    return redirect(request.referrer or url_for("radius_online_users_page"))


@app.route("/admin/radius/toggle-account", methods=["POST"])
@login_required
@permission_required("disconnect_radius_user")
def radius_toggle_account_page():
    username = clean_csv_value(request.form.get("username"))
    action = clean_csv_value(request.form.get("action"))
    if not username:
        flash("اسم المستخدم مطلوب.", "error")
        return redirect(request.referrer or url_for("radius_online_users_page"))
    from app.services.radius_provisioning import set_subscriber_enabled
    enable = action == "enable"
    res = set_subscriber_enabled(username=username, enabled=enable,
                                 requested_by=session.get("username") or "admin")
    if res.get("ok"):
        flash(("تم تفعيل الحساب." if enable else "تم تعطيل الحساب.") if res.get("live")
              else "سُجِّل الإجراء (سيُنفَّذ عند تفعيل الكتابة).", "success")
    else:
        flash(f"تعذّر تنفيذ الإجراء: {safe(str(res.get('message')))}", "error")
    return redirect(request.referrer or url_for("radius_online_users_page"))


@app.route("/admin/radius/user-lookup", methods=["GET", "POST"])
@login_required
@permission_required("view_radius_status")
def radius_user_lookup_page():
    username = clean_csv_value(request.form.get("username") if request.method == "POST" else request.args.get("username"))
    cards = {}
    sessions_data = {}
    usage_data = {}
    bandwidth_data = {}
    devices_data = {}
    error_text = ""
    if username:
        from app.services.radius_client import get_radius_client as _mrc
        from app.services.radius_client import is_api_under_development
        if is_api_under_development():
            error_text = "واجهة الريديوس غير مفعّلة — فعّل «تفعيل القراءة» من إعدادات المصادقة."
        else:
            try:
                client = _mrc()
                usage_data = mask_sensitive_data(client.get_user_usage(username) or {})
                sessions_data = mask_sensitive_data(client.get_user_sessions(username) or {})
                bandwidth_data = mask_sensitive_data(client.get_user_bandwidth(username) or {})
                _found = client.search_users(username, limit=5)
                _items = _found.get("data") if isinstance(_found, dict) else []
                devices_data = mask_sensitive_data(_items[0] if _items else {})
            except Exception as exc:
                error_text = str(exc)
    content = f"""
    <div class='hero'><div><h1>بحث مستخدم RADIUS</h1><p>عرض الجلسات والاستهلاك والأجهزة والبطاقات المتاحة للمستخدم.</p></div></div>
    <div class='card'><form method='POST'><div class='grid grid-2'><div><label>اسم المستخدم</label><input name='username' value='{safe(username)}' required></div><div class='actions' style='align-items:end'><button class='btn btn-primary' type='submit'>بحث</button></div></div></form></div>
    {f"<div class='flash error' style='margin-top:16px'>{safe(error_text)}</div>" if error_text else ""}
    <div class='grid grid-2' style='margin-top:16px'>
      <div class='card'><h3>الجلسات</h3><pre>{safe(json.dumps(sessions_data, ensure_ascii=False, indent=2)) if sessions_data else '-'}</pre></div>
      <div class='card'><h3>الاستهلاك</h3><pre>{safe(json.dumps(usage_data, ensure_ascii=False, indent=2)) if usage_data else '-'}</pre></div>
      <div class='card'><h3>الباندويث</h3><pre>{safe(json.dumps(bandwidth_data, ensure_ascii=False, indent=2)) if bandwidth_data else '-'}</pre></div>
      <div class='card'><h3>بيانات الحساب</h3><pre>{safe(json.dumps(devices_data, ensure_ascii=False, indent=2)) if devices_data else '-'}</pre></div>
    </div>
    """
    return render_page("بحث مستخدم RADIUS", content)
