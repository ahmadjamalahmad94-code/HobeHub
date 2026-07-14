# Card Management v2 — صفحات إدارة البطاقات الجديدة (Premium Corporate).
# لا يحذف الـ routes القديمة في 45_admin_cards_routes.py — يضيف فقط /admin/cards/* جديدة.

from flask import flash, redirect, render_template, request, session, url_for


def _safe_csv(value):
    try:
        return clean_csv_value(value)
    except Exception:
        return (value or "").strip() if isinstance(value, str) else ""


# ═══════════════════════════════════════════════════════════════════
# /admin/cards — نظرة عامة
# ═══════════════════════════════════════════════════════════════════
@app.route("/admin/cards", methods=["GET"])
@app.route("/admin/cards/overview", methods=["GET"])
@admin_login_required
def admin_cards_overview():
    from app.services.card_dispatcher import (
        get_inventory_counts,
        list_deliveries,
    )
    from app.services.quota_engine import get_active_categories
    from app.services.radius_client import get_radius_client

    cats = get_inventory_counts()
    inventory_total = sum(int(c.get("available") or 0) for c in cats)
    client = get_radius_client()
    pending = client.list_pending_actions(action_type="generate_user_cards", status="pending", limit=200)
    pending_count = len(pending)

    delivered_today_row = query_one(
        "SELECT COUNT(*) AS c FROM beneficiary_issued_cards WHERE DATE(issued_at) = DATE('now')"
    ) or {}
    delivered_today = int(delivered_today_row.get("c") or 0)

    policies_count_row = query_one(
        "SELECT COUNT(*) AS c FROM card_quota_policies WHERE is_active=TRUE"
    ) or {}
    policies_count = int(policies_count_row.get("c") or 0)

    recent_deliveries = list_deliveries(limit=10)

    from app.services.access_rules import describe_rules
    access_rules = describe_rules()

    # ─ بيانات RADIUS API (إن كانت مُفعَّلة) ─
    from app.services.radius_dashboard import (
        get_radius_kpis,
        get_radius_online_users,
        get_radius_profiles,
    )
    api_kpis = get_radius_kpis()
    api_online = get_radius_online_users(limit=10)
    api_profiles = get_radius_profiles()

    return render_template(
        "admin/cards/overview.html",
        categories=cats,
        inventory_total=inventory_total,
        pending_count=pending_count,
        delivered_today=delivered_today,
        policies_count=policies_count,
        recent_deliveries=recent_deliveries,
        access_rules=access_rules,
        api_kpis=api_kpis,
        api_online=api_online,
        api_profiles=api_profiles,
    )


# ═══════════════════════════════════════════════════════════════════
# /admin/cards/inventory
# ═══════════════════════════════════════════════════════════════════
@admin_login_required
def admin_cards_inventory_v2_handler():
    from app.services.card_dispatcher import get_inventory_counts

    cats = get_inventory_counts()
    inventory_total = sum(int(c.get("available") or 0) for c in cats)
    recent_cards = query_all(
        """
        SELECT *
        FROM manual_access_cards
        ORDER BY id DESC
        LIMIT 50
        """
    )
    return render_template(
        "admin/cards/inventory.html",
        categories=cats,
        inventory_total=inventory_total,
        recent_cards=recent_cards,
    )


# ═══════════════════════════════════════════════════════════════════
# /admin/cards/import — رفع ملف بطاقات
# ═══════════════════════════════════════════════════════════════════
@admin_login_required
def admin_cards_import_v2_handler():
    from app.services.quota_engine import get_active_categories, get_category_by_code

    if request.method == "POST":
        category_code = _safe_csv(request.form.get("category_code"))
        upload = request.files.get("cards_file")
        category = get_category_by_code(category_code)
        if not category:
            flash("اختر فئة بطاقات صالحة.", "error")
            return redirect(url_for("admin_cards_import_page"))
        if not upload or not _safe_csv(getattr(upload, "filename", "")):
            flash("يرجى اختيار ملف.", "error")
            return redirect(url_for("admin_cards_import_page"))
        try:
            inserted = import_manual_access_cards(
                int(category["duration_minutes"]),
                upload,
                _safe_csv(upload.filename),
                session.get("username", "admin"),
            )
            log_action(
                "import_manual_cards",
                "manual_access_cards",
                0,
                f"Imported {inserted} cards for category {category_code} ({category['duration_minutes']}min)",
            )
            flash(f"تم استيراد {inserted} بطاقة لفئة {category['label_ar']}.", "success")
            return redirect(url_for("admin_cards_inventory_page"))
        except Exception as exc:
            flash(f"تعذّر استيراد البطاقات: {exc}", "error")
            return redirect(url_for("admin_cards_import_page"))

    return render_template(
        "admin/cards/import.html",
        categories=get_active_categories(),
    )


# ═══════════════════════════════════════════════════════════════════
# /admin/cards/categories — إدارة فئات البطاقات
# ═══════════════════════════════════════════════════════════════════
@app.route("/admin/cards/categories", methods=["GET"])
@admin_login_required
def admin_cards_categories():
    # كل الفئات (الرسمية + المخصصة) — لا يوجد WHERE لاستثناء المخصصة
    cats = query_all(
        "SELECT * FROM card_categories ORDER BY display_order ASC, duration_minutes ASC"
    )
    return render_template("admin/cards/categories.html", categories=cats)


@app.route("/admin/cards/categories/add", methods=["POST"])
@admin_login_required
def admin_cards_categories_add():
    from app.services.quota_engine import OFFICIAL_CARD_CATEGORY_CODES

    code = _safe_csv(request.form.get("code")).lower()
    label_ar = _safe_csv(request.form.get("label_ar"))
    duration = int(_safe_csv(request.form.get("duration_minutes")) or "0")
    display_order = int(_safe_csv(request.form.get("display_order")) or "100")
    icon = _safe_csv(request.form.get("icon")) or "fa-clock"
    radius_profile_id = _safe_csv(request.form.get("radius_profile_id"))

    if not code or not label_ar or duration <= 0:
        flash("الكود والاسم والمدة حقول مطلوبة.", "error")
        return redirect(url_for("admin_cards_categories"))
    official_minutes = {
        "half_hour": 30,
        "one_hour": 60,
        "two_hours": 120,
        "three_hours": 180,
        "four_hours": 240,
    }
    if code not in OFFICIAL_CARD_CATEGORY_CODES or official_minutes.get(code) != duration:
        flash("الفئات الرسمية فقط: نصف ساعة، ساعة، ساعتين، 3 ساعات، و4 ساعات للحالات الخاصة.", "error")
        return redirect(url_for("admin_cards_categories"))

    existing = query_one("SELECT id FROM card_categories WHERE code=%s LIMIT 1", [code])
    if existing:
        flash(f"الكود {code} موجود مسبقًا.", "error")
        return redirect(url_for("admin_cards_categories"))

    execute_sql(
        """
        INSERT INTO card_categories
            (code, label_ar, duration_minutes, display_order, icon, radius_profile_id, is_active)
        VALUES (%s,%s,%s,%s,%s,%s,TRUE)
        """,
        [code, label_ar, duration, display_order, icon, radius_profile_id],
    )
    log_action("add_card_category", "card_categories", 0, f"code={code} duration={duration}")
    flash(f"تمت إضافة الفئة {label_ar}.", "success")
    return redirect(url_for("admin_cards_categories"))


@app.route("/admin/cards/categories/<int:category_id>/toggle", methods=["POST"])
@admin_login_required
def admin_cards_categories_toggle(category_id):
    row = query_one("SELECT id, is_active, code FROM card_categories WHERE id=%s LIMIT 1", [category_id])
    if not row:
        flash("الفئة غير موجودة.", "error")
        return redirect(url_for("admin_cards_categories"))
    new_state = not bool(row.get("is_active"))  # bool للتوافق مع Postgres + SQLite
    execute_sql(
        "UPDATE card_categories SET is_active=%s, updated_at=CURRENT_TIMESTAMP WHERE id=%s",
        [new_state, category_id],
    )
    log_action("toggle_card_category", "card_categories", category_id, f"is_active={new_state}")
    flash("تم تحديث حالة الفئة.", "success")
    return redirect(url_for("admin_cards_categories"))


# ═══════════════════════════════════════════════════════════════════
# /admin/cards/policies — سياسات الحصص
# ═══════════════════════════════════════════════════════════════════
@app.route("/admin/cards/policies", methods=["GET"])
@admin_login_required
def admin_cards_policies():
    policies = query_all(
        "SELECT * FROM card_quota_policies ORDER BY priority ASC, id DESC"
    )
    try:
        categories = query_all(
            "SELECT code, label_ar, duration_minutes FROM card_categories "
            "WHERE is_active=TRUE ORDER BY duration_minutes ASC"
        ) or []
    except Exception:
        categories = []
    return render_template("admin/cards/policies.html", policies=policies, categories=categories)


@app.route("/admin/cards/policies/add", methods=["POST"])
@admin_login_required
def admin_cards_policies_add():
    scope = _safe_csv(request.form.get("scope")) or "default"
    if scope not in {"default", "user", "group"}:
        flash("نطاق غير صالح.", "error")
        return redirect(url_for("admin_cards_policies"))

    def _intornone(v):
        v = _safe_csv(v)
        return int(v) if v else None

    target_id = _intornone(request.form.get("target_id"))
    daily_limit = _intornone(request.form.get("daily_limit"))
    weekly_limit = _intornone(request.form.get("weekly_limit"))
    priority = int(_safe_csv(request.form.get("priority")) or "100")
    allowed_days = _safe_csv(request.form.get("allowed_days"))
    allowed_categories = _safe_csv(request.form.get("allowed_category_codes"))
    valid_from = _safe_csv(request.form.get("valid_from")) or None
    valid_until = _safe_csv(request.form.get("valid_until")) or None
    valid_time_from = _safe_csv(request.form.get("valid_time_from")) or None
    valid_time_until = _safe_csv(request.form.get("valid_time_until")) or None
    notes = _safe_csv(request.form.get("notes"))

    if bool(valid_time_from) ^ bool(valid_time_until):
        flash("حدد بداية ونهاية ساعات الدوام معًا، أو اتركهما فارغتين.", "error")
        return redirect(url_for("admin_cards_policies"))

    if scope in {"user", "group"} and not target_id:
        flash("يلزم تحديد ID المستهدف للنطاق المختار.", "error")
        return redirect(url_for("admin_cards_policies"))

    execute_sql(
        """
        INSERT INTO card_quota_policies
            (scope, target_id, daily_limit, weekly_limit, allowed_days,
             allowed_category_codes, priority, valid_from, valid_until,
             valid_time_from, valid_time_until, notes, is_active, created_by_account_id)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,TRUE,%s)
        """,
        [
            scope, target_id, daily_limit, weekly_limit, allowed_days,
            allowed_categories, priority, valid_from, valid_until,
            valid_time_from, valid_time_until, notes, session.get("account_id"),
        ],
    )
    log_action("add_quota_policy", "card_quota_policies", 0,
               f"scope={scope} target={target_id} daily={daily_limit}")
    flash("تمت إضافة السياسة.", "success")
    return redirect(url_for("admin_cards_policies"))


@app.route("/admin/cards/policies/<int:policy_id>/toggle", methods=["POST"])
@admin_login_required
def admin_cards_policies_toggle(policy_id):
    row = query_one("SELECT id, is_active FROM card_quota_policies WHERE id=%s LIMIT 1", [policy_id])
    if not row:
        flash("السياسة غير موجودة.", "error")
        return redirect(url_for("admin_cards_policies"))
    new_state = not bool(row.get("is_active"))  # bool للتوافق مع Postgres + SQLite
    execute_sql(
        "UPDATE card_quota_policies SET is_active=%s, updated_at=CURRENT_TIMESTAMP WHERE id=%s",
        [new_state, policy_id],
    )
    log_action("toggle_quota_policy", "card_quota_policies", policy_id, f"is_active={new_state}")
    flash("تم تحديث حالة السياسة.", "success")
    return redirect(url_for("admin_cards_policies"))


# ═══════════════════════════════════════════════════════════════════
# /admin/cards/pending — طلبات معلّقة
# ═══════════════════════════════════════════════════════════════════
@app.route("/admin/cards/pending", methods=["GET"])
@admin_login_required
def admin_cards_pending():
    from app.services.radius_client import get_radius_client
    from app.services.quota_engine import get_category_by_code

    client = get_radius_client()
    raw_pending = client.list_pending_actions(
        action_type="generate_user_cards",
        status="pending",
        limit=200,
    )

    enriched = []
    for a in raw_pending:
        beneficiary = None
        if a.beneficiary_id:
            beneficiary = query_one(
                "SELECT full_name, phone FROM beneficiaries WHERE id=%s LIMIT 1",
                [a.beneficiary_id],
            )
        code = (a.payload or {}).get("category_code") or ""
        category = get_category_by_code(code)
        enriched.append({
            "id": a.id,
            "action_type": a.action_type,
            "payload": a.payload or {},
            "beneficiary_id": a.beneficiary_id,
            "beneficiary_name": (beneficiary or {}).get("full_name"),
            "beneficiary_phone": (beneficiary or {}).get("phone"),
            "category_label": (category or {}).get("label_ar"),
            "requested_at": a.requested_at,
            "notes": a.notes,
        })

    return render_template(
        "admin/cards/pending.html",
        pending_actions=enriched,
        pending_count=len(enriched),
    )


@app.route("/admin/cards/pending/<int:action_id>/fulfill", methods=["POST"])
@admin_login_required
def admin_cards_pending_fulfill(action_id):
    from app.services.card_dispatcher import fulfill_pending_card_action

    card_username = _safe_csv(request.form.get("card_username"))
    card_password = _safe_csv(request.form.get("card_password"))
    notes = _safe_csv(request.form.get("notes"))

    result = fulfill_pending_card_action(
        action_id,
        card_username=card_username,
        card_password=card_password,
        actor_username=session.get("username") or "admin",
        notes=notes,
    )
    if result.ok:
        flash(result.message, "success")
    else:
        flash(result.message, "error")
    return redirect(request.referrer or url_for("admin_request_center", type="card"))


@app.route("/admin/cards/pending/<int:action_id>/cancel", methods=["POST"])
@admin_login_required
def admin_cards_pending_cancel(action_id):
    from app.services.radius_client import get_radius_client

    client = get_radius_client()
    notes = _safe_csv(request.form.get("notes")) or "أُلغي يدويًا من الإدارة"
    client.cancel_pending(action_id, executed_by=session.get("username") or "admin", notes=notes)
    log_action("cancel_pending_action", "radius_pending_actions", action_id, notes)
    flash("تم إلغاء الطلب.", "success")
    return redirect(request.referrer or url_for("admin_request_center", type="card"))


# ═══════════════════════════════════════════════════════════════════
# /admin/cards/deliveries — سجل التسليم
# ═══════════════════════════════════════════════════════════════════
@app.route("/admin/cards/deliveries", methods=["GET"])
@admin_login_required
def admin_cards_deliveries():
    from app.services.card_dispatcher import list_deliveries
    from app.services.quota_engine import get_active_categories

    beneficiary_id = request.args.get("beneficiary_id", "").strip()
    category_code  = request.args.get("category_code", "").strip()
    q              = request.args.get("q", "").strip()
    phone          = request.args.get("phone", "").strip()
    date_from      = request.args.get("date_from", "").strip()
    date_to        = request.args.get("date_to", "").strip()

    filters = {
        "beneficiary_id": int(beneficiary_id) if beneficiary_id.isdigit() else None,
        "category_code": category_code or None,
        "q": q or None,
        "phone": phone or None,
        "date_from": date_from or None,
        "date_to": date_to or None,
    }
    rows = list_deliveries(
        limit=300,
        beneficiary_id=filters["beneficiary_id"],
        category_code=filters["category_code"],
        q=filters["q"],
        phone=filters["phone"],
        date_from=filters["date_from"],
        date_to=filters["date_to"],
    )
    return render_template(
        "admin/cards/deliveries.html",
        deliveries=rows,
        filters=filters,
        categories=get_active_categories(),
    )


# ═══════════════════════════════════════════════════════════════════
# /admin/cards/audit — التدقيق
# ═══════════════════════════════════════════════════════════════════
@app.route("/admin/cards/audit", methods=["GET"])
@admin_login_required
def admin_cards_audit():
    from app.services.card_dispatcher import list_recent_audit
    rows = list_recent_audit(limit=200)
    return render_template("admin/cards/audit.html", audit=rows)


# ═══════════════════════════════════════════════════════════════════
# Overrides: استبدال الـ handlers القديمة بالنسخ v2
# (الـ URLs الأصلية تبقى — فقط الدالة المنفّذة تتبدّل)
# ═══════════════════════════════════════════════════════════════════
app.view_functions["admin_cards_inventory_page"] = admin_login_required(admin_cards_inventory_v2_handler)
app.view_functions["admin_cards_import_page"] = admin_login_required(admin_cards_import_v2_handler)

# Aliases للـ url_for() الجديدة:
# admin_cards_inventory_v2 → admin_cards_inventory_page (نفس الـ handler)
# alias removed = app.view_functions["admin_cards_inventory_page"]
# alias removed = app.view_functions["admin_cards_import_page"]



# ═══════════════════════════════════════════════════════════════════
# /admin/cards/categories/sync-profiles — مزامنة من RADIUS API
# ═══════════════════════════════════════════════════════════════════
@app.route("/admin/cards/categories/sync-profiles", methods=["GET", "POST"])
@admin_login_required
def admin_cards_sync_profiles():
    """صفحة قديمة (تربط الفئة بـ profile/خطّة عبر radius_profile_id) — لم تعد
    مصدر التوليد. التوليد الحيّ يقرأ «ربط العروض» (card_offer_radius_links) فقط.
    لتفادي وجود مكانين للربط، نحوّل العرض إلى الصفحة المعتمدة «ربط العروض»."""
    from app.services.radius_dashboard import get_radius_profiles, invalidate_cache

    if request.method == "GET":
        flash("تم توحيد ربط العروض هنا — اربط كل فئة بباقة من السوق الإلكترونيّ.", "info")
        return redirect(url_for("admin_cards_radius_links_page"))

    if request.method == "POST":
        # حفظ الـ mapping: للحقول category_<id> = profile_id_value
        updated = 0
        for key, value in request.form.items():
            if not key.startswith("category_"):
                continue
            try:
                cat_id = int(key.replace("category_", ""))
            except ValueError:
                continue
            profile_id = clean_csv_value(value)
            execute_sql(
                "UPDATE card_categories SET radius_profile_id=%s, updated_at=CURRENT_TIMESTAMP WHERE id=%s",
                [profile_id, cat_id],
            )
            updated += 1
        log_action("sync_card_profiles", "card_categories", 0, f"Updated {updated} categories")
        flash(f"تم تحديث {updated} فئة بمعرّفات الباقات.", "success")
        return redirect(url_for("admin_cards_categories"))

    # GET: ابحث عن profiles من API
    invalidate_cache("radius:profiles")  # force fresh
    profiles_result = get_radius_profiles()
    cats = query_all(
        """
        SELECT * FROM card_categories
        WHERE code IN ('half_hour','one_hour','two_hours','three_hours','four_hours')
        ORDER BY display_order ASC, duration_minutes ASC
        """
    )
    return render_template(
        "admin/cards/sync_profiles.html",
        categories=cats,
        profiles_result=profiles_result,
    )
