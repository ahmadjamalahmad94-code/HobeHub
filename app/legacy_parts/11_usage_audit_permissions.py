# Auto-split from app/legacy.py lines 2246-2345. Loaded by app.legacy.
def get_week_start(today=None):
    today = today or today_local()
    delta = (today.weekday() - 5) % 7
    return today - timedelta(days=delta)


def get_month_start(today=None):
    today = today or today_local()
    return today.replace(day=1)


def get_year_start(today=None):
    today = today or today_local()
    return today.replace(month=1, day=1)


def parse_date_or_none(value):
    value = clean_csv_value(value)
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def usage_logs_filters_from_request():
    return {
        "q": clean_csv_value(request.args.get("q", "")).strip(),
        "reason": clean_csv_value(request.args.get("reason", "")).strip(),
        "card_type": clean_csv_value(request.args.get("card_type", "")).strip(),
        "user_type": clean_csv_value(request.args.get("user_type", "")).strip(),
        "date_from": clean_csv_value(request.args.get("date_from", "")).strip(),
        "date_to": clean_csv_value(request.args.get("date_to", "")).strip(),
    }


def build_usage_logs_where(filters):
    where = ["1=1"]
    params = []
    if filters["q"]:
        from app.services.smart_search import smart_search_clause

        clause, clause_params = smart_search_clause(
            filters["q"],
            text_columns=("b.search_name", "b.full_name"),
            phone_columns=("b.phone",),
            extra_columns=("l.card_type", "l.usage_reason"),
        )
        if clause:
            where.append(clause)
            params.extend(clause_params)
    if filters["reason"]:
        where.append("l.usage_reason = %s")
        params.append(filters["reason"])
    if filters["card_type"]:
        where.append("l.card_type = %s")
        params.append(filters["card_type"])
    if filters["user_type"]:
        where.append("b.user_type = %s")
        params.append(filters["user_type"])
    date_from = parse_date_or_none(filters["date_from"])
    date_to = parse_date_or_none(filters["date_to"])
    if date_from:
        where.append("l.usage_date >= %s")
        params.append(date_from)
    if date_to:
        where.append("l.usage_date <= %s")
        params.append(date_to)
    return " AND ".join(where), params


def log_action(action_type, target_type="", target_id=None, details=""):
    if not session.get("account_id"):
        return
    execute_sql("""
        INSERT INTO audit_logs (account_id, username_snapshot, action_type, target_type, target_id, details)
        VALUES (%s,%s,%s,%s,%s,%s)
    """, [
        session.get("account_id"),
        session.get("username"),
        action_type,
        target_type,
        target_id,
        details,
    ])


def get_account_permissions(account_id):
    rows = query_all("""
        SELECT p.name
        FROM account_permissions ap
        JOIN permissions p ON p.id = ap.permission_id
        WHERE ap.account_id = %s
    """, [account_id])
    return [r["name"] for r in rows]


def refresh_session_permissions(account_id):
    session["permissions"] = get_account_permissions(account_id)


def has_permission(permission_name):
    aid = session.get("account_id")
    if not aid:
        return False
    refresh_session_permissions(aid)
    return permission_name in session.get("permissions", [])
