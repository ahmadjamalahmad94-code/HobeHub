# 48ax_portal_list_route.py
# GET /admin/beneficiaries/portal-stats   — إحصائيات حسابات البوابة (JSON)
# GET /admin/beneficiaries/portal-rows    — صفوف HTML للجدول (partial)

from flask import jsonify, render_template, request


# ══════════════════════════════════════════════════════
# GET /admin/beneficiaries/portal-stats
# ══════════════════════════════════════════════════════
@app.route("/admin/beneficiaries/portal-stats")
@login_required
def admin_portal_stats():
    stats = query_one("""
        SELECT
          COUNT(*) AS total,
          SUM(CASE WHEN is_active=TRUE  AND must_set_password=FALSE THEN 1 ELSE 0 END) AS active,
          SUM(CASE WHEN is_active=TRUE  AND must_set_password=TRUE  THEN 1 ELSE 0 END) AS reset_pw,
          SUM(CASE WHEN is_active=FALSE THEN 1 ELSE 0 END) AS disabled
        FROM beneficiary_portal_accounts
        WHERE COALESCE(portal_membership_active, FALSE)=TRUE
    """) or {}
    outside = query_one("""
        SELECT COUNT(*) AS c FROM beneficiaries
        WHERE id NOT IN (
            SELECT beneficiary_id FROM beneficiary_portal_accounts
            WHERE COALESCE(portal_membership_active, FALSE)=TRUE
        )
    """) or {}
    return jsonify({
        "ok": True,
        "total":    int(stats.get("total")    or 0),
        "active":   int(stats.get("active")   or 0),
        "reset":    int(stats.get("reset_pw") or 0),
        "disabled": int(stats.get("disabled") or 0),
        "outside":  int(outside.get("c")      or 0),
    })


# ══════════════════════════════════════════════════════
# GET /admin/beneficiaries/portal-rows
# ══════════════════════════════════════════════════════
@app.route("/admin/beneficiaries/portal-rows")
@login_required
def admin_portal_rows():
    q      = (request.args.get("q") or "").strip()
    status = (request.args.get("status") or "").strip()

    conditions = []
    params = []

    if q:
        conditions.append(
            "(b.full_name LIKE %s OR b.phone LIKE %s OR bpa.username LIKE %s)"
        )
        like = "%" + q + "%"
        params += [like, like, like]

    if status == "active":
        conditions.append("bpa.is_active=TRUE AND bpa.must_set_password=FALSE")
    elif status == "reset":
        conditions.append("bpa.is_active=TRUE AND bpa.must_set_password=TRUE")
    elif status == "disabled":
        conditions.append("bpa.is_active=FALSE")
    conditions.append("COALESCE(bpa.portal_membership_active, FALSE)=TRUE")

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    rows = query_all(f"""
        SELECT
          b.id, b.full_name, b.phone, b.user_type,
          b.university_internet_method, b.freelancer_internet_method,
          bpa.id          AS portal_id,
          bpa.username    AS portal_username,
          bpa.is_active,
          bpa.must_set_password,
          bpa.last_login_at
        FROM beneficiary_portal_accounts bpa
        JOIN beneficiaries b ON b.id = bpa.beneficiary_id
        {where}
        ORDER BY bpa.id DESC
        LIMIT 1000
    """, params)

    def _access_mode(r):
        ut = (r.get("user_type") or "").lower()
        if ut == "university":
            return "username" if (r.get("university_internet_method") or "") in ("يوزر إنترنت", "username") else "cards"
        if ut == "freelancer":
            return "username" if (r.get("freelancer_internet_method") or "") in ("يوزر إنترنت", "username") else "cards"
        return "cards"

    _fmt = globals().get("format_dt_short") or (lambda v: str(v) if v else "")
    enriched = []
    for r in rows:
        r = dict(r)
        r["access_mode"] = _access_mode(r)
        if not r.get("is_active"):
            r["portal_status"] = "disabled"
            r["portal_status_label"] = "معطّل"
        elif r.get("must_set_password"):
            r["portal_status"] = "reset"
            r["portal_status_label"] = "مصفّر"
        else:
            r["portal_status"] = "active"
            r["portal_status_label"] = "نشط"
        try:
            r["last_login_fmt"] = _fmt(r.get("last_login_at")) or "—"
        except Exception:
            r["last_login_fmt"] = "—"
        enriched.append(r)

    html = render_template(
        "admin/beneficiaries/_portal_rows_partial.html",
        rows=enriched,
        has_permission=has_permission,
    )
    return jsonify({"ok": True, "html": html, "count": len(enriched)})
