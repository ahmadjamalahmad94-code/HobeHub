# /admin/internet-requests بالتصميم الجديد — override يستخدم القالب الجديد.

import json

from flask import abort, redirect, render_template, request, url_for


def _request_center_count(sql, params=None):
    row = query_one(sql, params or []) or {}
    return int(row.get("c") or 0)


def _request_center_action_count(action_types, status=None):
    if not action_types:
        return 0
    placeholders = ",".join(["%s"] * len(action_types))
    params = list(action_types)
    sql = f"SELECT COUNT(*) AS c FROM radius_pending_actions WHERE action_type IN ({placeholders})"
    if status:
        sql += " AND status=%s"
        params.append(status)
    return _request_center_count(sql, params)


def _request_center_action_rows(action_types, limit=6):
    if not action_types:
        return []
    placeholders = ",".join(["%s"] * len(action_types))
    rows = query_all(
        f"""
        SELECT a.*, b.full_name, b.phone
        FROM radius_pending_actions a
        LEFT JOIN beneficiaries b ON b.id = a.beneficiary_id
        WHERE a.action_type IN ({placeholders})
        ORDER BY a.requested_at DESC, a.id DESC
        LIMIT %s
        """,
        [*action_types, limit],
    )
    items = []
    for row in rows:
        payload = row.get("payload_json") or {}
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except (TypeError, ValueError, json.JSONDecodeError):
                payload = {}
        items.append({**row, "payload": payload or {}})
    return items


@app.route("/admin/requests", methods=["GET"])
@admin_login_required
def admin_request_center():
    """Unified request center. Specialized detail pages stay available for execution."""
    from app.services.request_center import get_request_center

    # رفض تلقائيّ للطلبات المعلّقة التي تجاوزت المهلة (مكبوح داخليًّا)
    try:
        expire_stale_card_approval_requests()
    except Exception:
        pass

    data = get_request_center(
        {
            "type": clean_csv_value(request.args.get("type")) or "all",
            "status": clean_csv_value(request.args.get("status")) or "",
            "q": clean_csv_value(request.args.get("q")) or "",
            "beneficiary_id": clean_csv_value(request.args.get("beneficiary_id")) or "",
            "date_from": clean_csv_value(request.args.get("date_from")) or "",
            "date_to": clean_csv_value(request.args.get("date_to")) or "",
        },
        limit=300,
    )
    return render_template(
        "admin/requests/center.html",
        items=data["items"],
        filters=data["filters"],
        summary=data["summary"],
        format_dt_short=format_dt_short,
    )


@app.route("/admin/requests/<source>/<int:request_id>", methods=["GET"])
@admin_login_required
def admin_request_center_detail(source, request_id):
    """Unified read-only request detail. Write operations keep their existing service routes."""
    from app.services.request_center import get_request_detail

    item = get_request_detail(source, request_id)
    if not item:
        abort(404)
    return render_template(
        "admin/requests/detail.html",
        item=item,
        format_dt_short=format_dt_short,
    )

def _admin_internet_requests_v2_view():
    """قائمة طلبات الإنترنت بالـ unified sidebar."""
    # تشغيل أي عمليات استعادة السرعة المستحقة (مثل ما يفعل القديم)
    try:
        process_due_speed_restores()
    except Exception:
        pass

    status_filter = clean_csv_value(request.args.get("status", ""))

    where = []
    params = []
    if status_filter:
        where.append("r.status=%s")
        params.append(status_filter)

    sql = """
    SELECT r.*, b.full_name
    FROM internet_service_requests r
    JOIN beneficiaries b ON b.id = r.beneficiary_id
    """
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += (
        " ORDER BY CASE WHEN r.status='pending' THEN 0 "
        "WHEN r.status='approved' THEN 1 ELSE 2 END, r.id DESC"
    )
    rows = query_all(sql, params)

    # KPIs لكل حالة
    def _count(status=None):
        if status:
            row = query_one(
                "SELECT COUNT(*) AS c FROM internet_service_requests WHERE status=%s",
                [status],
            ) or {}
        else:
            row = query_one("SELECT COUNT(*) AS c FROM internet_service_requests") or {}
        return int(row.get("c") or 0)

    kpi_total = _count()
    kpi_pending = _count("pending")
    kpi_approved = _count("approved")
    kpi_executed = _count("executed")
    kpi_failed = _count("failed")
    kpi_rejected = _count("rejected")

    return render_template(
        "admin/internet_requests/list.html",
        rows=rows,
        filters={"status": status_filter},
        kpi_total=kpi_total,
        kpi_pending=kpi_pending,
        kpi_approved=kpi_approved,
        kpi_executed=kpi_executed,
        kpi_failed=kpi_failed,
        kpi_rejected=kpi_rejected,
        internet_request_type_label=internet_request_type_label,
        format_dt_short=format_dt_short,
    )


# ─── Override /admin/internet-requests القديم ──────────
_legacy_internet_requests_view = app.view_functions.get("admin_internet_requests_page")


@login_required
@permission_required("manage_internet_requests")
def _new_internet_requests_router():
    """الـ /admin/internet-requests: التصميم الجديد افتراضيًا، القديم عبر ?legacy=1"""
    if request.args.get("legacy") == "1" and _legacy_internet_requests_view is not None:
        return _legacy_internet_requests_view()
    return redirect(url_for("admin_request_center", type="internet", status=clean_csv_value(request.args.get("status")) or None))


if "admin_internet_requests_page" in app.view_functions:
    app.view_functions["admin_internet_requests_page"] = _new_internet_requests_router


_legacy_user_requests_view = app.view_functions.get("admin_users_account_requests")
_legacy_cards_pending_view = app.view_functions.get("admin_cards_pending")
_legacy_internet_request_detail_view = app.view_functions.get("admin_internet_request_detail_page")


def _redirect_user_requests_to_center():
    if request.args.get("legacy") == "1" and _legacy_user_requests_view is not None:
        return _legacy_user_requests_view()
    return redirect(
        url_for(
            "admin_request_center",
            type="user",
            status=clean_csv_value(request.args.get("status")) or None,
            beneficiary_id=clean_csv_value(request.args.get("beneficiary_id")) or None,
        )
    )


def _redirect_card_requests_to_center():
    if request.args.get("legacy") == "1" and _legacy_cards_pending_view is not None:
        return _legacy_cards_pending_view()
    return redirect(url_for("admin_request_center", type="card"))


def _redirect_internet_detail_to_center(request_id):
    if request.args.get("legacy") == "1" and _legacy_internet_request_detail_view is not None:
        return _legacy_internet_request_detail_view(request_id)
    return redirect(url_for("admin_request_center_detail", source="internet", request_id=request_id))


if _legacy_user_requests_view is not None:
    app.view_functions["admin_users_account_requests"] = admin_login_required(_redirect_user_requests_to_center)
if _legacy_cards_pending_view is not None:
    app.view_functions["admin_cards_pending"] = admin_login_required(_redirect_card_requests_to_center)
if _legacy_internet_request_detail_view is not None:
    app.view_functions["admin_internet_request_detail_page"] = admin_login_required(_redirect_internet_detail_to_center)
