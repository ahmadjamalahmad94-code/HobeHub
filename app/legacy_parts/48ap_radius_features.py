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


def _status_snapshot_as_api_payload(snapshot):
    return {
        "conn_code": "online" if snapshot.get("is_online") else "offline",
        "is_online": 1 if snapshot.get("is_online") else 0,
        "profile_name": snapshot.get("profile_name") or "",
        "expiration": snapshot.get("expires_at") or "",
        "down_speed": snapshot.get("download_speed") or snapshot.get("down_speed") or "",
        "up_speed": snapshot.get("upload_speed") or snapshot.get("up_speed") or "",
        "val_usage_qouta": snapshot.get("usage_bytes") or 0,
        "val_rem": snapshot.get("remaining_bytes") or 0,
        "framed_ip": snapshot.get("framed_ip") or "",
        "mac_address": snapshot.get("mac_address") or "",
        "status": snapshot.get("status") or "",
        "status_label": snapshot.get("status_label") or "",
        "last_seen_at": snapshot.get("last_seen_at") or "",
    }


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
        from app.services.subscriber_radius_status import get_subscriber_radius_status

        snapshot = get_subscriber_radius_status(bid, username)
        return jsonify({
            "ok": True,
            "source": snapshot.get("source") or "local",
            "username": username,
            "details": _status_snapshot_as_api_payload(snapshot),
            "status": {},
            "account": {},
            "warning": "كلمة مرور حساب الإنترنت غير محفوظة، لذلك تظهر القراءة المتاحة محليًا فقط.",
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

    from app.services.subscriber_radius_status import get_subscriber_radius_status

    snapshot = get_subscriber_radius_status(bid, username)
    return jsonify({
        "ok": True,
        "source": snapshot.get("source") or "local_fallback",
        "username": username,
        "details": _status_snapshot_as_api_payload(snapshot),
        "status": {},
        "account": {},
        "warning": result.get("error") or "تعذّر الاتصال بواجهة المصادقة، لذلك تظهر القراءة المتاحة محليًا.",
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
        # ── ربط الريديوس: طبّق كلمة المرور فعليًّا (تغيير؛ وإن لم يوجد اليوزر أنشئه) ──
        try:
            from app.services.radius_provisioning import (
                provision_subscriber, reset_subscriber_password)
            _actor = session.get("username") or "admin"
            _rr = reset_subscriber_password(
                username=new_username, new_password=new_password,
                beneficiary_id=beneficiary_id, requested_by=_actor)
            _live_ok = bool(_rr.get("ok") and _rr.get("live"))
            if _rr.get("live") and not _rr.get("ok"):
                _cr = provision_subscriber(
                    beneficiary_id=beneficiary_id, username=new_username,
                    password=new_password, profile_id="", requested_by=_actor)
                _live_ok = bool(_cr.get("ok") and _cr.get("live"))
            if _live_ok:
                execute_sql(
                    "UPDATE beneficiary_radius_accounts SET status='active', "
                    "updated_at=CURRENT_TIMESTAMP WHERE beneficiary_id=%s",
                    [beneficiary_id])
        except Exception:
            pass
        log_action("radius_password_set", "beneficiary", beneficiary_id,
                   f"تعديل/إنشاء بيانات RADIUS API: {new_username}")
        return jsonify({"ok": True, "username": new_username, "password": new_password})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ════════════════════════════════════════════════════════════════
# /admin/users/<id>/api/status — يجلب البيانات الحية لمشترك من API
# (يستخدم username + password المخزّنين لهذا المشترك)
# ════════════════════════════════════════════════════════════════
def _admin_subscriber_details(username, expires_local=""):
    """يبني تفاصيل المشترك للعرض عبر **مفتاح الأدمن** (لا كلمة مرور المشترك):
    السرعة تُشتقّ من الباقة، والاستهلاك من نقاط الأدمن — فيعمل لكل الحسابات
    (المُنشأة والمُزامَنة). يُرجع None لو الواجهة غير مفعّلة."""
    from app.services.radius_client import get_radius_client, is_api_under_development
    if is_api_under_development():
        return None
    client = get_radius_client()

    def _to_int(v):
        try:
            return int(v or 0)
        except (TypeError, ValueError):
            return 0

    sess = client.get_user_sessions(username) or {}
    sess_list = sess.get("data") if isinstance(sess, dict) else sess
    if not isinstance(sess_list, list):
        sess_list = []
    usage = client.get_user_usage(username) or {}
    if not isinstance(usage, dict):
        usage = {}
    found = client.search_users(username, limit=5)
    items = found.get("data") if isinstance(found, dict) else []
    acct = (items[0] if items else {}) or {}

    down = _to_int(acct.get("download_speed_kbps"))
    up = _to_int(acct.get("upload_speed_kbps"))
    plan_id = acct.get("plan_id") or acct.get("profile_id") or ""
    plan_name = acct.get("plan_name") or ""
    if plan_id and ((not down and not up) or not plan_name):
        try:
            for p in (client.get_profiles() or []):
                if str(p.get("id") or p.get("external_id") or "") == str(plan_id):
                    down = down or _to_int(p.get("speed_down_kbps"))
                    up = up or _to_int(p.get("speed_up_kbps"))
                    plan_name = plan_name or (p.get("name") or p.get("plan_name")
                                              or p.get("title") or p.get("external_name") or "")
                    break
        except Exception:
            pass

    bin_ = _to_int(usage.get("used_bytes_in") or usage.get("total_bytes_in") or usage.get("bytes_in"))
    bout = _to_int(usage.get("used_bytes_out") or usage.get("total_bytes_out") or usage.get("bytes_out"))
    if not (bin_ or bout):
        try:
            acc = client.get_accounting_usage(username) or {}
            if isinstance(acc, dict):
                bin_ = bin_ or _to_int(acc.get("bytes_in") or acc.get("total_bytes_in"))
                bout = bout or _to_int(acc.get("bytes_out") or acc.get("total_bytes_out"))
        except Exception:
            pass
    if not (bin_ or bout):
        bin_ = sum(_to_int(x.get("bytes_in")) for x in sess_list if isinstance(x, dict))
        bout = sum(_to_int(x.get("bytes_out")) for x in sess_list if isinstance(x, dict))

    cur = sess_list[0] if sess_list else {}
    online = bool(sess_list)
    return {
        "conn_code": "online" if online else "offline",
        "is_online": 1 if online else 0,
        "profile_name": plan_name or (("باقة #%s" % plan_id) if plan_id else "—"),
        "status_label": acct.get("status") or "",
        "down_speed": ("%s Kbps" % down) if down else "",
        "up_speed": ("%s Kbps" % up) if up else "",
        "val_usage_qouta": bin_ + bout,
        "expiration": acct.get("expire_at") or acct.get("expires_at") or expires_local or "",
        "mac_address": (cur.get("calling_station_id") or cur.get("mac") or "") if online else "",
        "framed_ip": (cur.get("framed_ip") or cur.get("framedipaddress") or cur.get("ip") or "") if online else "",
        "last_seen_at": usage.get("last_seen_at") or usage.get("last_session_at") or "",
    }


@app.route("/admin/users/<int:beneficiary_id>/api/status", methods=["GET"])
@admin_login_required
def admin_user_api_status(beneficiary_id):
    from app.services.radius_subscriber_bridge import get_radius_username_for

    beneficiary = query_one("SELECT * FROM beneficiaries WHERE id=%s", [beneficiary_id])
    if not beneficiary:
        return jsonify({"ok": False, "error": "المشترك غير موجود."}), 404

    radius = query_one(
        "SELECT external_username, expires_at FROM beneficiary_radius_accounts WHERE beneficiary_id=%s LIMIT 1",
        [beneficiary_id],
    ) or {}
    username = radius.get("external_username") or get_radius_username_for(beneficiary)
    if not username:
        return jsonify({"ok": False, "error": "لا يوجد اسم مستخدم RADIUS لهذا المشترك."})

    # الجلب عبر مفتاح الأدمن (لا يحتاج كلمة مرور المشترك) — يعمل للمُزامَنة أيضًا.
    try:
        details = _admin_subscriber_details(username, expires_local=str(radius.get("expires_at") or ""))
    except Exception as exc:  # noqa: BLE001 — أي عطل يسقط للقراءة المحلية
        details = None
        _err = str(exc)
    else:
        _err = ""

    if details is not None:
        return jsonify({
            "ok": True, "username": username, "beneficiary_id": beneficiary_id, "details": details,
        })

    # سقوط: الواجهة غير مفعّلة أو عطل → قراءة محلية.
    from app.services.subscriber_radius_status import get_subscriber_radius_status
    snapshot = get_subscriber_radius_status(beneficiary_id, username)
    return jsonify({
        "ok": True,
        "source": snapshot.get("source") or "local",
        "username": username,
        "beneficiary_id": beneficiary_id,
        "details": _status_snapshot_as_api_payload(snapshot),
        "warning": _err or "واجهة المصادقة غير مفعّلة — تظهر القراءة المحلية المتاحة.",
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
# 7) Webhook receiver — أحداث الريديوس (RADIUS → HobeHub) → إشعارات
#    خادم↔خادم موقَّع بـHMAC (X-HobeRadius-Signature: sha256=…). لا CSRF
#    (مُعفى في 12_csrf) ولا تسجيل دخول. اضبط رابطه من إعدادات الريديوس +
#    HOBERADIUS_WEBHOOK_SECRET المشترك.
# ════════════════════════════════════════════════════════════════
def _handle_radius_webhook_event(event, data, payload):
    from app.services.notification_service import ADMIN_RECIPIENT, create_notification
    username = (data.get("username") or "").strip()
    bid = None
    if username:
        try:
            r = query_one(
                "SELECT beneficiary_id FROM beneficiary_radius_accounts "
                "WHERE external_username=%s LIMIT 1", [username]) or {}
            bid = r.get("beneficiary_id")
        except Exception:
            pass
    # الأحداث المهمّة فقط (نتجاهل الجلسات الضوضائيّة كي لا نُغرق مركز الإشعارات).
    mapping = {
        "account.expired":  ("انتهاء اشتراك مشترك على الريديوس", "danger"),
        "account.disabled": ("تعطيل مشترك على الريديوس", "warning"),
        "quota.threshold":  ("تنبيه: مشترك قارب/تجاوز حصّته", "warning"),
        "nas.unreachable":  ("راوتر/NAS لا يستجيب", "danger"),
        "card.consumed":    ("استُهلكت بطاقة لأول مرّة", "info"),
    }
    if event not in mapping:
        return
    title, status = mapping[event]
    bits = []
    if username:
        bits.append(f"المستخدم: {username}")
    for k in ("reason", "percent", "nas", "nas_ip", "occurred_at"):
        if data.get(k):
            bits.append(f"{k}: {data.get(k)}")
    try:
        create_notification(
            recipient_type=ADMIN_RECIPIENT,
            title=title,
            body=" · ".join(bits),
            event_type=f"radius:{event}",
            status=status,
            source_type="radius_webhook",
            action_url=(f"/admin/users/{bid}/profile" if bid else ""),
        )
    except Exception:
        pass


@app.route("/api/radius/webhook", methods=["POST"])
def radius_webhook_receiver():
    import hashlib
    import hmac
    import os
    secret = (os.getenv("HOBERADIUS_WEBHOOK_SECRET") or "").strip()
    if not secret:
        return jsonify({"ok": False, "error": "webhook secret not configured"}), 503
    raw = request.get_data() or b""
    sig = request.headers.get("X-HobeRadius-Signature", "") or ""
    expected = "sha256=" + hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
    if not (sig.startswith("sha256=") and hmac.compare_digest(expected, sig)):
        return jsonify({"ok": False, "error": "invalid signature"}), 401
    try:
        payload = _json.loads(raw.decode("utf-8") or "{}")
    except Exception:
        return jsonify({"ok": False, "error": "invalid json"}), 400
    event = str(payload.get("event") or "").strip()
    data = payload.get("data") or {}
    if not isinstance(data, dict):
        data = {}
    try:
        _handle_radius_webhook_event(event, data, payload)
    except Exception:
        pass
    return jsonify({"ok": True, "event": event})


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

    # التقط لقطة حيّة طازجة الآن (عبر الريديوس الحديث) كي يعكس التقرير أحدث
    # استهلاك بدل الاعتماد على آخر تشغيل لعامل اللقطات — أفضل جهد، لا يُفشل العرض.
    try:
        _take_snapshot_for_beneficiary(beneficiary)
    except Exception:
        pass

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
