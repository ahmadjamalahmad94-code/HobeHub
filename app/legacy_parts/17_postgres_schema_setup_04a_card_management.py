# Card management — extension migrations for PostgreSQL. Loaded by app.legacy.
# SAFE: CREATE TABLE IF NOT EXISTS only.

def _setup_postgres_card_management_schema(cur):
    """نسخة PostgreSQL من الجداول الإضافية لإدارة البطاقات."""

    cur.execute("""
    CREATE TABLE IF NOT EXISTS card_categories (
        id SERIAL PRIMARY KEY,
        code TEXT NOT NULL UNIQUE,
        label_ar TEXT NOT NULL,
        duration_minutes INTEGER NOT NULL,
        display_order INTEGER DEFAULT 100,
        is_active BOOLEAN DEFAULT TRUE,
        icon TEXT DEFAULT 'fa-clock',
        color_class TEXT DEFAULT 'd-badge',
        radius_profile_id TEXT DEFAULT '',
        notes TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS card_categories_active_idx ON card_categories (is_active, display_order)")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS beneficiary_groups (
        id SERIAL PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        description TEXT DEFAULT '',
        color_class TEXT DEFAULT 'd-badge--neutral',
        is_active BOOLEAN DEFAULT TRUE,
        created_by_account_id INTEGER NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS beneficiary_group_members (
        id SERIAL PRIMARY KEY,
        group_id INTEGER NOT NULL REFERENCES beneficiary_groups(id) ON DELETE CASCADE,
        beneficiary_id INTEGER NOT NULL REFERENCES beneficiaries(id) ON DELETE CASCADE,
        added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(group_id, beneficiary_id)
    )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS bg_members_beneficiary_idx ON beneficiary_group_members (beneficiary_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS bg_members_group_idx ON beneficiary_group_members (group_id)")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS card_quota_policies (
        id SERIAL PRIMARY KEY,
        scope TEXT NOT NULL CHECK (scope IN ('default','user','group')),
        target_id INTEGER NULL,
        daily_limit INTEGER NULL,
        weekly_limit INTEGER NULL,
        allowed_days TEXT DEFAULT '',
        allowed_category_codes TEXT DEFAULT '',
        valid_from DATE NULL,
        valid_until DATE NULL,
        valid_time_from TEXT DEFAULT '',
        valid_time_until TEXT DEFAULT '',
        priority INTEGER DEFAULT 100,
        is_active BOOLEAN DEFAULT TRUE,
        notes TEXT DEFAULT '',
        created_by_account_id INTEGER NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    cur.execute("ALTER TABLE card_quota_policies ADD COLUMN IF NOT EXISTS valid_time_from TEXT DEFAULT ''")
    cur.execute("ALTER TABLE card_quota_policies ADD COLUMN IF NOT EXISTS valid_time_until TEXT DEFAULT ''")
    cur.execute("CREATE INDEX IF NOT EXISTS cqp_scope_target_idx ON card_quota_policies (scope, target_id, is_active)")
    cur.execute("CREATE INDEX IF NOT EXISTS cqp_priority_idx ON card_quota_policies (priority)")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS card_audit_log (
        id SERIAL PRIMARY KEY,
        event_type TEXT NOT NULL,
        beneficiary_id INTEGER NULL,
        card_category_code TEXT DEFAULT '',
        issued_card_id INTEGER NULL,
        actor_account_id INTEGER NULL,
        actor_username TEXT DEFAULT '',
        actor_kind TEXT DEFAULT 'admin' CHECK (actor_kind IN ('admin','beneficiary','system')),
        details_json JSONB DEFAULT '{}'::jsonb,
        related_pending_action_id INTEGER NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS cal_beneficiary_idx ON card_audit_log (beneficiary_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS cal_event_idx ON card_audit_log (event_type)")
    cur.execute("CREATE INDEX IF NOT EXISTS cal_created_idx ON card_audit_log (created_at)")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS radius_pending_actions (
        id SERIAL PRIMARY KEY,
        action_type TEXT NOT NULL,
        target_kind TEXT DEFAULT '' CHECK (target_kind IN ('','user','card','profile','group','session')),
        target_external_id TEXT DEFAULT '',
        beneficiary_id INTEGER NULL,
        payload_json JSONB DEFAULT '{}'::jsonb,
        status TEXT NOT NULL DEFAULT 'pending'
            CHECK (status IN ('pending','in_progress','done','failed','cancelled')),
        attempted_by_mode TEXT DEFAULT 'manual'
            CHECK (attempted_by_mode IN ('manual','live')),
        api_endpoint TEXT DEFAULT '',
        api_response_json JSONB DEFAULT '{}'::jsonb,
        error_message TEXT DEFAULT '',
        notes TEXT DEFAULT '',
        requested_by_account_id INTEGER NULL,
        requested_by_username TEXT DEFAULT '',
        executed_by_account_id INTEGER NULL,
        executed_by_username TEXT DEFAULT '',
        requested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        executed_at TIMESTAMP NULL,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS rpa_status_idx ON radius_pending_actions (status, requested_at)")
    cur.execute("CREATE INDEX IF NOT EXISTS rpa_beneficiary_idx ON radius_pending_actions (beneficiary_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS rpa_action_type_idx ON radius_pending_actions (action_type)")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS notifications (
        id SERIAL PRIMARY KEY,
        recipient_type TEXT NOT NULL CHECK (recipient_type IN ('admin','beneficiary')),
        recipient_id INTEGER NULL,
        title TEXT NOT NULL,
        body TEXT DEFAULT '',
        event_type TEXT DEFAULT '',
        status TEXT DEFAULT '',
        source_type TEXT DEFAULT '',
        source_id INTEGER NULL,
        action_url TEXT DEFAULT '',
        actor_type TEXT DEFAULT '',
        actor_id INTEGER NULL,
        actor_name TEXT DEFAULT '',
        read_at TIMESTAMP NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS notifications_recipient_idx ON notifications (recipient_type, recipient_id, read_at, created_at)")
    cur.execute("CREATE INDEX IF NOT EXISTS notifications_source_idx ON notifications (source_type, source_id)")

    # ربط عروض HobeHub (الفئات) بعروض/باقات RADIUS الحقيقية — additive + idempotent.
    cur.execute("""
    CREATE TABLE IF NOT EXISTS card_offer_radius_links (
        id SERIAL PRIMARY KEY,
        category_code TEXT NOT NULL UNIQUE,
        radius_external_id TEXT NOT NULL DEFAULT '',
        radius_offer_name TEXT DEFAULT '',
        radius_duration_label TEXT DEFAULT '',
        updated_by_username TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS corl_category_idx ON card_offer_radius_links (category_code)")

    _seed_postgres_card_categories(cur)
    _enforce_postgres_card_category_contract(cur)


def _seed_postgres_card_categories(cur):
    cur.execute("SELECT COUNT(*) AS c FROM card_categories")
    row = cur.fetchone()
    count = row[0] if row else 0
    if count and int(count) > 0:
        return

    defaults = [
        ("half_hour",   "نصف ساعة",  30,  10, "fa-stopwatch",      "d-badge--neutral"),
        ("one_hour",    "ساعة",       60,  20, "fa-clock",          "d-badge"),
        ("two_hours",   "ساعتين",     120, 30, "fa-hourglass-half", "d-badge"),
        ("three_hours", "3 ساعات",   180, 40, "fa-business-time",  "d-badge--dark"),
        ("four_hours",  "4 ساعات",   240, 50, "fa-star",           "d-badge--warn"),
    ]
    for row in defaults:
        cur.execute(
            """
            INSERT INTO card_categories
                (code, label_ar, duration_minutes, display_order, icon, color_class, is_active)
            VALUES (%s, %s, %s, %s, %s, %s, TRUE)
            ON CONFLICT (code) DO NOTHING
            """,
            row,
        )

    cur.execute("SELECT COUNT(*) FROM card_quota_policies WHERE scope='default'")
    row = cur.fetchone()
    count = row[0] if row else 0
    if not count or int(count) == 0:
        cur.execute(
            """
            INSERT INTO card_quota_policies
                (scope, daily_limit, allowed_days, allowed_category_codes, priority, is_active, notes)
            VALUES ('default', 3, '', 'half_hour,one_hour,two_hours,three_hours', 1000, TRUE, 'السياسة الافتراضية لكل المشتركين')
            """
        )


def _enforce_postgres_card_category_contract(cur):
    official = [
        ("half_hour", "نصف ساعة", 30, 10, "fa-stopwatch", "d-badge--neutral", ""),
        ("one_hour", "ساعة", 60, 20, "fa-clock", "d-badge", ""),
        ("two_hours", "ساعتين", 120, 30, "fa-hourglass-half", "d-badge", ""),
        ("three_hours", "3 ساعات", 180, 40, "fa-business-time", "d-badge--dark", ""),
        ("four_hours", "4 ساعات", 240, 50, "fa-star", "d-badge--warn", "فئة خاصة: لا تظهر للمشترك إلا بسياسة مخصصة له أو لمجموعته"),
    ]
    official_codes = [row[0] for row in official]

    for code, label, minutes, order, icon, color, notes in official:
        cur.execute(
            """
            INSERT INTO card_categories
                (code, label_ar, duration_minutes, display_order, icon, color_class, is_active, notes)
            VALUES (%s,%s,%s,%s,%s,%s,TRUE,%s)
            ON CONFLICT (code) DO UPDATE SET
                label_ar=EXCLUDED.label_ar,
                duration_minutes=EXCLUDED.duration_minutes,
                display_order=EXCLUDED.display_order,
                icon=EXCLUDED.icon,
                color_class=EXCLUDED.color_class,
                is_active=TRUE,
                notes=EXCLUDED.notes,
                updated_at=CURRENT_TIMESTAMP
            """,
            [code, label, minutes, order, icon, color, notes],
        )

    cur.execute(
        """
        UPDATE card_categories
        SET is_active=FALSE, updated_at=CURRENT_TIMESTAMP
        WHERE code <> ALL(%s)
        """,
        [official_codes],
    )

    standard_codes = "half_hour,one_hour,two_hours,three_hours"
    alias_codes = {"hour": "one_hour", "six_hours": "four_hours", "day": "four_hours"}
    cur.execute(
        "SELECT id, allowed_category_codes FROM card_quota_policies WHERE COALESCE(allowed_category_codes, '') <> ''"
    )
    for policy_id, raw_codes in cur.fetchall():
        normalized = []
        for raw_code in str(raw_codes or "").split(","):
            code = alias_codes.get(raw_code.strip(), raw_code.strip())
            if code in official_codes and code not in normalized:
                normalized.append(code)
        cur.execute(
            "UPDATE card_quota_policies SET allowed_category_codes=%s, updated_at=CURRENT_TIMESTAMP WHERE id=%s",
            [",".join(normalized), policy_id],
        )

    cur.execute("SELECT COUNT(*) FROM card_quota_policies WHERE scope='default'")
    row = cur.fetchone()
    count = (row[0] if row else 0)
    if not count or int(count) == 0:
        cur.execute(
            """
            INSERT INTO card_quota_policies
                (scope, daily_limit, weekly_limit, allowed_days, allowed_category_codes, priority, is_active, notes)
            VALUES ('default', 3, NULL, '', %s, 1000, TRUE, 'السياسة الافتراضية: 3 بطاقات يوميا من الفئات العادية فقط')
            """,
            [standard_codes],
        )
