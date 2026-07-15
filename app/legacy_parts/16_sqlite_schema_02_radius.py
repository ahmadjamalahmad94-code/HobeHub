# Split helper extracted from 16_sqlite_schema.py. Loaded by app.legacy.

def _setup_sqlite_radius_schema(cur):
    cur.execute("""
    CREATE TABLE IF NOT EXISTS radius_api_settings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        base_url TEXT,
        master_api_key_encrypted TEXT,
        service_password_encrypted TEXT,
        admin_username TEXT,
        service_username TEXT,
        mode TEXT,
        read_enabled INTEGER,
        write_enabled INTEGER,
        verify_ssl INTEGER,
        router_login_url TEXT DEFAULT '',
        workday_start_time TEXT DEFAULT '08:00',
        workday_end_time TEXT DEFAULT '16:00',
        api_enabled INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    try:
        cur.execute("ALTER TABLE radius_api_settings ADD COLUMN router_login_url TEXT DEFAULT ''")
    except Exception:
        pass
    try:
        cur.execute("ALTER TABLE radius_api_settings ADD COLUMN admin_username TEXT")
    except Exception:
        pass
    try:
        cur.execute("ALTER TABLE radius_api_settings ADD COLUMN service_username TEXT")
    except Exception:
        pass
    try:
        cur.execute("ALTER TABLE radius_api_settings ADD COLUMN api_enabled INTEGER DEFAULT 0")
    except Exception:
        pass
    try:
        cur.execute("ALTER TABLE radius_api_settings ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
    except Exception:
        pass
    try:
        cur.execute("ALTER TABLE radius_api_settings ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
    except Exception:
        pass
    try:
        cur.execute("ALTER TABLE radius_api_settings ADD COLUMN workday_start_time TEXT DEFAULT '08:00'")
    except Exception:
        pass
    try:
        cur.execute("ALTER TABLE radius_api_settings ADD COLUMN workday_end_time TEXT DEFAULT '16:00'")
    except Exception:
        pass
    try:
        cur.execute("ALTER TABLE radius_api_settings ADD COLUMN timezone TEXT DEFAULT 'Asia/Gaza'")
    except Exception:
        pass
    try:
        cur.execute("ALTER TABLE radius_api_settings ADD COLUMN long_card_approval_codes TEXT DEFAULT 'three_hours,four_hours'")
    except Exception:
        pass
    try:
        cur.execute("""CREATE TABLE IF NOT EXISTS card_approval_exemptions (
            beneficiary_id INTEGER PRIMARY KEY,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""")
    except Exception:
        pass
    # ── إعدادات اتصال قابلة للتبديل (Path 4) — nullable = ورِّث من env ──
    for _col, _def in (
        ("service_password_encrypted", "TEXT"),
        ("mode", "TEXT"),
        ("api_flavor", "TEXT"),
        ("read_enabled", "INTEGER"),
        ("write_enabled", "INTEGER"),
        ("verify_ssl", "INTEGER"),
    ):
        try:
            cur.execute(f"ALTER TABLE radius_api_settings ADD COLUMN {_col} {_def}")
        except Exception:
            pass

    # ── هوية النسخة (white-label) — الاسم/الوسم فقط، الألوان تبقى ثابتة ──
    cur.execute("""
    CREATE TABLE IF NOT EXISTS app_branding (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        brand_name TEXT DEFAULT 'Hobe Hub',
        tagline TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS radius_api_sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        api_key TEXT,
        expires_at TIMESTAMP NULL,
        last_login_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS beneficiary_radius_accounts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
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

    # Beneficiary <-> RADIUS match & sync engine.
    cur.execute("""
    CREATE TABLE IF NOT EXISTS radius_match_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
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
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id INTEGER NOT NULL REFERENCES radius_match_runs(id) ON DELETE CASCADE,
        direction TEXT NOT NULL DEFAULT 'hobehub_to_radius',
        beneficiary_id INTEGER NULL,
        beneficiary_name TEXT DEFAULT '',
        radius_username TEXT DEFAULT '',
        radius_external_id TEXT DEFAULT '',
        matched_phone TEXT DEFAULT '',
        radius_is_active INTEGER NOT NULL DEFAULT 1,
        classification TEXT NOT NULL DEFAULT 'subscriber',
        is_admin_like INTEGER NOT NULL DEFAULT 0,
        suggested_action TEXT DEFAULT 'review',
        selected_default INTEGER NOT NULL DEFAULT 1,
        applied INTEGER NOT NULL DEFAULT 0,
        applied_at TIMESTAMP NULL,
        apply_result TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS radius_match_candidates_run_idx ON radius_match_candidates (run_id)")
