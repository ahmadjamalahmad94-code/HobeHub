# داشبورد مشترك اليوزر — Phase 1.
# لا يلمس /user/dashboard القديم — يضيف /user/account/* جديدة.

from flask import flash, redirect, render_template, request, session, url_for


def _build_context(extra=None):
    """يبني السياق المشترك لكل صفحات /user/account/*."""
    from app.services.radius_client import get_radius_client
    from app.services.subscriber_radius_status import get_subscriber_radius_status
    from app.services.access_rules import whatsapp_group_url_for_user_type

    beneficiary = get_current_portal_beneficiary() or {}
    beneficiary_id = int(session.get("beneficiary_id") or 0)
    radius_account = query_one(
        """
        SELECT external_username, current_profile_name
        FROM beneficiary_radius_accounts
        WHERE beneficiary_id=%s
        LIMIT 1
        """,
        [beneficiary_id],
    ) or {}
    radius_username = (
        radius_account.get("external_username")
        or session.get("beneficiary_username")
        or beneficiary.get("phone")
        or ""
    )

    client = get_radius_client()
    all_pending = client.list_pending_actions(action_type="", status="pending", limit=200)
    my_pending = [p for p in all_pending if p.beneficiary_id == beneficiary_id]

    done_row = query_one(
        "SELECT COUNT(*) AS c FROM radius_pending_actions WHERE beneficiary_id=%s AND status='done'",
        [beneficiary_id],
    ) or {}

    radius_status = get_subscriber_radius_status(beneficiary_id, radius_username)

    from app.services.subscriber_radius_view import build_subscriber_radius_view
    radius_view = build_subscriber_radius_view(
        beneficiary_id,
        radius_username,
        external_id=str(beneficiary.get("linked_radius_external_id") or ""),
    )
    account_status = "active" if (
        radius_status.get("is_online")
        or radius_status.get("available")
        or radius_account.get("current_profile_name")
        or radius_account.get("external_username")
    ) else (radius_status.get("status") or "pending")

    ctx = {
        "beneficiary_full_name": beneficiary.get("full_name") or session.get("beneficiary_full_name", ""),
        "beneficiary_first_name": (beneficiary.get("full_name") or "").split(" ")[0],
        "beneficiary_phone": beneficiary.get("phone"),
        "radius_username": radius_username,
        "current_profile_name": radius_account.get("current_profile_name") or "",
        "radius_status": radius_status,
        "radius_view": radius_view,
        "account_status": account_status,
        "whatsapp_group_url": whatsapp_group_url_for_user_type(beneficiary.get("user_type") or ""),
        "pending_count": len(my_pending),
        "done_count": int(done_row.get("c") or 0),
    }
    if extra:
        ctx.update(extra)
    return ctx


@app.route("/user/account", methods=["GET"])
@user_login_required
def user_account_dashboard():
    return render_template("portal/account/dashboard.html", **_build_context())


# ─── طلب تغيير كلمة المرور ───────────────────────────────────────────
@app.route("/user/account/change-password", methods=["GET", "POST"])
@user_login_required
def user_account_change_password():
    flash("تغيير كلمة المرور موقوف مؤقتًا. عند الحاجة تواصل مع الإدارة.", "warning")
    return render_template(
        "portal/account/forms.html",
        form_type="password_frozen",
        form_title="تغيير كلمة المرور موقوف مؤقتًا",
        form_subtitle="هذه الخدمة غير متاحة حاليًا من بوابة المشترك.",
        form_icon="fa-lock",
        **_build_context(),
    )

    from app.services.radius_client import get_radius_client

    if request.method == "POST":
        current = clean_csv_value(request.form.get("current_password"))
        new = clean_csv_value(request.form.get("new_password"))
        confirm = clean_csv_value(request.form.get("confirm_password"))

        if not current or not new or not confirm:
            flash("جميع الحقول مطلوبة.", "error")
            return redirect(url_for("user_account_change_password"))
        if new != confirm:
            flash("كلمة المرور الجديدة لا تطابق التأكيد.", "error")
            return redirect(url_for("user_account_change_password"))
        if len(new) < 6:
            flash("كلمة المرور القصيرة جدًا.", "error")
            return redirect(url_for("user_account_change_password"))

        beneficiary_id = int(session.get("beneficiary_id") or 0)
        username = session.get("beneficiary_username") or ""

        client = get_radius_client()
        # في الوضع manual: نسجل الطلب في قائمة الانتظار (لا نخزن كلمة المرور كاملة)
        result = client.reset_password(
            user_external_id=username,
            new_password=new,
            beneficiary_id=beneficiary_id,
            requested_by=session.get("beneficiary_username") or "user",
        )
        log_action("user_request_password", "radius_pending_actions",
                   result.pending_action_id or 0,
                   f"Password change request from {username}")
        flash("تم إرسال طلبك. سيتم تغيير كلمة المرور بعد الموافقة.", "success")
        return redirect(url_for("user_account_my_requests"))

    return render_template(
        "portal/account/forms.html",
        form_type="change_password",
        form_title="تغيير كلمة المرور",
        form_subtitle="غيّر كلمة مرور حساب الإنترنت",
        form_icon="fa-key",
        **_build_context(),
    )


# ─── طلب فتح موقع محظور ──────────────────────────────────────────────
@app.route("/user/account/unblock-site", methods=["GET", "POST"])
@user_login_required
def user_account_unblock_site():
    from app.services.radius_client import get_radius_client

    if request.method == "POST":
        site_url = clean_csv_value(request.form.get("site_url"))
        reason = clean_csv_value(request.form.get("reason"))

        if not site_url:
            flash("الرابط مطلوب.", "error")
            return redirect(url_for("user_account_unblock_site"))

        beneficiary_id = int(session.get("beneficiary_id") or 0)
        username = session.get("beneficiary_username") or ""

        client = get_radius_client()
        # نستخدم helper _enqueue من manual عبر دالة عامة في base — هنا نستدعيها بـ action مخصص
        from app.services.radius_client.manual import ManualRadiusClient
        manual = ManualRadiusClient()
        result = manual._enqueue(
            "unblock_site",
            target_kind="user",
            target_external_id=username,
            beneficiary_id=beneficiary_id,
            payload={"site_url": site_url, "reason": reason},
            requested_by=session.get("beneficiary_username") or "user",
        )
        log_action("user_request_unblock_site", "radius_pending_actions",
                   result.pending_action_id or 0,
                   f"Unblock site request from {username}: {site_url}")
        flash("تم إرسال طلب فتح الموقع. سيراجعه الفريق قريبًا.", "success")
        return redirect(url_for("user_account_my_requests"))

    return render_template(
        "portal/account/forms.html",
        form_type="unblock_site",
        form_title="طلب فتح موقع محظور",
        form_subtitle="اطلب فتح رابط معين",
        form_icon="fa-globe",
        **_build_context(),
    )


# ─── طلب رفع السرعة ──────────────────────────────────────────────────
@app.route("/user/account/speed-upgrade", methods=["GET", "POST"])
@user_login_required
def user_account_speed_upgrade():
    if request.method == "POST":
        speed = clean_csv_value(request.form.get("requested_speed"))
        duration = clean_csv_value(request.form.get("duration"))
        reason = clean_csv_value(request.form.get("reason"))

        if not speed or not duration:
            flash("السرعة والمدة مطلوبتان.", "error")
            return redirect(url_for("user_account_speed_upgrade"))

        beneficiary_id = int(session.get("beneficiary_id") or 0)
        username = session.get("beneficiary_username") or ""

        from app.services.radius_client.manual import ManualRadiusClient
        manual = ManualRadiusClient()
        result = manual._enqueue(
            "speed_upgrade",
            target_kind="user",
            target_external_id=username,
            beneficiary_id=beneficiary_id,
            payload={"requested_speed": speed, "duration": duration, "reason": reason},
            requested_by=session.get("beneficiary_username") or "user",
        )
        log_action("user_request_speed_upgrade", "radius_pending_actions",
                   result.pending_action_id or 0,
                   f"Speed upgrade {speed}/{duration} from {username}")
        flash("تم إرسال طلب رفع السرعة. ستراجعه الإدارة.", "success")
        return redirect(url_for("user_account_my_requests"))

    return render_template(
        "portal/account/forms.html",
        form_type="speed_upgrade",
        form_title="طلب رفع السرعة",
        form_subtitle="اطلب ترقية سرعة الإنترنت",
        form_icon="fa-gauge-high",
        **_build_context(),
    )


# ─── طلباتي ─────────────────────────────────────────────────────────
_USER_ACTION_LABELS = {
    "reset_password": "تغيير كلمة المرور",
    "unblock_site":   "فتح موقع",
    "speed_upgrade":  "رفع السرعة",
    "create_user":    "إنشاء حساب",
    "add_time":       "إضافة وقت",
    "add_quota_mb":   "إضافة كوتة",
    "disconnect":     "فصل جلسة",
}

@app.route("/user/account/requests", methods=["GET"])
@user_login_required
def user_account_my_requests():
    beneficiary_id = int(session.get("beneficiary_id") or 0)
    rows = query_all(
        """
        SELECT * FROM radius_pending_actions
        WHERE beneficiary_id=%s
        ORDER BY id DESC
        LIMIT 100
        """,
        [beneficiary_id],
    )
    items = []
    for r in rows:
        items.append({
            "id": r["id"],
            "action_type": r["action_type"],
            "type_label": _USER_ACTION_LABELS.get(r["action_type"], r["action_type"]),
            "requested_at": r.get("requested_at"),
            "status": r.get("status"),
            "notes": r.get("notes") or "",
        })
    return render_template(
        "portal/account/requests.html",
        items=items,
        **_build_context(),
    )
