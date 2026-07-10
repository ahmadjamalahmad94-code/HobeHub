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
        try:
            client = get_radius_client()
            sessions_data = mask_sensitive_data(client.get_user_sessions({"username": username}))
            usage_data = mask_sensitive_data(client.get_user_usage({"username": username}))
            bandwidth_data = mask_sensitive_data(client.get_user_bandwidth({"username": username}))
            devices_data = mask_sensitive_data(client.get_user_devices({"username": username}))
            cards = mask_sensitive_data(client.get_user_cards({"username": username}))
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
      <div class='card'><h3>الأجهزة والبطاقات</h3><pre>{safe(json.dumps({'devices': devices_data, 'cards': cards}, ensure_ascii=False, indent=2)) if devices_data or cards else '-'}</pre></div>
    </div>
    """
    return render_page("بحث مستخدم RADIUS", content)
