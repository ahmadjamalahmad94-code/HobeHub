# Auto-split from app/legacy.py lines 2573-2698. Loaded by app.legacy.
def _sqlite_column_exists(cur, table_name: str, column_name: str) -> bool:
    cur.execute(f"PRAGMA table_info({table_name})")
    return any(row["name"] == column_name for row in cur.fetchall())


def _sqlite_add_column_if_missing(cur, table_name: str, definition: str):
    column_name = definition.split()[0]
    if not _sqlite_column_exists(cur, table_name, column_name):
        cur.execute(f"ALTER TABLE {table_name} ADD COLUMN {definition}")


def _seed_local_demo_data(cur):
    cur.execute("SELECT COUNT(*) AS c FROM beneficiaries")
    if (cur.fetchone()["c"] or 0) > 0:
        return

    week_start = get_week_start()
    demo_beneficiaries = [
        (
            "university", "أحمد", "خالد", "", "", "أحمد خالد", normalize_search_ar("أحمد خالد"), "0599123456",
            "", "", "", "", "", "", "", "", "",
            "جامعة القدس المفتوحة", "الآداب", "لغة عربية", "الأحد,الثلاثاء", "يوزر إنترنت", "morning", "08:00", "12:00",
            2, week_start, "بيانات تجريبية محلية", 1, "admin"
        ),
        (
            "freelancer", "سارة", "عمر", "", "", "سارة عمر", normalize_search_ar("سارة عمر"), "0599234567",
            "", "", "تصميم", "مستقلة", "مرن", "نظام البطاقات", "", "", "",
            "", "", "", "", "", "", "", "",
            1, week_start, "مستخدمة بطاقات تجريبية", 1, "admin"
        ),
        (
            "tawjihi", "محمد", "علي", "", "", "محمد علي", normalize_search_ar("محمد علي"), "0599345678",
            "2006", "علمي", "", "", "", "", "", "", "",
            "", "", "", "", "", "", "", "",
            0, week_start, "طالب تجريبي", 1, "admin"
        ),
    ]
    cur.executemany(
        """
        INSERT INTO beneficiaries (
            user_type, first_name, second_name, third_name, fourth_name, full_name, search_name, phone,
            tawjihi_year, tawjihi_branch, freelancer_specialization, freelancer_company, freelancer_schedule_type,
            freelancer_internet_method, freelancer_time_mode, freelancer_time_from, freelancer_time_to,
            university_name, university_college, university_specialization, university_days, university_internet_method,
            university_time_mode, university_time_from, university_time_to, weekly_usage_count, weekly_usage_week_start,
            notes, added_by_account_id, added_by_username
        ) VALUES (
            %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
        )
        """,
        demo_beneficiaries,
    )

    cur.execute("SELECT id, phone, full_name, user_type FROM beneficiaries ORDER BY id")
    rows = cur.fetchall()
    first_id = rows[0]["id"]
    second_id = rows[1]["id"]

    cur.execute(
        """
        INSERT OR IGNORE INTO beneficiary_radius_accounts (
            beneficiary_id, external_user_id, external_username, current_profile_id, current_profile_name, original_profile_id, status
        ) VALUES (%s,%s,%s,%s,%s,%s,%s)
        """,
        [first_id, "demo-ext-1", "ahmad.demo", "basic-2m", "2MB", "basic-2m", "active"],
    )
    cur.execute(
        """
        INSERT OR IGNORE INTO beneficiary_portal_accounts (
            beneficiary_id, username, password_hash, is_active, portal_membership_active, must_set_password, activated_at, failed_login_attempts
        ) VALUES (%s,%s,%s,1,1,0,%s,0)
        """,
        [first_id, "0599123456", generate_password_hash("demo12345"), now_local()],
    )
    cur.execute(
        """
        INSERT OR IGNORE INTO internet_service_requests (
            beneficiary_id, request_type, status, requested_payload, admin_payload, api_endpoint, api_response,
            error_message, requested_by, reviewed_by, reviewed_at, executed_at
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """,
        [
            first_id,
            "add_quota",
            "pending",
            json.dumps({"quota_value": "2GB", "notes": "طلب تجريبي"}, ensure_ascii=False),
            json.dumps({}, ensure_ascii=False),
            "",
            json.dumps({}, ensure_ascii=False),
            "",
            "0599123456",
            "",
            None,
            None,
        ],
    )
    cur.execute(
        """
        INSERT OR IGNORE INTO internet_service_requests (
            beneficiary_id, request_type, status, requested_payload, admin_payload, api_endpoint, api_response,
            error_message, requested_by, reviewed_by, reviewed_at, executed_at
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """,
        [
            second_id,
            "request_card",
            "executed",
            json.dumps({"cards_count": "1"}, ensure_ascii=False),
            json.dumps({"notes": "تمت المعالجة محليًا"}, ensure_ascii=False),
            "/generate_user_cards",
            json.dumps({"mock": True, "cards": [{"card_no": "CARD-001"}]}, ensure_ascii=False),
            "",
            "admin",
            "admin",
            now_local(),
            now_local(),
        ],
    )
    cur.execute(
        """
        INSERT INTO beneficiary_usage_logs (
            beneficiary_id, usage_reason, card_type, usage_date, usage_time, notes, added_by_account_id, added_by_username
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        """,
        [second_id, "بطاقة أسبوعية", "ساعة", today_local(), now_local(), "سجل تجريبي", 1, "admin"],
    )
