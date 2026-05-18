# 48ap_radius_features.py
# مزايا تكامل RADIUS API: status widget للمشترك، تغيير كلمة المرور، live monitor، daily snapshots، monthly report.

from flask import request, jsonify, render_template, redirect, url_for, flash, session
from datetime import datetime
import json as _json


# ────────────────────────────────────────────────────────────────
# Schema: usage_snapshots — يومي لكل مشترك
# ────────────────────────────────────────────────────────────────
def _ensure_usage_snapshots_schema():
    try:
        if is_sqlite_database_url():
            execute_sql("""
                CREATE TABLE IF NOT EXISTS usage_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    beneficiary_id INTEGER NOT NULL,
                    username TEXT NOT NULL DEFAULT '',
                    snapshot_date TEXT NOT NULL,
                    profile_name TEXT DEFAULT '',
                    usage_bytes BIGINT DEFAULT 0,
                    down_speed TEXT DEFAULT '',
                    up_speed TEXT DEFAULT '',
                    is_online INTEGER DEFAULT 0,
                    status_code TEXT DEFAULT '',
                    raw_json TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
        else:
            execute_sql("""
                CREATE TABLE IF NOT EXISTS usage_snapshots (
                    id SERIAL PRIMARY KEY,
                    beneficiary_id INTEGER NOT NULL,
                    username TEXT NOT NULL DEFAULT '',
                    snapshot_date DATE NOT NULL,
                    profile_name TEXT DEFAULT '',
                    usage_bytes BIGINT DEFAULT 0,
                    down_speed TEXT DEFAULT '',
                    up_speed TEXT DEFAULT '',
                    is_online SMALLINT DEFAULT 0,
                    status_code TEXT DEFAULT '',
                    raw_json TEXT DEFAULT '',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
        execute_sql("CREATE INDEX IF NOT EXISTS usage_snapshots_bid_date ON usage_snapshots(beneficiary_id, snapshot_date)")
    except Exception:
        pass


_ensure_usage_snapshots_schema()


# ════════════════════════════════════════════════════════════════
# 1) /portal/account/api/status — الـ status JSON للمشترك (للـ widget)
# ════════════════════════════════════════════════════════════════
@app.route("/portal/account/api/status", methods=["GET"])
@user_login_required
def portal_account_status_api():
    """يستخدم AdvClient API (للمشترك فقط) — لا اعتماد على admin API."""
    from app.services.radius_subscriber_bridge import (
        fetch_subscriber_details_via_self,
        get_radius_username_for,
    )

    bid = int(session.get("beneficiary_id") or 0)
    if not bid:
        return jsonify({"ok": False, "error": "غير مسجّل دخول."}), 401

    beneficiary = query_one("SELECT * FROM beneficiaries WHERE id=%s", [bid]) or {}
    # ⚠ كلمة مرور الـ RADIUS مستقلة عن كلمة مرور البوابة:
    # - البوابة: beneficiary_portal_accounts.password_plain (للدخول إلى الموقع فقط)
    # - RADIUS: beneficiary_radius_accounts.plain_password (للـ API الخارجية)
    radius = query_one(
        "SELECT external_username, plain_password FROM beneficiary_radius_accounts WHERE beneficiary_id=%s LIMIT 1",
        [bid],
    ) or {}
    username = radius.get("external_username") or get_radius_username_for(beneficiary)
    password = radius.get("plain_password") or ""

    if not username:
        return jsonify({
            "ok": False,
            "error": "لا يوجد اسم مستخدم RADIUS مرتبط بحسابك. تواصل مع الإدارة.",
        })
    if not password:
        return jsonify({
            "ok": False,
            "error": "لا توجد كلمة مرور RADIUS محفوظة لحسابك.",
            "hint": "تواصل مع الإدارة لإدخال بيانات RADIUS الخاصة بك.",
        })

    # نستدعي subscriber API مباشرة بكريدنشيال RADIUS
    result = fetch_subscriber_details_via_self(username, password)
    if result.get("ok"):
        return jsonify({
            "ok": True,
            "source": "subscriber_api",
            "username": username,
            "details": result.get("details") or {},
            "status": result.get("status") or {},
            "account": result.get("account") or {},
        })

    return jsonify({
        "ok": False,
        "error": result.get("error") or "تعذّر الاتصال بـ RADIUS API.",
        "hint": "تأكّد أن كلمة مرور RADIUS المخزّنة هي ذاتها في خادم RADIUS.",
    })


# ════════════════════════════════════════════════════════════════
# 3) /portal/account/api/change-password — تغيير كلمة المرور عبر API
# ════════════════════════════════════════════════════════════════
@app.route("/portal/account/api/change-password", methods=["POST"])
@user_login_required
def portal_account_change_password_api():
    """يُنشئ طلب تغيير كلمة مرور للمراجعة من الإدارة + يحدّث DB."""
    return jsonify({
        "ok": False,
        "error": "تغيير كلمة المرور موقوف مؤقتًا. عند الحاجة تواصل مع الإدارة.",
    }), 503

    bid = int(session.get("beneficiary_id") or 0)
    if not bid:
        return jsonify({"ok": False, "error": "غير مسجّل دخول."}), 401

    current_pwd = (request.form.get("current_password") or "").strip()
    new_pwd = (request.form.get("new_password") or "").strip()
    confirm = (request.form.get("confirm_password") or "").strip()

    if not current_pwd or not new_pwd or not confirm:
        return jsonify({"ok": False, "error": "كل الحقول مطلوبة."}), 400
    if new_pwd != confirm:
        return jsonify({"ok": False, "error": "كلمتا المرور غير متطابقتين."}), 400
    if len(new_pwd) < 6:
        return jsonify({"ok": False, "error": "كلمة المرور قصيرة جدًا (6 أحرف على الأقل)."}), 400

    # تحقّق من كلمة المرور الحالية
    portal = query_one(
        "SELECT password_plain FROM beneficiary_portal_accounts WHERE beneficiary_id=%s LIMIT 1",
        [bid],
    )
    if portal and portal.get("password_plain") and portal.get("password_plain") != current_pwd:
        return jsonify({"ok": False, "error": "كلمة المرور الحالية غير صحيحة."}), 401

    # حدّث DB فقط — admin API لتطبيقها على RADIUS غير جاهز حاليًا
    try:
        from hashlib import sha256
        execute_sql(
            """
            UPDATE beneficiary_portal_accounts
            SET password_hash=%s, password_plain=%s, updated_at=CURRENT_TIMESTAMP
            WHERE beneficiary_id=%s
            """,
            [sha256(new_pwd.encode("utf-8")).hexdigest(), new_pwd, bid],
        )
    except Exception as e:
        return jsonify({"ok": False, "error": f"تعذّر حفظ كلمة المرور الجديدة: {e}"}), 500

    log_action("portal_password_changed", "beneficiary", bid, "تغيير كلمة المرور (DB فقط — RADIUS sync لاحقًا)")
    return jsonify({
        "ok": True,
        "message": "تم تحديث كلمة المرور في النظام. ستُطبَّق على RADIUS عند مزامنة الإدارة.",
    })


# ════════════════════════════════════════════════════════════════
# /admin/users/<id>/api/set-password — تعديل/تعيين بيانات RADIUS للمشترك
# هذه الكلمة تُستخدم في كل اتصال بـ RADIUS API، وهي **مستقلّة تماماً** عن كلمة مرور
# البوابة الموجودة في beneficiary_portal_accounts.password_plain.
# ════════════════════════════════════════════════════════════════
@app.route("/admin/users/<int:beneficiary_id>/api/set-password", methods=["POST"])
@admin_login_required
def admin_user_set_portal_password(beneficiary_id):
    new_password = (request.form.get("password") or "").strip()
    new_username = (request.form.get("username") or "").strip()
    if not new_password:
        return jsonify({"ok": False, "error": "كلمة مرور RADIUS مطلوبة."}), 400

    beneficiary = query_one("SELECT id, full_name, phone FROM beneficiaries WHERE id=%s", [beneficiary_id])
    if not beneficiary:
        return jsonify({"ok": False, "error": "المشترك غير موجود."}), 404

    # إذا لم يُدخل username نأخذ phone كافتراضي
    if not new_username:
        new_username = beneficiary.get("phone") or ""
    if not new_username:
        return jsonify({"ok": False, "error": "اسم مستخدم RADIUS مطلوب."}), 400

    # نحفظ في beneficiary_radius_accounts فقط — هذه بيانات الـ API
    # كلمة مرور البوابة منفصلة في beneficiary_portal_accounts ولا تتأثر هنا.
    existing = query_one(
        "SELECT id FROM beneficiary_radius_accounts WHERE beneficiary_id=%s LIMIT 1",
        [beneficiary_id],
    )
    try:
        from hashlib import md5
        pwd_md5 = md5(new_password.encode("utf-8")).hexdigest()
        if existing:
            execute_sql(
                """
                UPDATE beneficiary_radius_accounts SET
                    external_username=%s,
                    plain_password=%s,
                    password_md5=%s,
                    updated_at=CURRENT_TIMESTAMP
                WHERE beneficiary_id=%s
                """,
                [new_username, new_password, pwd_md5, beneficiary_id],
            )
        else:
            execute_sql(
                """
                INSERT INTO beneficiary_radius_accounts
                    (beneficiary_id, external_username, plain_password, password_md5, status)
                VALUES (%s,%s,%s,%s,'pending')
                """,
                [beneficiary_id, new_username, new_password, pwd_md5],
            )
        log_action("radius_password_set", "beneficiary", beneficiary_id,
                   f"تعديل/إنشاء بيانات RADIUS API: {new_username}")
        return jsonify({"ok": True, "username": new_username, "password": new_password})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ════════════════════════════════════════════════════════════════
# /admin/users/<id>/api/status — يجلب البيانات الحية لمشترك من API
# (يستخدم username + password المخزّنين لهذا المشترك)
# ════════════════════════════════════════════════════════════════
@app.route("/admin/users/<int:beneficiary_id>/api/status", methods=["GET"])
@admin_login_required
def admin_user_api_status(beneficiary_id):
    from app.services.radius_subscriber_bridge import (
        fetch_subscriber_details_via_self,
        get_radius_username_for,
    )

    beneficiary = query_one("SELECT * FROM beneficiaries WHERE id=%s", [beneficiary_id])
    if not beneficiary:
        return jsonify({"ok": False, "error": "المشترك غير موجود."}), 404

    # كلمة مرور RADIUS من جدول beneficiary_radius_accounts (مستقلّة عن البوابة)
    radius = query_one(
        "SELECT external_username, plain_password FROM beneficiary_radius_accounts WHERE beneficiary_id=%s LIMIT 1",
        [beneficiary_id],
    ) or {}
    username = radius.get("external_username") or get_radius_username_for(beneficiary)
    password = radius.get("plain_password") or ""

    if not username:
        return jsonify({
            "ok": False,
            "error": "لا يوجد اسم مستخدم RADIUS لهذا المشترك.",
        })
    if not password:
        return jsonify({
            "ok": False,
            "error": "لا توجد كلمة مرور RADIUS لهذا المشترك. أدخلها من عمود «كلمة المرور» في الجدول.",
        })

    result = fetch_subscriber_details_via_self(username, password)
    if result.get("ok"):
        return jsonify({
            "ok": True,
            "username": username,
            "beneficiary_id": beneficiary_id,
            "details": result.get("details") or {},
            "status": result.get("status") or {},
            "account": result.get("account") or {},
        })
    return jsonify({
        "ok": False,
        "error": result.get("error") or "فشل الاتصال بـ RADIUS API.",
        "username": username,
    })


# ════════════════════════════════════════════════════════════════
# 6) Live monitor — صفحة + JSON polling endpoint
# ════════════════════════════════════════════════════════════════
@app.route("/admin/radius/live-monitor", methods=["GET"])
@admin_login_required
def admin_radius_live_monitor():
    return render_template("admin/radius/live_monitor.html")


@app.route("/admin/radius/live-monitor/data", methods=["GET"])
@admin_login_required
def admin_radius_live_monitor_data():
    from app.services.radius_subscriber_bridge import fetch_online_users
    result = fetch_online_users(limit=200)
    return jsonify(result)


# ════════════════════════════════════════════════════════════════
# 8) Daily snapshot — لكل المشتركين النشطين
# ════════════════════════════════════════════════════════════════
def _take_snapshot_for_beneficiary(beneficiary):
    """يجلب البيانات الحالية لمشترك ويحفظها كـ snapshot."""
    from app.services.radius_subscriber_bridge import (
        fetch_subscriber_details_via_self,
        fetch_subscriber_status,
        get_radius_username_for,
    )
    bid = int(beneficiary.get("id") or 0)
    username = get_radius_username_for(beneficiary)
    if not bid or not username:
        return False

    # كلمة مرور RADIUS من جدول RADIUS المخصص (مستقلة عن البوابة)
    radius = query_one(
        "SELECT plain_password FROM beneficiary_radius_accounts WHERE beneficiary_id=%s LIMIT 1",
        [bid],
    ) or {}
    password = radius.get("plain_password") or ""

    payload = {}
    if username and password:
        r = fetch_subscriber_details_via_self(username, password)
        if r.get("ok"):
            payload = r.get("details") or {}
    if not payload:
        r2 = fetch_subscriber_status(username)
        if r2.get("ok"):
            payload = (r2.get("usage") or {})

    if not payload:
        return False

    # استخرج الحقول المهمة
    usage_bytes = int(payload.get("val_usage_qouta") or 0)
    profile_name = payload.get("profile_name") or ""
    down_speed = payload.get("down_speed") or ""
    up_speed = payload.get("up_speed") or ""
    is_online = 1 if (payload.get("conn_code") == "online" or payload.get("is_online")) else 0
    status_code = payload.get("status_code") or ""
    today = datetime.now().strftime("%Y-%m-%d")

    # لا تكرّر snapshot في نفس اليوم — حدّث الموجود
    existing = query_one(
        "SELECT id FROM usage_snapshots WHERE beneficiary_id=%s AND snapshot_date=%s",
        [bid, today],
    )
    if existing:
        execute_sql(
            """
            UPDATE usage_snapshots SET
                username=%s, profile_name=%s, usage_bytes=%s, down_speed=%s, up_speed=%s,
                is_online=%s, status_code=%s, raw_json=%s
            WHERE id=%s
            """,
            [username, profile_name, usage_bytes, down_speed, up_speed,
             is_online, status_code, _json.dumps(payload, ensure_ascii=False, default=str),
             existing["id"]],
        )
    else:
        execute_sql(
            """
            INSERT INTO usage_snapshots
                (beneficiary_id, username, snapshot_date, profile_name, usage_bytes,
                 down_speed, up_speed, is_online, status_code, raw_json)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            [bid, username, today, profile_name, usage_bytes, down_speed, up_speed,
             is_online, status_code, _json.dumps(payload, ensure_ascii=False, default=str)],
        )
    return True


@app.route("/admin/radius/snapshots/run", methods=["POST"])
@admin_login_required
def admin_radius_snapshots_run():
    """يأخذ snapshot يومي لكل المشتركين النشطين (يُستدعى يدويًا أو من cron)."""
    rows = query_all(
        """
        SELECT b.* FROM beneficiaries b
        JOIN beneficiary_portal_accounts pa ON pa.beneficiary_id = b.id
        WHERE pa.is_active = TRUE
          AND COALESCE(pa.portal_membership_active, FALSE)=TRUE
        """
    ) or []
    success = 0
    failed = 0
    for row in rows:
        try:
            if _take_snapshot_for_beneficiary(dict(row)):
                success += 1
            else:
                failed += 1
        except Exception:
            failed += 1
    log_action("snapshots_run", "system", None, f"snapshots: {success} success / {failed} failed")
    flash(f"تم أخذ {success} snapshot ({failed} فشل).", "success" if success else "error")
    return redirect(request.referrer or url_for("admin_radius_live_monitor"))


# ════════════════════════════════════════════════════════════════
# 8) Monthly report page
# ════════════════════════════════════════════════════════════════
@app.route("/admin/users/<int:beneficiary_id>/report/monthly", methods=["GET"])
@admin_login_required
def admin_user_monthly_report(beneficiary_id):
    beneficiary = query_one("SELECT * FROM beneficiaries WHERE id=%s", [beneficiary_id])
    if not beneficiary:
        flash("المشترك غير موجود.", "error")
        return redirect(url_for("beneficiaries_page"))

    # آخر 30 snapshot
    snapshots = query_all(
        """
        SELECT snapshot_date, usage_bytes, profile_name, is_online, status_code,
               down_speed, up_speed
        FROM usage_snapshots
        WHERE beneficiary_id=%s
        ORDER BY snapshot_date DESC
        LIMIT 60
        """,
        [beneficiary_id],
    ) or []

    # حسابات
    online_days = sum(1 for s in snapshots if int(s.get("is_online") or 0))
    total_gb = (snapshots[0].get("usage_bytes") or 0) / (1024**3) if snapshots else 0
    chart_data = list(reversed([
        {"d": s["snapshot_date"], "gb": round((s.get("usage_bytes") or 0) / (1024**3), 2)}
        for s in snapshots[:30]
    ]))

    return render_template(
        "admin/users/monthly_report.html",
        beneficiary=beneficiary,
        snapshots=snapshots,
        online_days=online_days,
        total_gb=total_gb,
        chart_data=chart_data,
    )
