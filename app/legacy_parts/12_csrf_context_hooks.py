# Auto-split from app/legacy.py lines 2348-2439. Loaded by app.legacy.
from app.utils.arabic_terms import arabize_audit_text, arabize_html_fragment, arabize_text

CSRF_SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}
CSRF_FORM_RE = re.compile(
    r"(<form\b(?=[^>]*\bmethod\s*=\s*['\"]?post['\"]?)[^>]*>)",
    re.IGNORECASE,
)


def get_csrf_token() -> str:
    token = session.get("_csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf_token"] = token
    return token


def csrf_token_input() -> str:
    return f'<input type="hidden" name="_csrf_token" value="{escape(get_csrf_token())}">'


def request_csrf_token() -> str:
    return (
        clean_csv_value(request.form.get("_csrf_token"))
        or clean_csv_value(request.headers.get("X-CSRFToken"))
        or clean_csv_value(request.headers.get("X-CSRF-Token"))
    )


@app.before_request
def enforce_csrf_protection():
    if request.method in CSRF_SAFE_METHODS or request.endpoint == "static":
        return None
    # مستقبِل webhook الريديوس موقَّع بـHMAC (خادم↔خادم) — لا CSRF له.
    if request.path == "/api/radius/webhook":
        return None
    expected = session.get("_csrf_token")
    supplied = request_csrf_token()
    if expected and supplied and hmac.compare_digest(expected, supplied):
        return None

    message = "انتهت صلاحية النموذج. حدّث الصفحة وحاول مرة أخرى."
    if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.path.startswith("/api/"):
        return jsonify({"ok": False, "message": message}), 400
    flash(message, "error")
    return redirect(request.referrer or url_for("root"))


@app.after_request
def set_security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    return response


@app.after_request
def inject_csrf_into_html(response):
    if response.mimetype != "text/html" or response.direct_passthrough:
        return response
    try:
        html = response.get_data(as_text=True)
    except (RuntimeError, UnicodeDecodeError):
        logging.getLogger("hobehub.csrf").warning("Unable to read HTML response for CSRF injection", exc_info=True)
        return response
    if "<form" not in html and "</head>" not in html:
        return response

    token = str(escape(get_csrf_token()))
    field = f'<input type="hidden" name="_csrf_token" value="{token}">'
    html = CSRF_FORM_RE.sub(r"\1" + field, html)
    if 'name="csrf-token"' not in html and "</head>" in html:
        meta = (
            f'<meta name="csrf-token" content="{token}">'
            f'<script>window.HOBEHUB_CSRF_TOKEN="{token}";'
            "(function(){if(!window.fetch||window.__hobehubCsrfFetch)return;"
            "window.__hobehubCsrfFetch=true;var originalFetch=window.fetch;"
            "window.fetch=function(input,init){init=init||{};"
            "var method=(init.method||'GET').toUpperCase();"
            "if(['POST','PUT','PATCH','DELETE'].indexOf(method)!==-1&&window.HOBEHUB_CSRF_TOKEN){"
            "var headers=new Headers(init.headers||{});"
            "if(!headers.has('X-CSRFToken'))headers.set('X-CSRFToken',window.HOBEHUB_CSRF_TOKEN);"
            "init.headers=headers;}return originalFetch(input,init);};})();</script>"
        )
        html = html.replace("</head>", meta + "</head>", 1)
    html = arabize_html_fragment(html)
    response.set_data(html)
    return response


ADMIN_GUIDES_PATH = os.path.join(os.path.dirname(__file__), "legacy_guides", "admin_page_guides.json")
with open(ADMIN_GUIDES_PATH, encoding="utf-8") as _admin_guides_file:
    _ADMIN_GUIDE_DATA = json.load(_admin_guides_file)

DEFAULT_ADMIN_GUIDE = _ADMIN_GUIDE_DATA["default"]
ADMIN_PAGE_GUIDES = _ADMIN_GUIDE_DATA["guides"]
ADMIN_GUIDE_PATHS = _ADMIN_GUIDE_DATA["paths"]


def admin_page_guide(path: str | None = None, page_title: str | None = None) -> dict:
    guide_key = ADMIN_GUIDE_PATHS.get(path or request.path)
    guide_source = ADMIN_PAGE_GUIDES.get(guide_key, DEFAULT_ADMIN_GUIDE)
    guide = dict(guide_source)
    guide["steps"] = list(guide.get("steps", []))
    guide["tips"] = list(guide.get("tips", []))
    guide["links"] = list(guide.get("links", []))
    if page_title and guide_source is DEFAULT_ADMIN_GUIDE:
        guide["title"] = page_title
    return guide


def _instance_branding():
    """هوية النسخة (white-label) — الاسم/الوسم من app_branding، الافتراضي Hobe Hub."""
    try:
        from app.services.branding import get_branding
        b = get_branding()
        return b.brand_name, b.tagline
    except Exception:
        return "Hobe Hub", "منصة إدارة وخدمات الإنترنت"


@app.context_processor
def inject_helpers():
    brand_name, brand_tagline = _instance_branding()
    # وقت النظام بالمنطقة المضبوطة — لعرض ساعة الهيدر الحيّة في كل الصفحات
    try:
        _n = now_local()
        _sys_now = _n.strftime("%Y-%m-%d %H:%M:%S")
        _sys_offset = _n.strftime("%z")
    except Exception:
        _sys_now, _sys_offset = "", ""
    try:
        _sys_tz = app_timezone_name()
    except Exception:
        _sys_tz = "Asia/Gaza"
    return {
        "csrf_token": get_csrf_token,
        "csrf_token_input": csrf_token_input,
        "has_permission": has_permission,
        "session": session,
        "admin_page_guide": admin_page_guide,
        "arabize_text": arabize_text,
        "arabize_audit_text": arabize_audit_text,
        "brand_name": brand_name,
        "brand_tagline": brand_tagline,
        "system_now": _sys_now,
        "system_tz": _sys_tz,
        "system_offset": _sys_offset,
    }


app.jinja_env.filters["arabize"] = arabize_text
app.jinja_env.filters["arabize_audit"] = arabize_audit_text
