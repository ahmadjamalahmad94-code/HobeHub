# Auto-split from app/legacy.py lines 1857-2035. Loaded by app.legacy.
from app.utils.text import clean_csv_value, full_name_from_parts, normalize_phone, normalize_search_ar, split_full_name
from app.utils.arabic_terms import arabize_audit_text, arabize_text


def as_local_dt(value):
    if not value:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except Exception:
            return None
    try:
        if getattr(value, "tzinfo", None) is None:
            value = value.replace(tzinfo=ZoneInfo("UTC"))
        # المنطقة الزمنيّة المضبوطة (تتراجع إلى APP_TZ إن لزم)
        _tz = app_timezone() if "app_timezone" in globals() else APP_TZ
        return value.astimezone(_tz)
    except Exception:
        return None


def format_dt_short(value):
    if not value:
        return ""
    localized = as_local_dt(value)
    if localized is not None:
        return localized.strftime('%Y-%m-%d %H:%M')
    text = str(value).replace('T', ' ')
    return text[:16] if len(text) >= 16 else text

def format_dt_compact(value):
    if not value:
        return ""
    localized = as_local_dt(value)
    if localized is not None:
        return localized.strftime('%Y-%m-%d %H:%M')
    text = str(value).replace('T', ' ')
    return text[:16] if len(text) >= 16 else text

def action_type_label(action_type=None):
    return {
        'login': 'تسجيل دخول',
        'logout': 'تسجيل خروج',
        'add': 'إضافة',
        'edit': 'تعديل',
        'delete': 'حذف',
        'bulk_delete': 'حذف جماعي',
        'import': 'استيراد',
        'usage_counter': 'إضافة بطاقة',
        'reset_weekly_usage': 'تجديد البطاقات',
        'power_timer_start': 'تشغيل المؤقت',
        'power_timer_pause': 'إيقاف مؤقت للمؤقت',
        'power_timer_resume': 'استئناف المؤقت',
        'power_timer_stop': 'إيقاف المؤقت',
        'export': 'تصدير',
        'backup': 'نسخة احتياطية',
        'archive_logs': 'أرشفة سجل البطاقات',
        'restore_archive': 'استرجاع من الأرشيف',
        'clear_archive': 'تنظيف الأرشيف',
        'clear_usage_logs': 'تنظيف سجل البطاقات',
        'export_archive': 'تصدير الأرشيف',
        'create': 'إنشاء',
        'update': 'تحديث',
        'approve': 'اعتماد',
        'sync_radius': 'مزامنة مع نظام المصادقة',
        'convert_access_mode': 'تغيير طريقة الوصول',
        'convert_access': 'تغيير طريقة الوصول',
        'portal_move_in': 'إضافة إلى حسابات البوابة',
        'set_tier': 'تغيير صلاحية البطاقات',
        'set_verification': 'تعديل التوثيق',
        'portal_reset': 'تصفير حساب البوابة',
        'portal_view_credentials': 'عرض بيانات دخول البوابة',
        'portal_set_credentials': 'تعديل بيانات دخول البوابة',
        'portal_account_create': 'إنشاء حساب بوابة',
        'portal_account_update': 'تعديل حساب بوابة',
        'portal_account_delete': 'حذف حساب بوابة',
        'portal_delete': 'حذف حساب بوابة',
        'manage_portal_account': 'إدارة حساب البوابة',
        'quick_edit_full': 'تعديل سريع شامل',
        'type_change': 'تغيير نوع المشترك',
        'admin_issue_card': 'إصدار بطاقة',
        'admin_issue_card_manual': 'إصدار بطاقة يدويًا',
        'issue_card': 'إصدار بطاقة',
        'import_manual_cards': 'استيراد بطاقات يدوية',
        'user_type_card_rules_save': 'تحديث قواعد البطاقات حسب النوع',
        'edit_quota_policy': 'تعديل سياسة حصص البطاقات',
        'delete_quota_policy': 'حذف سياسة حصص البطاقات',
        'delete_card_category': 'حذف فئة بطاقات',
        'quota_group_create': 'إنشاء مجموعة سياسات',
        'quota_group_member_add': 'إضافة عضو لمجموعة سياسات',
        'user_message_add': 'إضافة ملاحظة للمشترك',
        'user_message_delete': 'حذف ملاحظة من المشترك',
        'attachment_upload': 'رفع مرفق',
        'attachment_delete': 'حذف مرفق',
        'api_test_run': 'فحص واجهة الربط',
        'test_advradius_app_api_failed': 'فشل فحص واجهة الربط',
        'add_ajax': 'إضافة سريعة',
    }.get(clean_csv_value(action_type), arabize_audit_text(safe(action_type or '')))


def target_type_label(target_type=None):
    return {
        'beneficiary': 'مستفيد',
        'account': 'حساب',
        'power_timer': 'مؤقت الكهرباء',
    }.get(clean_csv_value(target_type), arabize_audit_text(safe(target_type or '')))


def permission_label(permission_name=None):
    key = clean_csv_value(permission_name)
    return PERMISSION_LABELS.get(key, safe(permission_name or ''))


def clean_csv_value(v):
    if v is None:
        return ""
    t = str(v).strip()
    if t.lower() in ("nan", "none", "null"):
        return ""
    return t


def normalize_phone(phone):
    text = clean_csv_value(phone)
    if text.endswith(".0"):
        text = text[:-2]
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) == 9 and not digits.startswith("0"):
        digits = "0" + digits
    return digits


def normalize_search_ar(text):
    text = clean_csv_value(text)
    repl = {
        "أ": "ا", "إ": "ا", "آ": "ا", "ى": "ي", "ة": "ه", "ؤ": "و", "ئ": "ي",
    }
    for old, new in repl.items():
        text = text.replace(old, new)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def split_full_name(name):
    parts = clean_csv_value(name).split()
    parts += [""] * (4 - len(parts))
    first = parts[0] if len(parts) > 0 else ""
    second = parts[1] if len(parts) > 1 else ""
    third = parts[2] if len(parts) > 2 else ""
    fourth = " ".join(parts[3:]).strip() if len(parts) > 3 else ""
    return first, second, third, fourth


def full_name_from_parts(first, second, third, fourth):
    return " ".join([x.strip() for x in [first, second, third, fourth] if clean_csv_value(x)]).strip()


# Keep legacy globals wired to the extracted utility module even while this
# compatibility part still carries the old definitions during migration.
from app.utils import text as _text_helpers

clean_csv_value = _text_helpers.clean_csv_value
normalize_phone = _text_helpers.normalize_phone
normalize_search_ar = _text_helpers.normalize_search_ar
split_full_name = _text_helpers.split_full_name
full_name_from_parts = _text_helpers.full_name_from_parts
