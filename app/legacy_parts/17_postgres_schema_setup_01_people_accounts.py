# Split helper extracted from 17_postgres_schema_setup_01.py. Loaded by app.legacy.

def _setup_postgres_people_accounts_schema(cur):
    cur.execute("""
    CREATE TABLE IF NOT EXISTS beneficiaries (
        id SERIAL PRIMARY KEY,
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
        weekly_usage_week_start DATE,
        notes TEXT DEFAULT '',
        added_by_account_id INTEGER,
        added_by_username TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cur.execute("ALTER TABLE beneficiaries ADD COLUMN IF NOT EXISTS notes TEXT DEFAULT ''")
    cur.execute("ALTER TABLE beneficiaries ADD COLUMN IF NOT EXISTS added_by_account_id INTEGER")
    cur.execute("ALTER TABLE beneficiaries ADD COLUMN IF NOT EXISTS added_by_username TEXT DEFAULT ''")
    cur.execute("ALTER TABLE beneficiaries ADD COLUMN IF NOT EXISTS university_number TEXT")
    cur.execute("ALTER TABLE beneficiaries ADD COLUMN IF NOT EXISTS freelancer_type TEXT")
    cur.execute("ALTER TABLE beneficiaries ADD COLUMN IF NOT EXISTS freelancer_field TEXT")
    cur.execute("ALTER TABLE beneficiaries ADD COLUMN IF NOT EXISTS company_proof TEXT")
    cur.execute("ALTER TABLE beneficiaries ADD COLUMN IF NOT EXISTS company_name TEXT")
    # RADIUS match engine - linked external radius account on the beneficiary.
    cur.execute("ALTER TABLE beneficiaries ADD COLUMN IF NOT EXISTS linked_radius_username TEXT")
    cur.execute("ALTER TABLE beneficiaries ADD COLUMN IF NOT EXISTS linked_radius_external_id TEXT")
    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS beneficiaries_phone_unique_idx ON beneficiaries (phone) WHERE phone IS NOT NULL AND btrim(phone) <> ''")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS app_accounts (
        id SERIAL PRIMARY KEY,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT,
        full_name TEXT DEFAULT '',
        is_active BOOLEAN DEFAULT TRUE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # توافق مع قواعد بيانات قديمة كانت تحتوي أعمدة مختلفة أو ناقصة.
    cur.execute("ALTER TABLE app_accounts ADD COLUMN IF NOT EXISTS password_hash TEXT")
    cur.execute("ALTER TABLE app_accounts ADD COLUMN IF NOT EXISTS full_name TEXT DEFAULT ''")
    cur.execute("ALTER TABLE app_accounts ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE")
    cur.execute("ALTER TABLE app_accounts ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
    cur.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    cur.execute("""
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_name = 'app_accounts' AND column_name = 'password'
        )
    """)
    has_old_password_col = cur.fetchone()[0]
    if has_old_password_col:
        cur.execute("""
            UPDATE app_accounts
            SET password_hash = CASE
                WHEN password_hash IS NOT NULL AND btrim(password_hash) <> '' THEN password_hash
                WHEN password IS NULL OR btrim(password) = '' THEN NULL
                WHEN password ~ '^[a-f0-9]{64}$' THEN password
                ELSE encode(digest(password, 'sha256'), 'hex')
            END
            WHERE password_hash IS NULL OR btrim(password_hash) = ''
        """)

    initial_admin_password = get_initial_admin_password()
    if initial_admin_password:
        cur.execute("""
            UPDATE app_accounts
            SET password_hash = %s
            WHERE username = 'admin' AND (password_hash IS NULL OR btrim(password_hash) = '')
        """, [admin_password_hash(initial_admin_password)])
