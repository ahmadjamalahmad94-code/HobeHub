# 48ay_portal_unified_actions.py
# إجراءات موحّدة لإدارة حسابات البوابة من تبويب /admin/beneficiaries
# - تصفير حساب + مسح البيانات (سجلات استخدام + عدّاد أسبوعي)
# - إنشاء حساب بوابة بنقرة واحدة (move-in + توليد كود)
#
# الـ endpoints القديمة في 48y_phase1_portal_section تظل كما هي.
# هذا الملف يضيف فقط ما هو جديد.

from flask import jsonify, request


# ─── Helpers (نقرأ من globals لأنهم معرّفون في 48y) ────────────────
def _portal_helpers():
    """يرجع (gen_code, sha256, expiry_72h) من legacy globals."""
    g = globals()
    return (
        g.get("_gen_activation_code") or (lambda: "000000"),
        g.get("_sha256") or (lambda s: ""),
        g.get("_expiry_72h") or (lambda: None),
    )


# ════════════════════════════════════════════════════════════════════
# POST /admin/portal-accounts/<id>/wipe-and-reset
# تصفير الحساب + مسح بيانات الاستخدام + توليد كود تفعيل جديد
# ════════════════════════════════════════════════════════════════════
@app.route("/admin/portal-accounts/<int:portal_id>/wipe-and-reset", methods=["POST"])
@login_required
@permission_required("manage_portal_accounts", "manage_accounts")
def admin_portal_account_wipe_and_reset(portal_id):
    row = query_one(
        "SELECT pa.id, pa.beneficiary_id, b.full_name "
        "FROM beneficiary_portal_accounts pa "
        "JOIN beneficiaries b ON b.id = pa.beneficiary_id "
        "WHERE pa.id=%s",
        [portal_id],
    )
    if not row:
        return jsonify({"ok": False, "message": "الحساب غير موجود."}), 404

    bid = row["beneficiary_id"]
    gen_code, sha256, expiry_72h = _portal_helpers()
    code = gen_code()

    # 1) تصفير الحساب (مثل /reset)
    execute_sql(
        """
        UPDATE beneficiary_portal_accounts SET
            password_hash='',
            password_plain=NULL,
            must_set_password=TRUE,
            is_active=TRUE,
            activation_code_hash=%s,
            activation_code_expires_at=%s,
            last_activation_sent_at=NULL,
            failed_login_attempts=0,
            locked_until=NULL,
            updated_at=CURRENT_TIMESTAMP
        WHERE id=%s
        """,
        [sha256(code), expiry_72h(), portal_id],
    )

    # 2) مسح بيانات الاستخدام للمشترك
    wiped = {"usage_logs": 0, "weekly_counter": False, "card_deliveries": 0}
    try:
        # سجلات الاستخدام
        execute_sql(
            "DELETE FROM beneficiary_usage_logs WHERE beneficiary_id=%s",
            [bid],
        )
        wiped["usage_logs"] = 1  # نعتبره ناجح
    except Exception:
        pass

    try:
        # العدّاد الأسبوعي
        execute_sql(
            "UPDATE beneficiaries SET weekly_usage_count=0 WHERE id=%s",
            [bid],
        )
        wiped["weekly_counter"] = True
    except Exception:
        pass

    try:
        # تسليمات البطاقات (لو الجدول موجود)
        execute_sql(
            "DELETE FROM card_deliveries WHERE beneficiary_id=%s",
            [bid],
        )
        wiped["card_deliveries"] = 1
    except Exception:
        pass

    try:
        log_action(
            "portal_wipe_and_reset",
            "beneficiary_portal_account",
            portal_id,
            f"تصفير شامل ومسح بيانات الاستخدام للمشترك {row.get('full_name')}",
        )
    except Exception:
        pass

    return jsonify({
        "ok": True,
        "message": "تم التصفير ومسح البيانات. الكود الجديد ظاهر أدناه.",
        "code": code,
        "expires_hours": 72,
        "wiped": wiped,
    })


# ════════════════════════════════════════════════════════════════════
# POST /admin/beneficiaries/<bid>/create-portal-account
# إنشاء حساب بوابة من صف المشترك أو الملف الشخصي بنقرة واحدة:
#   - نقل المشترك للبوابة (move-in)
#   - توليد كود تفعيل
#   - إرجاع الكود + portal_id
#
# يمنع التشغيل إذا كان للمشترك حساب بوابة مسبقاً (حماية من التصفير بالغلط).
# ════════════════════════════════════════════════════════════════════
@app.route("/admin/beneficiaries/<int:bid>/create-portal-account", methods=["POST"])
@login_required
@permission_required("manage_portal_accounts", "manage_accounts")
def admin_beneficiary_create_portal_account(bid):
    ben = query_one(
        "SELECT id, full_name, phone FROM beneficiaries WHERE id=%s",
        [bid],
    )
    if not ben:
        return jsonify({"ok": False, "message": "المستفيد غير موجود."}), 404

    existing = query_one(
        "SELECT id, username, password_hash, must_set_password FROM beneficiary_portal_accounts WHERE beneficiary_id=%s",
        [bid],
    )
    gen_code, sha256, expiry_72h = _portal_helpers()
    if existing:
        needs_code = (not existing.get("password_hash")) or bool(existing.get("must_set_password"))
        code = gen_code() if needs_code else ""
        if needs_code:
            execute_sql(
                """
                UPDATE beneficiary_portal_accounts SET
                    is_active=TRUE,
                    portal_membership_active=TRUE,
                    portal_access_state='active',
                    must_set_password=TRUE,
                    activation_code_hash=%s,
                    activation_code_expires_at=%s,
                    updated_at=CURRENT_TIMESTAMP
                WHERE id=%s
                """,
                [sha256(code), expiry_72h(), existing["id"]],
            )
        else:
            execute_sql(
                """
                UPDATE beneficiary_portal_accounts
                   SET is_active=TRUE,
                       portal_membership_active=TRUE,
                       portal_access_state='active',
                       updated_at=CURRENT_TIMESTAMP
                 WHERE id=%s
                """,
                [existing["id"]],
            )
        return jsonify({
            "ok": True,
            "message": "تم إدخال المشترك للبوابة من حسابه المحفوظ.",
            "portal_id": existing["id"],
            "username": existing.get("username") or "",
            "code": code,
            "expires_hours": 72 if code else 0,
            "phone": ben.get("phone") or "",
            "full_name": ben.get("full_name") or "",
        })
        return jsonify({
            "ok": False,
            "message": "للمشترك حساب بوابة مسبقاً. استخدم خيارات «التصفير» بدلاً من «إنشاء».",
            "portal_id": existing["id"],
        }), 409

    # اسم المستخدم: من الـ body أو رقم الجوال افتراضياً
    username = (request.form.get("username") or "").strip()
    if not username:
        username = (ben.get("phone") or "").strip()
    if not username:
        return jsonify({
            "ok": False,
            "message": "اسم المستخدم أو رقم الجوال مطلوب.",
        }), 400

    # تأكد من عدم تكرار اليوزر
    dup = query_one(
        "SELECT id FROM beneficiary_portal_accounts WHERE username=%s",
        [username],
    )
    if dup:
        return jsonify({
            "ok": False,
            "message": "اسم المستخدم مستخدم مسبقاً. اختر آخر.",
        }), 400

    code = gen_code()

    row = execute_sql(
        """
        INSERT INTO beneficiary_portal_accounts
            (beneficiary_id, username, password_hash, password_plain, is_active,
             portal_membership_active, portal_access_state, must_set_password, activation_code_hash, activation_code_expires_at)
        VALUES (%s, %s, '', NULL, TRUE, TRUE, 'active', TRUE, %s, %s)
        RETURNING id
        """,
        [bid, username, sha256(code), expiry_72h()],
        fetchone=True,
    )
    new_id = row["id"] if row else None

    try:
        log_action(
            "portal_create_from_beneficiary",
            "beneficiary_portal_account",
            new_id,
            f"إنشاء حساب بوابة لـ {ben.get('full_name')} (يوزر {username}) من صف المستفيد",
        )
    except Exception:
        pass

    return jsonify({
        "ok": True,
        "message": "تم إنشاء حساب البوابة. اعرض الكود للمشترك.",
        "portal_id": new_id,
        "username": username,
        "code": code,
        "expires_hours": 72,
        "phone": ben.get("phone") or "",
        "full_name": ben.get("full_name") or "",
    })
