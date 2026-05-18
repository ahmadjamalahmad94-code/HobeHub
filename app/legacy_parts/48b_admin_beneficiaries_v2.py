# /beneficiaries بالتصميم الجديد — override يستخدم القالب الجديد بدل البناء اليدوي.

from urllib.parse import urlencode as _urlencode
from flask import redirect, render_template, request, url_for


def _enrich_beneficiary_rows(rows):
    from app.dashboard.services import get_beneficiary_access_label, get_beneficiary_access_mode
    from app.services.access_rules import ACCESS_LABELS, can_switch_to

    enriched = []
    for row in rows or []:
        item = dict(row)
        access_mode = get_beneficiary_access_mode(item)
        target_mode = "username" if access_mode == "cards" else "cards"
        can_switch, switch_reason = can_switch_to((item.get("user_type") or "").strip().lower(), target_mode)
        portal_id = item.get("portal_account_id")
        is_active = item.get("portal_is_active")
        must_set_password = item.get("portal_must_set_password")
        if not portal_id:
            portal_status = "none"
            portal_status_label = "لا يوجد"
        elif must_set_password:
            portal_status = "reset"
            portal_status_label = "مصفّر"
        elif is_active:
            portal_status = "active"
            portal_status_label = "نشط"
        else:
            portal_status = "disabled"
            portal_status_label = "معطّل"
        item.update({
            "access_mode": access_mode,
            "access_label": get_beneficiary_access_label(item),
            "switch_target_mode": target_mode,
            "switch_target_label": ACCESS_LABELS.get(target_mode, target_mode),
            "can_switch_access": can_switch,
            "switch_block_reason": switch_reason,
            "portal_status": portal_status,
            "portal_status_label": portal_status_label,
        })
        enriched.append(item)
    return enriched


def _admin_beneficiaries_v2_view():
    """قائمة المستفيدين بالـ unified sidebar."""
    import math as _math

    # نستخدم نفس الـ helpers الموجودة
    args_dict = build_request_args_dict()
    if (request.args.get("segment") or "").strip() == "username":
        query_args = {}
        if request.args.get("q"):
            query_args["q"] = request.args.get("q")
        if request.args.get("user_type") in ("university", "freelancer"):
            query_args["user_type"] = request.args.get("user_type")
        target = "/admin/users-account"
        if query_args:
            target += "?" + _urlencode(query_args)
        return redirect(target, code=302)
    try:
        page = max(1, int(request.args.get("page", "1") or "1"))
    except ValueError:
        page = 1
    per_page = 25

    filter_clauses, params = build_beneficiary_filters(args_dict)
    where = " AND ".join(filter_clauses) if filter_clauses else "1=1"

    total = (query_one(f"SELECT COUNT(*) AS c FROM beneficiaries WHERE {where}", params) or {}).get("c") or 0
    total = int(total)
    pages = max(1, _math.ceil(total / per_page))
    page = min(page, pages)
    offset = (page - 1) * per_page

    rows = query_all(
        f"""
        SELECT b.*,
               pa.id AS portal_account_id,
               pa.username AS portal_username,
               pa.is_active AS portal_is_active,
               pa.must_set_password AS portal_must_set_password,
               pa.last_login_at AS portal_last_login_at
        FROM beneficiaries b
        LEFT JOIN beneficiary_portal_accounts pa ON pa.beneficiary_id = b.id
             AND COALESCE(pa.portal_membership_active, FALSE)=TRUE
        WHERE {where}
        ORDER BY b.id DESC
        LIMIT %s OFFSET %s
        """,
        params + [per_page, offset],
    )
    rows = _enrich_beneficiary_rows(rows)

    # KPIs لكل نوع
    def _count(user_type=None):
        if user_type:
            row = query_one("SELECT COUNT(*) AS c FROM beneficiaries WHERE user_type=%s", [user_type]) or {}
        else:
            row = query_one("SELECT COUNT(*) AS c FROM beneficiaries") or {}
        return int(row.get("c") or 0)

    kpi_total = _count()
    kpi_tawjihi = _count("tawjihi")
    kpi_university = _count("university")
    kpi_freelancer = _count("freelancer")
    kpi_cards = int((query_one("""
        SELECT COUNT(*) AS c FROM beneficiaries
        WHERE user_type='tawjihi'
           OR (user_type='university' AND COALESCE(university_internet_method, '') NOT IN ('يوزر إنترنت', 'يمتلك اسم مستخدم', 'username'))
           OR (user_type='freelancer' AND COALESCE(freelancer_internet_method, '') NOT IN ('يوزر إنترنت', 'يمتلك اسم مستخدم', 'username'))
    """) or {}).get("c") or 0)
    kpi_username = int((query_one("""
        SELECT COUNT(*) AS c FROM beneficiaries
        WHERE (user_type='university' AND COALESCE(university_internet_method, '') IN ('يوزر إنترنت', 'يمتلك اسم مستخدم', 'username'))
           OR (user_type='freelancer' AND COALESCE(freelancer_internet_method, '') IN ('يوزر إنترنت', 'يمتلك اسم مستخدم', 'username'))
    """) or {}).get("c") or 0)
    # مستخدمو البوابة — إجمالي الصفوف في beneficiary_portal_accounts (داخل البوابة)
    try:
        kpi_portal = int((query_one(
            "SELECT COUNT(*) AS c FROM beneficiary_portal_accounts WHERE COALESCE(portal_membership_active, FALSE)=TRUE"
        ) or {}).get("c") or 0)
    except Exception:
        kpi_portal = 0

    # قوائم القيم المميزة للفلاتر — تعالج list of strings أو list of dicts
    def _flatten(seq):
        out = []
        for x in (seq or []):
            if isinstance(x, dict):
                v = x.get("value") or next(iter(x.values()), "")
            else:
                v = x
            if v:
                out.append(str(v))
        return out

    tawjihi_years = _flatten(distinct_values("tawjihi_year", "tawjihi"))
    tawjihi_branches = _flatten(distinct_values("tawjihi_branch", "tawjihi"))
    university_names = _flatten(distinct_values("university_name", "university"))

    # helpers لبناء querystrings للروابط
    def _build_query(overrides=None):
        d = dict(args_dict or {})
        if overrides:
            d.update(overrides)
        d = {k: v for k, v in d.items() if v not in (None, "", "id", "desc")}
        return _urlencode(d, doseq=True)

    def make_tab_query(user_type):
        return _build_query({"user_type": user_type, "page": 1})

    def make_page_query(p):
        return _build_query({"page": p})

    return render_template(
        "admin/beneficiaries/list.html",
        beneficiaries=rows,
        total=total,
        page=page,
        pages=pages,
        filters={
            "q": args_dict.get("q", ""),
            "user_type": args_dict.get("user_type", ""),
            "tawjihi_year": args_dict.get("tawjihi_year", ""),
            "tawjihi_branch": args_dict.get("tawjihi_branch", ""),
            "university_name": args_dict.get("university_name", ""),
            "segment": args_dict.get("segment", ""),
            "has_portal": args_dict.get("has_portal", ""),
        },
        kpi_total=kpi_total,
        kpi_tawjihi=kpi_tawjihi,
        kpi_university=kpi_university,
        kpi_freelancer=kpi_freelancer,
        kpi_cards=kpi_cards,
        kpi_username=kpi_username,
        kpi_portal=kpi_portal,
        tawjihi_years=tawjihi_years,
        tawjihi_branches=tawjihi_branches,
        university_names=university_names,
        make_tab_query=make_tab_query,
        make_page_query=make_page_query,
        format_dt_short=format_dt_short,
    )


# ─── route جديد + alias ──────────────────────────────────────
@app.route("/admin/beneficiaries-new", methods=["GET"], endpoint="admin_beneficiaries_v2")
@login_required
@permission_required("view")
def admin_beneficiaries_v2():
    return _admin_beneficiaries_v2_view()


# ─── Override /beneficiaries القديم ──────────────────────────
_legacy_beneficiaries_view = app.view_functions.get("beneficiaries_page")


@login_required
@permission_required("view")
def _new_beneficiaries_router():
    """الـ /beneficiaries: التصميم الجديد افتراضيًا، القديم عبر ?legacy=1"""
    if request.args.get("legacy") == "1" and _legacy_beneficiaries_view is not None:
        return _legacy_beneficiaries_view()
    return _admin_beneficiaries_v2_view()


if "beneficiaries_page" in app.view_functions:
    app.view_functions["beneficiaries_page"] = _new_beneficiaries_router
