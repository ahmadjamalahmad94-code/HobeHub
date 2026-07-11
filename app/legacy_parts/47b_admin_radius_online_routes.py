# صفحة "المتصلون الآن" — قراءة من /get_online_users

from flask import flash, redirect, render_template, request, session, url_for


@app.route("/admin/radius/online", methods=["GET"])
@admin_login_required
def admin_radius_online():
    from app.services.radius_dashboard import (
        get_radius_online_users,
        get_radius_kpis,
        get_radius_server_info,
    )

    sessions_result = get_radius_online_users(limit=100)
    kpis_result = get_radius_kpis()
    server_info = get_radius_server_info()

    # نحضّر sessions مع تنسيق
    sessions_raw = sessions_result.get("data") or [] if sessions_result.get("available") else []
    sessions = []
    for s in sessions_raw:
        if not isinstance(s, dict):
            continue
        # هذا الـ shape غير معروف بعد — نحاول قراءة الحقول الشائعة
        sessions.append({
            "username":      s.get("username") or s.get("user_name") or s.get("user") or "—",
            "framed_ip":     s.get("framed_ip") or s.get("framedipaddress") or s.get("ip") or "—",
            "nas":           s.get("nasipaddress") or s.get("nas") or "—",
            "running_sec":   s.get("running_sec") or s.get("acctsessiontime") or 0,
            "calling_id":    s.get("callingstationid") or s.get("mac") or "—",
            "bytes_in":      s.get("bytes_in") or s.get("acctinputoctets") or 0,
            "bytes_out":     s.get("bytes_out") or s.get("acctoutputoctets") or 0,
            "session_id":    s.get("acctsessionid") or s.get("session_id") or "",
            "raw":           s,
        })

    # ── تصنيف الجلسات: مشترك (يوزر إنترنت) أم بطاقة — بمطابقة محليّة سريعة ──
    from app.db.queries import query_all
    _unames = [s["username"] for s in sessions if s["username"] and s["username"] != "—"]
    sub_set, card_set = set(), set()
    if _unames:
        _ph = ",".join(["%s"] * len(_unames))
        try:
            for _r in (query_all(
                f"SELECT external_username AS u FROM beneficiary_radius_accounts "
                f"WHERE external_username IN ({_ph})", _unames) or []):
                if _r.get("u"):
                    sub_set.add(str(_r["u"]))
        except Exception:
            pass
        # اسم المستخدم على الريديوس غالبًا = جوّال المستفيد — نطابقه أيضًا كي
        # لا يظهر المشتركون «غير معروف».
        try:
            for _r in (query_all(
                f"SELECT phone AS u FROM beneficiaries WHERE phone IN ({_ph})",
                _unames) or []):
                if _r.get("u"):
                    sub_set.add(str(_r["u"]))
        except Exception:
            pass
        try:
            for _r in (query_all(
                f"SELECT card_username AS u FROM manual_access_cards "
                f"WHERE card_username IN ({_ph})", _unames) or []):
                if _r.get("u"):
                    card_set.add(str(_r["u"]))
        except Exception:
            pass
    _KIND_LABEL = {"subscriber": "مشترك", "card": "بطاقة", "unknown": "غير معروف"}
    sub_count = card_count = unknown_count = 0
    for s in sessions:
        u = s["username"]
        if u in sub_set:
            kind = "subscriber"; sub_count += 1
        elif u in card_set:
            kind = "card"; card_count += 1
        else:
            kind = "unknown"; unknown_count += 1
        s["account_kind"] = kind
        s["account_kind_label"] = _KIND_LABEL[kind]

    return render_template(
        "admin/radius/online.html",
        sessions_result=sessions_result,
        sessions=sessions,
        kpis_result=kpis_result,
        server_info=server_info,
        online_count=len(sessions),
        subscriber_count=sub_count,
        card_count=card_count,
        unknown_count=unknown_count,
    )


@app.route("/admin/radius/nas", methods=["GET"])
@admin_login_required
def admin_radius_nas():
    """قائمة الـNAS/الراوترات من الريديوس (GET /api/v1/nas) — قراءة فقط."""
    from app.services.radius_client import get_radius_client, is_api_under_development
    available = not is_api_under_development()
    nas = []
    if available:
        try:
            client = get_radius_client()
            nas = client.get_nas_list() if hasattr(client, "get_nas_list") else []
        except Exception:
            nas = []
    return render_template("admin/radius/nas.html",
                           nas=nas, available=available, nas_count=len(nas))


@app.route("/admin/radius/online/refresh", methods=["POST"])
@admin_login_required
def admin_radius_online_refresh():
    """يلغي الكاش ويعيد التوجيه — يضمن جلب طازج."""
    from app.services.radius_dashboard import invalidate_cache
    invalidate_cache("radius:online_users")
    invalidate_cache("radius:quick_stats")
    flash("تم تحديث البيانات.", "success")
    return redirect(url_for("admin_radius_online"))
