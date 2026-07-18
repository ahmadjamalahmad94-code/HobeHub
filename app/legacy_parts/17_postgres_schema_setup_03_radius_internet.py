# Split helper extracted from 17_postgres_schema_setup_01.py. Loaded by app.legacy.

def _setup_postgres_radius_internet_schema(cur):
    cur.execute("""
    CREATE TABLE IF NOT EXISTS radius_api_settings (
        id SERIAL PRIMARY KEY,
        base_url TEXT,
        master_api_key_encrypted TEXT,
        service_password_encrypted TEXT,
        admin_username TEXT,
        service_username TEXT,
        mode TEXT,
        read_enabled BOOLEAN,
        write_enabled BOOLEAN,
        verify_ssl BOOLEAN,
        router_login_url TEXT DEFAULT '',
        workday_start_time TEXT DEFAULT '08:00',
        workday_end_time TEXT DEFAULT '16:00',
        api_enabled BOOLEAN DEFAULT FALSE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    cur.execute("ALTER TABLE radius_api_settings ADD COLUMN IF NOT EXISTS master_api_key_encrypted TEXT")
    cur.execute("ALTER TABLE radius_api_settings ADD COLUMN IF NOT EXISTS admin_username TEXT")
    cur.execute("ALTER TABLE radius_api_settings ADD COLUMN IF NOT EXISTS service_username TEXT")
    cur.execute("ALTER TABLE radius_api_settings ADD COLUMN IF NOT EXISTS router_login_url TEXT DEFAULT ''")
    cur.execute("ALTER TABLE radius_api_settings ADD COLUMN IF NOT EXISTS workday_start_time TEXT DEFAULT '08:00'")
    cur.execute("ALTER TABLE radius_api_settings ADD COLUMN IF NOT EXISTS workday_end_time TEXT DEFAULT '16:00'")
    cur.execute("ALTER TABLE radius_api_settings ADD COLUMN IF NOT EXISTS timezone TEXT DEFAULT 'Asia/Gaza'")
    cur.execute("ALTER TABLE radius_api_settings ADD COLUMN IF NOT EXISTS long_card_approval_codes TEXT DEFAULT 'three_hours,four_hours'")
    cur.execute("ALTER TABLE radius_api_settings ADD COLUMN IF NOT EXISTS card_approval_timeout_minutes INTEGER DEFAULT 15")
    cur.execute("""CREATE TABLE IF NOT EXISTS card_approval_exemptions (
        beneficiary_id INTEGER PRIMARY KEY,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    cur.execute("ALTER TABLE radius_api_settings ADD COLUMN IF NOT EXISTS api_enabled BOOLEAN DEFAULT FALSE")
    cur.execute("ALTER TABLE radius_api_settings ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
    cur.execute("ALTER TABLE radius_api_settings ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
    # ── إعدادات اتصال قابلة للتبديل (Path 4) — NULL = ورِّث من env ──
    cur.execute("ALTER TABLE radius_api_settings ADD COLUMN IF NOT EXISTS service_password_encrypted TEXT")
    cur.execute("ALTER TABLE radius_api_settings ADD COLUMN IF NOT EXISTS mode TEXT")
    cur.execute("ALTER TABLE radius_api_settings ADD COLUMN IF NOT EXISTS api_flavor TEXT")
    cur.execute("ALTER TABLE radius_api_settings ADD COLUMN IF NOT EXISTS read_enabled BOOLEAN")
    cur.execute("ALTER TABLE radius_api_settings ADD COLUMN IF NOT EXISTS write_enabled BOOLEAN")
    cur.execute("ALTER TABLE radius_api_settings ADD COLUMN IF NOT EXISTS verify_ssl BOOLEAN")

    # ── هوية النسخة (white-label) — الاسم/الوسم فقط، الألوان تبقى ثابتة ──
    cur.execute("""
    CREATE TABLE IF NOT EXISTS app_branding (
        id SERIAL PRIMARY KEY,
        brand_name TEXT DEFAULT 'Hobe Hub',
        tagline TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS radius_api_sessions (
        id SERIAL PRIMARY KEY,
        api_key TEXT,
        expires_at TIMESTAMP NULL,
        last_login_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS beneficiary_radius_accounts (
        id SERIAL PRIMARY KEY,
        beneficiary_id INTEGER NOT NULL REFERENCES beneficiaries(id) ON DELETE CASCADE,
        external_user_id TEXT NULL,
        external_username TEXT,
        current_profile_id TEXT NULL,
        current_profile_name TEXT NULL,
        original_profile_id TEXT NULL,
        status TEXT DEFAULT 'pending',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS beneficiary_radius_accounts_beneficiary_idx ON beneficiary_radius_accounts (beneficiary_id)")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS internet_service_requests (
        id SERIAL PRIMARY KEY,
        beneficiary_id INTEGER NOT NULL REFERENCES beneficiaries(id) ON DELETE CASCADE,
        request_type TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        requested_payload JSONB DEFAULT '{}'::jsonb,
        admin_payload JSONB DEFAULT '{}'::jsonb,
        api_endpoint TEXT DEFAULT '',
        api_response JSONB DEFAULT '{}'::jsonb,
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
        id SERIAL PRIMARY KEY,
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
        id SERIAL PRIMARY KEY,
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
        id SERIAL PRIMARY KEY,
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
        id SERIAL PRIMARY KEY,
        beneficiary_id INTEGER NOT NULL REFERENCES beneficiaries(id) ON DELETE CASCADE,
        external_username TEXT NOT NULL,
        old_profile_id TEXT NULL,
        new_profile_id TEXT NULL,
        starts_at TIMESTAMP NOT NULL,
        ends_at TIMESTAMP NOT NULL,
        status TEXT NOT NULL DEFAULT 'active',
        restore_api_response JSONB DEFAULT '{}'::jsonb,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS beneficiary_portal_accounts (
        id SERIAL PRIMARY KEY,
        beneficiary_id INTEGER NOT NULL REFERENCES beneficiaries(id) ON DELETE CASCADE,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        is_active BOOLEAN DEFAULT TRUE,
        last_login_at TIMESTAMP NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS beneficiary_portal_accounts_beneficiary_idx ON beneficiary_portal_accounts (beneficiary_id)")
    cur.execute("ALTER TABLE beneficiary_portal_accounts ADD COLUMN IF NOT EXISTS must_set_password BOOLEAN DEFAULT TRUE")
    cur.execute("ALTER TABLE beneficiary_portal_accounts ADD COLUMN IF NOT EXISTS activation_code_hash TEXT")
    cur.execute("ALTER TABLE beneficiary_portal_accounts ADD COLUMN IF NOT EXISTS activation_code_expires_at TIMESTAMP NULL")
    cur.execute("ALTER TABLE beneficiary_portal_accounts ADD COLUMN IF NOT EXISTS activated_at TIMESTAMP NULL")
    cur.execute("ALTER TABLE beneficiary_portal_accounts ADD COLUMN IF NOT EXISTS last_activation_sent_at TIMESTAMP NULL")
    cur.execute("ALTER TABLE beneficiary_portal_accounts ADD COLUMN IF NOT EXISTS failed_login_attempts INTEGER DEFAULT 0")
    cur.execute("ALTER TABLE beneficiary_portal_accounts ADD COLUMN IF NOT EXISTS locked_until TIMESTAMP NULL")
    cur.execute("ALTER TABLE beneficiary_portal_accounts ADD COLUMN IF NOT EXISTS portal_membership_active BOOLEAN DEFAULT FALSE")
    cur.execute("ALTER TABLE beneficiary_portal_accounts ADD COLUMN IF NOT EXISTS portal_access_state TEXT DEFAULT 'active'")

    # Beneficiary <-> RADIUS match & sync engine.
    cur.execute("""
    CREATE TABLE IF NOT EXISTS radius_match_runs (
        id SERIAL PRIMARY KEY,
        status TEXT NOT NULL DEFAULT 'running',
        radius_mode TEXT DEFAULT '',
        total INTEGER NOT NULL DEFAULT 0,
        processed INTEGER NOT NULL DEFAULT 0,
        matched_count INTEGER NOT NULL DEFAULT 0,
        radius_only_count INTEGER NOT NULL DEFAULT 0,
        admin_like_count INTEGER NOT NULL DEFAULT 0,
        message TEXT DEFAULT '',
        started_by_account_id INTEGER,
        started_by_username TEXT DEFAULT '',
        started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        finished_at TIMESTAMP NULL,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS radius_match_candidates (
        id SERIAL PRIMARY KEY,
        run_id INTEGER NOT NULL REFERENCES radius_match_runs(id) ON DELETE CASCADE,
        direction TEXT NOT NULL DEFAULT 'hobehub_to_radius',
        beneficiary_id INTEGER NULL,
        beneficiary_name TEXT DEFAULT '',
        radius_username TEXT DEFAULT '',
        radius_external_id TEXT DEFAULT '',
        matched_phone TEXT DEFAULT '',
        radius_is_active BOOLEAN NOT NULL DEFAULT TRUE,
        classification TEXT NOT NULL DEFAULT 'subscriber',
        is_admin_like BOOLEAN NOT NULL DEFAULT FALSE,
        suggested_action TEXT DEFAULT 'review',
        selected_default BOOLEAN NOT NULL DEFAULT TRUE,
        applied BOOLEAN NOT NULL DEFAULT FALSE,
        applied_at TIMESTAMP NULL,
        apply_result TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS radius_match_candidates_run_idx ON radius_match_candidates (run_id)")
