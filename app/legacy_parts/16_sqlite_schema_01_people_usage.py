# Split helper extracted from 16_sqlite_schema.py. Loaded by app.legacy.

def _setup_sqlite_people_usage_schema(cur):
    cur.execute("""
    CREATE TABLE IF NOT EXISTS beneficiaries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_type TEXT NOT NULL,
        first_name TEXT,
        second_name TEXT,
        third_name TEXT,
        fourth_name TEXT,
        full_name TEXT,
        search_name TEXT,
        phone TEXT,
        tawjihi_year TEXT,
        tawjihi_branch TEXT,
        freelancer_specialization TEXT,
        freelancer_company TEXT,
        freelancer_schedule_type TEXT,
        freelancer_internet_method TEXT,
        freelancer_time_mode TEXT,
        freelancer_time_from TEXT,
        freelancer_time_to TEXT,
        university_name TEXT,
        university_college TEXT,
        university_specialization TEXT,
        university_days TEXT,
        university_internet_method TEXT,
        university_time_mode TEXT,
        university_time_from TEXT,
        university_time_to TEXT,
        weekly_usage_count INTEGER DEFAULT 0,
        weekly_usage_week_start TEXT,
        notes TEXT DEFAULT '',
        added_by_account_id INTEGER,
        added_by_username TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    _sqlite_add_column_if_missing(cur, "beneficiaries", "university_number TEXT")
    _sqlite_add_column_if_missing(cur, "beneficiaries", "freelancer_type TEXT")
    _sqlite_add_column_if_missing(cur, "beneficiaries", "freelancer_field TEXT")
    _sqlite_add_column_if_missing(cur, "beneficiaries", "company_proof TEXT")
    _sqlite_add_column_if_missing(cur, "beneficiaries", "company_name TEXT")
    # RADIUS match engine - linked external radius account on the beneficiary.
    _sqlite_add_column_if_missing(cur, "beneficiaries", "linked_radius_username TEXT")
    _sqlite_add_column_if_missing(cur, "beneficiaries", "linked_radius_external_id TEXT")
    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS beneficiaries_phone_unique_idx ON beneficiaries (phone)")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS app_accounts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT,
        full_name TEXT DEFAULT '',
        is_active INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS permissions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS account_permissions (
        account_id INTEGER REFERENCES app_accounts(id) ON DELETE CASCADE,
        permission_id INTEGER REFERENCES permissions(id) ON DELETE CASCADE,
        PRIMARY KEY (account_id, permission_id)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS audit_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account_id INTEGER,
        username_snapshot TEXT,
        action_type TEXT,
        target_type TEXT,
        target_id INTEGER,
        details TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS beneficiary_usage_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        beneficiary_id INTEGER NOT NULL REFERENCES beneficiaries(id) ON DELETE CASCADE,
        usage_reason TEXT NOT NULL DEFAULT '',
        card_type TEXT NOT NULL DEFAULT 'ساعة',
        usage_date TEXT NOT NULL DEFAULT CURRENT_DATE,
        usage_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        notes TEXT DEFAULT '',
        added_by_account_id INTEGER,
        added_by_username TEXT DEFAULT ''
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS beneficiary_usage_logs_archive (
        archive_id INTEGER PRIMARY KEY AUTOINCREMENT,
        original_log_id INTEGER,
        beneficiary_id INTEGER,
        usage_reason TEXT NOT NULL DEFAULT '',
        card_type TEXT NOT NULL DEFAULT 'ساعة',
        usage_date TEXT NOT NULL DEFAULT CURRENT_DATE,
        usage_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        notes TEXT DEFAULT '',
        added_by_account_id INTEGER,
        added_by_username TEXT DEFAULT '',
        archived_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        archived_by_account_id INTEGER,
        archived_by_username TEXT DEFAULT ''
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS power_timer (
        id INTEGER PRIMARY KEY,
        duration_minutes INTEGER NOT NULL DEFAULT 30,
        cycle_started_at TIMESTAMP NULL,
        paused_remaining_seconds INTEGER NULL,
        auto_restart_delay_seconds INTEGER NOT NULL DEFAULT 10,
        state TEXT NOT NULL DEFAULT 'stopped',
        updated_by_username TEXT DEFAULT '',
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    cur.execute("INSERT OR IGNORE INTO power_timer (id, duration_minutes, auto_restart_delay_seconds, state, updated_by_username) VALUES (1, 30, 10, 'stopped', '')")
