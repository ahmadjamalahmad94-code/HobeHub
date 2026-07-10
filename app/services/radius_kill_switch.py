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
    """يرجع True إذا كان RADIUS API معطّلًا بالكامل في النظام.

    مصدر التفعيل (بالأولوية):
      1. متغيّر البيئة ``RADIUS_API_LIVE=1`` أو ``RADIUS_API_READY=1`` —
         تجاوزٌ سريع يعمل حتى لو تعذّرت قراءة قاعدة البيانات.
      2. إعدادات صفحة الإدارة المحفوظة في قاعدة البيانات: الوضع «مباشر»
         (``mode=live``) + «تفعيل القراءة» (``read_enabled``). هذا يتيح
         التفعيل/التعطيل من صفحة الإعدادات مباشرةً **دون تعديل ملف env أو SSH**
         (نفس مصدر الحقيقة الذي يستخدمه ``is_api_under_development``).

    غير ذلك → معطّل (الافتراضي الآمن).
    """
    # (1) تجاوز البيئة — سريع ولا يعتمد على قاعدة البيانات.
    if _enabled("RADIUS_API_LIVE") or _enabled("RADIUS_API_READY"):
        return False
    # (2) إعدادات قاعدة البيانات (صفحة الإعدادات) — تفعيل بلا SSH.
    try:
        from app.services.radius_config import resolve_radius_connection
        cfg = resolve_radius_connection()
        if getattr(cfg, "mode", "") == "live" and bool(getattr(cfg, "read_enabled", False)):
            return False
    except Exception:
        # أي تعذّر في قراءة الإعدادات → نبقى على الوضع الآمن (معطّل).
        pass
    return True


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
