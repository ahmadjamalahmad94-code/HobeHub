from flask import flash, redirect, render_template, request, session, url_for


OFFICIAL_CARD_CODES_SQL = "'half_hour','one_hour','two_hours','three_hours','four_hours'"


def _inventory_filters():
    category_code = clean_csv_value(request.args.get("category"))
    query = clean_csv_value(request.args.get("q"))
    state = clean_csv_value(request.args.get("state")) or "all"
    if state not in {"all", "available", "issued"}:
        state = "all"
    try:
        limit = int(request.args.get("limit") or 100)
    except (TypeError, ValueError):
        limit = 100
    limit = min(max(limit, 25), 500)
    return {"category": category_code, "q": query, "state": state, "limit": limit}


def _category_duration(category_code: str):
    if not category_code:
        return None
    row = query_one(
        f"""
        SELECT duration_minutes
        FROM card_categories
        WHERE code=%s AND code IN ({OFFICIAL_CARD_CODES_SQL})
        LIMIT 1
        """,
        [category_code],
    )
    return int(row["duration_minutes"]) if row else -1


def _available_where(filters):
    sql = """
    WHERE NOT EXISTS (
        SELECT 1 FROM beneficiary_issued_cards bic
        WHERE bic.card_username = mac.card_username
          AND bic.card_password = mac.card_password
    )
    """
    params = []
    duration = _category_duration(filters.get("category"))
    if duration is not None:
        if duration < 0:
            sql += " AND 1=0"
        else:
            sql += " AND mac.duration_minutes=%s"
            params.append(duration)
    if filters.get("q"):
        from app.services.smart_search import smart_search_clause

        clause, clause_params = smart_search_clause(
            filters["q"],
            text_columns=("mac.card_username", "mac.card_password"),
            extra_columns=("mac.source_file", "mac.imported_by_username"),
        )
        if clause:
            sql += " AND " + clause
            params.extend(clause_params)
    return sql, params


def _issued_where(filters):
    sql = "WHERE 1=1"
    params = []
    duration = _category_duration(filters.get("category"))
    if duration is not None:
        if duration < 0:
            sql += " AND 1=0"
        else:
            sql += " AND bic.duration_minutes=%s"
            params.append(duration)
    if filters.get("q"):
        from app.services.smart_search import smart_search_clause

        clause, clause_params = smart_search_clause(
            filters["q"],
            text_columns=("bic.card_username", "bic.card_password", "b.search_name", "b.full_name"),
            phone_columns=("b.phone",),
            extra_columns=("bic.issued_by",),
        )
        if clause:
            sql += " AND " + clause
            params.extend(clause_params)
    return sql, params


def _category_label_subquery(alias: str) -> str:
    return f"""
    (
        SELECT cc.label_ar
        FROM card_categories cc
        WHERE cc.duration_minutes = {alias}.duration_minutes
          AND cc.is_active = TRUE
          AND cc.code IN ({OFFICIAL_CARD_CODES_SQL})
        ORDER BY cc.display_order ASC, cc.id ASC
        LIMIT 1
    )
    """


def _available_cards(filters, limit):
    where_sql, params = _available_where(filters)
    rows = query_all(
        f"""
        SELECT
            'available' AS inventory_state,
            mac.id AS id,
            mac.id AS source_id,
            mac.duration_minutes,
            mac.card_username,
            mac.card_password,
            mac.source_file,
            mac.imported_by_username,
            mac.created_at,
            NULL AS issued_at,
            NULL AS issued_by,
            NULL AS beneficiary_id,
            NULL AS beneficiary_name,
            NULL AS beneficiary_phone,
            {_category_label_subquery('mac')} AS category_label
        FROM manual_access_cards mac
        {where_sql}
        ORDER BY mac.id DESC
        LIMIT %s
        """,
        [*params, int(limit)],
    )
    return [_enrich_inventory_row(row, None) for row in rows]


def _issued_cards(filters, limit):
    from app.services.card_status_service import get_card_statuses

    where_sql, params = _issued_where(filters)
    rows = query_all(
        f"""
        SELECT
            'issued' AS inventory_state,
            bic.id AS id,
            bic.id AS source_id,
            bic.duration_minutes,
            bic.card_username,
            bic.card_password,
            '' AS source_file,
            '' AS imported_by_username,
            NULL AS created_at,
            bic.issued_at,
            bic.issued_by,
            bic.beneficiary_id,
            b.full_name AS beneficiary_name,
            b.phone AS beneficiary_phone,
            {_category_label_subquery('bic')} AS category_label
        FROM beneficiary_issued_cards bic
        LEFT JOIN beneficiaries b ON b.id = bic.beneficiary_id
        {where_sql}
        ORDER BY bic.id DESC
        LIMIT %s
        """,
        [*params, int(limit)],
    )
    # ⚡ تحسين الأداء: لا نطلب usage لكل بطاقة (كان يستدعي RADIUS API
    # N مرة ويسبب بطء/فشل). نكتفي بقائمة الجلسات النشطة فقط (استدعاء واحد).
    # المدير يقدر يعمل تحديث لصف واحد عبر زر «حالة API» إذا أراد.
    try:
        statuses = get_card_statuses(rows, include_usage=False, usage_limit=0)
    except Exception:
        statuses = {}
    return [_enrich_inventory_row(row, statuses.get(int(row["id"]))) for row in rows]


def _enrich_inventory_row(row, status):
    item = dict(row)
    item["row_key"] = f"{item['inventory_state']}:{item['source_id']}"
    item["is_available"] = item["inventory_state"] == "available"
    item["inventory_state_label"] = "متاحة" if item["is_available"] else "تم الإصدار"
    if item["is_available"]:
        item["status"] = {
            "status": "available",
            "status_label": "متاحة للصرف",
            "is_online": False,
            "used_label": "0ث",
            "remaining_label": "كامل المدة",
            "last_seen_at": "",
            "started_at": "",
            "download_label": "0 B",
            "upload_label": "0 B",
            "total_data_label": "0 B",
            "framed_ip": "",
            "mac_address": "",
            "message": "",
        }
    else:
        item["status"] = status or {
            "status": "api_unavailable",
            "status_label": "تم الإصدار",
            "is_online": False,
            "used_label": "غير معروف",
            "remaining_label": "غير معروف",
            "last_seen_at": "",
            "started_at": "",
            "download_label": "غير معروف",
            "upload_label": "غير معروف",
            "total_data_label": "غير معروف",
            "framed_ip": "",
            "mac_address": "",
            "message": "لا توجد قراءة حية.",
        }
    return item


def _inventory_counts(filters):
    available_where, available_params = _available_where(filters)
    issued_where, issued_params = _issued_where(filters)
    available = query_one(f"SELECT COUNT(*) AS c FROM manual_access_cards mac {available_where}", available_params) or {}
    issued = query_one(
        f"""
        SELECT COUNT(*) AS c
        FROM beneficiary_issued_cards bic
        LEFT JOIN beneficiaries b ON b.id = bic.beneficiary_id
        {issued_where}
        """,
        issued_params,
    ) or {}
    return int(available.get("c") or 0), int(issued.get("c") or 0)


def _admin_cards_inventory_full():
    from app.services.card_dispatcher import get_inventory_counts
    from app.services.quota_engine import get_active_categories

    filters = _inventory_filters()
    available_count, issued_count = _inventory_counts(filters)
    per_side_limit = filters["limit"] if filters["state"] == "all" else filters["limit"]
    rows = []
    if filters["state"] in {"all", "available"}:
        rows.extend(_available_cards(filters, per_side_limit))
    if filters["state"] in {"all", "issued"}:
        rows.extend(_issued_cards(filters, per_side_limit))
    rows.sort(key=lambda row: str(row.get("issued_at") or row.get("created_at") or ""), reverse=True)
    rows = rows[: filters["limit"]]

    categories = get_inventory_counts()
    inventory_total = sum(int(c.get("available") or 0) for c in categories)
    return render_template(
        "admin/cards/inventory.html",
        categories=categories,
        active_categories=get_active_categories(),
        inventory_total=inventory_total,
        recent_cards=rows,
        filtered_total=available_count + issued_count,
        available_count=available_count,
        issued_count=issued_count,
        filters=filters,
    )


@app.route("/admin/cards/inventory/<int:card_id>/delete", methods=["POST"])
@admin_login_required
def admin_cards_inventory_delete_one(card_id):
    card = query_one("SELECT id, card_username FROM manual_access_cards WHERE id=%s LIMIT 1", [card_id])
    if not card:
        flash("البطاقة غير موجودة ضمن المتاح، أو تم إصدارها ولا يمكن حذفها من المخزون المتاح.", "error")
        return redirect(url_for("admin_cards_inventory_page"))
    execute_sql("DELETE FROM manual_access_cards WHERE id=%s", [card_id])
    log_action("delete_manual_card", "manual_access_cards", card_id, f"Deleted inventory card {card.get('card_username')}")
    flash("تم حذف البطاقة من المخزون المتاح.", "success")
    return redirect(request.referrer or url_for("admin_cards_inventory_page"))


@app.route("/admin/cards/inventory/delete-selected", methods=["POST"])
@admin_login_required
def admin_cards_inventory_delete_selected():
    ids = []
    for value in request.form.getlist("card_ids"):
        try:
            ids.append(int(value))
        except (TypeError, ValueError):
            continue
    ids = sorted(set(ids))
    if not ids:
        flash("حدد بطاقة واحدة على الأقل من البطاقات المتاحة.", "error")
        return redirect(request.referrer or url_for("admin_cards_inventory_page"))
    placeholders = ",".join(["%s"] * len(ids))
    count_row = query_one(f"SELECT COUNT(*) AS c FROM manual_access_cards WHERE id IN ({placeholders})", ids) or {}
    deleted_count = int(count_row.get("c") or 0)
    if deleted_count:
        execute_sql(f"DELETE FROM manual_access_cards WHERE id IN ({placeholders})", ids)
    log_action("delete_manual_cards_selected", "manual_access_cards", 0, f"Deleted selected inventory cards ids={ids}")
    flash(f"تم حذف {deleted_count} بطاقة متاحة. البطاقات الصادرة لا تُحذف من هنا.", "success")
    return redirect(request.referrer or url_for("admin_cards_inventory_page"))


@app.route("/admin/cards/inventory/delete-filtered", methods=["POST"])
@admin_login_required
def admin_cards_inventory_delete_filtered():
    category_code = clean_csv_value(request.form.get("category"))
    query_text = clean_csv_value(request.form.get("q"))
    confirm = clean_csv_value(request.form.get("confirm_delete"))
    if confirm not in {"حذف", "DELETE"}:
        flash("للحذف الجماعي اكتب حذف في خانة التأكيد.", "error")
        return redirect(url_for("admin_cards_inventory_page", category=category_code, q=query_text, state="available"))

    fake_args = {"category": category_code, "q": query_text, "state": "available", "limit": 500}
    where_sql, params = _available_where(fake_args)
    count_row = query_one(f"SELECT COUNT(*) AS c FROM manual_access_cards mac {where_sql}", params) or {}
    deleted_count = int(count_row.get("c") or 0)
    if deleted_count <= 0:
        flash("لا توجد بطاقات متاحة مطابقة للحذف.", "info")
        return redirect(url_for("admin_cards_inventory_page", category=category_code, q=query_text, state="available"))

    execute_sql(f"DELETE FROM manual_access_cards WHERE id IN (SELECT mac.id FROM manual_access_cards mac {where_sql})", params)
    log_action(
        "delete_manual_cards_filtered",
        "manual_access_cards",
        0,
        f"Deleted {deleted_count} available inventory cards category={category_code or '*'} q={query_text or '*'} by {session.get('username')}",
    )
    flash(f"تم حذف {deleted_count} بطاقة متاحة من المخزون. البطاقات الصادرة بقيت في السجل.", "success")
    return redirect(url_for("admin_cards_inventory_page"))


app.view_functions["admin_cards_inventory_page"] = admin_login_required(_admin_cards_inventory_full)
