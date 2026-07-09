"""
branding — هوية النسخة (white-label) القابلة لإعادة البيع.

يتيح تشغيل نفس التطبيق باسم علامة تجارية آخر (وربطه بخادم RADIUS آخر عبر
صفحة الإعدادات). نغيّر الاسم/الشعار النصي فقط — تبقى الهوية البصرية (أسود
#1E1E1E / ذهبي #F4BA2A) كما هي.

مصدر الحقيقة = جدول ``app_branding`` (صف واحد)؛ الافتراضي «Hobe Hub».
مُخزَّن مؤقتًا مع ``reset_branding_cache()`` (يُستدعى بعد الحفظ).
"""
from __future__ import annotations

from dataclasses import dataclass

DEFAULT_BRAND_NAME = "Hobe Hub"
DEFAULT_TAGLINE = "منصة إدارة وخدمات الإنترنت"


@dataclass(frozen=True)
class Branding:
    brand_name: str
    tagline: str


_cached: Branding | None = None


def _load_row() -> dict | None:
    try:
        from app.db.queries import query_one
        return query_one("SELECT * FROM app_branding ORDER BY id ASC LIMIT 1")
    except Exception:
        return None


def get_branding(refresh: bool = False) -> Branding:
    global _cached
    if _cached is not None and not refresh:
        return _cached
    row = _load_row() or {}
    name = (str(row.get("brand_name") or "").strip()) or DEFAULT_BRAND_NAME
    tagline = str(row.get("tagline") or "").strip()
    if not tagline:
        tagline = DEFAULT_TAGLINE
    _cached = Branding(brand_name=name, tagline=tagline)
    return _cached


def get_brand_name() -> str:
    return get_branding().brand_name


def get_tagline() -> str:
    return get_branding().tagline


def save_branding(brand_name: str | None, tagline: str | None) -> Branding:
    """يحفظ (upsert) هوية النسخة ويصفّر الكاش. يعيد الهوية الجديدة."""
    from app.db.queries import execute_sql, query_one

    name = (str(brand_name or "").strip()) or DEFAULT_BRAND_NAME
    tag = str(tagline or "").strip()

    existing = query_one("SELECT id FROM app_branding ORDER BY id ASC LIMIT 1")
    if existing:
        execute_sql(
            "UPDATE app_branding SET brand_name=%s, tagline=%s, updated_at=CURRENT_TIMESTAMP WHERE id=%s",
            [name, tag, existing["id"]],
        )
    else:
        execute_sql(
            "INSERT INTO app_branding (brand_name, tagline) VALUES (%s, %s)",
            [name, tag],
        )
    reset_branding_cache()
    return get_branding(refresh=True)


def reset_branding_cache() -> None:
    global _cached
    _cached = None
