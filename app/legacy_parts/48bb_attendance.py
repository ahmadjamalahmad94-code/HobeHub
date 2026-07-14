# صفحة «الحضور والغياب» — من حضر كل أسبوع:
#   • البطاقات: من سجل البطاقات المحلّيّ (أيّ يوم/ساعة أخذ بطاقة).
#   • الإنترنت: جلسات الريديوس (متى دخل/خرج كل يوم ومدّته).
# مع اسم/جوّال/نوع/تخصص/جامعة-شركة، فلترة بمدى زمنيّ، وتصدير CSV.

import csv as _csv
import io as _io
from datetime import datetime as _dt
from flask import render_template, request, Response

_TYPE_LABEL = {"university": "جامعي", "freelancer": "عمل حر", "tawjihi": "توجيهي"}
_AR_DAYS = ["الإثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]


def _spec_of(b):
    t = (b.get("user_type") or "").lower()
    if t == "university":
        return b.get("university_specialization") or ""
    if t == "freelancer":
        return b.get("freelancer_specialization") or ""
    if t == "tawjihi":
        return b.get("tawjihi_branch") or ""
    return ""


def _org_of(b):
    t = (b.get("user_type") or "").lower()
    if t == "university":
        return b.get("university_name") or ""
    if t == "freelancer":
        return b.get("freelancer_company") or ""
    if t == "tawjihi":
        return str(b.get("tawjihi_year") or "")
    return ""


def _day_name(date_str):
    try:
        return _AR_DAYS[_dt.fromisoformat(str(date_str)[:10]).weekday()]
    except Exception:
        return ""


def _hm(value):
    """يستخرج HH:MM من طابع زمنيّ نصّيّ."""
    s = str(value or "")
    if "T" in s:
        s = s.split("T", 1)[1]
    elif " " in s:
        s = s.split(" ", 1)[1]
    return s[:5] if len(s) >= 5 else s


def _attendance_range():
    d_from = clean_csv_value(request.args.get("from"))
    d_to = clean_csv_value(request.args.get("to"))
    today = today_local()
    if not d_from:
        d_from = str(get_week_start(today))
    if not d_to:
        d_to = str(today)
    return d_from, d_to


def _cards_attendance(d_from, d_to):
    rows = query_all(
        """
        SELECT l.usage_date, l.usage_time, l.card_type, l.usage_reason,
               b.full_name, b.phone, b.user_type,
               b.university_name, b.university_specialization,
               b.freelancer_company, b.freelancer_specialization,
               b.tawjihi_year, b.tawjihi_branch
        FROM beneficiary_usage_logs l
        JOIN beneficiaries b ON b.id = l.beneficiary_id
        WHERE l.usage_date >= %s AND l.usage_date <= %s
        ORDER BY l.usage_time DESC
        LIMIT 3000
        """,
        [d_from, d_to],
    )
    out = []
    for r in rows:
        out.append({
            "full_name": r.get("full_name") or "—",
            "phone": r.get("phone") or "—",
            "type_label": _TYPE_LABEL.get((r.get("user_type") or "").lower(), r.get("user_type") or "—"),
            "spec": _spec_of(r) or "—",
            "org": _org_of(r) or "—",
            "day_name": _day_name(r.get("usage_date")),
            "date": str(r.get("usage_date") or "")[:10],
            "time": _hm(r.get("usage_time")),
            "card_type": r.get("card_type") or "—",
            "reason": r.get("usage_reason") or "—",
        })
    return out


def _internet_attendance(d_from, d_to):
    from app.services.radius_client import get_radius_client, is_api_under_development
    if is_api_under_development():
        return []
    try:
        client = get_radius_client()
        sessions = client.get_accounting_sessions(limit=500) if hasattr(client, "get_accounting_sessions") else []
    except Exception:
        sessions = []
    if not sessions:
        return []
    # خريطة اسم المستخدم (الجوّال/الخارجيّ) → مستفيد
    ben_map = {}
    try:
        for b in query_all(
            "SELECT b.id, b.full_name, b.phone, b.user_type, b.university_name, "
            "b.university_specialization, b.freelancer_company, b.freelancer_specialization, "
            "b.tawjihi_year, b.tawjihi_branch, r.external_username "
            "FROM beneficiaries b "
            "LEFT JOIN beneficiary_radius_accounts r ON r.beneficiary_id=b.id"):
            if b.get("phone"):
                ben_map[str(b["phone"]).strip()] = b
            if b.get("external_username"):
                ben_map[str(b["external_username"]).strip()] = b
    except Exception:
        ben_map = {}
    out = []
    for s in sessions:
        if not isinstance(s, dict):
            continue
        uname = str(s.get("username") or "").strip()
        start = s.get("started_at") or s.get("acctstarttime") or ""
        stop = s.get("stopped_at") or s.get("acctstoptime") or ""
        day = str(start)[:10]
        if day and (day < d_from or day > d_to):
            continue
        b = ben_map.get(uname) or {}
        secs = 0
        try:
            secs = int(s.get("duration_sec") or s.get("acctsessiontime") or 0)
        except (TypeError, ValueError):
            secs = 0
        out.append({
            "full_name": b.get("full_name") or "—",
            "phone": b.get("phone") or uname or "—",
            "username": uname,
            "type_label": _TYPE_LABEL.get((b.get("user_type") or "").lower(), b.get("user_type") or "—"),
            "spec": _spec_of(b) or "—",
            "org": _org_of(b) or "—",
            "day_name": _day_name(day),
            "date": day,
            "start": _hm(start),
            "stop": _hm(stop) if stop else "—",
            "duration": ("%dس %dد" % (secs // 3600, (secs % 3600) // 60)) if secs else "—",
        })
    out.sort(key=lambda x: (x["date"], x["start"]), reverse=True)
    return out


def _csv_response(filename, headers, rows_iter):
    buf = _io.StringIO()
    buf.write("﻿")  # BOM كي تفتح Excel العربيّة صحيحًا
    w = _csv.writer(buf)
    w.writerow(headers)
    for row in rows_iter:
        w.writerow(row)
    return Response(
        buf.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.route("/admin/attendance", methods=["GET"])
@login_required
@permission_required("view")
def admin_attendance_page():
    d_from, d_to = _attendance_range()
    export = clean_csv_value(request.args.get("export"))

    if export == "cards":
        rows = _cards_attendance(d_from, d_to)
        return _csv_response(
            f"attendance-cards-{d_from}_{d_to}.csv",
            ["الاسم", "الجوال", "النوع", "التخصص", "الجامعة/الشركة", "اليوم", "التاريخ", "الوقت", "نوع البطاقة", "السبب"],
            ([r["full_name"], r["phone"], r["type_label"], r["spec"], r["org"],
              r["day_name"], r["date"], r["time"], r["card_type"], r["reason"]] for r in rows),
        )
    if export == "internet":
        rows = _internet_attendance(d_from, d_to)
        return _csv_response(
            f"attendance-internet-{d_from}_{d_to}.csv",
            ["الاسم", "الجوال", "اسم المستخدم", "النوع", "التخصص", "الجامعة/الشركة", "اليوم", "التاريخ", "الدخول", "الخروج", "المدة"],
            ([r["full_name"], r["phone"], r["username"], r["type_label"], r["spec"], r["org"],
              r["day_name"], r["date"], r["start"], r["stop"], r["duration"]] for r in rows),
        )

    cards_rows = _cards_attendance(d_from, d_to)
    internet_rows = _internet_attendance(d_from, d_to)
    return render_template(
        "admin/attendance/list.html",
        d_from=d_from, d_to=d_to,
        cards_rows=cards_rows, internet_rows=internet_rows,
        cards_count=len(cards_rows), internet_count=len(internet_rows),
    )
