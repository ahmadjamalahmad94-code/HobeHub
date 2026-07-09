"""
card_offer_links — مخزن ربط عروض/فئات HobeHub بعروض RADIUS الحقيقية.

كل فئة بطاقات في HobeHub (half_hour | one_hour | two_hours | three_hours |
four_hours أو أي فئة مخصصة) تُربط بعرض/باقة واحدة على RADIUS عبر
``radius_external_id``. عند طلب بطاقة تحت فئة HobeHub، يقرأ ``card_dispatcher``
هذا الربط ويولّد البطاقة *داخل* العرض المربوط بدل تخمين الفئة.

الجدول ``card_offer_radius_links`` يُنشأ في مخططَي SQLite/PostgreSQL
(16_/17_ …_04a_card_management) بشكل additive + idempotent.

القيم مخزّنة نصيًا (radius_external_id) مع اسم/مدة العرض مكاشّة (cache) للعرض
فقط — لا نعتمد على الكاش في التوليد، فقط ``radius_external_id`` هو الملزِم.
"""
from __future__ import annotations

from app import legacy


def _norm(value) -> str:
    return "" if value is None else str(value).strip()


def get_link(category_code: str) -> dict | None:
    """يرجع صف الربط لفئة معيّنة أو None إن لم تُربط بعد."""
    code = _norm(category_code)
    if not code:
        return None
    return legacy.query_one(
        "SELECT * FROM card_offer_radius_links WHERE category_code=%s LIMIT 1",
        [code],
    )


def get_linked_external_id(category_code: str) -> str:
    """اختصار: يرجع radius_external_id المربوط (نص فارغ إن لا ربط فعّال)."""
    row = get_link(category_code)
    return _norm((row or {}).get("radius_external_id")) if row else ""


def get_all_links() -> dict[str, dict]:
    """كل الروابط المحفوظة مفهرسة بـ category_code (للعرض في صفحة الربط)."""
    rows = legacy.query_all("SELECT * FROM card_offer_radius_links") or []
    return {_norm(r.get("category_code")): dict(r) for r in rows if r.get("category_code")}


def set_link(
    category_code: str,
    radius_external_id: str,
    *,
    radius_offer_name: str = "",
    radius_duration_label: str = "",
    updated_by: str = "",
) -> dict:
    """يحفظ/يحدّث ربط فئة → عرض RADIUS (upsert آمن على SQLite + PostgreSQL).

    تمرير ``radius_external_id`` فارغ = مسح الربط (بقاء الصف مع قيمة فارغة).
    يُرجع {'ok': bool, 'created'|'updated': bool}.
    """
    code = _norm(category_code)
    if not code:
        return {"ok": False, "error": "الفئة غير محددة."}
    ext = _norm(radius_external_id)
    name = _norm(radius_offer_name)
    duration = _norm(radius_duration_label)
    actor = _norm(updated_by)

    existing = legacy.query_one(
        "SELECT id FROM card_offer_radius_links WHERE category_code=%s LIMIT 1",
        [code],
    )
    if existing:
        legacy.execute_sql(
            """
            UPDATE card_offer_radius_links
            SET radius_external_id=%s,
                radius_offer_name=%s,
                radius_duration_label=%s,
                updated_by_username=%s,
                updated_at=CURRENT_TIMESTAMP
            WHERE category_code=%s
            """,
            [ext, name, duration, actor, code],
        )
        return {"ok": True, "updated": True, "created": False}

    legacy.execute_sql(
        """
        INSERT INTO card_offer_radius_links
            (category_code, radius_external_id, radius_offer_name,
             radius_duration_label, updated_by_username)
        VALUES (%s,%s,%s,%s,%s)
        """,
        [code, ext, name, duration, actor],
    )
    return {"ok": True, "created": True, "updated": False}


def clear_link(category_code: str, *, updated_by: str = "") -> dict:
    """يمسح ربط فئة (يجعل radius_external_id فارغًا)."""
    return set_link(category_code, "", updated_by=updated_by)
