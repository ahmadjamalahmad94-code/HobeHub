"""
RadiusClient — طبقة عزل بين باقي التطبيق وخدمة RADIUS الخارجية.

استخدام:
    from app.services.radius_client import get_radius_client

    client = get_radius_client()
    result = client.generate_user_cards(category_code="one_hour", count=1)

الاختيار بين النسخة اليدوية (ManualRadiusClient) والنسخة الحية (LiveRadiusClient)
يتم عبر متغير البيئة RADIUS_MODE.

القيم المدعومة:
    - "manual" (الافتراضي): يكتب العمليات في جدول radius_pending_actions ولا يتصل بأي API.
    - "live"  : يستدعي app_ad API الفعلي. ⚠️ معطّل في Phase 1.

⚠️ تنبيه Phase 1: حتى لو RADIUS_MODE=live، نمنع الاتصال الفعلي تلقائيًا.
سنفعّل الـ live بعد الاختبار الكامل والتحقق من الـ API.
"""
from __future__ import annotations

import os

from .base import RadiusClient, RadiusClientError, RadiusClientNotImplemented
from .dtos import (
    Card,
    PendingAction,
    Profile,
    Session,
    UsageSnapshot,
    UserAccount,
)
from .manual import ManualRadiusClient
from .live import LiveRadiusClient
from .apiv1 import ApiV1RadiusClient


__all__ = [
    "RadiusClient",
    "RadiusClientError",
    "RadiusClientNotImplemented",
    "Card",
    "PendingAction",
    "Profile",
    "Session",
    "UsageSnapshot",
    "UserAccount",
    "ApiV1RadiusClient",
    "get_radius_client",
    "reset_radius_client",
    "is_live_mode",
    "is_api_under_development",
]


def get_radius_mode() -> str:
    """يرجع الـ mode الحالي. مصدر الحقيقة = صف radius_api_settings (env احتياطي).
    الافتراضي: 'manual'."""
    from ..radius_config import resolve_radius_connection
    return resolve_radius_connection().mode


def is_live_mode() -> bool:
    return get_radius_mode() == "live"


def is_api_under_development() -> bool:
    """
    قيد التطوير = القراءة عبر الـ API غير مفعّلة بعد (read_enabled=0).
    تُضبط الآن من صفحة الإعدادات (read_enabled) أو RADIUS_API_READY كاحتياطي.
    """
    from ..radius_config import resolve_radius_connection
    cfg = resolve_radius_connection()
    if cfg.mode != "live":
        return True
    return not cfg.read_enabled


_singleton: RadiusClient | None = None


def get_radius_client() -> RadiusClient:
    """
    factory رئيسي. يحدّد النسخة المناسبة من البيئة، ويُرجع نسخة وحيدة (singleton).
    """
    global _singleton
    if _singleton is not None:
        return _singleton

    if is_live_mode() and not is_api_under_development():
        # اختيار العميل حسب نوع الـ API المُعدّ: الحديث /api/v1 أم القديم /app_ad2.
        from ..radius_config import resolve_radius_connection
        flavor = (resolve_radius_connection().api_flavor or "app_ad2").lower()
        if flavor == "apiv1":
            _singleton = ApiV1RadiusClient()
        else:
            _singleton = LiveRadiusClient()
    else:
        # الافتراضي + أي وضع غير جاهز = manual آمن
        _singleton = ManualRadiusClient()
    return _singleton


def reset_radius_client() -> None:
    """يعيد ضبط الـ singleton وكاش الإعدادات — يُستدعى في الاختبارات وبعد حفظ
    إعدادات RADIUS كي يلتقط العميل الهدف الجديد فورًا (تبديل بلا إعادة نشر)."""
    global _singleton
    _singleton = None
    from ..radius_config import reset_radius_config
    reset_radius_config()
