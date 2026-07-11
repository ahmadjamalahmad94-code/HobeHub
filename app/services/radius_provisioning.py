"""ربط إجراءات إدارة المشتركين بالريديوس عبر العميل الحديث (/api/v1).

كل دالّة تستخدم ``get_radius_client()`` (المصنع الحديث) وتُرجع dict موحّدًا ولا
ترمي استثناءً أبدًا:

    {"ok": bool, "live": bool, "message": str}

- ``ok=True,  live=True``  → طُبّق على الريديوس فعلًا (كتابة حيّة نجحت).
- ``ok=True,  live=False`` → الكتابة مقفلة/الوضع غير مباشر؛ إجراء الأدمن المحلّي
  تمّ وبقيَ في الطابور اليدويّ (``radius_pending_actions``) — لا نُفشل العملية.
- ``ok=False``             → الريديوس رفض الكتابة صراحةً (``message`` يحمل السبب).

فلسفة الأمان: الربط **إضافيّ**. لا نستدعي الكتابة الحيّة إلا في الوضع المباشر
(``is_live_mode`` + ليست قيد التطوير)، فلا نُكرِّر إدراج الطابور الذي يقوم به
``ManualRadiusClient`` في الوضع غير المباشر. أسوأ حالة = سلوك اليوم نفسه
(محلّي + طابور). يطابق نمط ``card_dispatcher``.
"""
from __future__ import annotations

from typing import Any


def _client():
    from app.services.radius_client import get_radius_client
    return get_radius_client()


def is_live_write() -> bool:
    """هل الوضع مباشر وواجهة القراءة مفعّلة؟ (لا يفحص write_enabled — يتكفّل
    به حارس العميل نفسه فيرمي RadiusClientNotImplemented عند إقفال الكتابة)."""
    try:
        from app.services.radius_client import is_api_under_development, is_live_mode
        return bool(is_live_mode()) and not bool(is_api_under_development())
    except Exception:  # noqa: BLE001
        return False


def _not_live(message: str = "الوضع غير مباشر — بقيَ الإجراء في الطابور اليدويّ.") -> dict:
    return {"ok": True, "live": False, "message": message}


def _from_result(result: Any, ok_msg: str, fail_prefix: str) -> dict:
    """يحوّل Result/dict العميل إلى القاموس الموحّد."""
    ok = getattr(result, "ok", None)
    msg = getattr(result, "message", "") or ""
    if ok is None and isinstance(result, dict):
        ok = bool(result.get("ok"))
        msg = str(result.get("message") or result.get("error") or "")
    if ok:
        return {"ok": True, "live": True, "message": ok_msg}
    return {"ok": False, "live": True, "message": (f"{fail_prefix}: {msg}" if msg else fail_prefix)}


def _guarded(call, ok_msg: str, fail_prefix: str) -> dict:
    """يشغّل نداء كتابة حيّ واحدًا مع التقاط «الكتابة مقفلة» وأي عطل."""
    if not is_live_write():
        return _not_live()
    from app.services.radius_client.base import RadiusClientError, RadiusClientNotImplemented
    try:
        result = call()
    except RadiusClientNotImplemented:
        return _not_live("الكتابة على الريديوس مقفلة — بقيَ الإجراء في الطابور اليدويّ.")
    except (RadiusClientError, Exception) as exc:  # noqa: BLE001 — أي عطل = فشل ناعم
        return {"ok": False, "live": True, "message": str(exc)}
    return _from_result(result, ok_msg, fail_prefix)


# ── التزويد (provisioning) ─────────────────────────────────────────────────
def provision_subscriber(*, beneficiary_id: int | None, username: str,
                         password: str, profile_id: str = "",
                         expire_at: str = "", requested_by: str = "") -> dict:
    """ينشئ يوزر المشترك على الريديوس (create_user). ``expire_at`` اختياريّ
    (سلسلة تاريخ ISO) تُمرَّر لجسم الطلب كـ ``expire_at`` إن حُدِّدت."""
    username = (username or "").strip()
    if not username or not password:
        return {"ok": False, "live": False, "message": "اسم المستخدم وكلمة المرور مطلوبان."}
    opts: dict[str, Any] = {}
    if (expire_at or "").strip():
        opts["expire_at"] = str(expire_at).strip()
    return _guarded(
        lambda: _client().create_user(
            username, password, str(profile_id or ""),
            beneficiary_id=beneficiary_id, requested_by=requested_by, **opts),
        "تم إنشاء يوزر المشترك على الريديوس.",
        "تعذّر إنشاء اليوزر على الريديوس",
    )


def reset_subscriber_password(*, username: str, new_password: str,
                              beneficiary_id: int | None = None,
                              requested_by: str = "") -> dict:
    """يغيّر كلمة مرور المشترك على الريديوس (reset_password)."""
    username = (username or "").strip()
    if not username or not new_password:
        return {"ok": False, "live": False, "message": "اسم المستخدم وكلمة المرور مطلوبان."}
    return _guarded(
        lambda: _client().reset_password(
            username, new_password,
            beneficiary_id=beneficiary_id, requested_by=requested_by),
        "تم تحديث كلمة المرور على الريديوس.",
        "تعذّر تحديث كلمة المرور",
    )


def set_subscriber_enabled(*, username: str, enabled: bool,
                           beneficiary_id: int | None = None,
                           requested_by: str = "") -> dict:
    """يفعّل/يعطّل المشترك على الريديوس. عند التعطيل نفصل جلساته أيضًا."""
    username = (username or "").strip()
    if not username:
        return {"ok": False, "live": False, "message": "اسم المستخدم مطلوب."}
    status = "active" if enabled else "disabled"
    res = _guarded(
        lambda: _client().update_user(
            username, status=status,
            beneficiary_id=beneficiary_id, requested_by=requested_by),
        ("تم تفعيل المشترك على الريديوس." if enabled else "تم تعطيل المشترك على الريديوس."),
        "تعذّر تحديث حالة المشترك",
    )
    if not enabled and res.get("live"):
        # طرد الجلسات القائمة بعد التعطيل (أفضل جهد؛ لا يُفشل النتيجة).
        disconnect_subscriber(username=username, requested_by=requested_by)
    return res


def disconnect_subscriber(*, username: str, session_id: str | None = None,
                          requested_by: str = "") -> dict:
    """يفصل جلسة/جلسات المشترك القائمة (disconnect)."""
    username = (username or "").strip()
    if not username:
        return {"ok": False, "live": False, "message": "اسم المستخدم مطلوب."}
    payload: dict[str, Any] = {"username": username}
    if session_id:
        payload["session_id"] = str(session_id)
    return _guarded(
        lambda: _client().disconnect(payload, requested_by=requested_by),
        "تم فصل جلسة المشترك.",
        "تعذّر فصل الجلسة",
    )


def deprovision_subscriber(*, username: str, beneficiary_id: int | None = None,
                           requested_by: str = "") -> dict:
    """يُعطّل يوزر المشترك على الريديوس قبل الحذف المحلّي (لا نقطة delete-user
    في /api/v1، فنُعطّل + نفصل كي لا يبقى يوزر يتيم يصادق)."""
    return set_subscriber_enabled(
        username=username, enabled=False,
        beneficiary_id=beneficiary_id, requested_by=requested_by)


def revoke_radius_card(*, card_external_id: str, requested_by: str = "") -> dict:
    """يُلغي بطاقة على الريديوس (remove_user_card)."""
    cid = str(card_external_id or "").strip()
    if not cid:
        return {"ok": False, "live": False, "message": "معرّف البطاقة مطلوب."}
    return _guarded(
        lambda: _client().remove_user_card(cid, requested_by=requested_by),
        "تم إلغاء البطاقة على الريديوس.",
        "تعذّر إلغاء البطاقة",
    )


def lock_session_mac(*, username: str, mac: str = "", session_id: str = "",
                     requested_by: str = "") -> dict:
    """يقفل جلسة المشترك على MAC الحاليّ (منع مشاركة الحساب)."""
    username = (username or "").strip()
    if not username:
        return {"ok": False, "live": False, "message": "اسم المستخدم مطلوب."}
    client = _client()
    if not hasattr(client, "lock_session_mac"):
        return {"ok": False, "live": False, "message": "قفل MAC غير مدعوم في هذا الوضع."}
    return _guarded(
        lambda: client.lock_session_mac(
            username, mac=mac, session_id=session_id, requested_by=requested_by),
        "تم قفل MAC للجلسة.",
        "تعذّر قفل MAC",
    )
