# 48z_phase2_user_profile.py
# Phase 2 — صفحة شخصية احترافية لكل مستفيد
# /admin/users/<id>/profile  →  bio, portal account, cards/usage, audit, type, card allowance, verification

import logging
from flask import render_template, request, jsonify, abort, session

_log = logging.getLogger("hobehub.phase2_profile")


def _profile_bio(beneficiary_id):
    # SELECT * — أكثر متانة على schema بأعمدة متفاوتة بين SQLite/Postgres
    return query_one("SELECT * FROM beneficiaries WHERE id=%s", [beneficiary_id])


def _profile_portal_account(beneficiary_id):
    return query_one(
        "SELECT * FROM beneficiary_portal_accounts WHERE beneficiary_id=%s",
        [beneficiary_id],
    )


def _profile_usage_stats(beneficiary_id):
    """آخر 20 سجل + إجمالي عبر الأسبوع/الشهر/الكل (متوافق SQLite + Postgres)."""
    from datetime import datetime, timedelta
    recent = query_all(
        "SELECT * FROM beneficiary_usage_logs WHERE beneficiary_id=%s ORDER BY id DESC LIMIT 20",
        [beneficiary_id],
    ) or []
    week_cut = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    month_cut = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    total = (query_one("SELECT COUNT(*) AS c FROM beneficiary_usage_logs WHERE beneficiary_id=%s", [beneficiary_id]) or {}).get("c") or 0
    week = (query_one("SELECT COUNT(*) AS c FROM beneficiary_usage_logs WHERE beneficiary_id=%s AND usage_date >= %s", [beneficiary_id, week_cut]) or {}).get("c") or 0
    month = (query_one("SELECT COUNT(*) AS c FROM beneficiary_usage_logs WHERE beneficiary_id=%s AND usage_date >= %s", [beneficiary_id, month_cut]) or {}).get("c") or 0
    return recent, {"total": int(total), "week": int(week), "month": int(month)}


def _profile_issued_cards(beneficiary_id):
    rows = query_all(
        """
        SELECT bic.*, cc.label_ar AS category_label
        FROM beneficiary_issued_cards bic
        LEFT JOIN card_categories cc
          ON cc.duration_minutes = bic.duration_minutes AND cc.is_active = TRUE
        WHERE bic.beneficiary_id=%s
        ORDER BY bic.id DESC
        LIMIT 20
        """,
        [beneficiary_id],
    ) or []
    try:
        from app.services.card_status_service import get_card_statuses
        statuses = get_card_statuses(rows, usage_limit=20)
    except Exception:
        statuses = {}
    enriched = []
    for row in rows:
        item = dict(row)
        item["status"] = statuses.get(int(row.get("id") or 0), {})
        enriched.append(item)
    return enriched


def _profile_requests(beneficiary_id):
    try:
        from app.services.request_center import get_request_center
        data = get_request_center({"beneficiary_id": str(beneficiary_id), "type": "all"}, limit=40)
        return data.get("items") or []
    except Exception:
        return []


def _profile_audit(beneficiary_id):
    """آخر 30 عملية بسجل العمليات تخص هذا المستفيد.
       الجدول الفعلي = audit_logs مع الأعمدة:
       action_type, target_type, target_id, details, username_snapshot, created_at.
       لو فشل الاستعلام (schema غير متطابق) نسجّل الخطأ ونعرض قائمة فارغة بدلاً من إخفائه."""
    try:
        return query_all(
            """
            SELECT id, action_type,
                   target_type AS entity_type,
                   target_id   AS entity_id,
                   details     AS description,
                   username_snapshot AS actor_username,
                   created_at
            FROM audit_logs
            WHERE (target_type='beneficiary' AND target_id=%s)
               OR (target_type='beneficiary_portal_account' AND target_id IN
                    (SELECT id FROM beneficiary_portal_accounts WHERE beneficiary_id=%s))
            ORDER BY id DESC LIMIT 30
            """,
            [beneficiary_id, beneficiary_id],
        ) or []
    except Exception as e:
        _log.warning("_profile_audit failed for beneficiary_id=%s: %s", beneficiary_id, e)
        return []


# ────────────────────────────────────────────────────────────────
# GET /admin/users/<id>/profile  — الصفحة الشخصية
# ────────────────────────────────────────────────────────────────
@app.route("/admin/users/<int:beneficiary_id>/profile")
@login_required
def admin_user_profile_page(beneficiary_id):
    bio = _profile_bio(beneficiary_id)
    if not bio:
        abort(404)
    portal = _profile_portal_account(beneficiary_id)
    usage, totals = _profile_usage_stats(beneficiary_id)
    issued_cards = _profile_issued_cards(beneficiary_id)
    requests = _profile_requests(beneficiary_id)
    audit = _profile_audit(beneficiary_id)

    # احسب المستوى الفعّال + التسمية بالساعات
    _eff_tier = 0
    _eff_tier_label = "افتراضي"
    try:
        _get_eff = globals().get("get_effective_tier")
        if callable(_get_eff):
            _eff_tier = int(_get_eff(beneficiary_id) or 0)
    except Exception:
        _eff_tier = 0
    _tier_hours_map = {0: "افتراضي", 1: "ساعتين", 2: "3 ساعات", 3: "4 ساعات"}
    _eff_tier_label = _tier_hours_map.get(_eff_tier, "افتراضي")

    # نمط الوصول: cards أم username (للتحكم بعرض الأقسام)
    _ut = (bio.get("user_type") or "").lower()
    _uni = (bio.get("university_internet_method") or "")
    _free = (bio.get("freelancer_internet_method") or "")
    _username_methods = ("يوزر إنترنت", "يمتلك اسم مستخدم", "username")
    if _ut == "tawjihi":
        _access_mode = "cards"
    elif _ut == "university":
        _access_mode = "username" if _uni in _username_methods else "cards"
    elif _ut == "freelancer":
        _access_mode = "username" if _free in _username_methods else "cards"
    else:
        _access_mode = "cards"

    return render_template(
        "admin/users/profile.html",
        bio=bio,
        portal=portal,
        usage=usage,
        issued_cards=issued_cards,
        requests=requests,
        totals=totals,
        audit=audit,
        action_type_label=action_type_label,
        format_dt_short=format_dt_short,
        effective_tier=_eff_tier,
        effective_tier_label=_eff_tier_label,
        profile_access_mode=_access_mode,
    )


# ────────────────────────────────────────────────────────────────
# POST /admin/users/<id>/set-tier — رفع/خفض مستوى السماح بالبطاقات
# ────────────────────────────────────────────────────────────────
@app.route("/admin/users/<int:beneficiary_id>/set-tier", methods=["POST"])
@login_required
@permission_required("edit")
def admin_user_set_tier(beneficiary_id):
    tier = clean_csv_value(request.form.get("tier") or "")
    if tier not in ("basic", "standard", "complete", "super"):
        return jsonify({"ok": False, "message": "مستوى صلاحية البطاقات غير صالح."}), 400
    execute_sql("UPDATE beneficiaries SET tier=%s WHERE id=%s", [tier, beneficiary_id])
    label = TIER_LABELS.get(tier, tier)
    log_action("set_tier", "beneficiary", beneficiary_id, f"صلاحية البطاقات ← {label}")
    try:
        from app.services.notification_service import notify_beneficiary_tier_updated
        notify_beneficiary_tier_updated(beneficiary_id, label, session.get("username") or "")
    except Exception:
        pass
    return jsonify({"ok": True, "message": f"تم تغيير صلاحية البطاقات إلى {label}."})


# ────────────────────────────────────────────────────────────────
# POST /admin/users/<id>/set-verification — توثيق مع تاريخ انتهاء
# ────────────────────────────────────────────────────────────────
@app.route("/admin/users/<int:beneficiary_id>/set-verification", methods=["POST"])
@login_required
@permission_required("edit")
def admin_user_set_verification(beneficiary_id):
    status = clean_csv_value(request.form.get("status") or "")
    until = clean_csv_value(request.form.get("until") or "")  # YYYY-MM-DD
    if status not in ("unverified", "reviewed", "verified", "super"):
        return jsonify({"ok": False, "message": "حالة توثيق غير صالحة."}), 400
    execute_sql(
        """
        UPDATE beneficiaries SET
            verification_status=%s,
            verified_until=%s,
            verified_by_username=%s,
            verified_at=CURRENT_TIMESTAMP
        WHERE id=%s
        """,
        [status, until or None, session.get("username") or "", beneficiary_id],
    )
    log_action(
        "set_verification", "beneficiary", beneficiary_id,
        f"توثيق ← {status}" + (f" حتى {until}" if until else ""),
    )
    try:
        from app.services.notification_service import notify_beneficiary_verification_updated
        status_label_text = {
            "unverified": "غير موثق",
            "reviewed": "تمت المراجعة",
            "verified": "موثق",
            "super": "توثيق خاص",
        }.get(status, status)
        notify_beneficiary_verification_updated(
            beneficiary_id,
            status_label_text,
            until,
            session.get("username") or "",
        )
    except Exception:
        pass
    return jsonify({"ok": True, "message": "تم تحديث حالة التوثيق."})
# phase 2 ready
