# /audit-log بالتصميم الجديد — override يستخدم القالب الجديد بدل البناء اليدوي.

from flask import render_template, request


# سقف الجلب من DB. الـ pagination يتم على المتصفح بدون reload.
_AUDIT_LOG_LIMIT = 1000


def _audit_log_v2_view():
    """سجل العمليات بالـ unified sidebar + client-side pagination."""
    total_row = query_one("SELECT COUNT(*) AS c FROM audit_logs") or {}
    total = int(total_row.get("c") or 0)

    rows = query_all(
        """
        SELECT * FROM audit_logs
        ORDER BY id DESC
        LIMIT %s
        """,
        [_AUDIT_LOG_LIMIT],
    )

    # إثراء: اسم المستفيد ورقم جوّاله في «التفاصيل» (للأهداف من نوع مستفيد).
    _BEN_TYPES = {"beneficiary", "beneficiary_login", "beneficiary_change_password"}
    _ben_ids = {
        int(r["target_id"]) for r in rows
        if r.get("target_type") in _BEN_TYPES and str(r.get("target_id") or "").isdigit()
    }
    _ben_map = {}
    if _ben_ids:
        _ph = ",".join(["%s"] * len(_ben_ids))
        for b in (query_all(
                f"SELECT id, full_name, phone FROM beneficiaries WHERE id IN ({_ph})",
                list(_ben_ids)) or []):
            _ben_map[b.get("id")] = b
    for r in rows:
        _b = None
        if r.get("target_type") in _BEN_TYPES and str(r.get("target_id") or "").isdigit():
            _b = _ben_map.get(int(r["target_id"]))
        r["ben_name"] = (_b or {}).get("full_name") or ""
        r["ben_phone"] = (_b or {}).get("phone") or ""

    return render_template(
        "admin/audit/list.html",
        rows=rows,
        total=total,
        loaded=len(rows),
        limit=_AUDIT_LOG_LIMIT,
        truncated=(total > _AUDIT_LOG_LIMIT),
        action_type_label=action_type_label,
        target_type_label=target_type_label,
        format_dt_compact=format_dt_compact,
    )


# ─── Override /audit-log القديم ──────────────────────────
_legacy_audit_log_view = app.view_functions.get("audit_log_page")


@login_required
@permission_required("view_audit_log")
def _new_audit_log_router():
    """الـ /audit-log: التصميم الجديد افتراضيًا، القديم عبر ?legacy=1"""
    if request.args.get("legacy") == "1" and _legacy_audit_log_view is not None:
        return _legacy_audit_log_view()
    return _audit_log_v2_view()


if "audit_log_page" in app.view_functions:
    app.view_functions["audit_log_page"] = _new_audit_log_router
