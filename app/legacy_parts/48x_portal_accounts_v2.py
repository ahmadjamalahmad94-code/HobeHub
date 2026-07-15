# 48x_portal_accounts_v2.py
# - إعادة تصميم /admin/portal-accounts
# - API لإنشاء وتعديل حسابات بوابة المشتركين
# - API لإصدار بطاقة من قائمة المستفيدين (يدوي — لا خصم من المخزون)

import hashlib
from flask import render_template, request, redirect, url_for, flash, session, jsonify


# ════════════════════════════════════════════════
# /admin/portal-accounts — صفحة قائمة الحسابات
# ════════════════════════════════════════════════
def _portal_accounts_v2_view():
    accounts = query_all(
        """
        SELECT pa.*, b.full_name, b.phone
        FROM beneficiary_portal_accounts pa
        JOIN beneficiaries b ON b.id = pa.beneficiary_id
        ORDER BY pa.id DESC
        """
    )
    active_count = sum(1 for a in (accounts or []) if a.get("is_active"))
    inactive_count = len(accounts or []) - active_count
    beneficiaries = query_all(
        "SELECT id, full_name, phone FROM beneficiaries ORDER BY id DESC LIMIT 1000"
    )
    return render_template(
        "admin/portal_accounts/list.html",
        accounts=accounts,
        active_count=active_count,
        inactive_count=inactive_count,
        beneficiaries=beneficiaries,
        format_dt_short=format_dt_short,
    )


if "admin_portal_accounts_page" in app.view_functions:
    @login_required
    @permission_required("manage_accounts")
    def _new_portal_accounts():
        return _portal_accounts_v2_view()
    app.view_functions["admin_portal_accounts_page"] = _new_portal_accounts


# ════════════════════════════════════════════════
# POST /admin/portal-accounts/create
# ════════════════════════════════════════════════
@app.route("/admin/portal-accounts/create", methods=["POST"])
@login_required
@permission_required("manage_accounts")
def admin_portal_accounts_create():
    try:
        beneficiary_id = int(clean_csv_value(request.form.get("beneficiary_id", "0")) or "0")
    except Exception:
        beneficiary_id = 0
    username = clean_csv_value(request.form.get("username"))
    password = clean_csv_value(request.form.get("password"))
    is_active = request.form.get("is_active") == "1"

    if beneficiary_id <= 0 or not username or not password:
        return jsonify({"ok": False, "message": "كل الحقول مطلوبة."}), 400

    ben = query_one("SELECT id FROM beneficiaries WHERE id=%s LIMIT 1", [beneficiary_id])
    if not ben:
        return jsonify({"ok": False, "message": "المستفيد غير موجود."}), 404

    existing = query_one(
        "SELECT id FROM beneficiary_portal_accounts WHERE beneficiary_id=%s LIMIT 1",
        [beneficiary_id],
    )
    if existing:
        dup_existing = query_one(
            "SELECT id FROM beneficiary_portal_accounts WHERE username=%s AND id<>%s LIMIT 1",
            [username, existing["id"]],
        )
        if dup_existing:
            return jsonify({"ok": False, "message": "اسم المستخدم مستخدم مسبقًا."}), 400
        pw_hash = hashlib.sha256(password.encode("utf-8")).hexdigest()
        execute_sql(
            """
            UPDATE beneficiary_portal_accounts
               SET username=%s,
                   password_hash=%s,
                   is_active=%s,
                   portal_membership_active=TRUE,
                   portal_access_state='active',
                   must_set_password=FALSE,
                   activated_at=COALESCE(activated_at, CURRENT_TIMESTAMP),
                   updated_at=CURRENT_TIMESTAMP
             WHERE id=%s
            """,
            [username, pw_hash, bool(is_active), existing["id"]],
        )
        return jsonify({"ok": True, "message": "تم إدخال المستفيد للبوابة من حسابه المحفوظ."})

    dup = query_one(
        "SELECT id FROM beneficiary_portal_accounts WHERE username=%s LIMIT 1", [username]
    )
    if dup:
        return jsonify({"ok": False, "message": "اسم المستخدم مستخدم مسبقًا."}), 400

    pw_hash = hashlib.sha256(password.encode("utf-8")).hexdigest()
    row = execute_sql(
        """
        INSERT INTO beneficiary_portal_accounts
            (beneficiary_id, username, password_hash, is_active, portal_membership_active, portal_access_state, must_set_password, activated_at)
        VALUES (%s, %s, %s, %s, TRUE, 'active', 0, CURRENT_TIMESTAMP)
        RETURNING id
        """,
        [beneficiary_id, username, pw_hash, bool(is_active)],
        fetchone=True,
    )
    new_id = row["id"] if row else None
    log_action(
        "create_portal_account", "beneficiary_portal_account", new_id,
        f"إنشاء حساب بوابة للمستفيد {beneficiary_id} باسم {username}",
    )
    return jsonify({"ok": True, "message": "تم إنشاء الحساب بنجاح."})


# ════════════════════════════════════════════════
# POST /admin/portal-accounts/<id>/update
# ════════════════════════════════════════════════
@app.route("/admin/portal-accounts/<int:portal_id>/update", methods=["POST"])
@login_required
@permission_required("manage_accounts")
def admin_portal_accounts_update(portal_id):
    row = query_one(
        "SELECT * FROM beneficiary_portal_accounts WHERE id=%s LIMIT 1", [portal_id]
    )
    if not row:
        return jsonify({"ok": False, "message": "الحساب غير موجود."}), 404

    username = clean_csv_value(request.form.get("username")) or row.get("username")
    password = clean_csv_value(request.form.get("password"))
    is_active = request.form.get("is_active") == "1"

    dup = query_one(
        "SELECT id FROM beneficiary_portal_accounts WHERE username=%s AND id<>%s LIMIT 1",
        [username, portal_id],
    )
    if dup:
        return jsonify({"ok": False, "message": "اسم المستخدم مستخدم مسبقًا لحساب آخر."}), 400

    if password:
        pw_hash = hashlib.sha256(password.encode("utf-8")).hexdigest()
        execute_sql(
            """
            UPDATE beneficiary_portal_accounts
            SET username=%s, password_hash=%s, is_active=%s, must_set_password=FALSE,
                updated_at=CURRENT_TIMESTAMP, failed_login_attempts=0, locked_until=NULL
            WHERE id=%s
            """,
            [username, pw_hash, bool(is_active), portal_id],
        )
    else:
        execute_sql(
            """
            UPDATE beneficiary_portal_accounts
            SET username=%s, is_active=%s, updated_at=CURRENT_TIMESTAMP
            WHERE id=%s
            """,
            [username, bool(is_active), portal_id],
        )
    log_action(
        "update_portal_account", "beneficiary_portal_account", portal_id,
        f"تعديل حساب بوابة {username}",
    )
    return jsonify({"ok": True, "message": "تم حفظ التعديلات."})


# ════════════════════════════════════════════════
# POST /admin/beneficiaries/<id>/issue-card
# إصدار يدوي — لا يخصم من المخزون.
# الورق فعلي عند الإدارة، النظام فقط يسجّل الاستخدام.
# ════════════════════════════════════════════════
@app.route("/admin/beneficiaries/<int:beneficiary_id>/issue-card", methods=["GET", "POST"])
@login_required
@permission_required("usage_counter")
def admin_beneficiary_issue_card(beneficiary_id):
    from app.services.quota_engine import get_active_categories

    ben = query_one(
        "SELECT id, full_name, user_type, phone FROM beneficiaries WHERE id=%s",
        [beneficiary_id],
    )
    if not ben:
        return jsonify({"ok": False, "message": "المستفيد غير موجود."}), 404

    if request.method == "GET":
        cats = get_active_categories() or []
        return jsonify({
            "ok": True,
            "beneficiary": {
                "id": ben["id"], "full_name": ben["full_name"],
                "user_type": ben.get("user_type"), "phone": ben.get("phone") or "",
            },
            "categories": [
                {"code": c["code"], "label": c["label_ar"], "duration": c.get("duration_minutes")}
                for c in cats
            ],
            "reasons": list(USAGE_REASON_OPTIONS) if USAGE_REASON_OPTIONS else [],
        })

    # POST: توليد بطاقة حيّة على الريديوس عبر الـdispatcher (لا سحب من مخزون محلّيّ)
    category_code = clean_csv_value(request.form.get("category_code"))
    reason = clean_csv_value(request.form.get("reason"))
    delivery_mode = clean_csv_value(request.form.get("delivery_mode")) or "paper"
    notes = clean_csv_value(request.form.get("notes"))

    if not category_code:
        return jsonify({"ok": False, "message": "الرجاء اختيار فئة البطاقة."}), 400
    if not reason:
        return jsonify({"ok": False, "message": "الرجاء اختيار سبب البطاقة."}), 400

    category = query_one(
        "SELECT label_ar, duration_minutes FROM card_categories WHERE code=%s", [category_code]
    ) or {}
    card_type_label = category.get("label_ar") or category_code
    delivery_label = "ورقية" if delivery_mode == "paper" else "SMS"
    full_notes = (notes + (" — تسليم: " + delivery_label) + (" — سبب: " + reason)).strip(" —")

    # قاعدة التسليم:
    #   • ورقيّ  → البطاقة الورقيّة عند الإدارة؛ لا توليد على الريديوس/السوق،
    #             نُسجّل الاستخدام فقط (تقارير/حضور).
    #   • إلكترونيّ (SMS) → توليد حيّ من باقة السوق المربوطة عبر الـdispatcher.
    is_paper = (delivery_mode == "paper")

    card_user, card_pass = "", ""
    disp = None
    if not is_paper:
        # التوليد الحيّ: يُنشئ بطاقة حقيقيّة كشراء من السوق المربوط بالفئة.
        # (يتطلّب ربط الفئة بباقة من «ربط العروض» + تفعيل الكتابة؛ وإلّا خطأ واضح.)
        try:
            from app.services.card_dispatcher import request_card_via_radius
            disp = request_card_via_radius(
                beneficiary_id, category_code,
                actor_username=session.get("username") or "admin",
                skip_quota=True, notes=full_notes,
            )
        except Exception as exc:  # noqa: BLE001
            return jsonify({"ok": False, "message": f"تعذّر توليد البطاقة: {safe(str(exc))}"}), 500

        if not getattr(disp, "ok", False):
            return jsonify({"ok": False, "message": getattr(disp, "message", "تعذّر توليد البطاقة.")}), 400

        card_user = getattr(disp, "card_username", "") or ""
        card_pass = getattr(disp, "card_password", "") or ""

    # سجّل في beneficiary_usage_logs (للتقارير/الحضور) + العداد الأسبوعي — للنمطين.
    try:
        execute_sql(
            """
            INSERT INTO beneficiary_usage_logs
                (beneficiary_id, usage_reason, card_type, usage_date, usage_time,
                 added_by_account_id, added_by_username, notes)
            VALUES (%s, %s, %s, DATE('now'), CURRENT_TIMESTAMP, %s, %s, %s)
            """,
            [beneficiary_id, reason, card_type_label,
             session.get("account_id"), session.get("username", ""), full_notes],
        )
    except Exception:
        pass
    try:
        execute_sql(
            "UPDATE beneficiaries SET weekly_usage_count=COALESCE(weekly_usage_count,0)+1 WHERE id=%s",
            [beneficiary_id],
        )
    except Exception:
        pass

    log_action(
        "admin_issue_card_paper" if is_paper else "admin_issue_card_live",
        "beneficiary", beneficiary_id,
        f"{'تسجيل تسليم ورقيّ' if is_paper else 'توليد بطاقة على الريديوس'} "
        f"({delivery_label}): فئة={card_type_label}, سبب={reason} — {ben['full_name']}",
    )

    if is_paper:
        msg = f"✓ سُجِّل تسليم بطاقة {card_type_label} ورقيًّا لـ {ben['full_name']} (بلا توليد على الريديوس)."
    elif card_user:
        msg = f"✓ تم توليد بطاقة {card_type_label} على الريديوس لـ {ben['full_name']}."
    else:
        # نجاح بلا بيانات حيّة = طُوِّب للتنفيذ اليدوي (الكتابة على الريديوس مقفلة).
        msg = getattr(disp, "message", "") or f"سُجِّل طلب بطاقة {card_type_label} (سيُنفَّذ عند تفعيل الكتابة)."

    return jsonify({
        "ok": True,
        "message": msg,
        "card_username": card_user,
        "card_password": card_pass,
        "delivery_mode": delivery_mode,
        "sms_pending": (delivery_mode == "sms"),
    })
