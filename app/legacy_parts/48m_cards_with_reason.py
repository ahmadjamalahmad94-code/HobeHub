# 48m_cards_with_reason.py
# تحديث بوابة البطاقات للمشترك:
#   1) إضافة قائمة الأسباب في الـ dashboard (تظهر في modal قبل التأكيد)
#   2) قبول usage_reason في POST /cards/request وحفظه ضمن الـ audit

import json

from flask import render_template, request, redirect, url_for, flash, session


def _my_pending_card_actions(beneficiary_id: int, limit: int = 20) -> list[dict]:
    rows = query_all(
        """
        SELECT id, payload_json, requested_at
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
        actions.append({"id": row["id"], "payload": payload, "requested_at": row.get("requested_at")})
    return actions


def _user_cards_dashboard_v2():
    """نفس داشبورد البطاقات + يمرر USAGE_REASON_OPTIONS للقالب."""
    from app.services.quota_engine import check_quota, get_available_categories_for_beneficiary, QuotaDecision
    from app.services.card_status_service import get_card_statuses, format_seconds
    from app.services.access_rules import whatsapp_group_url_for_user_type

    beneficiary = get_current_portal_beneficiary() or {}
    beneficiary_id = int(session.get("beneficiary_id") or 0)

    quota = check_quota(beneficiary_id) if beneficiary_id else None
    if quota is None:
        quota = QuotaDecision(allowed=False, reason="لا توجد سياسة محددة لحسابك.", daily_used=0)

    categories = get_available_categories_for_beneficiary(beneficiary_id)

    # سبب واضح للمشترك عند تعذّر الطلب — لا رسالة عامّة بلا تفسير.
    no_cards_reason = ""
    if not getattr(quota, "allowed", False):
        no_cards_reason = (getattr(quota, "reason", "") or "").strip() or "لا يمكنك طلب بطاقة الآن."
    elif not categories:
        rem = None
        try:
            from app.services.quota_engine import _remaining_workday_minutes
            rem = _remaining_workday_minutes()
        except Exception:
            rem = None
        if rem is not None and rem <= 0:
            no_cards_reason = "انتهى وقت الدوام لهذا اليوم — تعود البطاقات في الدوام القادم."
        elif rem is not None:
            no_cards_reason = (
                f"لم يتبقَّ سوى {rem} دقيقة حتى نهاية الدوام — لا تكفي لأيّ بطاقة متاحة لك. "
                "لا يُصدَر نظامنا بطاقةً أطول من الوقت المتبقّي للدوام."
            )
        else:
            no_cards_reason = "لا توجد فئات بطاقات متاحة لك حاليًا."

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
    card_statuses = get_card_statuses(today_cards)

    my_pending_actions = _my_pending_card_actions(beneficiary_id, limit=20)

    return render_template(
        "portal/cards/dashboard.html",
        beneficiary_full_name=beneficiary.get("full_name") or session.get("beneficiary_full_name", ""),
        quota=quota,
        categories=categories,
        no_cards_reason=no_cards_reason,
        today_cards=today_cards,
        card_statuses=card_statuses,
        format_card_seconds=format_seconds,
        my_pending_actions=my_pending_actions,
        my_pending_count=len(my_pending_actions),
        router_url=get_router_login_url(),
        whatsapp_group_url=whatsapp_group_url_for_user_type(beneficiary.get("user_type") or ""),
        reason_options=list(USAGE_REASON_OPTIONS) if USAGE_REASON_OPTIONS else [],
    )


_CARD_REQUEST_COOLDOWN_SEC = 30


def _card_request_cooldown_remaining(beneficiary_id):
    """ثوانٍ متبقّية من مهلة منع التكرار (0 = مسموح). يقيس منذ آخر طلب/بطاقة
    لنفس المشترك مقارنةً بساعة قاعدة البيانات (تفادي انزياح UTC/محلّي)."""
    try:
        row = query_one(
            "SELECT CURRENT_TIMESTAMP AS db_now, "
            "(SELECT MAX(requested_at) FROM radius_pending_actions "
            "  WHERE beneficiary_id=%s AND action_type='generate_user_cards') AS last_pending, "
            "(SELECT MAX(usage_time) FROM beneficiary_usage_logs WHERE beneficiary_id=%s) AS last_usage",
            [int(beneficiary_id), int(beneficiary_id)],
        ) or {}
    except Exception:
        return 0

    from datetime import datetime as _dt

    def _naive(ts):
        if not ts:
            return None
        try:
            if isinstance(ts, str):
                ts = _dt.fromisoformat(ts.replace("Z", "").replace("T", " ").split(".")[0].strip())
            if getattr(ts, "tzinfo", None) is not None:
                ts = ts.replace(tzinfo=None)
            return ts
        except Exception:
            return None

    db_now = _naive(row.get("db_now"))
    last = max([t for t in (_naive(row.get("last_pending")), _naive(row.get("last_usage"))) if t], default=None)
    if not db_now or not last:
        return 0
    elapsed = (db_now - last).total_seconds()
    if 0 <= elapsed < _CARD_REQUEST_COOLDOWN_SEC:
        return int(_CARD_REQUEST_COOLDOWN_SEC - elapsed) or 1
    return 0


def _user_cards_request_v2():
    """طلب بطاقة من بوابة المشترك — **توليد فوري حيّ عبر RADIUS أوّلًا**،
    ويقبل usage_reason ويسجّله في beneficiary_usage_logs.

    ملاحظة مهمّة: كانت النسخة السابقة تجرّب المخزون المحلّي (الفارغ) أوّلًا ثم
    تعامل أيّ نجاح من ``request_card_via_radius`` كأنّه «طلب معلّق» فتُحوّل
    المشترك لصفحة المعلّقات الفارغة — رغم أنّ البطاقة تُولَّد فعليًّا على
    الريديوس. النتيجة: البطاقة تُصدَر لكن المشترك يظنّ أنّه «لم يُصدَر شيء».
    الإصلاح: نفرّق بين نجاح حيّ (issued_card_id) ونجاح معلّق (pending_action_id)."""
    from app.services.card_dispatcher import (
        issue_card_from_inventory,
        request_card_via_radius,
    )

    beneficiary_id = int(session.get("beneficiary_id") or 0)
    category_code = clean_csv_value(request.form.get("category_code"))
    usage_reason = clean_csv_value(request.form.get("usage_reason"))

    if not beneficiary_id:
        flash("يجب تسجيل الدخول.", "error")
        return redirect(url_for("user_login"))
    if not category_code:
        flash("الرجاء اختيار فئة البطاقة.", "error")
        return redirect(url_for("user_cards_dashboard"))

    # منع التكرار السريع: مهلة قصيرة بين طلبات البطاقة لنفس المشترك
    _wait = _card_request_cooldown_remaining(beneficiary_id)
    if _wait > 0:
        flash(f"لقد أرسلت طلبًا للتوّ. انتظر {_wait} ثانية قبل إرسال طلب جديد.", "warning")
        return redirect(url_for("user_cards_dashboard"))

    note = "توليد فوري من بوابة المشترك"
    if usage_reason and usage_reason != "تلقائي":
        note += f" — السبب: {usage_reason}"

    # ── بوّابة الموافقة: البطاقات الطويلة (٣/٤ ساعات) تحتاج موافقة الإدارة ──
    # (قابل للضبط عامًّا + إعفاء مستفيدين). لا تُصدَر بطاقة الآن، ولا يُحتسب أنّه
    # أخذ بطاقة — فقط طلب معلّق + إشعار، يُصدَّق عند موافقة الإدارة.
    try:
        if needs_card_approval(beneficiary_id, category_code):
            create_card_approval_request(
                beneficiary_id, category_code,
                usage_reason=usage_reason,
                actor_username=_portal_actor_username(),
            )
            flash(
                "بطاقتك المطلوبة طويلة وتحتاج موافقة الإدارة. أُرسِل طلبك — ستصلك "
                "البطاقة فور الموافقة، وستجدها في «سجل بطاقاتي».", "info",
            )
            return redirect(url_for("user_cards_pending_list"))
    except Exception:
        pass  # تدهور ناعم: لو تعذّر التحقّق نُكمل بالمسار المعتاد

    # ── المسار الأساسي: توليد فوري حيّ من الباقة المربوطة عبر RADIUS ──────
    result = request_card_via_radius(
        beneficiary_id, category_code,
        actor_username=_portal_actor_username(),
        notes=note,
    )

    # (أ) نجاح حيّ: بطاقة حقيقية وُلّدت وسُلّمت فورًا → أظهرها في الداشبورد
    if result.ok and result.issued_card_id:
        try:
            _log_card_usage_reason(beneficiary_id, category_code, usage_reason, result)
        except Exception:
            pass
        msg = f"تم توليد بطاقتك ({result.duration_label}) فورًا! تجدها في الأسفل جاهزة للدخول."
        if usage_reason:
            msg += f" (السبب: {usage_reason})"
        flash(msg, "success")
        return redirect(url_for("user_cards_dashboard"))

    # (ب) كتابة معطّلة/وضع يدوي → طلب مُسجّل بانتظار التنفيذ فعلًا
    if result.ok and result.pending_action_id:
        flash("تم تسجيل طلبك. ستسلّمك الإدارة البطاقة قريبًا.", "info")
        return redirect(url_for("user_cards_pending_list"))

    # (ج) فشل (أهلية/حصة أو خطأ تقني) → جرّب المخزون المحلّي احتياطيًّا (legacy)
    fallback = issue_card_from_inventory(
        beneficiary_id, category_code,
        actor_username=_portal_actor_username(),
    )
    if fallback.ok:
        try:
            _log_card_usage_reason(beneficiary_id, category_code, usage_reason, fallback)
        except Exception:
            pass
        msg = f"تم إصدار بطاقتك ({fallback.duration_label}) من المخزون. تجدها في الأسفل."
        if usage_reason:
            msg += f" (السبب: {usage_reason})"
        flash(msg, "success")
        return redirect(url_for("user_cards_dashboard"))

    flash(result.message or fallback.message, "error")
    return redirect(url_for("user_cards_dashboard"))


def _log_card_usage_reason(beneficiary_id, category_code, reason, dispatch_result):
    """تسجيل سبب البطاقة في beneficiary_usage_logs لظهوره في /admin/usage-logs."""
    if not reason:
        return
    try:
        category = query_one(
            "SELECT label_ar FROM card_categories WHERE code=%s LIMIT 1",
            [category_code],
        ) or {}
        card_type = category.get("label_ar") or category_code
        execute_sql(
            """
            INSERT INTO beneficiary_usage_logs
                (beneficiary_id, usage_reason, card_type, usage_time, usage_date, added_by_username, notes)
            VALUES (%s, %s, %s, CURRENT_TIMESTAMP, DATE('now'), %s, %s)
            """,
            [beneficiary_id, reason, card_type, _portal_actor_username(),
             f"إصدار من بوابة المشترك — {getattr(dispatch_result, 'duration_label', '') or ''}"],
        )
    except Exception:
        # نتجاهل الفشل بصمت — البطاقة أُصدرت بنجاح والسبب فقط فشل تسجيله
        pass


# ─── استبدال الـ view functions القائمة ───
if "user_cards_dashboard" in app.view_functions:
    @user_login_required
    def _new_cards_dashboard():
        return _user_cards_dashboard_v2()
    app.view_functions["user_cards_dashboard"] = _new_cards_dashboard

if "user_cards_request" in app.view_functions:
    @user_login_required
    def _new_cards_request():
        return _user_cards_request_v2()
    app.view_functions["user_cards_request"] = _new_cards_request
