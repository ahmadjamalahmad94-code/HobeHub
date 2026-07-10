# /admin/radius/settings بالتصميم الجديد — override يستخدم القالب الجديد.
# Path 4: ربط RADIUS قابل للتبديل بالكامل من الصفحة + هوية نسخة (white-label).

from flask import render_template, request, redirect, url_for, flash, session

from app.services.branding import get_branding, save_branding
from app.services.radius_config import resolve_radius_connection
from app.services.secret_box import encrypt_secret
from app.services.radius_client import reset_radius_client
from app.services.radius_client.live import LiveRadiusClient
from app.services.radius_client.apiv1 import ApiV1RadiusClient


def _norm_base_url(value: str) -> str:
    return (value or "").strip().rstrip("/")


def _run_radius_connection_test():
    """اختبار اتصال آمن (قراءة فقط) ضد الهدف المُعدّ حاليًا في قاعدة البيانات."""
    reset_radius_client()  # التقط الهدف الجديد المحفوظ للتو
    cfg = resolve_radius_connection(refresh=True)
    if not cfg.base_url:
        return ("لم يُضبط Base URL بعد — احفظ الرابط أولًا ثم اختبر.", "error")
    # نختبر بالعميل المطابق لنوع الـ API المُعدّ (الحديث /api/v1 أم القديم).
    if (cfg.api_flavor or "app_ad2").lower() == "apiv1":
        client = ApiV1RadiusClient()
    else:
        client = LiveRadiusClient()
    result = client.health_check() if cfg.read_enabled else client.ping()
    if result.get("ok"):
        data = result.get("data") or {}
        version = data.get("version") or data.get("app_version") or data.get("v") or ""
        extra = f" — الإصدار: {version}" if version else ""
        return (f"نجح الاتصال بالهدف المُعدّ ({cfg.base_url}){extra}.", "success")
    return (f"فشل الاتصال: {result.get('error') or 'خطأ غير معروف'}", "error")


def _radius_settings_v2_view():
    """إعدادات RADIUS بالـ unified sidebar — كل معطيات الاتصال قابلة للتحرير."""
    settings_row = get_radius_settings_row()
    test_message = ""
    test_category = "info"

    if request.method == "POST":
        action = clean_csv_value(request.form.get("action", "save")) or "save"

        # ── حفظ هوية النسخة (white-label) ──
        if action == "save_branding":
            brand_name = clean_csv_value(request.form.get("brand_name"))
            tagline = clean_csv_value(request.form.get("tagline"))
            try:
                save_branding(brand_name, tagline)
                log_action("update_app_branding", "app_branding", None, f"brand_name={brand_name}")
            except Exception:
                pass
            flash("تم حفظ هوية النسخة.", "success")
            return redirect(url_for("radius_settings_page"))

        # ── حفظ إعدادات اتصال RADIUS ──
        base_url = _norm_base_url(request.form.get("base_url"))
        admin_username = clean_csv_value(request.form.get("admin_username"))
        service_username = clean_csv_value(request.form.get("service_username"))
        mode = (clean_csv_value(request.form.get("mode")) or "manual").lower()
        if mode not in ("manual", "live"):
            mode = "manual"
        api_flavor = (clean_csv_value(request.form.get("api_flavor")) or "").lower()
        if api_flavor not in ("apiv1", "app_ad2"):
            api_flavor = "apiv1" if "/api/v1" in (base_url or "").lower() else "app_ad2"
        read_enabled = request.form.get("read_enabled") == "1"
        write_enabled = request.form.get("write_enabled") == "1"
        verify_ssl = request.form.get("verify_ssl") == "1"
        api_enabled = request.form.get("api_enabled") == "1"
        master_key_input = (request.form.get("master_api_key") or "").strip()
        service_password_input = (request.form.get("service_password") or "").strip()

        # التحقق من Base URL حسب نوع الـ API المختار (apiv1 -> /api/v1 · app_ad2 -> /app_ad2).
        if base_url:
            if api_flavor == "apiv1" and not base_url.endswith("/api/v1"):
                flash("عند اختيار الـ API الحديث يجب أن ينتهي Base URL بـ /api/v1. لم يُحفظ.", "error")
                return redirect(url_for("radius_settings_page"))
            if api_flavor == "app_ad2" and not base_url.endswith("/app_ad2"):
                flash("عند اختيار الـ API القديم يجب أن ينتهي Base URL بـ /app_ad2 (وليس /app_ad). لم يُحفظ.", "error")
                return redirect(url_for("radius_settings_page"))

        # تحذير: اسم مستخدم الخدمة يفضَّل ألا يكون المالك 'admin'
        if service_username.lower() == "admin":
            flash("تحذير: اسم مستخدم الخدمة هو 'admin' (حساب المالك). يُفضَّل استخدام حساب خدمة فرعي.", "info")

        fields = {
            "base_url": base_url,
            "admin_username": admin_username,
            "service_username": service_username,
            "mode": mode,
            "api_flavor": api_flavor,
            "read_enabled": read_enabled,
            "write_enabled": write_enabled,
            "verify_ssl": verify_ssl,
            "api_enabled": api_enabled,
        }
        # الأسرار: لا تُحفظ إلا إن أُدخلت (فارغ = إبقاء القيمة الحالية). لا نص صريح.
        if master_key_input:
            fields["master_api_key_encrypted"] = encrypt_secret(master_key_input)
        if service_password_input:
            fields["service_password_encrypted"] = encrypt_secret(service_password_input)

        set_clause = ", ".join(f"{k}=%s" for k in fields) + ", updated_at=CURRENT_TIMESTAMP"
        execute_sql(
            f"UPDATE radius_api_settings SET {set_clause} WHERE id=%s",
            list(fields.values()) + [settings_row["id"]],
        )
        try:
            log_action(
                "update_radius_settings",
                "radius_settings",
                settings_row["id"],
                f"base_url={base_url} mode={mode} read={read_enabled} write={write_enabled} api_enabled={api_enabled}",
            )
        except Exception:
            pass

        # صفّر الـ singleton + الكاش كي يلتقط العميل الهدف الجديد فورًا (تبديل بلا نشر)
        reset_radius_client()
        settings_row = get_radius_settings_row()

        if action == "test":
            test_message, test_category = _run_radius_connection_test()
        else:
            flash("تم حفظ إعدادات الاتصال. الأسرار مخزّنة مشفّرة.", "success")
            return redirect(url_for("radius_settings_page"))

    import os as _os
    cfg = resolve_radius_connection(refresh=True)
    env_status = {
        "base": bool(_os.getenv("RADIUS_API_BASE_URL")),
        "master": bool(_os.getenv("RADIUS_API_MASTER_KEY")),
        "user": bool(_os.getenv("RADIUS_API_USERNAME")),
        "password": bool(_os.getenv("RADIUS_API_PASSWORD")),
    }
    env_mode = _os.getenv("RADIUS_MODE", "manual")
    env_ready = _os.getenv("RADIUS_API_READY", "0") in ("1", "true", "True")
    env_writes = _os.getenv("RADIUS_API_WRITES_ENABLED", "0") in ("1", "true", "True")
    branding = get_branding(refresh=True)

    # هل يوجد سرّ محفوظ (لعرض «محفوظ» دون كشف القيمة)
    has_master = bool((settings_row or {}).get("master_api_key_encrypted"))
    has_service_pw = bool((settings_row or {}).get("service_password_encrypted"))

    return render_template(
        "admin/radius_settings/settings.html",
        settings=settings_row,
        cfg=cfg,
        env_status=env_status,
        env_mode=env_mode,
        env_ready=env_ready,
        env_writes=env_writes,
        branding=branding,
        has_master=has_master,
        has_service_pw=has_service_pw,
        test_message=test_message,
        test_category=test_category,
    )


# ─── Override /admin/radius/settings القديم ──────────────
_legacy_radius_settings_view = app.view_functions.get("radius_settings_page")


@login_required
@permission_required("manage_radius_settings")
def _new_radius_settings_router():
    """التصميم الجديد افتراضيًا، القديم عبر ?legacy=1"""
    if request.args.get("legacy") == "1" and _legacy_radius_settings_view is not None:
        return _legacy_radius_settings_view()
    return _radius_settings_v2_view()


if "radius_settings_page" in app.view_functions:
    app.view_functions["radius_settings_page"] = _new_radius_settings_router
