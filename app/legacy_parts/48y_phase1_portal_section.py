# 48y_phase1_portal_section.py
# Phase 1 — حسابات بوابة المشتركين بقسمين (داخل/خارج البوابة)
# - schema: إضافة password_plain للسماح للإدارة بمراجعة كلمة المرور (غير سرية عن الإدارة)
# - endpoints: تصفير + بوكس كود التفعيل + SMS stub + نقل لخارج/داخل البوابة + قائمة AJAX

import hashlib
import logging
import random
from datetime import datetime, timedelta
from flask import render_template, request, jsonify

_log = logging.getLogger("hobehub.phase1_portal")

# قابل للضبط لاحقاً عند ربط مزوّد SMS فعلي
SMS_PROVIDER_CONFIGURED = False


def _expiry_72h():
    return (datetime.now() + timedelta(hours=72)).strftime("%Y-%m-%d %H:%M:%S")


def _is_already_exists_error(err):
    """يحدد هل الخطأ بسبب عمود/جدول موجود مسبقاً (نتجاهله بهدوء)."""
    msg = str(err).lower()
    return any(
        token in msg
        for token in ("duplicate column", "already exists", "duplicate", "already defined")
    )


# ────────────────────────────────────────────────────────────────
# Schema additions (idempotent — مع تسجيل واضح للأخطاء غير المتوقعة)
# ────────────────────────────────────────────────────────────────
for _stmt in (
    "ALTER TABLE beneficiary_portal_accounts ADD COLUMN password_plain TEXT",
    "ALTER TABLE beneficiary_portal_accounts ADD COLUMN portal_membership_active BOOLEAN DEFAULT FALSE",
    "ALTER TABLE beneficiary_portal_accounts ADD COLUMN portal_access_state TEXT DEFAULT 'active'",
    # حقول Phase 3 — مستويات السماح والتوثيق (تُضاف الآن لتجنّب SELECT errors)
    "ALTER TABLE beneficiaries ADD COLUMN verification_status TEXT DEFAULT 'unverified'",
    "ALTER TABLE beneficiaries ADD COLUMN verified_until DATE",
    "ALTER TABLE beneficiaries ADD COLUMN verified_by_username TEXT",
    "ALTER TABLE beneficiaries ADD COLUMN verified_at TIMESTAMP",
    "ALTER TABLE beneficiaries ADD COLUMN tier TEXT DEFAULT 'basic'",
):
    try:
        execute_sql(_stmt)
        _log.info("schema bootstrap applied: %s", _stmt[:80])
    except Exception as e:
        if _is_already_exists_error(e):
            _log.debug("schema bootstrap skipped (already applied): %s", _stmt[:80])
        else:
            _log.warning("schema bootstrap FAILED for: %s | error: %s", _stmt[:120], e)


# ────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────
def _gen_activation_code():
    return "{:06d}".format(random.randint(0, 999999))


def _sha256(s):
    return hashlib.sha256((s or "").encode("utf-8")).hexdigest()


def _with_access_mode(rows):
    from app.dashboard.services import get_beneficiary_access_label, get_beneficiary_access_mode

    enriched = []
    for row in rows or []:
        item = dict(row)
        item["access_mode"] = get_beneficiary_access_mode(item)
        item["access_label"] = get_beneficiary_access_label(item)
        enriched.append(item)
    return enriched


def _portal_access_state(row):
    if not row:
        return "active"
    state = (row.get("portal_access_state") or "").strip().lower()
    if state in {"active", "frozen", "disabled"}:
        return state
    if not row.get("is_active"):
        return "disabled"
    return "active"


def _fetch_portal_accounts(search=""):
    """مشتركو البوابة (داخل) — مع رقم الجوال والاسم الكامل."""
    sql = (
        "SELECT pa.*, b.full_name, b.phone, b.user_type, b.verification_status, b.tier, "
        "COALESCE(b.tawjihi_verified, FALSE) AS tawjihi_verified, "
        "b.university_internet_method, b.freelancer_internet_method "
        "FROM beneficiary_portal_accounts pa "
        "JOIN beneficiaries b ON b.id = pa.beneficiary_id "
    )
    params = []
    where = ["COALESCE(pa.portal_membership_active, FALSE)=TRUE"]
    if search:
        like = "%" + search + "%"
        where.append("(b.full_name ILIKE %s OR b.phone ILIKE %s OR pa.username ILIKE %s)")
        params.extend([like, like, like])
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY pa.id DESC LIMIT 500"
    return _with_access_mode(query_all(sql, params))


def _fetch_outside_beneficiaries(search=""):
    """مستفيدون لم يتم تفعيل حساب بوابة لهم بعد."""
    sql = (
        "SELECT b.id, b.full_name, b.phone, b.user_type, b.verification_status, b.tier, "
        "b.university_internet_method, b.freelancer_internet_method "
        "FROM beneficiaries b "
        "LEFT JOIN beneficiary_portal_accounts pa ON pa.beneficiary_id = b.id "
        "AND COALESCE(pa.portal_membership_active, FALSE)=TRUE "
        "WHERE pa.id IS NULL"
    )
    params = []
    if search:
        like = "%" + search + "%"
        sql += " AND (b.full_name ILIKE %s OR b.phone ILIKE %s)"
        params.extend([like, like])
    sql += " ORDER BY b.id DESC LIMIT 500"
    return _with_access_mode(query_all(sql, params))


def _portal_account_counts(search=""):
    portal_sql = (
        "SELECT "
        "COUNT(*) AS total, "
        "SUM(CASE WHEN pa.is_active=TRUE AND COALESCE(pa.portal_access_state, 'active') <> 'disabled' THEN 1 ELSE 0 END) AS active, "
        "SUM(CASE WHEN pa.is_active=TRUE AND COALESCE(pa.portal_access_state, 'active') = 'frozen' THEN 1 ELSE 0 END) AS frozen, "
        "SUM(CASE WHEN pa.is_active<>TRUE OR COALESCE(pa.portal_access_state, 'active') = 'disabled' THEN 1 ELSE 0 END) AS inactive "
        "FROM beneficiary_portal_accounts pa "
        "JOIN beneficiaries b ON b.id = pa.beneficiary_id "
        "WHERE COALESCE(pa.portal_membership_active, FALSE)=TRUE"
    )
    portal_params = []
    where = []
    if search:
        like = "%" + search + "%"
        where.append("(b.full_name ILIKE %s OR b.phone ILIKE %s OR pa.username ILIKE %s)")
        portal_params.extend([like, like, like])
    if where:
        portal_sql += " AND " + " AND ".join(where)
    portal = query_one(portal_sql, portal_params) or {}

    outside_sql = (
        "SELECT COUNT(*) AS total "
        "FROM beneficiaries b "
        "LEFT JOIN beneficiary_portal_accounts pa ON pa.beneficiary_id = b.id "
        "AND COALESCE(pa.portal_membership_active, FALSE)=TRUE "
        "WHERE pa.id IS NULL"
    )
    outside_params = []
    if search:
        like = "%" + search + "%"
        outside_sql += " AND (b.full_name ILIKE %s OR b.phone ILIKE %s)"
        outside_params.extend([like, like])
    outside = query_one(outside_sql, outside_params) or {}

    return {
        "inside": int(portal.get("total") or 0),
        "active": int(portal.get("active") or 0),
        "frozen": int(portal.get("frozen") or 0),
        "inactive": int(portal.get("inactive") or 0),
        "outside": int(outside.get("total") or 0),
    }


# ────────────────────────────────────────────────────────────────
# GET /admin/portal-accounts — override الـ view القديم
# ────────────────────────────────────────────────────────────────
def _portal_accounts_phase1_view():
    q = clean_csv_value(request.args.get("q")) if "clean_csv_value" in globals() else (request.args.get("q") or "").strip()
    inside = _fetch_portal_accounts(q) or []
    outside = _fetch_outside_beneficiaries(q) or []
    counts = _portal_account_counts(q)
    return render_template(
        "admin/portal_accounts/list.html",
        inside=inside,
        outside=outside,
        active_count=counts["active"],
        frozen_count=counts["frozen"],
        inactive_count=counts["inactive"],
        inside_count=counts["inside"],
        outside_count=counts["outside"],
        q=q,
        # backward compat — لو فيه أماكن لسا تستخدم accounts/beneficiaries
        accounts=inside,
        beneficiaries=outside,
        format_dt_short=format_dt_short,
    )


if "admin_portal_accounts_page" in app.view_functions:
    @login_required
    @permission_required("manage_accounts")
    def _phase1_portal_accounts():
        return _portal_accounts_phase1_view()
    app.view_functions["admin_portal_accounts_page"] = _phase1_portal_accounts


# ────────────────────────────────────────────────────────────────
# GET /admin/portal-accounts/list-ajax — بحث بدون reload
# ────────────────────────────────────────────────────────────────
@app.route("/admin/portal-accounts/list-ajax")
@login_required
@permission_required("manage_accounts")
def admin_portal_accounts_list_ajax():
    q = clean_csv_value(request.args.get("q") or "")
    inside = _fetch_portal_accounts(q) or []
    outside = _fetch_outside_beneficiaries(q) or []
    inside_html = render_template(
        "admin/portal_accounts/_inside_rows.html",
        inside=inside,
        format_dt_short=format_dt_short,
    )
    outside_html = render_template(
        "admin/portal_accounts/_outside_rows.html",
        outside=outside,
    )
    counts = _portal_account_counts(q)
    return jsonify({
        "ok": True,
        "inside_html": inside_html,
        "outside_html": outside_html,
            "counts": {
            "inside": counts["inside"],
            "outside": counts["outside"],
            "active": counts["active"],
            "frozen": counts["frozen"],
            "inactive": counts["inactive"],
        },
    })


# ────────────────────────────────────────────────────────────────
# POST /admin/portal-accounts/<id>/reset — تصفير + توليد كود
# ────────────────────────────────────────────────────────────────
@app.route("/admin/portal-accounts/<int:portal_id>/reset", methods=["POST"])
@login_required
@permission_required("manage_accounts")
def admin_portal_account_reset(portal_id):
    row = query_one("SELECT * FROM beneficiary_portal_accounts WHERE id=%s", [portal_id])
    if not row:
        return jsonify({"ok": False, "message": "الحساب غير موجود."}), 404
    code = _gen_activation_code()
    # ملاحظة: password_hash بـ NOT NULL constraint — نضع سلسلة فاضية (لا أحد يقدر يطابقها)
    # بدل NULL. الـ must_set_password=1 يجبر المستفيد على استخدام كود التفعيل
    execute_sql(
        """
        UPDATE beneficiary_portal_accounts SET
            password_hash='',
            password_plain=NULL,
            must_set_password=TRUE,
            activation_code_hash=%s,
            activation_code_expires_at=%s,
            last_activation_sent_at=NULL,
            updated_at=CURRENT_TIMESTAMP
        WHERE id=%s
        """,
        [_sha256(code), _expiry_72h(), portal_id],
    )
    log_action("portal_reset", "beneficiary_portal_account", portal_id, "تصفير الحساب وتوليد رمز تفعيل")
    return jsonify({
        "ok": True,
        "message": "تم تصفير الحساب. اعرض الكود للمشترك أو أرسله SMS.",
        "code": code,
        "expires_hours": 72,
    })


# ────────────────────────────────────────────────────────────────
# GET /admin/portal-accounts/<id>/credentials — كشف كلمة المرور
# ────────────────────────────────────────────────────────────────
@app.route("/admin/portal-accounts/<int:portal_id>/credentials")
@login_required
@permission_required("manage_accounts")
def admin_portal_account_credentials(portal_id):
    row = query_one(
        "SELECT pa.username, pa.password_plain, pa.must_set_password, b.full_name, b.phone "
        "FROM beneficiary_portal_accounts pa "
        "JOIN beneficiaries b ON b.id = pa.beneficiary_id "
        "WHERE pa.id=%s",
        [portal_id],
    )
    if not row:
        return jsonify({"ok": False, "message": "الحساب غير موجود."}), 404
    log_action("portal_view_credentials", "beneficiary_portal_account", portal_id, "كشف كلمة مرور البوابة")
    return jsonify({
        "ok": True,
        "username": row.get("username") or "",
        "password": row.get("password_plain") or "",
        "must_set_password": bool(row.get("must_set_password")),
        "full_name": row.get("full_name") or "",
        "phone": row.get("phone") or "",
    })


# ────────────────────────────────────────────────────────────────
# POST /admin/portal-accounts/<id>/send-sms — إرسال رمز التفعيل SMS (stub)
# ────────────────────────────────────────────────────────────────
@app.route("/admin/portal-accounts/<int:portal_id>/send-sms", methods=["POST"])
@login_required
@permission_required("manage_accounts")
def admin_portal_account_send_sms(portal_id):
    row = query_one(
        "SELECT pa.id, pa.activation_code_expires_at, b.phone, b.full_name "
        "FROM beneficiary_portal_accounts pa "
        "JOIN beneficiaries b ON b.id = pa.beneficiary_id "
        "WHERE pa.id=%s",
        [portal_id],
    )
    if not row:
        return jsonify({"ok": False, "message": "الحساب غير موجود."}), 404
    if not row.get("activation_code_expires_at"):
        return jsonify({"ok": False, "message": "لا يوجد رمز تفعيل نشط. اضغط «تصفير» أولاً."}), 400

    # لو مزوّد SMS غير مفعّل — لا نزيّف نجاحاً
    if not SMS_PROVIDER_CONFIGURED:
        log_action(
            "portal_sms_skipped", "beneficiary_portal_account", portal_id,
            f"محاولة إرسال SMS بدون مزوّد مفعّل — الجوال {row.get('phone')}",
        )
        return jsonify({
            "ok": False,
            "configured": False,
            "message": "إرسال SMS غير مفعّل بعد. الرجاء نقل الرمز للمشترك يدوياً (نسخ + إخبار).",
            "phone": row.get("phone") or "",
        }), 503

    # عند تفعيل مزوّد SMS لاحقاً: نفّذ الإرسال هنا قبل الـ UPDATE
    execute_sql(
        "UPDATE beneficiary_portal_accounts SET last_activation_sent_at=CURRENT_TIMESTAMP WHERE id=%s",
        [portal_id],
    )
    log_action("portal_sms_send", "beneficiary_portal_account", portal_id, f"إرسال SMS للجوال {row.get('phone')}")
    return jsonify({
        "ok": True,
        "configured": True,
        "message": "تم إرسال SMS بنجاح.",
        "phone": row.get("phone") or "",
    })


# ────────────────────────────────────────────────────────────────
# POST /admin/portal-accounts/<id>/delete — حذف الحساب (يبقى المستفيد)
# ────────────────────────────────────────────────────────────────
@app.route("/admin/portal-accounts/<int:portal_id>/delete", methods=["POST"])
@login_required
@permission_required("manage_accounts")
def admin_portal_account_delete(portal_id):
    row = query_one("SELECT username, beneficiary_id FROM beneficiary_portal_accounts WHERE id=%s", [portal_id])
    if not row:
        return jsonify({"ok": False, "message": "الحساب غير موجود."}), 404
    execute_sql(
        "UPDATE beneficiary_portal_accounts SET portal_membership_active=FALSE, updated_at=CURRENT_TIMESTAMP WHERE id=%s",
        [portal_id],
    )
    log_action("portal_disable_membership", "beneficiary_portal_account", portal_id, f"إخراج حساب البوابة {row.get('username')} من التصنيف النشط")
    return jsonify({"ok": True, "message": "تم إخراج المشترك من البوابة مع حفظ حسابه."})


# ────────────────────────────────────────────────────────────────
# POST /admin/portal-accounts/move-in — تفعيل حساب بوابة لمستفيد
# ────────────────────────────────────────────────────────────────
@app.route("/admin/portal-accounts/move-in", methods=["POST"])
@login_required
@permission_required("manage_accounts")
def admin_portal_account_move_in():
    try:
        beneficiary_id = int(clean_csv_value(request.form.get("beneficiary_id", "0")) or "0")
    except Exception:
        beneficiary_id = 0
    username = clean_csv_value(request.form.get("username") or "")
    if beneficiary_id <= 0:
        return jsonify({"ok": False, "message": "المستفيد مطلوب."}), 400
    ben = query_one("SELECT id, phone, full_name FROM beneficiaries WHERE id=%s", [beneficiary_id])
    if not ben:
        return jsonify({"ok": False, "message": "المستفيد غير موجود."}), 404
    existing = query_one(
        "SELECT id, username, password_hash, must_set_password FROM beneficiary_portal_accounts WHERE beneficiary_id=%s",
        [beneficiary_id],
    )
    if existing:
        needs_code = (not existing.get("password_hash")) or bool(existing.get("must_set_password"))
        code = _gen_activation_code() if needs_code else ""
        if needs_code:
            execute_sql(
                """
                UPDATE beneficiary_portal_accounts
                    SET is_active=TRUE,
                    portal_membership_active=TRUE,
                    portal_access_state='active',
                    must_set_password=TRUE,
                    activation_code_hash=%s,
                    activation_code_expires_at=%s,
                    updated_at=CURRENT_TIMESTAMP
                WHERE id=%s
                """,
                [_sha256(code), _expiry_72h(), existing["id"]],
            )
        else:
            execute_sql(
                "UPDATE beneficiary_portal_accounts SET is_active=TRUE, portal_membership_active=TRUE, portal_access_state='active', updated_at=CURRENT_TIMESTAMP WHERE id=%s",
                [existing["id"]],
            )
        final_username = existing.get("username") or username or ben.get("phone") or ""
        log_action(
            "portal_enable", "beneficiary_portal_account", existing["id"],
            f"تفعيل بوابة {ben.get('full_name')} (يوزر {final_username})",
        )
        return jsonify({
            "ok": True,
            "message": "تم تفعيل حساب البوابة.",
            "portal_id": existing["id"],
            "username": final_username,
            "code": code,
            "expires_hours": 72 if code else 0,
            "phone": ben.get("phone") or "",
        })

    if not username:
        username = (ben.get("phone") or "").strip()
    if not username:
        return jsonify({"ok": False, "message": "اسم المستخدم أو رقم الجوال مطلوب."}), 400

    dup = query_one("SELECT id FROM beneficiary_portal_accounts WHERE username=%s", [username])
    if dup:
        return jsonify({"ok": False, "message": "اسم المستخدم مستخدم مسبقًا."}), 400

    code = _gen_activation_code()
    # password_hash بـ NOT NULL — نستخدم سلسلة فاضية + must_set_password=1
    row = execute_sql(
        """
        INSERT INTO beneficiary_portal_accounts
            (beneficiary_id, username, password_hash, password_plain, is_active,
             portal_membership_active, portal_access_state, must_set_password, activation_code_hash, activation_code_expires_at)
        VALUES (%s, %s, '', NULL, TRUE, TRUE, 'active', TRUE, %s, %s)
        RETURNING id
        """,
        [beneficiary_id, username, _sha256(code), _expiry_72h()],
        fetchone=True,
    )
    new_id = row["id"] if row else None
    log_action(
        "portal_enable", "beneficiary_portal_account", new_id,
        f"تفعيل حساب بوابة {ben.get('full_name')} (يوزر {username})",
    )
    return jsonify({
        "ok": True,
        "message": "تم إنشاء حساب البوابة. اعرض الكود أو أرسله SMS.",
        "portal_id": new_id,
        "username": username,
        "code": code,
        "expires_hours": 72,
        "phone": ben.get("phone") or "",
    })


# phase 1 ready
