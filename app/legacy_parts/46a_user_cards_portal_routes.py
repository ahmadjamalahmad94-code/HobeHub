# داشبورد مشترك البطاقات — Phase 1 (Premium Corporate).
# لا يلمس /user/dashboard القديم — يضيف /user/cards/* فقط.

import json

from flask import flash, redirect, render_template, request, session, url_for


def _portal_actor_username():
    return session.get("beneficiary_username") or session.get("beneficiary_full_name") or "user"


class _ActionDict(dict):
    def __getattr__(self, key):
        return self.get(key)


def _pending_card_action_rows(beneficiary_id: int, limit: int = 50) -> list[dict]:
    rows = query_all(
        """
        SELECT id, payload_json, requested_at, status
        FROM radius_pending_actions
        WHERE beneficiary_id=%s
          AND action_type='generate_user_cards'
          AND status='pending'
        ORDER BY id DESC
        LIMIT %s
        """,
        [beneficiary_id, limit],
    )
    actions = []
    for row in rows:
        try:
            payload = json.loads(row.get("payload_json") or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            payload = {}
        actions.append(
            _ActionDict({
                "id": row["id"],
                "payload": payload,
                "requested_at": row.get("requested_at"),
                "status": row.get("status") or "pending",
            })
        )
    return actions


@app.route("/user/cards", methods=["GET"])
@user_login_required
def user_cards_dashboard():
    """الصفحة الرئيسية لمشتركي البطاقات."""
    from app.services.quota_engine import check_quota, get_available_categories_for_beneficiary
    from app.services.card_dispatcher import get_inventory_counts
    from app.services.card_status_service import get_card_statuses, format_seconds

    beneficiary = get_current_portal_beneficiary() or {}
    beneficiary_id = int(session.get("beneficiary_id") or 0)

    # هل يتخطى هذا النوع مودال "سبب البطاقة"؟
    try:
        skip_reason = bool(should_skip_reason_for_user_type(beneficiary.get("user_type") or ""))
    except Exception:
        skip_reason = False

    quota = check_quota(beneficiary_id) if beneficiary_id else None
    if quota is None:
        # احتياط: ابني decision فاضي
        from app.services.quota_engine import QuotaDecision
        quota = QuotaDecision(allowed=False, reason="لا توجد سياسة محددة لحسابك.", daily_used=0)

    categories = get_available_categories_for_beneficiary(beneficiary_id)

    # بطاقات اليوم لهذا المشترك
    today_cards = query_all(
        """
        SELECT bic.*,
               (
                   SELECT cc.label_ar
                   FROM card_categories cc
                   WHERE cc.duration_minutes = bic.duration_minutes
                     AND cc.is_active = TRUE
                     AND cc.code IN ('half_hour','one_hour','two_hours','three_hours','four_hours')
                   ORDER BY cc.display_order ASC, cc.id ASC
                   LIMIT 1
               ) AS duration_label
        FROM beneficiary_issued_cards bic
        WHERE bic.beneficiary_id=%s
          AND DATE(bic.issued_at) = DATE('now')
        ORDER BY bic.id DESC
        """,
        [beneficiary_id],
    )

    # الطلبات المعلّقة لهذا المشترك
    my_pending_actions = _pending_card_action_rows(beneficiary_id, limit=20)

    return render_template(
        "portal/cards/dashboard.html",
        beneficiary_full_name=beneficiary.get("full_name") or session.get("beneficiary_full_name", ""),
        beneficiary_user_type=beneficiary.get("user_type") or "",
        skip_reason_modal=skip_reason,
        quota=quota,
        categories=categories,
        today_cards=today_cards,
        my_pending_actions=my_pending_actions,
        my_pending_count=len(my_pending_actions),
        router_url=get_router_login_url(),
    )


@app.route("/user/cards/request", methods=["POST"])
@user_login_required
def user_cards_request():
    """طلب بطاقة — توليد فوري من العرض عبر RADIUS (المخزون المحلي كخيار احتياطي).

    المسار الأساسي: يستدعي RADIUS لتوليد بطاقة فورية من العرض المطابق للفئة.
      - كتابة RADIUS مُفعّلة وحيّة → بطاقة حقيقية تُسلّم فورًا وتظهر في الأسفل.
      - كتابة RADIUS غير مفعّلة/وضع يدوي → لا نلفّق بطاقة؛ يُسجّل طلب بانتظار
        التنفيذ (قيد التطوير) ويظهر للمشترك بوضوح.
    الخيار الاحتياطي (legacy): إن تعذّر التوليد الفوري لسبب تقني نجرّب المخزون.
    """
    from app.services.card_dispatcher import (
        issue_card_from_inventory,
        request_card_via_radius,
    )

    beneficiary_id = int(session.get("beneficiary_id") or 0)
    category_code = clean_csv_value(request.form.get("category_code"))
    usage_reason = clean_csv_value(request.form.get("usage_reason")) or ""

    if not beneficiary_id:
        flash("يجب تسجيل الدخول.", "error")
        return redirect(url_for("user_login"))
    if not category_code:
        flash("الرجاء اختيار فئة البطاقة.", "error")
        return redirect(url_for("user_cards_dashboard"))

    note = "توليد فوري من بوابة المشترك"
    if usage_reason and usage_reason != "تلقائي":
        note += f" — السبب: {usage_reason}"

    # ── المسار الأساسي: توليد فوري من العرض عبر RADIUS ──────────────────
    result = request_card_via_radius(
        beneficiary_id, category_code,
        actor_username=_portal_actor_username(),
        notes=note,
    )

    # (أ) نجاح حي: بطاقة حقيقية وُلّدت وسُلّمت
    if result.ok and result.issued_card_id:
        flash(
            f"تم توليد بطاقتك ({result.duration_label}) فورًا! تجدها في الأسفل جاهزة للدخول.",
            "success",
        )
        return redirect(url_for("user_cards_dashboard"))

    # (ب) الكتابة غير مفعّلة / وضع يدوي → طلب مُسجّل بانتظار التنفيذ (قيد التطوير)
    if result.ok and result.pending_action_id:
        flash(
            "تم تسجيل طلبك للتوليد الفوري وهو الآن بانتظار التنفيذ (الميزة قيد التطوير). "
            "ستصلك البطاقة قريبًا وتظهر في «طلباتي المعلّقة».",
            "info",
        )
        return redirect(url_for("user_cards_pending_list"))

    # (ج) فشل (أهلية/حصة أو خطأ تقني) → جرّب المخزون المحلي كخيار احتياطي legacy
    fallback = issue_card_from_inventory(
        beneficiary_id, category_code,
        actor_username=_portal_actor_username(),
    )
    if fallback.ok:
        flash(
            f"تم إصدار بطاقتك ({fallback.duration_label}) من المخزون. تجدها في الأسفل.",
            "success",
        )
        return redirect(url_for("user_cards_dashboard"))

    flash(result.message or fallback.message, "error")
    return redirect(url_for("user_cards_dashboard"))


@app.route("/user/cards/history", methods=["GET"])
@user_login_required
def user_cards_history():
    """سجل كل بطاقات هذا المشترك."""
    from app.services.quota_engine import check_quota, get_available_categories_for_beneficiary
    from app.services.card_status_service import get_card_statuses, format_seconds

    beneficiary = get_current_portal_beneficiary() or {}
    beneficiary_id = int(session.get("beneficiary_id") or 0)

    all_cards = query_all(
        """
        SELECT bic.*,
               (
                   SELECT cc.label_ar
                   FROM card_categories cc
                   WHERE cc.duration_minutes = bic.duration_minutes
                     AND cc.is_active = TRUE
                     AND cc.code IN ('half_hour','one_hour','two_hours','three_hours','four_hours')
                   ORDER BY cc.display_order ASC, cc.id ASC
                   LIMIT 1
               ) AS duration_label
        FROM beneficiary_issued_cards bic
        WHERE bic.beneficiary_id=%s
        ORDER BY bic.id DESC
        LIMIT 200
        """,
        [beneficiary_id],
    )

    # نمرّر السياق نفسه ليعمل الـ sidebar
    quota = check_quota(beneficiary_id)
    my_pending = _pending_card_action_rows(beneficiary_id, limit=20)

    return render_template(
        "portal/cards/history.html",
        beneficiary_full_name=beneficiary.get("full_name") or session.get("beneficiary_full_name", ""),
        quota=quota,
        categories=get_available_categories_for_beneficiary(beneficiary_id),
        today_cards=[],
        card_statuses=get_card_statuses(all_cards, include_usage=False),
        format_card_seconds=format_seconds,
        my_pending_actions=[],
        my_pending_count=len(my_pending),
        router_url=get_router_login_url(),
        all_cards=all_cards,
    )


@app.route("/user/cards/pending", methods=["GET"])
@user_login_required
def user_cards_pending_list():
    """طلباتي المعلّقة."""
    from app.services.quota_engine import check_quota, get_available_categories_for_beneficiary, get_category_by_code

    beneficiary = get_current_portal_beneficiary() or {}
    beneficiary_id = int(session.get("beneficiary_id") or 0)

    # سجل كامل لكل حركات المستفيد (قيد المراجعة/موافقة/رفض) مع تباين لونيّ
    raw_pending = query_all(
        """
        SELECT id, payload_json, requested_at, executed_at, status, error_message
        FROM radius_pending_actions
        WHERE beneficiary_id=%s AND action_type='generate_user_cards'
        ORDER BY id DESC LIMIT 100
        """,
        [beneficiary_id],
    ) or []
    _STATUS_MAP = {
        "pending": ("قيد المراجعة", "st-pending"),
        "in_progress": ("قيد التنفيذ", "st-pending"),
        "done": ("تمت الموافقة", "st-approved"),
        "cancelled": ("مرفوض", "st-rejected"),
        "failed": ("مرفوض", "st-rejected"),
    }
    my_actions = []
    pending_count = 0
    for a in raw_pending:
        try:
            payload = json.loads(a.get("payload_json") or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            payload = {}
        code = payload.get("category_code") or ""
        cat = get_category_by_code(code)
        st = a.get("status") or "pending"
        if st in ("pending", "in_progress"):
            pending_count += 1
        label, cls = _STATUS_MAP.get(st, (st, "st-pending"))
        my_actions.append({
            "id": a["id"],
            "payload": payload,
            "category_label": (cat or {}).get("label_ar") or code,
            "requested_at": a.get("requested_at"),
            "executed_at": a.get("executed_at"),
            "status": st,
            "status_label": label,
            "status_class": cls,
        })

    quota = check_quota(beneficiary_id)
    return render_template(
        "portal/cards/pending.html",
        beneficiary_full_name=beneficiary.get("full_name") or session.get("beneficiary_full_name", ""),
        quota=quota,
        categories=get_available_categories_for_beneficiary(beneficiary_id),
        today_cards=[],
        my_pending_actions=my_actions,
        my_pending_count=pending_count,
        pending_actions=my_actions,
        router_url=get_router_login_url(),
    )
