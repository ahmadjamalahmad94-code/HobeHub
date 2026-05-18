# 48k_user_portal_redesign.py
# إعادة تصميم صفحتين في بوابة المشترك (يوزر):
#   - /internet/request و /user/internet/request → wizard كروت خدمات
#   - /user/profile  → ملف شخصي قابل للتعديل (عدا الجوال)

from flask import render_template, request, redirect, url_for, flash, session


# ════════════════════════════════════════════════════════════════
# Wizard: طلب خدمة إنترنت
# ════════════════════════════════════════════════════════════════
def _internet_request_wizard_view():
    beneficiary = get_current_portal_beneficiary() or {}
    if request.method == "POST":
        # نستخدم نفس normalize القديم لاستخراج البيانات
        _bid, request_type, payload = normalize_internet_request_form(request.form)
        payload["portal_source"] = "beneficiary"
        if not request_type:
            flash("الرجاء اختيار نوع الخدمة.", "error")
            return redirect(request.path)
        if request_type == "reset_password":
            flash("تغيير كلمة المرور موقوف مؤقتًا. عند الحاجة تواصل مع الإدارة.", "warning")
            return redirect(request.path)
        req_id = create_internet_service_request(beneficiary["id"], request_type, payload)
        log_action(
            "submit_internet_request",
            "internet_request",
            req_id,
            f"Submit {request_type} for beneficiary {beneficiary['id']}",
        )
        try:
            from app.services.notification_service import notify_internet_request_created
            notify_internet_request_created(req_id)
        except Exception:
            pass
        flash("تم تسجيل طلبك بنجاح! ستجد التحديث في «طلباتي».", "success")
        return redirect(url_for("user_account_my_requests"))

    return render_template(
        "portal/user_internet/request_wizard.html",
        beneficiary_full_name=beneficiary.get("full_name") or session.get("beneficiary_full_name", ""),
    )


# نستبدل الـ view القديم على نفس الـ endpoint
_old_internet_request = app.view_functions.get("user_internet_request_page")


@user_login_required
def _new_user_internet_request():
    return _internet_request_wizard_view()


if "user_internet_request_page" in app.view_functions:
    app.view_functions["user_internet_request_page"] = _new_user_internet_request

# نضيف نفس الـ wizard على /internet/request (للأدمن المُعار للمشترك أيضًا)
_old_internet_legacy = app.view_functions.get("internet_request_page")
if "internet_request_page" in app.view_functions:
    # نوّجه نفس الـ wizard لكن بدون فرض user_login_required
    # (لأن /internet/request له permission_required من الأدمن أصلًا)
    pass  # نبقي السلوك القديم للأدمن، الـ wizard للمشترك فقط على /user/internet/request


# ════════════════════════════════════════════════════════════════
# الملف الشخصي القابل للتعديل
# ════════════════════════════════════════════════════════════════
_USER_TYPE_LABELS = {
    "tawjihi":    "طالب توجيهي",
    "university": "طالب جامعي",
    "freelancer": "عامل حر",
}


def _portal_messages_for_profile(beneficiary_id, limit=20):
    if not beneficiary_id:
        return []
    rows = query_all(
        """
        SELECT id, kind, body, by_username, created_at
        FROM user_messages
        WHERE beneficiary_id=%s
        ORDER BY id DESC
        LIMIT %s
        """,
        [beneficiary_id, int(limit or 20)],
    ) or []
    labels = {
        "note": "ملاحظة",
        "warning": "تحذير",
        "complaint": "شكوى",
        "reminder": "تذكير",
        "info": "تنبيه",
    }
    icons = {
        "note": "fa-message",
        "warning": "fa-triangle-exclamation",
        "complaint": "fa-circle-exclamation",
        "reminder": "fa-bell",
        "info": "fa-circle-info",
    }
    messages = []
    for row in rows:
        item = dict(row)
        kind = (item.get("kind") or "note").strip().lower()
        if kind not in labels:
            kind = "note"
        item["kind"] = kind
        item["kind_label"] = labels[kind]
        item["kind_icon"] = icons[kind]
        messages.append(item)
    return messages


def _user_profile_editable_view():
    beneficiary = get_current_portal_beneficiary() or {}
    try:
        from app.services.access_rules import whatsapp_group_url_for_user_type
        whatsapp_group_url = whatsapp_group_url_for_user_type(beneficiary.get("user_type") or "")
    except Exception:
        whatsapp_group_url = ""
    portal_account = query_one(
        "SELECT * FROM beneficiary_portal_accounts WHERE id=%s LIMIT 1",
        [session.get("beneficiary_portal_account_id")],
    )

    if request.method == "POST":
        # ── الحقول القابلة للتعديل عن كل المشتركين ──
        updates = {}
        for f in ("first_name", "second_name", "third_name", "fourth_name"):
            v = clean_csv_value(request.form.get(f))
            if v:
                updates[f] = v

        # ── الحقول حسب نوع المشترك ──
        ut = (beneficiary.get("user_type") or "").lower()
        if ut == "tawjihi":
            for f in ("tawjihi_year", "tawjihi_branch"):
                v = clean_csv_value(request.form.get(f))
                updates[f] = v
        elif ut == "university":
            for f in ("university_name", "university_college", "university_specialization"):
                v = clean_csv_value(request.form.get(f))
                updates[f] = v
        elif ut == "freelancer":
            for f in ("freelancer_specialization", "freelancer_company"):
                v = clean_csv_value(request.form.get(f))
                updates[f] = v

        # ── حدّث الـ beneficiary ──
        if updates:
            # احسب full_name تلقائيًا من الأسماء الأربعة لو تغيّرت
            full = " ".join(filter(None, [
                updates.get("first_name") or beneficiary.get("first_name") or "",
                updates.get("second_name") or beneficiary.get("second_name") or "",
                updates.get("third_name") or beneficiary.get("third_name") or "",
                updates.get("fourth_name") or beneficiary.get("fourth_name") or "",
            ])).strip()
            if full:
                updates["full_name"] = full

            set_clause = ", ".join([f"{k}=%s" for k in updates.keys()])
            values = list(updates.values()) + [beneficiary["id"]]
            execute_sql(
                f"UPDATE beneficiaries SET {set_clause} WHERE id=%s",
                values,
            )
            log_action("update_profile", "beneficiary", beneficiary["id"], "Self-edit from portal")
            session["beneficiary_full_name"] = updates.get("full_name") or session.get("beneficiary_full_name", "")
            flash("تم حفظ التعديلات بنجاح ✓", "success")

        # ── تغيير كلمة مرور البوابة (اختياري) ──
        cur_pw = clean_csv_value(request.form.get("current_password"))
        new_pw = clean_csv_value(request.form.get("new_password"))
        confirm_pw = clean_csv_value(request.form.get("confirm_password"))
        # نشغّل المنطق فقط لو طلب المشترك تغيير كلمة المرور (أحد الحقول مملوء)
        if cur_pw or new_pw or confirm_pw:
            if not portal_account:
                flash("لا يوجد حساب بوابة لتغيير كلمة مروره.", "error")
            elif not cur_pw or not new_pw or not confirm_pw:
                flash("لتغيير كلمة المرور، عبّئ الحقول الثلاثة (الحالية، الجديدة، تأكيد الجديدة).", "error")
            elif new_pw != confirm_pw:
                flash("كلمة المرور الجديدة لا تطابق التأكيد.", "error")
            elif len(new_pw) < 4:
                flash("كلمة المرور الجديدة قصيرة جدًا (4 أحرف على الأقل).", "error")
            else:
                # تحقق من كلمة المرور الحالية
                try:
                    import hashlib as _h
                    cur_hash = _h.sha256((cur_pw or "").encode("utf-8")).hexdigest()
                except Exception:
                    cur_hash = ""
                stored_hash = (portal_account.get("password_hash") or "").strip()
                if stored_hash and stored_hash != cur_hash:
                    flash("كلمة المرور الحالية غير صحيحة.", "error")
                else:
                    try:
                        import hashlib as _h2
                        new_hash = _h2.sha256(new_pw.encode("utf-8")).hexdigest()
                    except Exception:
                        new_hash = new_pw
                    execute_sql(
                        """
                        UPDATE beneficiary_portal_accounts SET
                            password_hash=%s,
                            password_plain=%s,
                            must_set_password=FALSE,
                            updated_at=CURRENT_TIMESTAMP
                        WHERE id=%s
                        """,
                        [new_hash, new_pw, portal_account["id"]],
                    )
                    try:
                        log_action(
                            "beneficiary_change_password",
                            "beneficiary_portal_account",
                            portal_account["id"],
                            "Self-changed portal password from /user/profile",
                        )
                    except Exception:
                        pass
                    flash("تم تحديث كلمة مرور البوابة بنجاح ✓", "success")

        return redirect(url_for("user_profile_page"))

    # GET — اعرض النموذج
    return render_template(
        "portal/user_profile/profile.html",
        beneficiary=beneficiary,
        user_type_label=_USER_TYPE_LABELS.get((beneficiary.get("user_type") or "").lower(), "—"),
        whatsapp_group_url=whatsapp_group_url,
        admin_messages=_portal_messages_for_profile(beneficiary.get("id")),
    )


# نستبدل الـ view القديم
_old_profile = app.view_functions.get("user_profile_page")


@user_login_required
def _new_user_profile():
    return _user_profile_editable_view()


if "user_profile_page" in app.view_functions:
    app.view_functions["user_profile_page"] = _new_user_profile
