# 48j_radius_schema_extension.py
# توسيع schema لمطابقة RADIUS:
#   - إضافة حقول جديدة لـ beneficiary_radius_accounts (password_md5, expires_at,
#     mac_address, data/time quotas, last_sync_at, sync_status)
#   - إنشاء جدول access_transitions لتدقيق التحويلات بين البطاقات واليوزر
#
# الفلسفة: idempotent — يمكن تشغيله بدون كسر. يضيف العمود فقط إن لم يكن موجودًا.

def _column_exists(table_name: str, column_name: str) -> bool:
    """فحص وجود عمود في جدول. يدعم SQLite + PostgreSQL."""
    try:
        if is_sqlite_database_url():
            rows = query_all(f"PRAGMA table_info({table_name})")
            return any((r.get("name") == column_name) for r in (rows or []))
        else:
            row = query_one(
                """
                SELECT 1 FROM information_schema.columns
                WHERE table_name=%s AND column_name=%s
                LIMIT 1
                """,
                [table_name, column_name],
            )
            return bool(row)
    except Exception:
        return False


def _add_column_if_missing(table_name: str, column_name: str, column_def: str) -> None:
    """إضافة عمود إن لم يكن موجودًا."""
    if _column_exists(table_name, column_name):
        return
    try:
        execute_sql(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_def}")
    except Exception:
        # تجاهل بصمت — نريد بدء التشغيل دون انهيار
        pass


def _ensure_radius_aligned_columns() -> None:
    """يضمن وجود الأعمدة المتوافقة مع RADIUS في beneficiary_radius_accounts."""
    table = "beneficiary_radius_accounts"
    cols = [
        ("password_md5",                 "TEXT DEFAULT ''"),
        ("plain_password",               "TEXT DEFAULT ''"),  # احتياط — تنظَّف بعد المزامنة
        ("mac_address",                  "TEXT DEFAULT ''"),
        ("expires_at",                   "TIMESTAMP NULL"),
        ("schedule_days",                "TEXT DEFAULT ''"),   # أيام الدوام: قائمة مفصولة بفواصل sun..sat
        ("schedule_from",                "TEXT DEFAULT ''"),   # بداية ساعات الدوام HH:MM
        ("schedule_to",                  "TEXT DEFAULT ''"),   # نهاية ساعات الدوام HH:MM
        ("data_quota_mb_total",          "BIGINT DEFAULT 0"),
        ("data_quota_mb_used",           "BIGINT DEFAULT 0"),
        ("time_quota_minutes_total",     "INTEGER DEFAULT 0"),
        ("time_quota_minutes_used",      "INTEGER DEFAULT 0"),
        ("last_sync_at",                 "TIMESTAMP NULL"),
        ("sync_status",                  "TEXT DEFAULT 'pending'"),  # pending|synced|failed
        ("sync_error",                   "TEXT DEFAULT ''"),
        ("notes",                        "TEXT DEFAULT ''"),
    ]
    # SQLite لا يعرف BIGINT/JSONB — استبدل
    for col_name, col_def in cols:
        actual_def = col_def
        if is_sqlite_database_url():
            actual_def = (
                col_def.replace("BIGINT", "INTEGER")
                       .replace("TIMESTAMP", "TIMESTAMP")
            )
        _add_column_if_missing(table, col_name, actual_def)


def _ensure_access_transitions_table() -> None:
    """جدول تدقيق التحويلات بين أنواع الوصول."""
    if is_sqlite_database_url():
        execute_sql("""
        CREATE TABLE IF NOT EXISTS access_transitions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            beneficiary_id INTEGER NOT NULL,
            from_mode TEXT NOT NULL,
            to_mode TEXT NOT NULL,
            from_state TEXT DEFAULT '',
            to_state TEXT DEFAULT '',
            performed_by TEXT DEFAULT '',
            reason TEXT DEFAULT '',
            api_synced INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        execute_sql("CREATE INDEX IF NOT EXISTS access_transitions_ben_idx ON access_transitions(beneficiary_id)")
    else:
        execute_sql("""
        CREATE TABLE IF NOT EXISTS access_transitions (
            id SERIAL PRIMARY KEY,
            beneficiary_id INTEGER NOT NULL REFERENCES beneficiaries(id) ON DELETE CASCADE,
            from_mode TEXT NOT NULL,
            to_mode TEXT NOT NULL,
            from_state TEXT DEFAULT '',
            to_state TEXT DEFAULT '',
            performed_by TEXT DEFAULT '',
            reason TEXT DEFAULT '',
            api_synced BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        execute_sql("CREATE INDEX IF NOT EXISTS access_transitions_ben_idx ON access_transitions(beneficiary_id)")


# نفّذ عند تحميل الـ legacy module
try:
    _ensure_radius_aligned_columns()
    _ensure_access_transitions_table()
except Exception:
    # لا نوقف بدء التطبيق إن فشلت الـ migration
    pass
