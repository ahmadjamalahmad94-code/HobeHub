# Auto-split from app/legacy.py lines 7378-7618. Loaded by app.legacy.
def get_beneficiary_portal_account_by_username(username: str):
    normalized = normalize_portal_username(username)
    return query_one(
        """
        SELECT pa.*, b.full_name, b.phone
        FROM beneficiary_portal_accounts pa
        JOIN beneficiaries b ON b.id = pa.beneficiary_id
        WHERE pa.username=%s
          AND pa.is_active=TRUE
          AND COALESCE(pa.portal_membership_active, FALSE)=TRUE
        LIMIT 1
        """,
        [normalized],
    )


def normalize_portal_username(username: str) -> str:
    raw = clean_csv_value(username)
    if any(ch.isalpha() for ch in raw):
        return raw
    return normalize_phone(raw)


def generate_activation_code() -> str:
    return str(secrets.randbelow(900000) + 100000)


def activation_code_hash(code: str) -> str:
    return sha256_text(clean_csv_value(code))


def portal_password_hash(password: str) -> str:
    return generate_password_hash(password)


def verify_portal_password(stored_hash: str | None, password: str) -> bool:
    stored = clean_csv_value(stored_hash)
    raw = clean_csv_value(password)
    if not stored or not raw:
        return False
    if stored.startswith("pbkdf2:") or stored.startswith("scrypt:"):
        try:
            return check_password_hash(stored, raw)
        except ValueError:
            return False
    return stored == sha256_text(raw)


def portal_account_is_locked(row: dict | None) -> bool:
    if not row:
        return False
    locked_until = as_local_dt(row.get("locked_until"))
    return bool(locked_until and locked_until > now_local())


def register_portal_failed_attempt(account_id: int):
    row = query_one("SELECT failed_login_attempts FROM beneficiary_portal_accounts WHERE id=%s LIMIT 1", [account_id])
    attempts = int((row or {}).get("failed_login_attempts") or 0) + 1
    lock_until = now_local() + timedelta(minutes=15) if attempts >= 5 else None
    execute_sql(
        """
        UPDATE beneficiary_portal_accounts
        SET failed_login_attempts=%s, locked_until=%s, updated_at=CURRENT_TIMESTAMP
        WHERE id=%s
        """,
        [attempts, lock_until, account_id],
    )


def clear_portal_failed_attempts(account_id: int):
    execute_sql(
        """
        UPDATE beneficiary_portal_accounts
        SET failed_login_attempts=0, locked_until=NULL, updated_at=CURRENT_TIMESTAMP
        WHERE id=%s
        """,
        [account_id],
    )


def set_portal_session(row: dict):
    session.clear()
    session["portal_type"] = "beneficiary"
    session["beneficiary_id"] = row["beneficiary_id"]
    session["beneficiary_portal_account_id"] = row["id"]
    session["beneficiary_username"] = row["username"]
    session["beneficiary_full_name"] = row.get("full_name") or ""
    session["portal_access_state"] = (row.get("portal_access_state") or "active").strip().lower()


def finalize_beneficiary_portal_login(row: dict):
    set_portal_session(row)
    execute_sql(
        """
        UPDATE beneficiary_portal_accounts
        SET last_login_at=CURRENT_TIMESTAMP, failed_login_attempts=0, locked_until=NULL, updated_at=CURRENT_TIMESTAMP
        WHERE id=%s
        """,
        [row["id"]],
    )


def issue_activation_code_for_portal_account(account_id: int, hours_valid: int = 72):
    code = generate_activation_code()
    execute_sql(
        """
        UPDATE beneficiary_portal_accounts
        SET activation_code_hash=%s,
            activation_code_expires_at=%s,
            must_set_password=TRUE,
            password_hash='',
            activated_at=NULL,
            last_activation_sent_at=CURRENT_TIMESTAMP,
            failed_login_attempts=0,
            locked_until=NULL,
            updated_at=CURRENT_TIMESTAMP
        WHERE id=%s
        """,
        [activation_code_hash(code), now_local() + timedelta(hours=hours_valid), account_id],
    )
    return code


def get_current_portal_beneficiary():
    beneficiary_id = int(session.get("beneficiary_id") or 0)
    if beneficiary_id <= 0:
        return None
    return query_one("SELECT * FROM beneficiaries WHERE id=%s LIMIT 1", [beneficiary_id])


def get_user_radius_account():
    beneficiary = get_current_portal_beneficiary()
    if not beneficiary:
        return None
    return get_radius_account(beneficiary["id"])


def get_user_requests():
    beneficiary = get_current_portal_beneficiary()
    if not beneficiary:
        return []
    return query_all(
        """
        SELECT * FROM internet_service_requests
        WHERE beneficiary_id=%s
        ORDER BY id DESC
        """,
        [beneficiary["id"]],
    )
