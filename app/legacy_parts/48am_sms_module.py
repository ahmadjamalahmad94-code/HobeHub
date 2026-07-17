# 48am_sms_module.py
# قسم SMS الكامل — إعدادات API + سجل الرسائل + خدمات قابلة للتفعيل
#
# جداول:
#   sms_settings        — صفّ واحد للإعدادات (api_url, api_key, sender_id, enabled)
#   sms_services        — كل خدمة بإعدادها (service_code, label, enabled)
#   sms_log             — سجل كل رسالة (recipient, content, service_code, status, ts, error)
#
# المسارات:
#   /admin/sms                  → لوحة (KPIs + Quick test + روابط)
#   /admin/sms/settings         → إعدادات API
#   /admin/sms/settings/save    → POST حفظ
#   /admin/sms/services         → تفعيل/إيقاف خدمات SMS
#   /admin/sms/services/toggle  → POST toggle service
#   /admin/sms/log              → سجل الرسائل
#   /admin/sms/send-test        → POST إرسال تجريبي

from flask import render_template, request, redirect, url_for, flash, jsonify
from datetime import datetime


# ────────────────────────────────────────────────────────────────
# الخدمات المعروفة في النظام (قابلة للتوسعة لاحقًا)
# ────────────────────────────────────────────────────────────────
_KNOWN_SERVICES = [
    ("portal_activation_code",   "كود تفعيل البوابة",         "إرسال رمز تفعيل حساب البوابة للمشترك"),
    ("password_reset",           "تصفير كلمة المرور",         "إخطار المشترك بكلمة مرور مؤقتة جديدة"),
    ("card_issued",              "إصدار بطاقة",               "إخطار المشترك ببطاقته الجديدة (يوزر/باسوورد)"),
    ("internet_request_status",  "حالة طلب الإنترنت",        "إخطار المشترك بقبول/رفض طلب الإنترنت"),
    ("account_status_changed",   "تغيير حالة الحساب",         "إخطار عند تفعيل/إيقاف/تحويل وضع الحساب"),
    ("welcome_message",          "رسالة ترحيب",              "ترحيب بالمشتركين الجدد عند إضافتهم"),
    ("usage_quota_warning",      "تنبيه استهلاك",             "تنبيه قرب نفاد الحصة اليومية/الأسبوعية"),
    ("admin_notification",       "إخطار يدوي للإدارة",        "إرسال رسالة يدوية لمشترك من الإدارة"),
]


# ────────────────────────────────────────────────────────────────
# Schema bootstrap
# ────────────────────────────────────────────────────────────────
def _ensure_sms_schema():
    is_sql = is_sqlite_database_url()
    try:
        # sms_settings: صفّ واحد (id=1)
        if is_sql:
            execute_sql("""
                CREATE TABLE IF NOT EXISTS sms_settings (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    enabled      INTEGER NOT NULL DEFAULT 0,
                    api_url      TEXT NOT NULL DEFAULT '',
                    api_key      TEXT NOT NULL DEFAULT '',
                    sender_id    TEXT NOT NULL DEFAULT '',
                    method       TEXT NOT NULL DEFAULT 'POST',
                    body_template TEXT NOT NULL DEFAULT '{"to":"{{phone}}","text":"{{text}}"}',
                    updated_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
        else:
            execute_sql("""
                CREATE TABLE IF NOT EXISTS sms_settings (
                    id           SERIAL PRIMARY KEY,
                    enabled      SMALLINT NOT NULL DEFAULT 0,
                    api_url      TEXT NOT NULL DEFAULT '',
                    api_key      TEXT NOT NULL DEFAULT '',
                    sender_id    TEXT NOT NULL DEFAULT '',
                    method       TEXT NOT NULL DEFAULT 'POST',
                    body_template TEXT NOT NULL DEFAULT '{"to":"{{phone}}","text":"{{text}}"}',
                    updated_at   TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
        # seed الصفّ الافتراضي
        existing = query_one("SELECT id FROM sms_settings WHERE id=1")
        if not existing:
            execute_sql("INSERT INTO sms_settings (id, enabled) VALUES (1, 0)")

        # هجرة: أعمدة مزوّد TweetSMS المبسّط (اسم مستخدم/كلمة مرور/المزوّد)
        for _col in ("provider", "sms_username", "sms_password"):
            try:
                execute_sql(f"ALTER TABLE sms_settings ADD COLUMN {_col} TEXT NOT NULL DEFAULT ''")
            except Exception:
                pass  # العمود موجود مسبقًا
        # هجرة: ضوابط التفعيل الذاتيّ (حدّ أقصى للرسائل + قصر على مستخدمي البطاقات)
        for _col, _default in (("activation_max_sends", 0), ("activation_cards_only", 1)):
            try:
                execute_sql(f"ALTER TABLE sms_settings ADD COLUMN {_col} INTEGER NOT NULL DEFAULT {_default}")
            except Exception:
                pass

        # sms_services
        if is_sql:
            execute_sql("""
                CREATE TABLE IF NOT EXISTS sms_services (
                    service_code TEXT PRIMARY KEY,
                    label        TEXT NOT NULL,
                    description  TEXT NOT NULL DEFAULT '',
                    enabled      INTEGER NOT NULL DEFAULT 0,
                    updated_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
        else:
            execute_sql("""
                CREATE TABLE IF NOT EXISTS sms_services (
                    service_code TEXT PRIMARY KEY,
                    label        TEXT NOT NULL,
                    description  TEXT NOT NULL DEFAULT '',
                    enabled      SMALLINT NOT NULL DEFAULT 0,
                    updated_at   TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
        # seed الخدمات المعروفة
        for code, label, desc in _KNOWN_SERVICES:
            row = query_one("SELECT service_code FROM sms_services WHERE service_code=%s", [code])
            if not row:
                execute_sql(
                    "INSERT INTO sms_services (service_code, label, description, enabled) VALUES (%s,%s,%s,0)",
                    [code, label, desc],
                )

        # sms_log
        if is_sql:
            execute_sql("""
                CREATE TABLE IF NOT EXISTS sms_log (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    recipient_phone TEXT NOT NULL,
                    beneficiary_id  INTEGER,
                    service_code    TEXT NOT NULL DEFAULT '',
                    content         TEXT NOT NULL DEFAULT '',
                    status          TEXT NOT NULL DEFAULT 'pending',
                    error_message   TEXT,
                    sent_by         TEXT,
                    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    delivered_at    TIMESTAMP,
                    read_at         TIMESTAMP
                )
            """)
        else:
            execute_sql("""
                CREATE TABLE IF NOT EXISTS sms_log (
                    id              SERIAL PRIMARY KEY,
                    recipient_phone TEXT NOT NULL,
                    beneficiary_id  INTEGER,
                    service_code    TEXT NOT NULL DEFAULT '',
                    content         TEXT NOT NULL DEFAULT '',
                    status          TEXT NOT NULL DEFAULT 'pending',
                    error_message   TEXT,
                    sent_by         TEXT,
                    created_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    delivered_at    TIMESTAMPTZ,
                    read_at         TIMESTAMPTZ
                )
            """)
    except Exception as e:
        import logging
        logging.getLogger("hobehub.sms").warning("sms schema bootstrap failed: %s", e)


_ensure_sms_schema()


# ────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────
def _get_sms_settings():
    return query_one("SELECT * FROM sms_settings WHERE id=1") or {}


def _is_service_enabled(service_code: str) -> bool:
    row = query_one(
        "SELECT enabled FROM sms_services WHERE service_code=%s",
        [service_code],
    )
    return bool(int((row or {}).get("enabled") or 0))


def sms_log_entry(recipient_phone, content, service_code="manual",
                  beneficiary_id=None, status="pending", error_message=None):
    """تسجيل رسالة في sms_log — يُستدعى من أي خدمة ترسل."""
    try:
        execute_sql(
            """
            INSERT INTO sms_log (recipient_phone, beneficiary_id, service_code,
                                 content, status, error_message, sent_by)
            VALUES (%s,%s,%s,%s,%s,%s,%s)
            """,
            [recipient_phone, beneficiary_id, service_code,
             content, status, error_message, session.get("username") or "system"],
        )
    except Exception:
        pass


_TWEETSMS_URL = "https://www.tweetsms.ps/api.php"
_TWEETSMS_ERRORS = {
    "-100": "بيانات ناقصة (اسم المستخدم/كلمة المرور/الرقم/النص/المرسل).",
    "-110": "اسم المستخدم أو كلمة المرور غير صحيحة.",
    "-113": "الرصيد غير كافٍ لدى TweetSMS.",
    "-115": "اسم المرسل غير مفتوح لحسابك لدى TweetSMS.",
    "-116": "اسم المرسل غير صالح.",
    "-2":   "رقم غير صالح أو دولة غير مدعومة.",
    "-999": "فشل الإرسال لدى مزوّد الرسائل.",
}


def _sms_provider(settings):
    """المزوّد الحاليّ: 'tweetsms' (مبسّط: يوزر/باس/مرسل) أو 'custom' (api_url عامّ).
    التوافق الرجعيّ: لو كان api_url مضبوطًا بلا provider نعتبره custom."""
    p = (settings.get("provider") or "").strip().lower()
    if p:
        return p
    return "custom" if (settings.get("api_url") or "").strip() else "tweetsms"


def _sms_settings_configured(settings):
    """هل المزوّد جاهز للإرسال؟ (بحسب نوعه)."""
    if not int(settings.get("enabled") or 0):
        return False
    if _sms_provider(settings) == "tweetsms":
        return bool((settings.get("sms_username") or "").strip()
                    and (settings.get("sms_password") or "").strip()
                    and (settings.get("sender_id") or "").strip())
    return bool((settings.get("api_url") or "").strip())


def _tweetsms_dispatch(settings, phone, text):
    """يرسل عبر TweetSMS (GET user/pass/sender). مهمّ: TweetSMS يردّ HTTP 200 حتى
    عند الأخطاء، فنحلّل نصّ الردّ: أوّل حقل = رمز النتيجة (1 = نجاح)."""
    user = (settings.get("sms_username") or "").strip()
    pw = (settings.get("sms_password") or "").strip()
    sender = (settings.get("sender_id") or "").strip()
    if not (user and pw and sender):
        return False, "أكمل: اسم المستخدم وكلمة المرور واسم المرسل."
    try:
        import requests as _rq
        params = {"comm": "sendsms", "user": user, "pass": pw,
                  "to": phone, "message": text, "sender": sender}
        r = _rq.get(_TWEETSMS_URL, params=params, timeout=15)
        body = (r.text or "").strip()
        first = (body.splitlines()[0] if body else "").strip()
        code = (first.split(":")[0] if first else "").strip()
        if code == "1":
            return True, None
        if code == "u":
            return False, "حالة الرسالة غير معروفة لدى المزوّد."
        return False, _TWEETSMS_ERRORS.get(code) or (f"ردّ المزوّد: {first[:80]}" if first else f"HTTP {r.status_code}")
    except Exception as e:
        return False, str(e)[:200]


def _sms_http_dispatch(phone, text):
    """يُرسل رسالة واحدة عبر المزوّد المضبوط. يُرجع (ok, error)."""
    settings = _get_sms_settings()
    if _sms_provider(settings) == "tweetsms":
        return _tweetsms_dispatch(settings, phone, text)
    # ── مزوّد مخصّص (api_url + قالب): {{phone}} {{text}} {{api_key}} {{sender}} ──
    api_url = (settings.get("api_url") or "").strip()
    if not api_url:
        return False, "api_url غير مضبوط"
    try:
        import requests as _rq, json as _json
        api_key = settings.get("api_key") or ""
        sender = settings.get("sender_id") or ""
        method = (settings.get("method") or "POST").upper()
        body_tpl = settings.get("body_template") or '{"to":"{{phone}}","text":"{{text}}"}'
        payload = (body_tpl
                   .replace("{{phone}}", phone)
                   .replace("{{text}}", text)
                   .replace("{{api_key}}", api_key)
                   .replace("{{sender}}", sender))
        try:
            payload_obj = _json.loads(payload)
        except Exception:
            payload_obj = payload
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        if method == "GET":
            r = _rq.get(api_url, params=payload_obj if isinstance(payload_obj, dict) else None,
                        headers=headers, timeout=12)
        else:
            r = _rq.post(api_url,
                         json=payload_obj if isinstance(payload_obj, dict) else None,
                         data=None if isinstance(payload_obj, dict) else payload_obj,
                         headers=headers, timeout=12)
        if r.status_code >= 400:
            return False, f"HTTP {r.status_code}: {(r.text or '')[:120]}"
        return True, None
    except Exception as e:
        return False, str(e)[:200]


def send_sms(phone, text, *, service_code="manual", beneficiary_id=None, require_service=True):
    """المرسِل الموحّد للـ SMS: يحترم تفعيل المزوّد وتفعيل الخدمة، ويسجّل في
    sms_log. يُرجع dict {ok, configured, message}. متاح كـ legacy global لبقيّة
    الأقسام (مثل تفعيل حساب البوابة)."""
    phone = (phone or "").strip()
    if not phone:
        return {"ok": False, "configured": True, "message": "لا يوجد رقم جوال مسجّل للمشترك."}
    settings = _get_sms_settings()
    configured = _sms_settings_configured(settings)
    if not configured:
        sms_log_entry(phone, text, service_code, beneficiary_id, status="failed",
                      error_message="مزوّد SMS غير مفعّل/غير مضبوط")
        return {"ok": False, "configured": False,
                "message": "إرسال SMS غير مفعّل بعد — انقل الرمز للمشترك يدويًّا."}
    if require_service and not _is_service_enabled(service_code):
        sms_log_entry(phone, text, service_code, beneficiary_id, status="failed",
                      error_message="الخدمة غير مفعّلة في «خدمات SMS»")
        return {"ok": False, "configured": True,
                "message": "خدمة SMS هذه غير مفعّلة — فعّلها من «رسائل SMS ← الخدمات»."}
    ok, err = _sms_http_dispatch(phone, text)
    sms_log_entry(phone, text, service_code, beneficiary_id,
                  status="sent" if ok else "failed", error_message=err)
    return {"ok": ok, "configured": True,
            "message": (f"أُرسل عبر SMS إلى {phone}." if ok else f"تعذّر إرسال SMS: {err}")}


def count_activation_sms_sent(beneficiary_id=None, phone=None):
    """عدد رسائل رمز التفعيل المُرسَلة بنجاح لمشترك (لفرض الحدّ الأقصى)."""
    try:
        if beneficiary_id:
            row = query_one(
                "SELECT COUNT(*) AS c FROM sms_log WHERE beneficiary_id=%s "
                "AND service_code='portal_activation_code' AND status='sent'",
                [int(beneficiary_id)],
            )
        elif phone:
            row = query_one(
                "SELECT COUNT(*) AS c FROM sms_log WHERE recipient_phone=%s "
                "AND service_code='portal_activation_code' AND status='sent'",
                [phone],
            )
        else:
            return 0
        return int((row or {}).get("c") or 0)
    except Exception:
        return 0


def sms_stats():
    def _c(sql, params=None):
        try:
            row = query_one(sql, params or [])
            return int((row or {}).get("c") or 0)
        except Exception:
            return 0
    return {
        "total":       _c("SELECT COUNT(*) AS c FROM sms_log"),
        "pending":     _c("SELECT COUNT(*) AS c FROM sms_log WHERE status='pending'"),
        "sent":        _c("SELECT COUNT(*) AS c FROM sms_log WHERE status='sent'"),
        "delivered":   _c("SELECT COUNT(*) AS c FROM sms_log WHERE status='delivered'"),
        "failed":      _c("SELECT COUNT(*) AS c FROM sms_log WHERE status='failed'"),
        "today":       _c("SELECT COUNT(*) AS c FROM sms_log WHERE DATE(created_at)=DATE('now')")
                       if is_sqlite_database_url()
                       else _c("SELECT COUNT(*) AS c FROM sms_log WHERE DATE(created_at)=CURRENT_DATE"),
        "services_on": _c("SELECT COUNT(*) AS c FROM sms_services WHERE enabled=1"),
        "services_total": len(_KNOWN_SERVICES),
    }


# ────────────────────────────────────────────────────────────────
# الصفحة الرئيسية / لوحة SMS
# ────────────────────────────────────────────────────────────────
@app.route("/admin/sms", methods=["GET"])
@admin_login_required
def admin_sms_dashboard():
    settings = _get_sms_settings()
    services = query_all("SELECT * FROM sms_services ORDER BY service_code ASC") or []
    recent = query_all(
        "SELECT * FROM sms_log ORDER BY id DESC LIMIT 10"
    ) or []
    return render_template(
        "admin/sms/dashboard.html",
        settings=settings,
        services=services,
        stats=sms_stats(),
        recent=recent,
    )


# ────────────────────────────────────────────────────────────────
# الإعدادات
# ────────────────────────────────────────────────────────────────
@app.route("/admin/sms/settings", methods=["GET"])
@admin_login_required
def admin_sms_settings_page():
    return render_template(
        "admin/sms/settings.html",
        settings=_get_sms_settings(),
    )


@app.route("/admin/sms/settings/save", methods=["POST"])
@admin_login_required
def admin_sms_settings_save():
    cur = _get_sms_settings()
    enabled = 1 if request.form.get("enabled") else 0
    provider = (request.form.get("provider") or "tweetsms").strip().lower()
    if provider not in ("tweetsms", "custom"):
        provider = "tweetsms"
    sender_id = (request.form.get("sender_id") or "").strip()
    sms_username = (request.form.get("sms_username") or "").strip()
    # كلمة المرور: إن تُركت فارغة نُبقي المحفوظة (لا نمسحها)
    sms_password = (request.form.get("sms_password") or "").strip()
    if not sms_password:
        sms_password = cur.get("sms_password") or ""
    # حقول المزوّد المخصّص (تبقى للتوافق)
    api_url = (request.form.get("api_url") or cur.get("api_url") or "").strip()
    api_key = (request.form.get("api_key") or cur.get("api_key") or "").strip()
    method = (request.form.get("method") or cur.get("method") or "POST").strip().upper()
    body_template = (request.form.get("body_template") or cur.get("body_template") or "").strip()
    if method not in ("POST", "GET"):
        method = "POST"
    # ضوابط التفعيل الذاتيّ
    try:
        activation_max_sends = max(int(request.form.get("activation_max_sends") or 0), 0)
    except ValueError:
        activation_max_sends = 0
    activation_cards_only = 1 if request.form.get("activation_cards_only") else 0
    try:
        execute_sql(
            """
            UPDATE sms_settings SET
                enabled=%s, provider=%s, sender_id=%s,
                sms_username=%s, sms_password=%s,
                api_url=%s, api_key=%s, method=%s, body_template=%s,
                activation_max_sends=%s, activation_cards_only=%s,
                updated_at=CURRENT_TIMESTAMP
            WHERE id=1
            """,
            [enabled, provider, sender_id, sms_username, sms_password,
             api_url, api_key, method, body_template,
             activation_max_sends, activation_cards_only],
        )
        log_action("sms_settings_save", "sms_settings", 1, f"تحديث إعدادات SMS ({provider})")
        flash("تم حفظ إعدادات SMS بنجاح.", "success")
    except Exception as e:
        flash(f"تعذّر الحفظ: {e}", "error")
    return redirect(url_for("admin_sms_settings_page"))


@app.route("/admin/sms/check-balance", methods=["POST"])
@admin_login_required
def admin_sms_check_balance():
    """فحص رصيد TweetSMS (chk_balance) — يتحقّق أيضًا من صحّة اسم المستخدم/كلمة المرور."""
    settings = _get_sms_settings()
    if _sms_provider(settings) != "tweetsms":
        return jsonify({"ok": False, "message": "فحص الرصيد متاح لمزوّد TweetSMS فقط."}), 200
    user = (settings.get("sms_username") or "").strip()
    pw = (settings.get("sms_password") or "").strip()
    if not (user and pw):
        return jsonify({"ok": False, "message": "أدخل اسم المستخدم وكلمة المرور واحفظ أوّلًا."}), 200
    try:
        import requests as _rq
        r = _rq.get(_TWEETSMS_URL, params={"comm": "chk_balance", "user": user, "pass": pw}, timeout=15)
        body = (r.text or "").strip()
        first = (body.splitlines()[0] if body else "").strip()
        code = (first.split(":")[0] if first else "").strip()
        if code in _TWEETSMS_ERRORS:
            return jsonify({"ok": False, "message": _TWEETSMS_ERRORS[code]}), 200
        if not first:
            return jsonify({"ok": False, "message": f"ردّ فارغ (HTTP {r.status_code})."}), 200
        return jsonify({"ok": True, "balance": first, "message": f"✅ الاتصال سليم — الرصيد: {first}"})
    except Exception as e:
        return jsonify({"ok": False, "message": f"تعذّر الاتصال: {str(e)[:120]}"}), 200


# ────────────────────────────────────────────────────────────────
# الخدمات
# ────────────────────────────────────────────────────────────────
@app.route("/admin/sms/services", methods=["GET"])
@admin_login_required
def admin_sms_services_page():
    services = query_all("SELECT * FROM sms_services ORDER BY service_code ASC") or []
    return render_template("admin/sms/services.html", services=services)


@app.route("/admin/sms/services/toggle", methods=["POST"])
@admin_login_required
def admin_sms_services_toggle():
    code = (request.form.get("service_code") or "").strip()
    if not code:
        return jsonify({"ok": False, "message": "خدمة غير محددة."}), 400
    row = query_one("SELECT enabled FROM sms_services WHERE service_code=%s", [code])
    if not row:
        return jsonify({"ok": False, "message": "خدمة غير موجودة."}), 404
    new_val = 0 if int(row.get("enabled") or 0) else 1
    execute_sql(
        "UPDATE sms_services SET enabled=%s, updated_at=CURRENT_TIMESTAMP WHERE service_code=%s",
        [new_val, code],
    )
    log_action("sms_service_toggle", "sms_service", None, f"{code} → {'enabled' if new_val else 'disabled'}")
    return jsonify({"ok": True, "enabled": bool(new_val)})


# ────────────────────────────────────────────────────────────────
# سجل الرسائل
# ────────────────────────────────────────────────────────────────
@app.route("/admin/sms/log", methods=["GET"])
@admin_login_required
def admin_sms_log_page():
    q = (request.args.get("q") or "").strip()
    status = (request.args.get("status") or "").strip()
    service = (request.args.get("service") or "").strip()

    sql = "SELECT * FROM sms_log WHERE 1=1"
    params = []
    if q:
        from app.services.smart_search import smart_search_clause

        clause, clause_params = smart_search_clause(
            q,
            text_columns=("content",),
            phone_columns=("recipient_phone",),
            extra_columns=("service_code", "status"),
        )
        if clause:
            sql += " AND " + clause
            params.extend(clause_params)
    if status in ("pending", "sent", "delivered", "failed", "read"):
        sql += " AND status=%s"
        params.append(status)
    if service:
        sql += " AND service_code=%s"
        params.append(service)
    sql += " ORDER BY id DESC LIMIT 500"
    rows = query_all(sql, params) or []

    services = query_all("SELECT service_code, label FROM sms_services ORDER BY label") or []
    stats = sms_stats()

    # ─ AJAX mode: JSON يحتوي tbody HTML + الإحصائيات ─
    if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.args.get("ajax") == "1":
        from flask import render_template_string, jsonify
        tbody_html = render_template_string(
            """{% for r in rows %}<tr>
  <td>#{{ r.id }}</td>
  <td style="font-family:monospace;font-size:12.5px">{{ r.recipient_phone }}</td>
  <td style="font-size:12.5px;max-width:280px;line-height:1.5">{{ r.content }}</td>
  <td style="font-size:11px"><code style="background:#fbfaf7;padding:2px 6px;border-radius:6px">{{ r.service_code }}</code></td>
  <td>{% set s = r.status or 'pending' %}<span class="d-badge {% if s in ['sent','delivered','read'] %}d-badge--success{% elif s == 'failed' %}d-badge--warn{% else %}d-badge--neutral{% endif %}" style="font-size:11px;white-space:nowrap">{{ {'pending':'معلّق','sent':'مرسل','delivered':'واصل','read':'مقروء','failed':'فشل'}.get(s, s) }}</span></td>
  <td style="font-size:11px;color:var(--d-text-muted);white-space:nowrap">{{ r.created_at }}</td>
  <td style="font-size:11px;color:var(--d-text-muted);white-space:nowrap">{{ r.delivered_at or '—' }}</td>
  <td style="font-size:11.5px">{{ r.sent_by or '—' }}</td>
  <td style="font-size:11px;color:#b91c1c;max-width:200px">{{ r.error_message or '' }}</td>
</tr>{% else %}<tr class="no-paginate"><td colspan="9" style="text-align:center;padding:30px;color:var(--d-text-muted)">لا توجد رسائل مطابقة.</td></tr>{% endfor %}""",
            rows=rows,
        )
        return jsonify({"ok": True, "tbody_html": tbody_html, "count": len(rows), "stats": stats})

    return render_template(
        "admin/sms/log.html",
        rows=rows,
        services=services,
        filters={"q": q, "status": status, "service": service},
        stats=stats,
    )


# ────────────────────────────────────────────────────────────────
# إرسال تجريبي
# ────────────────────────────────────────────────────────────────
@app.route("/admin/sms/send-test", methods=["POST"])
@admin_login_required
def admin_sms_send_test():
    phone = (request.form.get("phone") or "").strip()
    text = (request.form.get("text") or "").strip() or "رسالة اختبار من Hobe Hub"
    if not phone:
        flash("أدخل رقم الجوال.", "error")
        return redirect(url_for("admin_sms_dashboard"))
    settings = _get_sms_settings()
    if not int(settings.get("enabled") or 0):
        sms_log_entry(phone, text, "test", status="failed", error_message="SMS مُعطّل في الإعدادات")
        flash("SMS مُعطّل في الإعدادات. فعّله أولاً.", "error")
        return redirect(url_for("admin_sms_dashboard"))
    if not _sms_settings_configured(settings):
        miss = ("اسم المستخدم/كلمة المرور/اسم المرسل" if _sms_provider(settings) == "tweetsms" else "api_url")
        sms_log_entry(phone, text, "test", status="failed", error_message=f"إعداد ناقص: {miss}")
        flash(f"أكمل إعدادات المزوّد أولاً ({miss}).", "error")
        return redirect(url_for("admin_sms_dashboard"))

    # محاولة فعلية للإرسال عبر المرسِل الموحّد (بلا اشتراط تفعيل خدمة — هذا اختبار)
    ok, err = _sms_http_dispatch(phone, text)
    status = "sent" if ok else "failed"
    sms_log_entry(phone, text, "test", status=status, error_message=err)
    if status == "sent":
        flash(f"تم إرسال رسالة الاختبار إلى {phone}.", "success")
    else:
        flash(f"تعذّر إرسال رسالة الاختبار: {err}", "error")
    return redirect(url_for("admin_sms_dashboard"))


# ────────────────────────────────────────────────────────────────
# تحديث حالة رسالة (للاستدعاء من webhook لاحقًا)
# ────────────────────────────────────────────────────────────────
@app.route("/admin/sms/log/<int:msg_id>/mark", methods=["POST"])
@admin_login_required
def admin_sms_log_mark(msg_id):
    new_status = (request.form.get("status") or "").strip()
    if new_status not in ("pending", "sent", "delivered", "failed", "read"):
        return jsonify({"ok": False, "message": "حالة غير صالحة."}), 400
    extra = ""
    if new_status == "delivered":
        extra = ", delivered_at=CURRENT_TIMESTAMP"
    elif new_status == "read":
        extra = ", read_at=CURRENT_TIMESTAMP"
    execute_sql(f"UPDATE sms_log SET status=%s{extra} WHERE id=%s", [new_status, msg_id])
    return jsonify({"ok": True, "status": new_status})
