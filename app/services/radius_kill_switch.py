"""
radius_kill_switch — مفتاح إيقاف موحّد لكل استدعاءات RADIUS API.

الفلسفة:
- المرحلة الحالية: API معطّل بالكامل (لا أي استدعاء HTTP لأي API خارجي).
- المرحلة التالية (عند التفعيل الرسمي): اضبط متغير البيئة:
    RADIUS_API_LIVE=1
  وتلقائياً ترجع كل الاستدعاءات للعمل الفعلي.

الاستخدام:
    from app.services.radius_kill_switch import is_radius_offline, radius_offline_response

    def fetch_something(...):
        if is_radius_offline():
            return radius_offline_response()
        # ... real API call ...
"""
from __future__ import annotations
import os


def _enabled(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


# ────────────────────────────────────────────────────────────────
# المفتاح الرئيسي
# ────────────────────────────────────────────────────────────────
def is_radius_offline() -> bool:
    """يرجع True إذا كان RADIUS API معطّل بالكامل في النظام.

    افتراضياً معطّل. للتفعيل: RADIUS_API_LIVE=1 في البيئة.
    نقبل RADIUS_API_READY=1 كاسم قديم/محلي للقراءة فقط حتى لا تتعطل واجهات
    الاستعلام عند تشغيل البيئة المحلية أو Render بإعدادات سابقة.
    """
    return not (_enabled("RADIUS_API_LIVE") or _enabled("RADIUS_API_READY"))


# ────────────────────────────────────────────────────────────────
# Helpers للـ shortcut responses
# ────────────────────────────────────────────────────────────────
OFFLINE_REASON = "RADIUS API معطّل حالياً (قيد التفعيل الرسمي)."


def radius_offline_response(extra: dict | None = None) -> dict:
    """يرجع response موحّد عندما يكون API معطّل."""
    out = {
        "ok": False,
        "offline": True,
        "error": OFFLINE_REASON,
        "hint": "سيُفعَّل تلقائياً عند ضبط RADIUS_API_LIVE=1.",
    }
    if extra:
        out.update(extra)
    return out
