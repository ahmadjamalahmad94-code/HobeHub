# 48ai_unified_login.py
# تسجيل دخول المشتركين فقط — /login مقيّد للمشتركين (beneficiaries) حصراً
# المسارات النشطة:
#   /login                    → صفحة دخول المشتركين فقط
#   /login/check              → JSON يتحقق من وجود المشترك (لا يبحث في المدراء)
#   /login/submit             → JSON يتحقق من كلمة مرور المشترك فقط
#   /login/activate           → JSON تفعيل (كود + كلمة مرور جديدة)
#   /x9k2p7-mgmt/sign-in      → يحوّل لبوابة الإدارة الفاخرة (لا يعالج دخول هنا)
# المدراء: يجب عليهم استخدام /h0be-vault-9k2x7p/master-gateway حصراً

import hashlib
import logging
from flask import jsonify, render_template, request, redirect, session, url_for

_log = logging.getLogger("hobehub.unified_login")

# مسار الإدارة الخفي — لا تنشره في أي صفحة عامة
_ADMIN_SECRET_PATH = "/x9k2p7-mgmt/sign-in"


def _sha256(s):
    return hashlib.sha256((s or "").encode("utf-8")).hexdigest()


def _normalize_identifier(raw):
    s = (raw or "").strip()
    if not s:
        return s
    digits_only = "".join(c for c in s if c.isdigit())
    if len(digits_only) >= 8 and len(digits_only) == len(s.replace(" ", "").replace("-", "")):
        return digits_only
    return s


# ────────────────────────────────────────────────────────────────
# نحتفظ بالـ view القديم لدخول الإدارة قبل أي استبدال
# ────────────────────────────────────────────────────────────────
_old_admin_login = app.view_functions.get("login")


def _unified_login_view():
    if session.get("account_id"):
        return redirect(url_for("dashboard"))
    if session.get("portal_type") == "beneficiary" and session.get("beneficiary_id"):
        return redirect(url_for("user_dashboard"))
    return render_template("auth/unified_login.html")


# المسار الخفي القديم → يحوّل لبوابة الإدارة الفاخرة مباشرة (لا يعرض unified_login)
def _hidden_admin_login_view():
    if session.get("account_id"):
        try:
            return redirect(url_for("dashboard"))
        except Exception:
            return redirect("/admin/dashboard")
    # حوّل للبوابة الفاخرة الجديدة
    try:
        return redirect(url_for("master_admin_portal"))
    except Exception:
        return redirect("/h0be-vault-9k2x7p/master-gateway")


app.add_url_rule(
    _ADMIN_SECRET_PATH,
    endpoint="hidden_admin_login",
    view_func=_hidden_admin_login_view,
    methods=["GET"],
)


# ────────────────────────────────────────────────────────────────
# Before-request handler يفرض الفورم الموحّد لكل صفحات الدخول/الخروج
# هذا أقوى من تعديل view_functions لأنه يعترض الطلب قبل الـ dispatcher
# ────────────────────────────────────────────────────────────────
_LEGACY_LOGIN_PATHS = ("/user/login", "/card/login")
_LEGACY_LOGOUT_PATHS = ("/user/logout", "/card/logout")


@app.before_request
def _funnel_all_login_paths_to_unified():
    try:
        p = request.path or ""
        m = request.method or "GET"

        # /login GET → الفورم الموحّد مباشرة (يتجاوز أي view function أخرى)
        if p == "/login" and m == "GET":
            if session.get("account_id"):
                return redirect(url_for("dashboard"))
            if session.get("portal_type") == "beneficiary" and session.get("beneficiary_id"):
                return redirect(url_for("user_dashboard"))
            return render_template("auth/unified_login.html")

        # الدخول القديم → /login الموحّد
        if p in _LEGACY_LOGIN_PATHS:
            if session.get("portal_type") == "beneficiary" and session.get("beneficiary_id"):
                return redirect(url_for("user_dashboard"))
            return redirect("/login")

        # الخروج القديم → امسح الجلسة وارجع للفورم الموحّد
        if p in _LEGACY_LOGOUT_PATHS:
            try:
                if p == "/card/logout":
                    log_action(
                        "beneficiary_logout",
                        "beneficiary_portal_account",
                        session.get("beneficiary_portal_account_id"),
                        f"Card portal logout (unified) for beneficiary {session.get('beneficiary_id')}",
                    )
            except Exception:
                pass
            try:
                session.clear()
            except Exception:
                pass
            return redirect("/login")
    except Exception:
        pass
    return None


# ────────────────────────────────────────────────────────────────
# POST /login/check — يستقبل username/phone ويرجع حالة المستخدم
# ────────────────────────────────────────────────────────────────
@app.route("/login/check", methods=["POST"])
def login_check():
    """يتحقق من هوية المشترك فقط — المدراء لا يُقبلون هنا."""
    raw = request.form.get("identifier") or request.form.get("username") or ""
    ident = _normalize_identifier(raw)
    if not ident:
        return jsonify({"ok": False, "message": "أدخل رقم الجوال أو اسم المستخدم."}), 400

    try:
        from app.legacy import normalize_portal_username
        norm_user = normalize_portal_username(ident)
    except Exception:
        norm_user = ident
    portal = query_one(
        """
        SELECT pa.*, b.full_name, b.phone, b.user_type
        FROM beneficiary_portal_accounts pa
        JOIN beneficiaries b ON b.id = pa.beneficiary_id
        WHERE (pa.username=%s OR b.phone=%s)
          AND COALESCE(pa.portal_membership_active, FALSE)=TRUE
        LIMIT 1
        """,
        [norm_user, ident],
    )
    if portal:
        access_state = (portal.get("portal_access_state") or "active").strip().lower()
        if access_state == "disabled" or not portal.get("is_active"):
            return jsonify({"ok": False, "message": "حسابك معطل. يرجى مراجعة الإدارة."}), 403
        if portal.get("must_set_password"):
            return jsonify({
                "ok": True,
                "type": "beneficiary",
                "state": "reset",
                "label": portal.get("full_name") or portal.get("username"),
                "username": portal.get("username"),
                "next": "activation_code",
            })
        if not portal.get("is_active"):
            return jsonify({"ok": False, "message": "حساب البوابة معطّل. تواصل مع الإدارة."}), 403
        return jsonify({
            "ok": True,
            "type": "beneficiary",
            "state": "frozen" if access_state == "frozen" else "active",
            "label": portal.get("full_name") or portal.get("username"),
            "username": portal.get("username"),
            "next": "password",
            "message": "حسابك مجمّد مؤقتًا. يمكنك الدخول لتحديث ملفك الشخصي." if access_state == "frozen" else "",
        })

    try:
        ben = query_one(
            "SELECT id, full_name, phone, user_type FROM beneficiaries WHERE phone=%s LIMIT 1",
            [ident],
        )
    except Exception:
        ben = None
    if ben:
        return jsonify({
            "ok": True,
            "type": "beneficiary",
            "state": "no_account",
            "label": ben.get("full_name") or ben.get("phone"),
            "next": "request_activation",
            "message": "لا تملك حساب بوابة حالياً. راجع الإدارة لتفعيل حسابك.",
        })

    return jsonify({
        "ok": True,
        "state": "unknown",
        "next": "not_found",
        "message": "لم نجد هذا الرقم. تحقّق من الإدخال أو سجّل اشتراك جديد.",
    })


# ────────────────────────────────────────────────────────────────
# POST /login/submit — كلمة المرور
# ────────────────────────────────────────────────────────────────
@app.route("/login/submit", methods=["POST"])
def login_submit():
    """يتحقق من كلمة مرور المشترك فقط — المدراء لا يُقبلون هنا."""
    raw = request.form.get("identifier") or request.form.get("username") or ""
    ident = _normalize_identifier(raw)
    password = (request.form.get("password") or "").strip()
    if not ident or not password:
        return jsonify({"ok": False, "message": "أدخل بياناتك كاملة."}), 400

    try:
        from app.legacy import normalize_portal_username
        norm_user = normalize_portal_username(ident)
    except Exception:
        norm_user = ident
    portal = query_one(
        """
        SELECT pa.*, b.full_name, b.phone
        FROM beneficiary_portal_accounts pa
        JOIN beneficiaries b ON b.id = pa.beneficiary_id
        WHERE (pa.username=%s OR b.phone=%s)
          AND COALESCE(pa.portal_membership_active, FALSE)=TRUE
        LIMIT 1
        """,
        [norm_user, ident],
    )
    if not portal:
        return jsonify({"ok": False, "message": "لا تملك حساب بوابة حالياً. راجع الإدارة لتفعيل حسابك."}), 404
    access_state = (portal.get("portal_access_state") or "active").strip().lower()
    if access_state == "disabled" or not portal.get("is_active"):
        return jsonify({"ok": False, "message": "حسابك معطل. يرجى مراجعة الإدارة."}), 403
    if portal_account_is_locked(portal):
        return jsonify({"ok": False, "message": "تم إيقاف المحاولة مؤقتًا. حاول لاحقًا."}), 429
    if portal.get("must_set_password"):
        return jsonify({
            "ok": False,
            "state": "reset",
            "message": "حسابك مصفّر — أدخل كود التفعيل أولاً.",
        }), 403
    if verify_portal_password(portal.get("password_hash"), password):
        finalize_beneficiary_portal_login(portal)
        log_action("beneficiary_login", "beneficiary_portal_account", portal["id"], "تسجيل دخول مشترك (موحد)")
        redirect_target = url_for("user_profile_page") if access_state == "frozen" else url_for("user_dashboard")
        return jsonify({"ok": True, "redirect": redirect_target, "label": portal.get("full_name") or portal.get("username"), "state": access_state})
    register_portal_failed_attempt(portal["id"])
    return jsonify({"ok": False, "message": "كلمة المرور غير صحيحة."}), 401


# ────────────────────────────────────────────────────────────────
# POST /login/activate — كود التفعيل + كلمة مرور جديدة + تسجيل دخول تلقائي
# ────────────────────────────────────────────────────────────────
@app.route("/login/activate", methods=["POST"])
def login_activate():
    raw = request.form.get("identifier") or request.form.get("username") or ""
    ident = _normalize_identifier(raw)
    code = (request.form.get("activation_code") or "").strip()
    new_password = (request.form.get("new_password") or "").strip()
    if not ident or not code or not new_password:
        return jsonify({"ok": False, "message": "أدخل البيانات كاملة."}), 400
    if len(new_password) < 6:
        return jsonify({"ok": False, "message": "كلمة المرور قصيرة جداً (6 أحرف على الأقل)."}), 400

    try:
        from app.legacy import normalize_portal_username
        norm_user = normalize_portal_username(ident)
    except Exception:
        norm_user = ident
    portal = query_one(
        """
        SELECT pa.*, b.full_name
        FROM beneficiary_portal_accounts pa
        JOIN beneficiaries b ON b.id = pa.beneficiary_id
        WHERE (pa.username=%s OR b.phone=%s)
          AND COALESCE(pa.portal_membership_active, FALSE)=TRUE
        LIMIT 1
        """,
        [norm_user, ident],
    )
    if not portal:
        return jsonify({"ok": False, "message": "لا تملك حساب بوابة حالياً. راجع الإدارة لتفعيل حسابك."}), 404
    access_state = (portal.get("portal_access_state") or "active").strip().lower()
    if access_state == "disabled" or not portal.get("is_active"):
        return jsonify({"ok": False, "message": "حسابك معطل. يرجى مراجعة الإدارة."}), 403
    if not portal.get("must_set_password"):
        return jsonify({"ok": False, "message": "هذا الحساب غير مصفّر — استخدم كلمة المرور المعتادة."}), 400

    expected = portal.get("activation_code_hash")
    if not expected or _sha256(code) != expected:
        log_action("portal_activation_bad_code", "beneficiary_portal_account", portal["id"], "")
        return jsonify({"ok": False, "message": "رمز التفعيل غير صحيح."}), 401

    from datetime import datetime
    try:
        exp = portal.get("activation_code_expires_at")
        if exp:
            try:
                expiry = exp if hasattr(exp, "year") else datetime.fromisoformat(str(exp).replace(" ", "T"))
                if expiry < datetime.now():
                    return jsonify({"ok": False, "message": "انتهت صلاحية رمز التفعيل. اطلب رمزاً جديداً."}), 410
            except Exception:
                pass
    except Exception:
        pass

    # ⚡ إصلاح: عند التفعيل الناجح يجب ضبط is_active=TRUE
    # كان يظل FALSE (لأن المدير ينشئ الحساب بحالة reset)، فيظهر "معطّل" بعد التفعيل.
    execute_sql(
        """
        UPDATE beneficiary_portal_accounts SET
            password_hash=%s, password_plain=%s,
            is_active=TRUE,
            must_set_password=FALSE,
            activation_code_hash=NULL, activation_code_expires_at=NULL,
            activated_at=CURRENT_TIMESTAMP, failed_login_attempts=0, locked_until=NULL,
            updated_at=CURRENT_TIMESTAMP
        WHERE id=%s
        """,
        [_sha256(new_password), new_password, portal["id"]],
    )
    log_action("portal_activation_success", "beneficiary_portal_account", portal["id"], "تفعيل + اختيار كلمة مرور جديدة")

    finalize_beneficiary_portal_login(portal)
    return jsonify({"ok": True, "redirect": url_for("user_dashboard"), "message": "تم تفعيل حسابك وتسجيل الدخول."})


# ────────────────────────────────────────────────────────────────
# POST /login/request-activation-code — خدمة ذاتيّة من بوّابة المشترك:
#   المشترك (بلا حساب بوابة أو حسابه غير مفعّل) يطلب رمز التفعيل بنفسه؛
#   نفعّل/ننشئ الحساب ونرسل الرمز عبر SMS للرقم المسجّل. لا نُرجع الرمز أبدًا.
# ────────────────────────────────────────────────────────────────
_ACTIVATION_RESEND_COOLDOWN_SEC = 120


def _parse_naive_dt(ts):
    """يحوّل طابعًا زمنيًّا (datetime أو نصّ) إلى datetime بلا منطقة زمنيّة."""
    if not ts:
        return None
    try:
        from datetime import datetime as _dt
        if isinstance(ts, str):
            ts = _dt.fromisoformat(ts.replace("Z", "").replace("T", " ").split(".")[0].strip())
        if getattr(ts, "tzinfo", None) is not None:
            ts = ts.replace(tzinfo=None)
        return ts
    except Exception:
        return None


def _seconds_since_db(last_ts):
    """ثوانٍ بين آخر إرسال وساعة قاعدة البيانات نفسها (تفادي انزياح UTC/محلّي).
    يُرجع None إذا تعذّر الحساب."""
    last = _parse_naive_dt(last_ts)
    if last is None:
        return None
    try:
        row = query_one("SELECT CURRENT_TIMESTAMP AS db_now")
        db_now = _parse_naive_dt((row or {}).get("db_now"))
        if db_now is None:
            return None
        return (db_now - last).total_seconds()
    except Exception:
        return None


@app.route("/login/request-activation-code", methods=["POST"])
def login_request_activation_code():
    raw = request.form.get("identifier") or request.form.get("username") or ""
    ident = _normalize_identifier(raw)
    if not ident:
        return jsonify({"ok": False, "message": "أدخل رقم الجوال."}), 400
    try:
        from app.legacy import normalize_portal_username
        norm_user = normalize_portal_username(ident)
    except Exception:
        norm_user = ident

    _ben_cols = ("user_type", "university_internet_method", "freelancer_internet_method")
    portal = query_one(
        """
        SELECT pa.*, b.full_name, b.phone, b.id AS b_id,
               b.user_type, b.university_internet_method, b.freelancer_internet_method
        FROM beneficiary_portal_accounts pa
        JOIN beneficiaries b ON b.id = pa.beneficiary_id
        WHERE pa.username=%s OR b.phone=%s
        LIMIT 1
        """,
        [norm_user, ident],
    )

    # ─── صفّ المستفيد لفحوص السياسة (قبل أي تعديل) ───
    if portal:
        ben_row = portal
        check_bid = int(portal.get("b_id") or portal.get("beneficiary_id") or 0)
    else:
        ben_row = query_one(
            "SELECT id, full_name, phone, user_type, university_internet_method, "
            "freelancer_internet_method FROM beneficiaries WHERE phone=%s LIMIT 1",
            [ident],
        )
        if not ben_row:
            return jsonify({"ok": False, "message": "لم نجد هذا الرقم لدينا. تحقّق من الإدخال أو راجع الإدارة."}), 404
        check_bid = int(ben_row["id"])

    _sms_cfg = _get_sms_settings()
    # سياسة (١): التفعيل الذاتيّ متاح لمستخدمي البطاقات فقط (قابل للتغيير من الإعدادات)
    if int(_sms_cfg.get("activation_cards_only") or 0):
        try:
            from app.dashboard.services import get_beneficiary_access_mode
            _mode = get_beneficiary_access_mode(ben_row)
        except Exception:
            _mode = "cards"
        if _mode != "cards":
            return jsonify({"ok": False, "message": "التفعيل الذاتيّ متاح حاليًّا لمستخدمي البطاقات فقط. يرجى مراجعة الإدارة."}), 403
    # سياسة (٢): الحدّ الأقصى لرسائل التفعيل لكل مشترك (0 = بلا حدّ)
    _max = int(_sms_cfg.get("activation_max_sends") or 0)
    if _max > 0 and count_activation_sms_sent(beneficiary_id=check_bid) >= _max:
        return jsonify({"ok": False, "message": f"بلغتَ الحدّ الأقصى المسموح لرسائل التفعيل ({_max}). يرجى مراجعة الإدارة."}), 429

    username = norm_user or (ben_row.get("phone") or ident)
    if portal:
        access_state = (portal.get("portal_access_state") or "active").strip().lower()
        if access_state == "disabled":
            return jsonify({"ok": False, "message": "حسابك معطّل. يرجى مراجعة الإدارة."}), 403
        # حساب مفعّل بكلمة مرور بالفعل — لا نسمح بتصفيره من العلن
        if portal.get("password_hash") and not portal.get("must_set_password"):
            return jsonify({"ok": False, "message": "حسابك مفعّل بالفعل — سجّل الدخول بكلمة المرور."}), 409
        # مهلة إعادة الإرسال
        elapsed = _seconds_since_db(portal.get("last_activation_sent_at"))
        if elapsed is not None and 0 <= elapsed < _ACTIVATION_RESEND_COOLDOWN_SEC:
            wait = int(_ACTIVATION_RESEND_COOLDOWN_SEC - elapsed)
            return jsonify({"ok": False, "message": f"أرسلنا رمزًا مؤخرًا. انتظر {wait} ثانية ثم أعد المحاولة."}), 429
        account_id = portal["id"]
        bid = check_bid
        phone = portal.get("phone") or ident
        execute_sql(
            "UPDATE beneficiary_portal_accounts SET is_active=TRUE, portal_membership_active=TRUE, "
            "portal_access_state='active', updated_at=CURRENT_TIMESTAMP WHERE id=%s",
            [account_id],
        )
    else:
        bid = check_bid
        phone = ben_row.get("phone") or ident
        dup = query_one("SELECT id FROM beneficiary_portal_accounts WHERE username=%s", [username])
        if dup:
            account_id = dup["id"]
            execute_sql(
                "UPDATE beneficiary_portal_accounts SET beneficiary_id=%s, is_active=TRUE, "
                "portal_membership_active=TRUE, portal_access_state='active', updated_at=CURRENT_TIMESTAMP WHERE id=%s",
                [bid, account_id],
            )
        else:
            row = execute_sql(
                "INSERT INTO beneficiary_portal_accounts "
                "(beneficiary_id, username, password_hash, is_active, portal_membership_active, "
                " portal_access_state, must_set_password) "
                "VALUES (%s,%s,'',TRUE,TRUE,'active',TRUE) RETURNING id",
                [bid, username], fetchone=True,
            )
            account_id = (row or {}).get("id")

    if not account_id:
        return jsonify({"ok": False, "message": "تعذّر تجهيز الحساب. حاول لاحقًا."}), 500

    code = issue_activation_code_for_portal_account(account_id)

    sms = {"ok": False, "configured": False, "message": ""}
    try:
        sms = send_sms(
            phone,
            f"رمز تفعيل حساب البوابة الخاص بك: {code} — صالح ٧٢ ساعة.",
            service_code="portal_activation_code", beneficiary_id=bid,
        ) or sms
    except Exception:
        pass
    log_action("portal_self_request_code", "beneficiary_portal_account", account_id,
               f"طلب ذاتيّ لرمز التفعيل (جوال {phone}) — SMS={'sent' if sms.get('ok') else 'no'}")

    if sms.get("ok"):
        return jsonify({
            "ok": True, "state": "reset", "next": "activation_code",
            "username": (portal.get("username") if portal else username),
            "message": "أرسلنا رمز التفعيل عبر رسالة نصّيّة إلى رقمك. أدخله ثمّ اختر كلمة المرور.",
        })
    if not sms.get("configured"):
        return jsonify({"ok": False,
                        "message": "خدمة الرسائل غير مفعّلة حاليًا. يرجى مراجعة الإدارة للحصول على الرمز."}), 503
    return jsonify({"ok": False,
                    "message": sms.get("message") or "تعذّر إرسال الرمز الآن. حاول لاحقًا."}), 502
