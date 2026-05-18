# 48ae_quota_groups.py
# مجموعات السياسات (Quota Groups) — تجميع مستفيدين لتطبيق سياسة واحدة عليهم
# Schema + endpoints (create/edit/delete/members add/remove) + search beneficiaries

import logging
from flask import jsonify, render_template, request

_log = logging.getLogger("hobehub.quota_groups")


# ─── Schema (idempotent) — يستخدم نفس آلية كشف SQLite/Postgres
try:
    _IS_SQLITE = is_sqlite_database_url()
except Exception:
    _IS_SQLITE = True

_GRP_ID = "INTEGER PRIMARY KEY AUTOINCREMENT" if _IS_SQLITE else "SERIAL PRIMARY KEY"

for _stmt in (
    f"""CREATE TABLE IF NOT EXISTS quota_groups (
        id {_GRP_ID},
        name TEXT NOT NULL,
        description TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        created_by TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS quota_group_members (
        group_id INTEGER NOT NULL,
        beneficiary_id INTEGER NOT NULL,
        added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (group_id, beneficiary_id)
    )""",
    "CREATE INDEX IF NOT EXISTS qgm_group_idx ON quota_group_members(group_id)",
    "CREATE INDEX IF NOT EXISTS qgm_bid_idx ON quota_group_members(beneficiary_id)",
):
    try:
        execute_sql(_stmt)
    except Exception as e:
        msg = str(e).lower()
        if "already exists" in msg or "duplicate" in msg:
            _log.debug("quota_groups schema skipped (exists)")
        else:
            _log.warning("quota_groups schema failed: %s | %s", _stmt[:60], e)


# ─── Helpers
def _list_groups_with_counts():
    return query_all(
        """
        SELECT g.*,
               (SELECT COUNT(*) FROM quota_group_members m WHERE m.group_id = g.id) AS members_count
        FROM quota_groups g
        ORDER BY g.id DESC
        """
    ) or []


def _group_members(group_id):
    return query_all(
        """
        SELECT m.beneficiary_id, m.added_at, b.full_name, b.phone, b.user_type
        FROM quota_group_members m
        JOIN beneficiaries b ON b.id = m.beneficiary_id
        WHERE m.group_id=%s
        ORDER BY m.added_at DESC
        """,
        [group_id],
    ) or []


# ─── GET /admin/quota-groups — صفحة الإدارة
@app.route("/admin/quota-groups")
@admin_login_required
def admin_quota_groups_page():
    groups = _list_groups_with_counts()
    return render_template("admin/quota_groups/list.html", groups=groups)


# ─── GET /admin/quota-groups/list-ajax — للاستخدام في dropdown السياسة
@app.route("/admin/quota-groups/list-ajax")
@admin_login_required
def admin_quota_groups_list_ajax():
    groups = _list_groups_with_counts()
    return jsonify({
        "ok": True,
        "groups": [
            {"id": g["id"], "name": g.get("name") or "", "members_count": int(g.get("members_count") or 0)}
            for g in groups
        ],
    })


# ─── POST /admin/quota-groups/create
@app.route("/admin/quota-groups/create", methods=["POST"])
@admin_login_required
def admin_quota_groups_create():
    name = clean_csv_value(request.form.get("name") or "")
    description = clean_csv_value(request.form.get("description") or "")
    if not name:
        return jsonify({"ok": False, "message": "اسم المجموعة مطلوب."}), 400
    row = execute_sql(
        "INSERT INTO quota_groups (name, description, created_by) VALUES (%s, %s, %s) RETURNING id",
        [name, description, session.get("username") or ""],
        fetchone=True,
    )
    new_id = row["id"] if row else None
    log_action("quota_group_create", "quota_groups", new_id, f"إنشاء مجموعة: {name}")
    return jsonify({"ok": True, "message": "تم إنشاء المجموعة.", "id": new_id})


# ─── POST /admin/quota-groups/<id>/edit
@app.route("/admin/quota-groups/<int:group_id>/edit", methods=["POST"])
@admin_login_required
def admin_quota_groups_edit(group_id):
    if not query_one("SELECT id FROM quota_groups WHERE id=%s", [group_id]):
        return jsonify({"ok": False, "message": "المجموعة غير موجودة."}), 404
    name = clean_csv_value(request.form.get("name") or "")
    description = clean_csv_value(request.form.get("description") or "")
    if not name:
        return jsonify({"ok": False, "message": "اسم المجموعة مطلوب."}), 400
    execute_sql("UPDATE quota_groups SET name=%s, description=%s WHERE id=%s", [name, description, group_id])
    log_action("quota_group_edit", "quota_groups", group_id, f"تعديل المجموعة: {name}")
    return jsonify({"ok": True, "message": "تم حفظ التعديلات."})


# ─── POST /admin/quota-groups/<id>/delete
@app.route("/admin/quota-groups/<int:group_id>/delete", methods=["POST"])
@admin_login_required
def admin_quota_groups_delete(group_id):
    if not query_one("SELECT id FROM quota_groups WHERE id=%s", [group_id]):
        return jsonify({"ok": False, "message": "المجموعة غير موجودة."}), 404
    execute_sql("DELETE FROM quota_group_members WHERE group_id=%s", [group_id])
    execute_sql("DELETE FROM quota_groups WHERE id=%s", [group_id])
    log_action("quota_group_delete", "quota_groups", group_id, "حذف المجموعة")
    return jsonify({"ok": True, "message": "تم حذف المجموعة."})


# ─── GET /admin/quota-groups/<id>/members — قائمة الأعضاء (JSON)
@app.route("/admin/quota-groups/<int:group_id>/members")
@admin_login_required
def admin_quota_group_members_list(group_id):
    g = query_one("SELECT * FROM quota_groups WHERE id=%s", [group_id])
    if not g:
        return jsonify({"ok": False, "message": "المجموعة غير موجودة."}), 404
    members = _group_members(group_id)
    return jsonify({
        "ok": True,
        "group": {"id": g["id"], "name": g.get("name"), "description": g.get("description") or ""},
        "members": [
            {
                "beneficiary_id": m["beneficiary_id"],
                "full_name": m.get("full_name") or "",
                "phone": m.get("phone") or "",
                "user_type": m.get("user_type") or "",
                "added_at": str(m.get("added_at") or ""),
            } for m in members
        ],
    })


# ─── POST /admin/quota-groups/<id>/members/add
@app.route("/admin/quota-groups/<int:group_id>/members/add", methods=["POST"])
@admin_login_required
def admin_quota_group_member_add(group_id):
    if not query_one("SELECT id FROM quota_groups WHERE id=%s", [group_id]):
        return jsonify({"ok": False, "message": "المجموعة غير موجودة."}), 404
    try:
        bid = int(clean_csv_value(request.form.get("beneficiary_id") or "0") or "0")
    except (TypeError, ValueError):
        bid = 0
    if bid <= 0:
        return jsonify({"ok": False, "message": "اختر المستفيد."}), 400
    ben = query_one("SELECT id, full_name FROM beneficiaries WHERE id=%s", [bid])
    if not ben:
        return jsonify({"ok": False, "message": "المستفيد غير موجود."}), 404
    dup = query_one(
        "SELECT 1 AS x FROM quota_group_members WHERE group_id=%s AND beneficiary_id=%s",
        [group_id, bid],
    )
    if dup:
        return jsonify({"ok": False, "message": "العضو موجود مسبقاً في المجموعة."}), 400
    execute_sql(
        "INSERT INTO quota_group_members (group_id, beneficiary_id) VALUES (%s, %s)",
        [group_id, bid],
    )
    log_action(
        "quota_group_member_add", "quota_groups", group_id,
        f"إضافة المستفيد {ben.get('full_name')} (#{bid})",
    )
    return jsonify({"ok": True, "message": f"تمت إضافة {ben.get('full_name')}."})


# ─── POST /admin/quota-groups/<id>/members/<bid>/remove
@app.route("/admin/quota-groups/<int:group_id>/members/<int:bid>/remove", methods=["POST"])
@admin_login_required
def admin_quota_group_member_remove(group_id, bid):
    res = query_one(
        "SELECT 1 AS x FROM quota_group_members WHERE group_id=%s AND beneficiary_id=%s",
        [group_id, bid],
    )
    if not res:
        return jsonify({"ok": False, "message": "العضو غير موجود."}), 404
    execute_sql(
        "DELETE FROM quota_group_members WHERE group_id=%s AND beneficiary_id=%s",
        [group_id, bid],
    )
    log_action("quota_group_member_remove", "quota_groups", group_id, f"إزالة المستفيد #{bid}")
    return jsonify({"ok": True, "message": "تم إزالة العضو."})


# ─── GET /admin/beneficiaries/search — البحث بالاسم/الجوال (JSON) لاستخدام modal السياسة
@app.route("/admin/beneficiaries/search")
@admin_login_required
def admin_beneficiaries_search():
    q = clean_csv_value(request.args.get("q") or "")
    if not q or len(q) < 2:
        return jsonify({"ok": True, "results": []})
    from app.services.smart_search import smart_search_clause

    clause, params = smart_search_clause(
        q,
        text_columns=("search_name", "full_name"),
        phone_columns=("phone",),
        extra_columns=("tawjihi_year", "tawjihi_branch", "university_number"),
    )
    if q.strip().isdigit():
        if clause:
            clause = f"({clause} OR CAST(id AS TEXT) = %s)"
            params.append(q.strip())
        else:
            clause = "CAST(id AS TEXT) = %s"
            params = [q.strip()]
    rows = query_all(
        f"""
        SELECT id, full_name, phone, user_type
        FROM beneficiaries
        WHERE {clause or "1=0"}
        ORDER BY id DESC
        LIMIT 12
        """,
        params,
    ) or []
    return jsonify({
        "ok": True,
        "results": [
            {"id": r["id"], "full_name": r.get("full_name") or "—",
             "phone": r.get("phone") or "—", "user_type": r.get("user_type") or ""}
            for r in rows
        ],
    })
