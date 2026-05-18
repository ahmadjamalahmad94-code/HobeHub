from __future__ import annotations

import json
from typing import Any

from app import legacy
from app.services.smart_search import smart_search_clause


USER_ACTION_TYPES = {
    "reset_password",
    "unblock_site",
    "speed_upgrade",
    "create_user",
    "update_user",
    "add_time",
    "add_quota_mb",
    "disconnect",
}
CARD_ACTION_TYPES = {"generate_user_cards"}


def status_label(status: str | None) -> str:
    value = (status or "pending").lower()
    return {
        "pending": "معلّق",
        "in_progress": "قيد التنفيذ",
        "approved": "معتمد",
        "done": "منجز",
        "executed": "منفّذ",
        "cancelled": "ملغي",
        "rejected": "مرفوض",
        "failed": "فشل",
    }.get(value, status or "معلّق")


REQUEST_ACTION_LABELS = {
    "reset_password": "إعادة ضبط كلمة المرور",
    "password_reset": "إعادة ضبط كلمة المرور",
    "unblock_site": "فتح موقع محجوب",
    "open_blocked_site": "فتح موقع محجوب",
    "open_site": "فتح موقع محجوب",
    "speed_upgrade": "طلب رفع السرعة",
    "temporary_speed_upgrade": "طلب رفع السرعة مؤقتًا",
    "change_speed": "طلب رفع السرعة",
    "create_user": "إنشاء حساب إنترنت",
    "new_service": "طلب خدمة إنترنت",
    "update_user": "تعديل بيانات حساب الإنترنت",
    "add_time": "إضافة وقت للحساب",
    "add_quota": "إضافة رصيد بيانات",
    "add_quota_mb": "إضافة رصيد بيانات",
    "disconnect": "فصل جلسة حالية",
    "generate_user_cards": "طلب بطاقة إنترنت",
    "request_card": "طلب بطاقة إنترنت",
    "extra_card": "طلب بطاقة إضافية",
    "connection_issue": "بلاغ مشكلة اتصال",
    "update_mac": "تغيير عنوان الجهاز",
    "change_mac": "تغيير عنوان الجهاز",
    "other": "طلب آخر",
}


def action_label(action_type: str | None) -> str:
    value = (action_type or "").strip().lower()
    if not value:
        return "طلب"
    return REQUEST_ACTION_LABELS.get(value, value.replace("_", " "))


def get_request_center(filters: dict[str, str] | None = None, *, limit: int = 300) -> dict[str, Any]:
    filters = filters or {}
    source = (filters.get("type") or "all").strip().lower()
    status = (filters.get("status") or "").strip().lower()
    query = (filters.get("q") or "").strip()
    beneficiary_id = _safe_int(filters.get("beneficiary_id"))
    date_from = (filters.get("date_from") or "").strip()
    date_to = (filters.get("date_to") or "").strip()

    items: list[dict[str, Any]] = []
    if source in {"", "all", "internet"}:
        items.extend(_internet_items(status=status, query=query, beneficiary_id=beneficiary_id, date_from=date_from, date_to=date_to, limit=limit))
    if source in {"", "all", "user"}:
        items.extend(
            _pending_action_items(
                USER_ACTION_TYPES,
                source="user",
                source_label="طلبات حساب الإنترنت",
                status=status,
                query=query,
                beneficiary_id=beneficiary_id,
                date_from=date_from,
                date_to=date_to,
                limit=limit,
            )
        )
    if source in {"", "all", "card", "cards"}:
        items.extend(
            _pending_action_items(
                CARD_ACTION_TYPES,
                source="card",
                source_label="طلبات البطاقات",
                status=status,
                query=query,
                beneficiary_id=beneficiary_id,
                date_from=date_from,
                date_to=date_to,
                limit=limit,
            )
        )

    items.sort(key=lambda row: (row.get("sort_at") or "", int(row.get("id") or 0)), reverse=True)
    items = items[:limit]

    return {
        "items": items,
        "filters": {
            "type": source or "all",
            "status": status,
            "q": query,
            "beneficiary_id": str(beneficiary_id or ""),
            "date_from": date_from,
            "date_to": date_to,
        },
        "summary": _summary(),
    }


def get_request_detail(source: str, request_id: int) -> dict[str, Any] | None:
    source = (source or "").strip().lower()
    if source in {"card", "cards"}:
        item = _pending_action_detail("card", CARD_ACTION_TYPES, request_id)
    elif source == "user":
        item = _pending_action_detail("user", USER_ACTION_TYPES, request_id)
    elif source == "internet":
        item = _internet_detail(request_id)
    else:
        return None
    if not item:
        return None
    item["events"] = _request_events(item)
    return item


def _internet_items(*, status: str, query: str, beneficiary_id: int | None, date_from: str, date_to: str, limit: int) -> list[dict[str, Any]]:
    where = []
    params: list[Any] = []
    if status:
        where.append("r.status=%s")
        params.append(status)
    if beneficiary_id:
        where.append("r.beneficiary_id=%s")
        params.append(beneficiary_id)
    if query:
        clause, clause_params = smart_search_clause(
            query,
            text_columns=("b.search_name", "b.full_name"),
            phone_columns=("b.phone",),
            extra_columns=("r.request_type", "r.requested_by"),
        )
        if clause:
            where.append(clause)
            params.extend(clause_params)
    if date_from:
        where.append("DATE(r.created_at) >= %s")
        params.append(date_from)
    if date_to:
        where.append("DATE(r.created_at) <= %s")
        params.append(date_to)

    sql = """
        SELECT r.id, r.beneficiary_id, r.request_type, r.status, r.created_at, r.requested_by,
               b.full_name, b.phone
        FROM internet_service_requests r
        LEFT JOIN beneficiaries b ON b.id = r.beneficiary_id
    """
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY r.created_at DESC, r.id DESC LIMIT %s"
    params.append(limit)

    rows = legacy.query_all(sql, params)
    return [
        {
            "source": "internet",
            "source_label": "طلبات خدمات الإنترنت",
            "id": row.get("id"),
            "beneficiary_id": row.get("beneficiary_id"),
            "full_name": row.get("full_name"),
            "phone": row.get("phone"),
            "action_type": row.get("request_type"),
            "action_label": action_label(row.get("request_type")),
            "status": row.get("status") or "pending",
            "status_label": status_label(row.get("status")),
            "created_at": row.get("created_at"),
            "sort_at": str(row.get("created_at") or ""),
            "requested_by": row.get("requested_by"),
            "last_event": _last_event("internet_request", row.get("id")),
            "payload": {},
            "href": f"/admin/requests/internet/{row.get('id')}",
            "profile_href": _profile_href(row.get("beneficiary_id")),
            "beneficiary_requests_href": _beneficiary_requests_href(row.get("beneficiary_id")),
            "specialized_href": f"/admin/internet-requests/{row.get('id')}?legacy=1",
            "primary_action": "مراجعة",
        }
        for row in rows
    ]


def _internet_detail(request_id: int) -> dict[str, Any] | None:
    row = legacy.query_one(
        """
        SELECT r.*, b.full_name, b.phone
        FROM internet_service_requests r
        LEFT JOIN beneficiaries b ON b.id = r.beneficiary_id
        WHERE r.id=%s
        LIMIT 1
        """,
        [int(request_id)],
    )
    if not row:
        return None
    payload = _payload(row.get("requested_payload") or row.get("payload_json") or row.get("requested_payload_json"))
    admin_payload = _payload(row.get("admin_payload") or row.get("admin_payload_json"))
    api_response = _payload(row.get("api_response"))
    if not api_response:
        api_response = _payload(row.get("api_response_json"))
    return {
        "source": "internet",
        "source_label": "طلبات خدمات الإنترنت",
        "id": row.get("id"),
        "beneficiary_id": row.get("beneficiary_id"),
        "full_name": row.get("full_name"),
        "phone": row.get("phone"),
        "action_type": row.get("request_type"),
        "action_label": action_label(row.get("request_type")),
        "status": row.get("status") or "pending",
        "status_label": status_label(row.get("status")),
        "created_at": row.get("created_at"),
        "requested_by": row.get("requested_by"),
        "reviewed_by": row.get("reviewed_by"),
        "reviewed_at": row.get("reviewed_at"),
        "executed_at": row.get("executed_at"),
        "notes": row.get("admin_notes") or row.get("notes") or "",
        "error_message": row.get("error_message") or "",
        "payload": payload,
        "admin_payload": admin_payload,
        "api_response": api_response,
        "href": f"/admin/requests/internet/{row.get('id')}",
        "profile_href": _profile_href(row.get("beneficiary_id")),
        "beneficiary_requests_href": _beneficiary_requests_href(row.get("beneficiary_id")),
        "specialized_href": f"/admin/internet-requests/{row.get('id')}?legacy=1",
    }


def _pending_action_items(
    action_types: set[str],
    *,
    source: str,
    source_label: str,
    status: str,
    query: str,
    beneficiary_id: int | None,
    date_from: str,
    date_to: str,
    limit: int,
) -> list[dict[str, Any]]:
    if not action_types:
        return []
    placeholders = ",".join(["%s"] * len(action_types))
    where = [f"a.action_type IN ({placeholders})"]
    params: list[Any] = list(action_types)
    if status:
        where.append("a.status=%s")
        params.append(status)
    if beneficiary_id:
        where.append("a.beneficiary_id=%s")
        params.append(beneficiary_id)
    if query:
        clause, clause_params = smart_search_clause(
            query,
            text_columns=("b.search_name", "b.full_name"),
            phone_columns=("b.phone",),
            extra_columns=("a.action_type", "a.notes"),
        )
        if clause:
            where.append(clause)
            params.extend(clause_params)
    if date_from:
        where.append("DATE(a.requested_at) >= %s")
        params.append(date_from)
    if date_to:
        where.append("DATE(a.requested_at) <= %s")
        params.append(date_to)

    rows = legacy.query_all(
        f"""
        SELECT a.*, b.full_name, b.phone
        FROM radius_pending_actions a
        LEFT JOIN beneficiaries b ON b.id = a.beneficiary_id
        WHERE {" AND ".join(where)}
        ORDER BY a.requested_at DESC, a.id DESC
        LIMIT %s
        """,
        [*params, limit],
    )

    items = []
    for row in rows:
        payload = _payload(row.get("payload_json"))
        category = payload.get("category_code") or payload.get("duration_minutes") or ""
        items.append(
            {
                "source": source,
                "source_label": source_label,
                "id": row.get("id"),
                "beneficiary_id": row.get("beneficiary_id"),
                "full_name": row.get("full_name"),
                "phone": row.get("phone"),
                "action_type": row.get("action_type"),
                "action_label": action_label(row.get("action_type")),
                "status": row.get("status") or "pending",
                "status_label": status_label(row.get("status")),
                "created_at": row.get("requested_at"),
                "sort_at": str(row.get("requested_at") or ""),
                "requested_by": row.get("requested_by") or row.get("created_by"),
                "last_event": _last_event("radius_pending_actions", row.get("id")),
                "payload": payload,
                "notes": row.get("notes") or "",
                "detail": str(category) if category else "",
                "href": f"/admin/requests/{source}/{row.get('id')}",
                "profile_href": _profile_href(row.get("beneficiary_id")),
                "beneficiary_requests_href": _beneficiary_requests_href(row.get("beneficiary_id")),
                "specialized_href": (
                    "/admin/cards/pending"
                    if source == "card"
                    else f"/admin/users-account/requests?beneficiary_id={row.get('beneficiary_id') or ''}"
                ),
                "primary_action": "تسليم" if source == "card" else "تنفيذ",
            }
        )
    return items


def _pending_action_detail(source: str, action_types: set[str], action_id: int) -> dict[str, Any] | None:
    if not action_types:
        return None
    placeholders = ",".join(["%s"] * len(action_types))
    row = legacy.query_one(
        f"""
        SELECT a.*, b.full_name, b.phone
        FROM radius_pending_actions a
        LEFT JOIN beneficiaries b ON b.id = a.beneficiary_id
        WHERE a.id=%s AND a.action_type IN ({placeholders})
        LIMIT 1
        """,
        [int(action_id), *action_types],
    )
    if not row:
        return None
    payload = _payload(row.get("payload_json"))
    api_response = _payload(row.get("api_response_json"))
    return {
        "source": source,
                "source_label": "طلبات البطاقات" if source == "card" else "طلبات حساب الإنترنت",
        "id": row.get("id"),
        "beneficiary_id": row.get("beneficiary_id"),
        "full_name": row.get("full_name"),
        "phone": row.get("phone"),
        "action_type": row.get("action_type"),
        "action_label": action_label(row.get("action_type")),
        "status": row.get("status") or "pending",
        "status_label": status_label(row.get("status")),
        "created_at": row.get("requested_at"),
        "requested_by": row.get("requested_by") or row.get("created_by"),
        "executed_by": row.get("executed_by_username") or "",
        "executed_at": row.get("executed_at"),
        "notes": row.get("notes") or "",
        "error_message": row.get("error_message") or "",
        "payload": payload,
        "api_response": api_response,
        "detail": str(payload.get("category_code") or payload.get("duration_minutes") or ""),
        "href": f"/admin/requests/{source}/{row.get('id')}",
        "profile_href": _profile_href(row.get("beneficiary_id")),
        "beneficiary_requests_href": _beneficiary_requests_href(row.get("beneficiary_id")),
                "specialized_href": "/admin/cards/pending?legacy=1" if source == "card" else f"/admin/users-account/requests?legacy=1&beneficiary_id={row.get('beneficiary_id') or ''}",
    }


def _request_events(item: dict[str, Any]) -> list[dict[str, Any]]:
    source_type = "internet_request" if item.get("source") == "internet" else "radius_pending_actions"
    rows = legacy.query_all(
        """
        SELECT id, title, body, status, actor_name, created_at, read_at
        FROM notifications
        WHERE source_type=%s AND source_id=%s
        ORDER BY id DESC
        LIMIT 20
        """,
        [source_type, int(item.get("id") or 0)],
    )
    events = [
        {
            "id": row.get("id"),
            "title": row.get("title") or status_label(row.get("status")),
            "body": row.get("body") or "",
            "status": row.get("status") or "",
            "actor_name": row.get("actor_name") or "",
            "created_at": row.get("created_at"),
            "read_at": row.get("read_at"),
        }
        for row in rows
    ]
    if not events:
        events.append(
            {
                "id": "",
                "title": "تم إنشاء الطلب",
                "body": item.get("notes") or item.get("action_label") or "",
                "status": item.get("status") or "pending",
                "actor_name": item.get("requested_by") or item.get("full_name") or "",
                "created_at": item.get("created_at"),
                "read_at": "",
            }
        )
    return events


def _last_event(source_type: str, source_id: Any) -> str:
    try:
        row = legacy.query_one(
            """
            SELECT title, status, created_at
            FROM notifications
            WHERE source_type=%s AND source_id=%s
            ORDER BY id DESC
            LIMIT 1
            """,
            [source_type, int(source_id or 0)],
        ) or {}
    except Exception:
        row = {}
    if not row:
        return ""
    return f"{row.get('title') or status_label(row.get('status'))} · {row.get('created_at') or ''}".strip(" ·")


def _summary() -> dict[str, Any]:
    return {
        "internet": _internet_summary(),
        "user": _action_summary(USER_ACTION_TYPES),
        "card": _action_summary(CARD_ACTION_TYPES),
    }


def _internet_summary() -> dict[str, int]:
    total = _count("SELECT COUNT(*) AS c FROM internet_service_requests")
    pending = _count("SELECT COUNT(*) AS c FROM internet_service_requests WHERE status=%s", ["pending"])
    return {"total": total, "pending": pending}


def _action_summary(action_types: set[str]) -> dict[str, int]:
    if not action_types:
        return {"total": 0, "pending": 0}
    placeholders = ",".join(["%s"] * len(action_types))
    total = _count(
        f"SELECT COUNT(*) AS c FROM radius_pending_actions WHERE action_type IN ({placeholders})",
        list(action_types),
    )
    pending = _count(
        f"SELECT COUNT(*) AS c FROM radius_pending_actions WHERE action_type IN ({placeholders}) AND status=%s",
        [*action_types, "pending"],
    )
    return {"total": total, "pending": pending}


def _count(sql: str, params: list[Any] | None = None) -> int:
    row = legacy.query_one(sql, params or []) or {}
    return int(row.get("c") or 0)


def _payload(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            data = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}
    return {}


def _safe_int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _profile_href(beneficiary_id: Any) -> str:
    number = _safe_int(beneficiary_id)
    return f"/admin/users/{number}/profile" if number else ""


def _beneficiary_requests_href(beneficiary_id: Any) -> str:
    number = _safe_int(beneficiary_id)
    return f"/admin/requests?beneficiary_id={number}" if number else ""
