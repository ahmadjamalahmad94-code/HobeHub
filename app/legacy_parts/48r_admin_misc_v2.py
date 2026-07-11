# 48p_admin_misc_v2.py — إعادة تصميم 7 صفحات admin متبقية:
#   /profile, /admin/internet-requests/<id>, /usage-archive,
#   /timer, /admin-control,
#   /admin/radius/users-online, /admin/radius/user-lookup, /admin/radius/app-test

import json as _json
from flask import render_template, request, redirect, url_for, flash, session


def _short_dt(value):
    """يختصر طابع الوقت إلى «YYYY-MM-DD HH:MM» (بلا ثوانٍ ولا T/Z)."""
    s = str(value or "").strip()
    if not s:
        return ""
    s = s.replace("T", " ").replace("Z", "")
    if "." in s:
        s = s.split(".", 1)[0]
    parts = s.split(" ")
    if len(parts) == 2 and ":" in parts[1]:
        return parts[0] + " " + ":".join(parts[1].split(":")[:2])
    return s[:16]


try:
    app.jinja_env.filters["shortdt"] = _short_dt  # noqa: F821 — app من legacy globals
except Exception:
    pass


# ════════════════════════════════════════════════════
# /profile (admin self-edit)
# ════════════════════════════════════════════════════
def _profile_v2():
    account = query_one("SELECT * FROM app_accounts WHERE id=%s", [session.get("account_id")])
    if not account:
        flash("الحساب غير موجود.", "error")
        return redirect(url_for("dashboard"))

    perms_rows = query_all(
        """SELECT p.name FROM account_permissions ap
           JOIN permissions p ON p.id=ap.permission_id
           WHERE ap.account_id=%s ORDER BY p.name""",
        [session.get("account_id")],
    )
    permissions = [r["name"] for r in (perms_rows or [])]

    if request.method == "POST":
        current_password = clean_csv_value(request.form.get("current_password"))
        new_password = clean_csv_value(request.form.get("new_password"))
        full_name = clean_csv_value(request.form.get("full_name"))
        if not verify_admin_password(account.get("password_hash"), current_password):
            flash("كلمة المرور الحالية غير صحيحة.", "error")
            return redirect(url_for("profile_page"))
        if not new_password or len(new_password) < 6:
            flash("كلمة المرور الجديدة قصيرة (6 أحرف على الأقل).", "error")
            return redirect(url_for("profile_page"))
        execute_sql(
            "UPDATE app_accounts SET full_name=%s, password_hash=%s WHERE id=%s",
            [full_name, admin_password_hash(new_password), session.get("account_id")],
        )
        session["full_name"] = full_name
        log_action("change_password", "account", session.get("account_id"), "تغيير من الصفحة الشخصية")
        flash("تم تحديث بياناتك ✓", "success")
        return redirect(url_for("profile_page"))

    return render_template(
        "admin/profile/profile.html",
        account=account, permissions=permissions,
        permission_label=permission_label,
    )


if "profile_page" in app.view_functions:
    @login_required
    def _new_profile():
        return _profile_v2()
    app.view_functions["profile_page"] = _new_profile


# ════════════════════════════════════════════════════
# /admin/internet-requests/<id> detail
# ════════════════════════════════════════════════════
def _admin_internet_request_detail_v2(request_id):
    try:
        process_due_speed_restores()
    except Exception:
        pass
    req = get_internet_request_row(request_id)
    if not req:
        flash("الطلب غير موجود.", "error")
        return redirect(url_for("admin_internet_requests_page"))

    requested_payload = json_safe_dict(req.get("requested_payload"))
    admin_payload = json_safe_dict(req.get("admin_payload"))
    api_response = json_safe_dict(req.get("api_response"))
    linked_account = get_radius_account(req["beneficiary_id"]) or {}
    merged_username = get_request_external_username(req, linked_account)

    return render_template(
        "admin/internet_requests/detail.html",
        req=req,
        requested_payload=requested_payload,
        admin_payload=admin_payload,
        linked_account=linked_account,
        merged_username=merged_username,
        requested_payload_json=_json.dumps(requested_payload, ensure_ascii=False, indent=2) if requested_payload else "",
        admin_payload_json=_json.dumps(admin_payload, ensure_ascii=False, indent=2) if admin_payload else "",
        api_response_json=_json.dumps(api_response, ensure_ascii=False, indent=2) if api_response else "",
        internet_request_type_label=internet_request_type_label,
        format_dt_short=format_dt_short,
    )


if "admin_internet_request_detail_page" in app.view_functions:
    @login_required
    @permission_required("manage_internet_requests")
    def _new_admin_inet_req_detail(request_id):
        return _admin_internet_request_detail_v2(request_id)
    app.view_functions["admin_internet_request_detail_page"] = _new_admin_inet_req_detail


# ════════════════════════════════════════════════════
# /usage-archive
# ════════════════════════════════════════════════════
def _usage_archive_v2():
    before_date = parse_date_or_none(request.args.get("date_to"))
    where = ""
    params = []
    if before_date:
        where = "WHERE l.usage_date <= %s"
        params = [before_date]

    rows = query_all(
        f"""
        SELECT l.*, b.full_name, b.phone, b.user_type
        FROM beneficiary_usage_logs_archive l
        LEFT JOIN beneficiaries b ON b.id = l.beneficiary_id
        {where}
        ORDER BY l.usage_time DESC, l.archive_id DESC
        LIMIT 1000
        """,
        params,
    )

    total_row = query_one("SELECT COUNT(*) AS c FROM beneficiary_usage_logs_archive") or {}
    total = int(total_row.get("c") or 0)
    oldest_row = query_one("SELECT MIN(usage_date) AS d FROM beneficiary_usage_logs_archive") or {}
    oldest = oldest_row.get("d")

    return render_template(
        "admin/usage_archive/list.html",
        rows=rows,
        total=total,
        oldest=oldest,
        filters={"date_to": request.args.get("date_to") or ""},
        can_export=has_permission("export_archive"),
        can_restore=has_permission("restore_archive"),
        can_delete=has_permission("delete_archive"),
        can_clear=has_permission("delete_archive") or has_permission("restore_archive"),
        format_dt_short=format_dt_short,
    )


if "usage_archive_page" in app.view_functions:
    @login_required
    @permission_required("view_archive")
    def _new_usage_archive():
        return _usage_archive_v2()
    app.view_functions["usage_archive_page"] = _new_usage_archive


# ════════════════════════════════════════════════════
# /timer
# ════════════════════════════════════════════════════
def _timer_v2():
    return render_template("admin/timer/timer.html")


if "power_timer_page" in app.view_functions:
    @login_required
    def _new_timer():
        return _timer_v2()
    app.view_functions["power_timer_page"] = _new_timer


# ════════════════════════════════════════════════════
# /admin-control
# ════════════════════════════════════════════════════
def _admin_control_v2():
    if not (has_permission("manage_bulk_ops") or has_permission("manage_system_cleanup")):
        flash("غير مصرح لك بهذه الصفحة.", "error")
        return redirect(url_for("dashboard"))

    return render_template(
        "admin/control/panel.html",
        can_bulk=has_permission("manage_bulk_ops"),
        can_cleanup=has_permission("manage_system_cleanup"),
    )


if "admin_control_panel" in app.view_functions:
    @login_required
    def _new_admin_control():
        return _admin_control_v2()
    app.view_functions["admin_control_panel"] = _new_admin_control


# ════════════════════════════════════════════════════
# /admin/radius/users-online
# ════════════════════════════════════════════════════
def _radius_online_users_v2():
    rows = []
    error_text = ""
    try:
        client = get_radius_client()
        raw = client.get_online_users() or []
        for s in raw:
            rows.append({
                "username": getattr(s, "username", "") or "",
                "framed_ip": getattr(s, "framed_ip_address", "") or "",
                "ip": getattr(s, "ip", "") or "",
                "mac": getattr(s, "mac_address", "") or "",
                "start_time": getattr(s, "start_time", "") or "",
                "usage_mb": getattr(s, "usage_mb", "") or "0",
            })
    except Exception as exc:
        error_text = str(exc)

    return render_template(
        "admin/radius/users_online.html",
        rows=rows,
        error_text=error_text,
    )


if "radius_online_users_page" in app.view_functions:
    @login_required
    @permission_required("view_radius_status")
    def _new_radius_online():
        return _radius_online_users_v2()
    app.view_functions["radius_online_users_page"] = _new_radius_online


# ════════════════════════════════════════════════════
# /admin/radius/user-lookup
# ════════════════════════════════════════════════════
def _radius_user_lookup_v2():
    username = clean_csv_value(
        request.form.get("username") if request.method == "POST" else request.args.get("username")
    )
    sessions_json = usage_json = bandwidth_json = devices_cards_json = ""
    error_text = ""
    summary = {}
    if username:
        # العميل الحديث (/api/v1) بدل القديم (advrapp) الذي كان يُظهر «إعدادات
        # التكامل غير مكتملة».
        from app.services.radius_client import get_radius_client as _mrc
        from app.services.radius_client import is_api_under_development
        if is_api_under_development():
            error_text = "واجهة الريديوس غير مفعّلة — فعّل «تفعيل القراءة» من إعدادات المصادقة."
        else:
            try:
                client = _mrc()
                sd = mask_sensitive_data(client.get_user_sessions(username) or {})
                ud = mask_sensitive_data(client.get_user_usage(username) or {})
                bd = mask_sensitive_data(client.get_user_bandwidth(username) or {})
                _found = client.search_users(username, limit=5)
                _items = _found.get("data") if isinstance(_found, dict) else []
                dd = mask_sensitive_data(_items[0] if _items else {})
                # ملخّص منسّق للعرض (بدل JSON خام)
                _acct = dd if isinstance(dd, dict) else {}
                _usage = ud if isinstance(ud, dict) else {}
                _sess = (sd.get("data") if isinstance(sd, dict) else sd) or []
                _bin = int(_usage.get("used_bytes_in") or _usage.get("total_bytes_in") or _usage.get("bytes_in") or 0)
                _bout = int(_usage.get("used_bytes_out") or _usage.get("total_bytes_out") or _usage.get("bytes_out") or 0)
                _down = int(_acct.get("download_speed_kbps") or 0)
                _up = int(_acct.get("upload_speed_kbps") or 0)
                # الاستهلاك: لو نقطة usage رجعت صفرًا، اجمعه من الجلسات النشطة.
                _sess_in = sum(int(x.get("bytes_in") or 0) for x in _sess if isinstance(x, dict))
                _sess_out = sum(int(x.get("bytes_out") or 0) for x in _sess if isinstance(x, dict))
                _bin = _bin or _sess_in
                _bout = _bout or _sess_out
                # السرعة والاسم مخزّنان على الباقة لا الحساب — اجلبهما من الباقة عند غيابهما.
                _plan_name = _acct.get("plan_name") or ""
                if _acct.get("plan_id") and ((not _down and not _up) or not _plan_name):
                    try:
                        for _p in (client.get_profiles() or []):
                            if str(_p.get("id") or _p.get("external_id") or "") == str(_acct.get("plan_id")):
                                _down = _down or int(_p.get("speed_down_kbps") or 0)
                                _up = _up or int(_p.get("speed_up_kbps") or 0)
                                _plan_name = _plan_name or (
                                    _p.get("name") or _p.get("plan_name") or _p.get("title")
                                    or _p.get("external_name") or "")
                                break
                    except Exception:
                        pass
                # اسم صاحب الحساب من مستفيدي HobeHub (بالجوّال أو اسم مستخدم الريديوس).
                _owner = ""
                try:
                    _bo = query_one("SELECT full_name FROM beneficiaries WHERE phone=%s LIMIT 1", [username]) or {}
                    _owner = _bo.get("full_name") or ""
                    if not _owner:
                        _bo2 = query_one(
                            "SELECT b.full_name FROM beneficiary_radius_accounts r "
                            "JOIN beneficiaries b ON b.id=r.beneficiary_id "
                            "WHERE r.external_username=%s LIMIT 1", [username]) or {}
                        _owner = _bo2.get("full_name") or ""
                except Exception:
                    pass
                summary = {
                    "username": username,
                    "owner": _owner,
                    "found": bool(_acct),
                    "online": bool(_sess),
                    "status": _acct.get("status") or ("online" if _sess else "offline"),
                    "plan": _plan_name or (("باقة #%s" % _acct.get("plan_id")) if _acct.get("plan_id") else ""),
                    "down": ("%s Kbps" % _down) if _down else "",
                    "up": ("%s Kbps" % _up) if _up else "",
                    "usage_gb": round((_bin + _bout) / (1024 ** 3), 2),
                    "sessions": len(_sess) if isinstance(_sess, list) else 0,
                    "last_seen": _short_dt(_usage.get("last_seen_at") or _usage.get("last_session_at") or ""),
                    "mobile": _acct.get("mobile") or "",
                }
                _sessions_list = []
                for _s in (_sess if isinstance(_sess, list) else []):
                    if not isinstance(_s, dict):
                        continue
                    _si = int(_s.get("bytes_in") or 0)
                    _so = int(_s.get("bytes_out") or 0)
                    _rs = int(_s.get("running_seconds") or _s.get("running_sec") or 0)
                    _sessions_list.append({
                        "ip": _s.get("framed_ip") or _s.get("framedipaddress") or _s.get("ip") or "—",
                        "mac": _s.get("calling_station_id") or _s.get("mac") or "—",
                        "nas": _s.get("nas_ip") or _s.get("nasipaddress") or "—",
                        "running_min": _rs // 60,
                        "in_mb": round(_si / (1024 * 1024), 2),
                        "out_mb": round(_so / (1024 * 1024), 2),
                        "session_id": _s.get("session_id") or _s.get("acctsessionid") or "",
                    })
                _secs = int(_usage.get("used_seconds") or _usage.get("total_seconds") or 0)
                _uniq = {s["mac"] for s in _sessions_list if s.get("mac") and s["mac"] != "—"}
                _cur = _sessions_list[0] if _sessions_list else {}
                _qtot = _acct.get("download_quota_mb") or _acct.get("combined_quota_mb") or 0
                summary.update({
                    "plan_id": _acct.get("plan_id") or "",
                    "user_type": _acct.get("user_type") or "",
                    "down_kbps": _down,
                    "up_kbps": _up,
                    "down_mb": round(_bin / (1024 * 1024), 2),
                    "up_mb": round(_bout / (1024 * 1024), 2),
                    "seconds": _secs,
                    "time_label": (("%dس %dد" % (_secs // 3600, (_secs % 3600) // 60)) if _secs else "0د"),
                    "expires_at": _short_dt(_acct.get("expire_at") or _acct.get("expires_at") or ""),
                    "quota_total_mb": int(_qtot) if _qtot else 0,
                    "unique_macs": len(_uniq),
                    "cur_ip": _cur.get("ip") or "—",
                    "cur_mac": _cur.get("mac") or "—",
                    "cur_nas": _cur.get("nas") or "—",
                    "cur_session_id": _cur.get("session_id") or "",
                    "enabled": str(_acct.get("status") or "").strip().lower() not in ("disabled", "suspended", "blocked", "expired"),
                    "sessions_list": _sessions_list,
                })
                # سجلّ الاحتساب: استهلاك تراكميّ حقيقيّ + الجلسات المنتهية.
                try:
                    _acc = client.get_accounting_usage(username) if hasattr(client, "get_accounting_usage") else None
                except Exception:
                    _acc = None
                if isinstance(_acc, dict):
                    _ai = int(_acc.get("total_bytes_in") or _acc.get("used_bytes_in") or _acc.get("bytes_in") or 0)
                    _ao = int(_acc.get("total_bytes_out") or _acc.get("used_bytes_out") or _acc.get("bytes_out") or 0)
                    if _ai or _ao:
                        summary["down_mb"] = round(_ai / (1024 * 1024), 2)
                        summary["up_mb"] = round(_ao / (1024 * 1024), 2)
                        summary["usage_gb"] = round((_ai + _ao) / (1024 ** 3), 2)
                _closed = []
                _hist_secs = 0
                try:
                    _hist = client.get_accounting_history(username, limit=50) if hasattr(client, "get_accounting_history") else []
                except Exception:
                    _hist = []
                for _h in (_hist or []):
                    if not isinstance(_h, dict):
                        continue
                    _hi = int(_h.get("bytes_in") or _h.get("acctinputoctets") or 0)
                    _ho = int(_h.get("bytes_out") or _h.get("acctoutputoctets") or 0)
                    _hd = int(_h.get("duration_sec") or _h.get("acctsessiontime") or _h.get("session_time") or 0)
                    _hist_secs += _hd
                    _closed.append({
                        "start": _short_dt(_h.get("started_at") or _h.get("acctstarttime") or ""),
                        "stop": _short_dt(_h.get("stopped_at") or _h.get("acctstoptime") or ""),
                        "ip": _h.get("framed_ip") or _h.get("framedipaddress") or _h.get("ip") or "—",
                        "mac": _h.get("calling_station_id") or _h.get("callingstationid") or _h.get("mac") or "—",
                        "in_mb": round(_hi / (1024 * 1024), 2),
                        "out_mb": round(_ho / (1024 * 1024), 2),
                        "duration_min": _hd // 60,
                    })
                summary["closed_sessions"] = _closed
                # وقت الاستخدام: مجموع مدد الجلسات المنتهية عند غياب seconds من usage.
                if not summary.get("seconds") and _hist_secs:
                    summary["seconds"] = _hist_secs
                    summary["time_label"] = ("%dس %dد" % (_hist_secs // 3600, (_hist_secs % 3600) // 60))
                sessions_json = _json.dumps(sd, ensure_ascii=False, indent=2) if sd else ""
                usage_json = _json.dumps(ud, ensure_ascii=False, indent=2) if ud else ""
                bandwidth_json = _json.dumps(bd, ensure_ascii=False, indent=2) if bd else ""
                devices_cards_json = _json.dumps({"account": dd}, ensure_ascii=False, indent=2) if dd else ""
            except Exception as exc:
                error_text = str(exc)

    return render_template(
        "admin/radius/user_lookup.html",
        username=username,
        summary=summary,
        sessions_json=sessions_json,
        usage_json=usage_json,
        bandwidth_json=bandwidth_json,
        devices_cards_json=devices_cards_json,
        error_text=error_text,
    )


if "radius_user_lookup_page" in app.view_functions:
    @login_required
    @permission_required("view_radius_status")
    def _new_radius_user_lookup():
        return _radius_user_lookup_v2()
    app.view_functions["radius_user_lookup_page"] = _new_radius_user_lookup


# ════════════════════════════════════════════════════
# /admin/radius/app-test
# ════════════════════════════════════════════════════
def _radius_app_test_v2():
    result = None
    account_json = details_json = ""
    if request.method == "POST":
        try:
            result = test_advradius_app_connection()
            log_action(
                "test_advradius_app_api", "radius_settings", None,
                f"AdvRadius App API ok account={_json.dumps(result.get('account') or {}, ensure_ascii=False)}",
            )
            account_json = _json.dumps(result.get("account") or {}, ensure_ascii=False, indent=2)
            details_json = _json.dumps(result.get("details") or {}, ensure_ascii=False, indent=2)
            flash("تم تنفيذ الاختبار بنجاح ✓", "success")
        except Exception as exc:
            log_action("test_advradius_app_api_failed", "radius_settings", None, str(exc))
            flash(f"فشل الاختبار: {exc}", "error")

    return render_template(
        "admin/radius/app_test.html",
        result=result,
        account_json=account_json,
        details_json=details_json,
    )


if "advradius_app_test_route" in app.view_functions:
    @login_required
    @permission_required("manage_radius_settings")
    def _new_radius_app_test():
        return _radius_app_test_v2()
    app.view_functions["advradius_app_test_route"] = _new_radius_app_test
