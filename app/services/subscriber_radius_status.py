from __future__ import annotations

from typing import Any

from app import legacy
from app.services.card_status_service import format_seconds
from app.services.radius_client import get_radius_client, is_api_under_development
from app.services.radius_kill_switch import is_radius_offline


def _first(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def _get(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return default


def _normalize_username(value: Any) -> str:
    return str(value or "").strip().lower()


def _session_username(session: Any) -> str:
    return str(
        _first(
            _get(session, "username"),
            _get(session, "user_name"),
            _get(session, "login"),
            _get(session, "name"),
        )
        or ""
    ).strip()


def _usage_data(payload: Any) -> dict:
    if isinstance(payload, dict):
        data = payload.get("data")
        return data if isinstance(data, dict) else payload
    return {}


def _bytes_to_label(total: int) -> str:
    total = max(int(total or 0), 0)
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(total)
    unit = units[0]
    for unit in units:
        if value < 1024 or unit == units[-1]:
            break
        value /= 1024
    if unit in {"B", "KB"}:
        return f"{value:.0f} {unit}"
    return f"{value:.1f} {unit}"


def get_subscriber_radius_status(beneficiary_id: int, username: str = "") -> dict[str, Any]:
    local_account = legacy.query_one(
        "SELECT * FROM beneficiary_radius_accounts WHERE beneficiary_id=%s LIMIT 1",
        [int(beneficiary_id or 0)],
    ) or {}
    radius_username = str(
        _first(username, local_account.get("external_username"), local_account.get("external_user_id")) or ""
    ).strip()
    external_id = str(_first(local_account.get("external_user_id"), radius_username) or "").strip()

    snapshot: dict[str, Any] = {
        "available": False,
        "source": "local",
        "mode": get_radius_client().mode,
        "username": radius_username,
        "external_id": external_id,
        "status": local_account.get("status") or "pending",
        "status_label": _status_label(local_account.get("status") or "pending"),
        "profile_name": local_account.get("current_profile_name") or "",
        "profile_id": local_account.get("current_profile_id") or "",
        "expires_at": local_account.get("expires_at"),
        "mac_address": local_account.get("mac_address") or "",
        "is_online": False,
        "running_seconds": 0,
        "running_label": "غير متصل",
        "total_seconds": _int(local_account.get("time_quota_minutes_used")) * 60,
        "total_time_label": format_seconds(_int(local_account.get("time_quota_minutes_used")) * 60),
        "quota_used_label": _bytes_to_label(_int(local_account.get("data_quota_mb_used")) * 1024 * 1024),
        "quota_total_label": _bytes_to_label(_int(local_account.get("data_quota_mb_total")) * 1024 * 1024),
        "last_seen_at": None,
        "framed_ip": "",
        "sync_status": local_account.get("sync_status") or "pending",
        "sync_error": local_account.get("sync_error") or "",
        "message": "الوضع المحلي يعمل بدون قراءة حية من RADIUS.",
    }

    if not radius_username or is_api_under_development() or is_radius_offline():
        return snapshot

    client = get_radius_client()
    try:
        sessions = client.get_online_users() or []
    except Exception as exc:
        snapshot["message"] = str(exc)
        return snapshot

    for session in sessions:
        if _normalize_username(_session_username(session)) != _normalize_username(radius_username):
            continue
        running = _int(_first(_get(session, "running_seconds"), _get(session, "running_sec"), _get(session, "acctsessiontime")))
        snapshot.update(
            {
                "available": True,
                "source": "radius_online",
                "status": "online",
                "status_label": "متصل الآن",
                "is_online": True,
                "running_seconds": running,
                "running_label": format_seconds(running),
                "framed_ip": str(_first(_get(session, "framed_ip"), _get(session, "framedipaddress")) or ""),
                "mac_address": str(_first(_get(session, "calling_station_id"), _get(session, "mac"), snapshot["mac_address"]) or ""),
                "message": "",
            }
        )
        break

    usage = None
    try:
        usage = client.get_user_usage(external_id or radius_username)
    except Exception:
        usage = None
    data = _usage_data(usage)
    if data:
        total_seconds = _int(
            _first(
                data.get("total_seconds"),
                data.get("used_seconds"),
                data.get("acctsessiontime"),
                data.get("time_used_seconds"),
            )
        )
        bytes_in = _int(_first(data.get("total_bytes_in"), data.get("bytes_in"), data.get("download_bytes")))
        bytes_out = _int(_first(data.get("total_bytes_out"), data.get("bytes_out"), data.get("upload_bytes")))
        snapshot.update(
            {
                "available": True,
                "source": "radius_mixed" if snapshot["is_online"] else "radius_usage",
                "total_seconds": total_seconds,
                "total_time_label": format_seconds(total_seconds),
                "quota_used_label": _bytes_to_label(bytes_in + bytes_out),
                "last_seen_at": _first(data.get("last_session_at"), data.get("last_seen_at"), data.get("last_login_at")),
                "message": "" if snapshot.get("message") else snapshot.get("message", ""),
            }
        )

    # تفاصيل الحساب الحيّة من الريديوس (الباقة/السرعة/الحالة/الانتهاء) — لا نكتفي
    # بالحساب المحلّي الذي يكون فارغًا للمشتركين المُرحَّلين، فنجلب الحساب بالاسم.
    acct = None
    try:
        _found = client.search_users(radius_username, limit=1)
        _items = _found.get("data") if isinstance(_found, dict) else None
        acct = _items[0] if isinstance(_items, list) and _items else None
    except Exception:
        acct = None
    if isinstance(acct, dict):
        snapshot["available"] = True
        if snapshot.get("source") == "local":
            snapshot["source"] = "radius_account"
        _pname = _first(acct.get("plan_name"), acct.get("profile_name"), acct.get("plan"))
        _pid = _first(acct.get("plan_id"), acct.get("profile_id"))
        if _pname:
            snapshot["profile_name"] = _pname
        elif _pid and not snapshot.get("profile_name"):
            snapshot["profile_name"] = f"باقة #{_pid}"
        if _pid:
            snapshot["profile_id"] = _pid
        if not snapshot["is_online"]:
            _st = _first(acct.get("status"), acct.get("state"))
            if _st:
                snapshot["status"] = _st
                snapshot["status_label"] = _status_label(_st)
        _exp = _first(acct.get("expire_at"), acct.get("expires_at"), acct.get("expiration"))
        if _exp:
            snapshot["expires_at"] = _exp
        _down = _int(_first(acct.get("download_speed_kbps"), acct.get("speed_down_kbps"), acct.get("download_speed")))
        _up = _int(_first(acct.get("upload_speed_kbps"), acct.get("speed_up_kbps"), acct.get("upload_speed")))
        if _down:
            snapshot["download_speed"] = _down
        if _up:
            snapshot["upload_speed"] = _up

    return snapshot


def _status_label(status: str) -> str:
    return {
        "active": "نشط",
        "online": "متصل الآن",
        "pending": "قيد التجهيز",
        "suspended": "موقوف",
        "expired": "منتهي",
        "synced": "متزامن",
        "failed": "فشل المزامنة",
    }.get((status or "").strip().lower(), status or "غير معروف")
