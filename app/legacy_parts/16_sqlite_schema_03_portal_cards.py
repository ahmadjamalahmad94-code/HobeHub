# Split helper extracted from 16_sqlite_schema.py. Loaded by app.legacy.

def _setup_sqlite_portal_card_schema(cur):
    cur.execute("""
    CREATE TABLE IF NOT EXISTS internet_service_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        beneficiary_id INTEGER NOT NULL REFERENCES beneficiaries(id) ON DELETE CASCADE,
        request_type TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        requested_payload TEXT DEFAULT '{}',
        admin_payload TEXT DEFAULT '{}',
        api_endpoint TEXT DEFAULT '',
        api_response TEXT DEFAULT '{}',
        error_message TEXT DEFAULT '',
        requested_by TEXT DEFAULT '',
        reviewed_by TEXT DEFAULT '',
        reviewed_at TIMESTAMP NULL,
        executed_at TIMESTAMP NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS beneficiary_signup_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        phone TEXT NOT NULL,
        first_name TEXT,
        second_name TEXT,
        third_name TEXT,
        fourth_name TEXT,
        full_name TEXT,
        search_name TEXT,
        user_type TEXT NOT NULL,
        tawjihi_year TEXT,
        university_name TEXT,
        university_major TEXT,
        university_number TEXT,
        freelancer_type TEXT,
        freelancer_specialization TEXT,
        freelancer_field TEXT,
        company_proof TEXT,
        company_name TEXT,
        summary_note TEXT DEFAULT '',
        notes TEXT DEFAULT '',
        status TEXT NOT NULL DEFAULT 'pending',
        reviewed_by TEXT DEFAULT '',
        reviewed_at TIMESTAMP NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS manual_access_cards (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        duration_minutes INTEGER NOT NULL,
        card_username TEXT NOT NULL,
        card_password TEXT NOT NULL,
        source_file TEXT DEFAULT '',
        imported_by_username TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS beneficiary_issued_cards (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        beneficiary_id INTEGER NOT NULL REFERENCES beneficiaries(id) ON DELETE CASCADE,
        duration_minutes INTEGER NOT NULL,
        card_username TEXT NOT NULL,
        card_password TEXT NOT NULL,
        request_id INTEGER NULL,
        issued_by TEXT DEFAULT 'system',
        router_login_url_snapshot TEXT DEFAULT '',
        issued_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS temporary_speed_upgrades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        beneficiary_id INTEGER NOT NULL REFERENCES beneficiaries(id) ON DELETE CASCADE,
        external_username TEXT NOT NULL,
        old_profile_id TEXT NULL,
        new_profile_id TEXT NULL,
        starts_at TIMESTAMP NOT NULL,
        ends_at TIMESTAMP NOT NULL,
        status TEXT NOT NULL DEFAULT 'active',
        restore_api_response TEXT DEFAULT '{}',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS beneficiary_portal_accounts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        beneficiary_id INTEGER NOT NULL REFERENCES beneficiaries(id) ON DELETE CASCADE,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        is_active INTEGER DEFAULT 1,
        last_login_at TIMESTAMP NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS beneficiary_portal_accounts_beneficiary_idx ON beneficiary_portal_accounts (beneficiary_id)")

    _sqlite_add_column_if_missing(cur, "beneficiary_portal_accounts", "must_set_password INTEGER DEFAULT 1")
    _sqlite_add_column_if_missing(cur, "beneficiary_portal_accounts", "activation_code_hash TEXT")
    _sqlite_add_column_if_missing(cur, "beneficiary_portal_accounts", "activation_code_expires_at TIMESTAMP NULL")
    _sqlite_add_column_if_missing(cur, "beneficiary_portal_accounts", "activated_at TIMESTAMP NULL")
    _sqlite_add_column_if_missing(cur, "beneficiary_portal_accounts", "last_activation_sent_at TIMESTAMP NULL")
    _sqlite_add_column_if_missing(cur, "beneficiary_portal_accounts", "failed_login_attempts INTEGER DEFAULT 0")
    _sqlite_add_column_if_missing(cur, "beneficiary_portal_accounts", "locked_until TIMESTAMP NULL")
    _sqlite_add_column_if_missing(cur, "beneficiary_portal_accounts", "portal_membership_active INTEGER DEFAULT 0")
    _sqlite_add_column_if_missing(cur, "beneficiary_portal_accounts", "portal_access_state TEXT DEFAULT 'active'")
