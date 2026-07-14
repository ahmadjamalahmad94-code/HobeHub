# /usage-logs بالتصميم الجديد — override يستخدم القالب الجديد بدل البناء اليدوي.

from flask import render_template, render_template_string, request, jsonify


def _admin_usage_logs_v2_view():
    """سجل البطاقات التفصيلي بالـ unified sidebar."""
    filters = usage_logs_filters_from_request()
    where, params = build_usage_logs_where(filters)

    rows = query_all(
        f"""
        SELECT l.*, b.full_name, b.phone, b.user_type,
               b.university_specialization,
               b.freelancer_specialization, b.tawjihi_branch
        FROM beneficiary_usage_logs l
        JOIN beneficiaries b ON b.id = l.beneficiary_id
        WHERE {where}
        ORDER BY l.usage_time DESC, l.id DESC
        LIMIT 500
        """,
        params,
    )
    # التخصص مشتقّ من نوع المستفيد: كليّة الجامعيّ / تخصّص العمل الحرّ / فرع التوجيهيّ.
    for _r in rows:
        _t = (_r.get("user_type") or "").lower()
        if _t == "university":
            _r["spec"] = _r.get("university_specialization") or ""
        elif _t == "freelancer":
            _r["spec"] = _r.get("freelancer_specialization") or ""
        elif _t == "tawjihi":
            _r["spec"] = _r.get("tawjihi_branch") or ""
        else:
            _r["spec"] = ""

    today = today_local()
    week_start = get_week_start(today)
    month_start = get_month_start(today)
    year_start = get_year_start(today)

    def _count_since(date_val):
        row = query_one(
            f"""
            SELECT COUNT(*) AS c FROM beneficiary_usage_logs l
            JOIN beneficiaries b ON b.id = l.beneficiary_id
            WHERE {where} AND l.usage_date >= %s
            """,
            params + [date_val],
        ) or {}
        return int(row.get("c") or 0)

    week_total = _count_since(week_start)
    month_total = _count_since(month_start)
    year_total = _count_since(year_start)
    archive_total = int(
        (query_one("SELECT COUNT(*) AS c FROM beneficiary_usage_logs_archive") or {}).get("c") or 0
    )

    # خيارات الفلاتر — مرّرها كقوائم بسيطة
    reason_options = list(USAGE_REASON_OPTIONS) if USAGE_REASON_OPTIONS else []
    card_options = list(CARD_TYPE_OPTIONS) if CARD_TYPE_OPTIONS else []

    can_archive = has_permission("archive_logs")
    can_clear = has_permission("backup")
    can_view_archive = has_permission("view_archive")

    # ─ AJAX mode: نرجّع JSON يحوي tbody HTML + counters ─
    if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.args.get("ajax") == "1":
        tbody_html = render_template_string(
            """{% for r in rows %}<tr class="usage-row">
  <td class="col-id">{{ loop.index }}</td>
  <td class="col-name">{{ r.full_name or '—' }}</td>
  <td class="col-phone">{{ r.phone or '—' }}</td>
  <td>{% if r.user_type == 'tawjihi' %}<span class="user-type-badge utype-tawjihi">توجيهي</span>{% elif r.user_type == 'university' %}<span class="user-type-badge utype-university">جامعي</span>{% elif r.user_type == 'freelancer' %}<span class="user-type-badge utype-freelancer">عمل حر</span>{% else %}—{% endif %}</td>
  <td class="col-spec">{{ r.spec or '—' }}</td>
  <td><span class="reason-tag">{{ r.usage_reason or '—' }}</span></td>
  <td><span class="card-tag">{{ r.card_type or '—' }}</span></td>
  <td class="col-when">{{ format_dt_short(r.usage_time) }}</td>
  <td style="font-size:11.5px;color:var(--d-text-soft)">{{ r.added_by_username or '—' }}</td>
  <td class="col-notes">{{ r.notes or '—' }}</td>
</tr>{% else %}<tr class="no-paginate"><td colspan="10" style="text-align:center;color:var(--d-text-muted);padding:30px">لا توجد بطاقات مطابقة.</td></tr>{% endfor %}""",
            rows=rows,
            format_dt_short=format_dt_short,
        )
        return jsonify({
            "ok": True,
            "tbody_html": tbody_html,
            "count": len(rows),
            "stats": {
                "week": week_total,
                "month": month_total,
                "year": year_total,
                "archive": archive_total,
            },
        })

    return render_template(
        "admin/usage_logs/list.html",
        rows=rows,
        filters=filters,
        week_total=week_total,
        month_total=month_total,
        year_total=year_total,
        archive_total=archive_total,
        reason_options=reason_options,
        card_options=card_options,
        can_archive=can_archive,
        can_clear=can_clear,
        can_view_archive=can_view_archive,
        format_dt_short=format_dt_short,
    )


# ─── Override /usage-logs القديم ──────────────────────────
_legacy_usage_logs_view = app.view_functions.get("usage_logs_page")


@login_required
@permission_required("view")
def _new_usage_logs_router():
    """الـ /usage-logs: التصميم الجديد افتراضيًا، القديم عبر ?legacy=1"""
    if request.args.get("legacy") == "1" and _legacy_usage_logs_view is not None:
        return _legacy_usage_logs_view()
    return _admin_usage_logs_v2_view()


if "usage_logs_page" in app.view_functions:
    app.view_functions["usage_logs_page"] = _new_usage_logs_router
