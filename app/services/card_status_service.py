from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from app.services.radius_client import get_radius_client, is_api_under_development
from app.services.radius_kill_switch import is_radius_offline


CARD_STATUS_LABELS = {
    "not_started": "غير مستخدمة",
    "online": "متصلة الآن",
    "used": "مستخدمة جزئياً",
    "expired": "منتهية",
    "unknown": "غير معروف",
    "api_unavailable": "القراءة الحية غير متاحة",
}


@dataclass(frozen=True)
class CardStatus:
    card_id: int
    username: str
    status: str
    source: str
    is_online: bool = False
    used_seconds: int | None = None
    remaining_seconds: int | None = None
    running_seconds: int | None = None
    last_seen_at: Any = None
    started_at: Any = None
    framed_ip: str = ""
    mac_address: str = ""
    bytes_in: int = 0
    bytes_out: int = 0
    message: str = ""

    @property
    def status_label(self) -> str:
        return CARD_STATUS_LABELS.get(self.status, CARD_STATUS_LABELS["unknown"])

    @property
    def used_label(self) -> str:
        return format_seconds(self.used_seconds)

    @property
    def remaining_label(self) -> str:
        return format_seconds(self.remaining_seconds)

    @property
    def download_label(self) -> str:
        return format_bytes(self.bytes_in)

    @property
    def upload_label(self) -> str:
        return format_bytes(self.bytes_out)

    @property
    def total_data_label(self) -> str:
        return format_bytes(self.bytes_in + self.bytes_out)

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status_label"] = self.status_label
        data["used_label"] = self.used_label
        data["remaining_label"] = self.remaining_label
        data["download_label"] = self.download_label
        data["upload_label"] = self.upload_label
        data["total_data_label"] = self.total_data_label
        return data


def get_card_status(card: dict[str, Any]) -> dict[str, Any]:
    return get_card_statuses([card]).get(_card_id(card), _unknown_status(card).as_dict())


def get_card_statuses(
    cards: list[dict[str, Any]],
    *,
    include_usage: bool = True,
    usage_limit: int = 20,
) -> dict[int, dict[str, Any]]:
    cards = cards or []
    statuses: dict[int, dict[str, Any]] = {}
    client = get_radius_client()
    # ⚡ Kill-switch موحّد: لا أي استدعاء HTTP إذا كان API معطّل
    if is_radius_offline() and _is_real_radius_client(client):
        for card in cards:
            card_id = _card_id(card)
            statuses[card_id] = _api_unavailable_status(
                card,
                "RADIUS API معطّل حالياً (قيد التفعيل الرسمي).",
            ).as_dict()
        return statuses
    api_ready = getattr(client, "mode", "live") == "live" and not is_api_under_development()
    sessions = _online_sessions_by_username(client)
    usage_calls = 0

    for card in cards:
        card_id = _card_id(card)
        username = _card_username(card)
        duration_seconds = _duration_seconds(card)
        session = sessions.get(_normalize_username(username))

        if session:
            statuses[card_id] = _status_from_online_session(
                card,
                session,
                duration_seconds,
            ).as_dict()
            continue

        if not api_ready:
            statuses[card_id] = _api_unavailable_status(
                card,
                "RADIUS API غير مفعّل حالياً؛ لا يمكن معرفة حالة البطاقة الحية.",
            ).as_dict()
            continue

        # هذه بطاقات (جدول cards) لا حسابات مشتركين — نقرأ حالتها عبر
        # /cards/check الذي يُرجع المتبقّي/المستخدَم حتى قبل أوّل استخدام،
        # بدل /accounts/<u>/usage الذي لا يعرف البطاقات.
        if include_usage and usage_calls < usage_limit:
            check_fn = getattr(client, "get_card_check", None)
            if callable(check_fn):
                try:
                    card_check = check_fn(username)
                except Exception:
                    card_check = None
                usage_calls += 1
                if card_check:
                    statuses[card_id] = _status_from_card_check(
                        card, card_check, duration_seconds,
                    ).as_dict()
                    continue

        usage_payload = None
        if include_usage and usage_calls < usage_limit:
            usage_payload = _fetch_usage_or_sessions(client, username)
            usage_calls += 1

        if usage_payload is None:
            statuses[card_id] = CardStatus(
                card_id=card_id,
                username=username,
                status="api_unavailable",
                source="radius_unavailable",
                message="تعذر جلب جلسات أو استخدام البطاقة من RADIUS.",
            ).as_dict()
            continue

        statuses[card_id] = _status_from_usage(
            card,
            usage_payload,
            duration_seconds,
        ).as_dict()

    return statuses


def format_seconds(total_seconds: int | None) -> str:
    if total_seconds is None:
        return "غير معروف"
    total_seconds = max(int(total_seconds or 0), 0)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    if hours:
        return f"{hours}س {minutes}د"
    if minutes:
        return f"{minutes}د {seconds}ث"
    return f"{seconds}ث"


def format_bytes(total_bytes: int | None) -> str:
    total = max(int(total_bytes or 0), 0)
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


def _status_from_online_session(card: dict[str, Any], session: Any, duration_seconds: int) -> CardStatus:
    running = _session_running_seconds(session)
    remaining = max(duration_seconds - running, 0) if duration_seconds else None
    return CardStatus(
        card_id=_card_id(card),
        username=_card_username(card),
        status="expired" if remaining == 0 else "online",
        source="radius_online",
        is_online=True,
        used_seconds=running,
        remaining_seconds=remaining,
        running_seconds=running,
        started_at=_first(_get(session, "started_at"), _get(session, "start_time"), _get(session, "acctstarttime")),
        last_seen_at=_first(_get(session, "last_seen_at"), _get(session, "updated_at")),
        framed_ip=str(_first(_get(session, "framed_ip"), _get(session, "framedipaddress")) or ""),
        mac_address=str(_first(_get(session, "calling_station_id"), _get(session, "mac"), _get(session, "mac_address")) or ""),
        bytes_in=_bytes_in(session),
        bytes_out=_bytes_out(session),
    )


def _status_from_usage(card: dict[str, Any], payload: Any, duration_seconds: int) -> CardStatus:
    used = _usage_seconds(payload)
    remaining = max(duration_seconds - used, 0) if duration_seconds else None
    if used <= 0:
        status = "not_started"
    elif remaining == 0:
        status = "expired"
    else:
        status = "used"
    return CardStatus(
        card_id=_card_id(card),
        username=_card_username(card),
        status=status,
        source="radius_usage",
        used_seconds=used,
        remaining_seconds=remaining,
        last_seen_at=_usage_last_seen(payload),
        bytes_in=_usage_bytes_in(payload),
        bytes_out=_usage_bytes_out(payload),
    )


def _status_from_card_check(
    card: dict[str, Any], cc: dict[str, Any], duration_seconds: int
) -> CardStatus:
    """يبني حالة البطاقة من رد /cards/check (يعرف المتبقّي/المستخدَم/الاتصال)."""
    summ = cc.get("accounting_summary") if isinstance(cc.get("accounting_summary"), dict) else {}
    budget = _int(_first(cc.get("accounting_budget_seconds"), duration_seconds)) or (duration_seconds or 0)

    remaining_raw = cc.get("remaining_seconds")
    remaining = int(remaining_raw) if isinstance(remaining_raw, (int, float)) else None

    used = _int(summ.get("total_session_seconds"))
    if used <= 0 and budget and remaining is not None:
        used = max(0, budget - remaining)
    if remaining is None and budget:
        remaining = max(budget - used, 0)

    online = bool(cc.get("active_session")) or _int(summ.get("online_sessions")) > 0
    cc_status = str(cc.get("status") or "").strip()

    if online:
        status = "online"
    elif cc_status == "revoked" or bool(cc.get("revoked")):
        status = "expired"
    elif cc_status == "expired" or (remaining == 0 and used > 0):
        status = "expired"
    elif used <= 0:
        status = "not_started"
    else:
        status = "used"

    return CardStatus(
        card_id=_card_id(card),
        username=_card_username(card),
        status=status,
        source="radius_card_check",
        is_online=online,
        used_seconds=used,
        remaining_seconds=remaining,
        last_seen_at=_first(cc.get("last_seen_at"), summ.get("last_session_at")),
        started_at=cc.get("started_at"),
        bytes_in=_int(summ.get("total_download_bytes")),
        bytes_out=_int(summ.get("total_upload_bytes")),
    )


def _api_unavailable_status(card: dict[str, Any], message: str) -> CardStatus:
    return CardStatus(
        card_id=_card_id(card),
        username=_card_username(card),
        status="api_unavailable",
        source="local_fallback",
        message=message,
    )


def _unknown_status(card: dict[str, Any]) -> CardStatus:
    return CardStatus(
        card_id=_card_id(card),
        username=_card_username(card),
        status="unknown",
        source="local_fallback",
        message="لا توجد بيانات كافية لتحديد حالة البطاقة.",
    )


def _online_sessions_by_username(client: Any) -> dict[str, Any]:
    if getattr(client, "mode", "live") != "live" or is_api_under_development():
        return {}
    try:
        sessions = client.get_online_users() or []
    except Exception:
        return {}
    mapped: dict[str, Any] = {}
    for session in sessions:
        username = _normalize_username(_session_username(session))
        if username:
            mapped[username] = session
    return mapped


def _is_real_radius_client(client: Any) -> bool:
    return client.__class__.__module__.startswith("app.services.radius_client.")


def _fetch_usage_or_sessions(client: Any, username: str) -> Any:
    for method_name in ("get_user_sessions", "get_user_usage"):
        method = getattr(client, method_name, None)
        if not callable(method):
            continue
        try:
            payload = method(username)
        except Exception:
            payload = None
        if _has_usage_signal(payload):
            return payload
    return None


def _has_usage_signal(payload: Any) -> bool:
    if payload is None:
        return False
    if isinstance(payload, list):
        return bool(payload)
    if isinstance(payload, dict):
        if payload.get("error") is True:
            return False
        if _usage_seconds(payload) > 0:
            return True
        if _usage_last_seen(payload):
            return True
        return bool(_pick_list(payload))
    return False


def _usage_seconds(payload: Any) -> int:
    rows = _pick_list(payload)
    if rows:
        return sum(_row_seconds(row) for row in rows)
    data = payload.get("data") if isinstance(payload, dict) and isinstance(payload.get("data"), dict) else payload
    if not isinstance(data, dict):
        return 0
    return _int(
        _first(
            data.get("total_seconds"),
            data.get("used_seconds"),
            data.get("acctsessiontime"),
            data.get("time_used_seconds"),
            data.get("running_sec"),
        )
    )


def _usage_last_seen(payload: Any) -> Any:
    rows = _pick_list(payload)
    if rows:
        return _first(*[_row_last_seen(row) for row in rows])
    data = payload.get("data") if isinstance(payload, dict) and isinstance(payload.get("data"), dict) else payload
    if not isinstance(data, dict):
        return None
    return _first(data.get("last_session_at"), data.get("last_seen_at"), data.get("last_login_at"), data.get("acctstoptime"))


def _usage_bytes_in(payload: Any) -> int:
    rows = _pick_list(payload)
    if rows:
        return sum(_bytes_in(row) for row in rows)
    data = payload.get("data") if isinstance(payload, dict) and isinstance(payload.get("data"), dict) else payload
    return _bytes_in(data)


def _usage_bytes_out(payload: Any) -> int:
    rows = _pick_list(payload)
    if rows:
        return sum(_bytes_out(row) for row in rows)
    data = payload.get("data") if isinstance(payload, dict) and isinstance(payload.get("data"), dict) else payload
    return _bytes_out(data)


def _bytes_in(row: Any) -> int:
    return _int(
        _first(
            _get(row, "bytes_in"),
            _get(row, "total_bytes_in"),
            _get(row, "download_bytes"),
            _get(row, "acctinputoctets"),
            _get(row, "acct_input_octets"),
        )
    )


def _bytes_out(row: Any) -> int:
    return _int(
        _first(
            _get(row, "bytes_out"),
            _get(row, "total_bytes_out"),
            _get(row, "upload_bytes"),
            _get(row, "acctoutputoctets"),
            _get(row, "acct_output_octets"),
        )
    )


def _row_seconds(row: Any) -> int:
    return _int(
        _first(
            _get(row, "total_seconds"),
            _get(row, "used_seconds"),
            _get(row, "acctsessiontime"),
            _get(row, "running_sec"),
            _get(row, "session_time"),
        )
    )


def _row_last_seen(row: Any) -> Any:
    return _first(_get(row, "last_session_at"), _get(row, "last_seen_at"), _get(row, "acctstoptime"), _get(row, "acctstarttime"))


def _pick_list(payload: Any) -> list:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("data", "sessions", "rows", "users", "items", "__list__"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []


def _card_id(card: Any) -> int:
    return int(_get(card, "id", 0) or 0)


def _card_username(card: Any) -> str:
    return str(_get(card, "card_username", "") or "")


def _duration_seconds(card: Any) -> int:
    return max(_int(_get(card, "duration_minutes")) * 60, 0)


def _get(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def _first(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None


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


def _session_running_seconds(session: Any) -> int:
    return _int(
        _first(
            _get(session, "running_seconds"),
            _get(session, "running_sec"),
            _get(session, "uptime_seconds"),
            _get(session, "acctsessiontime"),
            _get(session, "session_time"),
        )
    )
