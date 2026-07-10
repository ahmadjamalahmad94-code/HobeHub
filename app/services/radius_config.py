"""
radius_config — مُحلِّل إعدادات اتصال RADIUS (مصدر الحقيقة = قاعدة البيانات).

قبل هذا المُحلِّل كان ``LiveRadiusClient`` يقرأ الاتصال من متغيرات البيئة فقط،
ما يعني أن تبديل خادم RADIUS يتطلّب إعادة نشر. الآن صف ``radius_api_settings``
هو مصدر الحقيقة، ومتغيرات البيئة احتياطي (fallback) فقط — تمشيًا مع قاعدة
CLAUDE.md رقم 4 «التكاملات مدفوعة بـ env/config». نتيجة ذلك: تبديل RADIUS =
تعديل صفحة /admin/radius/settings بلا إعادة نشر.

سياسة الدمج (DB-first):
- الحقول النصية (base_url / secrets / username): قيمة قاعدة البيانات إن كانت
  غير فارغة، وإلا متغير البيئة.
- الأعلام الثلاثية (mode / read_enabled / write_enabled / verify_ssl): إن كان
  عمود قاعدة البيانات ``NULL`` فهذا يعني «ورِّث من البيئة» (سلوك ما قبل التعديل
  محفوظ تمامًا)؛ وبمجرد أن يحفظ المسؤول الصفحة تصبح قيمة قاعدة البيانات صريحة
  وتتحكّم. هذا يمنع أي تراجع على النشرات الحالية المعتمدة على env.

المُحلِّل مُخزَّن مؤقتًا (cache) ويُصفَّر عبر ``reset_radius_config()`` (يُستدعى
أيضًا من ``reset_radius_client()`` وبعد حفظ الإعدادات) كي يُلتقط التبديل فورًا.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class RadiusConnectionConfig:
    base_url: str
    master_key: str
    service_username: str
    service_password: str
    mode: str            # 'manual' | 'live'
    read_enabled: bool
    write_enabled: bool
    verify_ssl: bool
    api_enabled: bool
    source: str          # 'db' | 'env' — للتشخيص فقط (بلا أسرار)
    api_flavor: str = "app_ad2"  # 'apiv1' (الحديث) | 'app_ad2' (القديم)


_VALID_MODES = {"manual", "live"}
_VALID_FLAVORS = {"apiv1", "app_ad2"}
_TRUE_TOKENS = {"1", "true", "yes", "on", "t"}
_FALSE_TOKENS = {"0", "false", "no", "off", "f", ""}

_cached: RadiusConnectionConfig | None = None


# ─── helpers ──────────────────────────────────────────────────────────
def _env(name: str) -> str:
    return (os.getenv(name, "") or "").strip()


def _env_bool(name: str, default: bool = False) -> bool:
    raw = _env(name)
    if raw == "":
        return default
    return raw.lower() in _TRUE_TOKENS


def _bool_or_none(value):
    """تحويل قيمة عمود ثلاثية: None = ورِّث، وإلا bool."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    token = str(value).strip().lower()
    if token in _TRUE_TOKENS:
        return True
    if token in _FALSE_TOKENS:
        return False
    return None


def _first_nonempty(*values) -> str:
    for v in values:
        if v is None:
            continue
        s = str(v).strip()
        if s:
            return s
    return ""


def _load_settings_row() -> dict | None:
    """يقرأ صف الإعدادات؛ يعيد None إن تعذّر (DB غير مهيّأة/اختبار مبكر)."""
    try:
        from app.db.queries import query_one
        return query_one("SELECT * FROM radius_api_settings ORDER BY id ASC LIMIT 1")
    except Exception:
        return None


# ─── resolver ─────────────────────────────────────────────────────────
def resolve_radius_connection(refresh: bool = False) -> RadiusConnectionConfig:
    global _cached
    if _cached is not None and not refresh:
        return _cached

    from .secret_box import decrypt_secret

    row = _load_settings_row() or {}
    has_db = bool(row)

    base_url = _first_nonempty(
        row.get("base_url"),
        _env("RADIUS_API_BASE_URL"),
    ).rstrip("/")

    master_key = _first_nonempty(
        decrypt_secret(row.get("master_api_key_encrypted")),
        _env("RADIUS_API_MASTER_KEY"),
    )

    service_username = _first_nonempty(
        row.get("service_username"),
        row.get("admin_username"),
        _env("RADIUS_API_USERNAME"),
    )

    service_password = _first_nonempty(
        decrypt_secret(row.get("service_password_encrypted")),
        _env("RADIUS_API_PASSWORD"),
    )

    # mode: قيمة DB الصالحة تسبق، وإلا env، وإلا manual.
    db_mode = str(row.get("mode") or "").strip().lower()
    mode = db_mode if db_mode in _VALID_MODES else ""
    if not mode:
        env_mode = _env("RADIUS_MODE").lower()
        mode = env_mode if env_mode in _VALID_MODES else "manual"

    # الأعلام الثلاثية: None في DB = ورِّث من البيئة.
    read_db = _bool_or_none(row.get("read_enabled"))
    read_enabled = read_db if read_db is not None else _env_bool("RADIUS_API_READY")

    write_db = _bool_or_none(row.get("write_enabled"))
    write_enabled = write_db if write_db is not None else _env_bool("RADIUS_API_WRITES_ENABLED")

    verify_db = _bool_or_none(row.get("verify_ssl"))
    verify_ssl = verify_db if verify_db is not None else _env_bool("RADIUS_API_VERIFY_SSL", default=True)

    api_enabled = bool(_bool_or_none(row.get("api_enabled"))) if has_db else False

    # نوع الـ API: قيمة DB الصالحة تسبق، ثم البيئة، وإلّا كشْف تلقائي من الرابط.
    db_flavor = str(row.get("api_flavor") or "").strip().lower()
    api_flavor = db_flavor if db_flavor in _VALID_FLAVORS else ""
    if not api_flavor:
        env_flavor = _env("RADIUS_API_FLAVOR").lower()
        api_flavor = env_flavor if env_flavor in _VALID_FLAVORS else ""
    if not api_flavor:
        api_flavor = "apiv1" if "/api/v1" in base_url.lower() else "app_ad2"

    _cached = RadiusConnectionConfig(
        base_url=base_url,
        master_key=master_key,
        service_username=service_username,
        service_password=service_password,
        mode=mode,
        read_enabled=read_enabled,
        write_enabled=write_enabled,
        verify_ssl=verify_ssl,
        api_enabled=api_enabled,
        source="db" if has_db else "env",
        api_flavor=api_flavor,
    )
    return _cached


def reset_radius_config() -> None:
    """يصفّر الكاش كي يُلتقط أي تعديل على صف الإعدادات فورًا."""
    global _cached
    _cached = None
