"""radius_subscriber_bridge — جسر حالة مشترك معيّن عبر واجهة الريديوس الحديثة (/api/v1).

مُرحَّل (2026-07) من طبقة AdvRadius/app_ad القديمة (advrapp.com:6950/app) إلى العميل
الحديث ``get_radius_client()``:
  - قراءات الحالة تُبنى من ``subscriber_radius_status.get_subscriber_radius_status``
    (يستخدم العميل الحديث) وتُشكَّل بنفس مفاتيح adv القديمة (``_snapshot_to_payload``)
    كي لا يتغيّر أيّ مستهلك (widget المشترك/الأدمن + اللقطة اليوميّة + المراقبة الحيّة).
  - تغيير كلمة المرور و«المتصلون الآن» عبر ``get_radius_client()`` مباشرة.

كل نداء محكوم بـ ``is_radius_offline`` الموحّد (يقرأ mode=live + read_enabled من DB).
لم تَعُد هذه الوحدة تستورد ``RadiusApiClient``/``AdvClientApi`` القديمين.
"""
from __future__ import annotations

from typing import Any

from app.services.radius_kill_switch import is_radius_offline, radius_offline_response


# ───────── Username lookup ─────────
def get_radius_username_for(beneficiary_row: dict) -> str:
    """يرجّع اسم المستخدم في RADIUS لمشترك: radius_username ثم username ثم phone."""
    if not beneficiary_row:
        return ""
    for key in ("radius_username", "username", "phone"):
        v = (beneficiary_row.get(key) or "").strip()
        if v:
            return v
    return ""


def _client():
    from app.services.radius_client import get_radius_client
    return get_radius_client()


def _resolve_bid(username: str) -> int:
    try:
        from app.db.queries import query_one
        row = query_one(
            "SELECT beneficiary_id FROM beneficiary_radius_accounts "
            "WHERE external_username=%s LIMIT 1", [username]) or {}
        return int(row.get("beneficiary_id") or 0)
    except Exception:  # noqa: BLE001
        return 0


def _snapshot_to_payload(snapshot: dict) -> dict:
    """يطابق ``_status_snapshot_as_api_payload`` في 48ap تمامًا — نفس المفاتيح كي
    يقرأها المستهلك القائم (val_usage_qouta / conn_code / down_speed …) بلا تغيير."""
    snapshot = snapshot or {}
    return {
        "conn_code":       "online" if snapshot.get("is_online") else "offline",
        "is_online":       1 if snapshot.get("is_online") else 0,
        "profile_name":    snapshot.get("profile_name") or "",
        "expiration":      snapshot.get("expires_at") or "",
        "down_speed":      snapshot.get("download_speed") or snapshot.get("down_speed") or "",
        "up_speed":        snapshot.get("upload_speed") or snapshot.get("up_speed") or "",
        "val_usage_qouta": snapshot.get("usage_bytes") or 0,
        "val_rem":         snapshot.get("remaining_bytes") or 0,
        "framed_ip":       snapshot.get("framed_ip") or "",
        "mac_address":     snapshot.get("mac_address") or "",
        "status":          snapshot.get("status") or "",
        "status_label":    snapshot.get("status_label") or "",
        "last_seen_at":    snapshot.get("last_seen_at") or "",
    }


def _status_payload_for(username: str) -> dict:
    from app.services.subscriber_radius_status import get_subscriber_radius_status
    snapshot = get_subscriber_radius_status(_resolve_bid(username), username) or {}
    return _snapshot_to_payload(snapshot)


# ───────── Status: يُبنى من العميل الحديث ─────────
def fetch_subscriber_status(username: str) -> dict:
    """ملخّص حالة مشترك (بشكل adv القديم كي لا يتغيّر المستهلك)."""
    if is_radius_offline():
        return radius_offline_response({"username": username})
    if not username:
        return {"ok": False, "error": "اسم المستخدم غير محدد."}
    try:
        return {"ok": True, "username": username,
                "usage": _status_payload_for(username), "sessions": {}}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


# ───────── Password reset (عبر العميل الحديث) ─────────
def reset_subscriber_password(username: str, new_password: str) -> dict:
    if is_radius_offline():
        return radius_offline_response({"username": username})
    if not username or not new_password:
        return {"ok": False, "error": "اسم المستخدم وكلمة المرور مطلوبان."}
    if len(new_password) < 6:
        return {"ok": False, "error": "كلمة المرور قصيرة جدًا (6 أحرف على الأقل)."}
    try:
        result = _client().reset_password(username, new_password)
        if bool(getattr(result, "ok", False)):
            return {"ok": True, "result": {"message": getattr(result, "message", "")}}
        return {"ok": False, "error": getattr(result, "message", "") or "تعذّر تغيير كلمة المرور."}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


# ───────── Online users (للمراقبة الحيّة) ─────────
def fetch_online_users(limit: int = 100) -> dict:
    if is_radius_offline():
        return radius_offline_response({"data": {}})
    try:
        sessions = _client().get_online_users() or []
        if isinstance(sessions, list) and limit:
            sessions = sessions[: int(limit)]
        else:
            sessions = sessions if isinstance(sessions, list) else []
        return {"ok": True, "data": {"items": sessions, "count": len(sessions)}}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


# ───────── Subscriber details (كان AdvClient الذاتيّ؛ صار إداريًّا حديثًا) ─────────
def fetch_subscriber_details_via_self(username: str, password: str = "") -> dict:
    """كان يستخدم كريدنشيال المشترك عبر AdvClient القديم. الواجهة الحديثة إداريّة
    فقط (لا دخول ذاتيّ للمشترك)، فنقرأ حالته عبر العميل الإداريّ الحديث بالاسم
    (كلمة المرور لم تَعُد لازمة). يُبقى شكل الإرجاع {ok, username, details, status,
    account} — و``details`` بنفس مفاتيح adv كي لا يتغيّر المستهلك."""
    if is_radius_offline():
        return radius_offline_response({"username": username})
    if not username:
        return {"ok": False, "error": "اسم المستخدم مطلوب."}
    try:
        return {"ok": True, "username": username,
                "details": _status_payload_for(username), "status": {}, "account": {}}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
