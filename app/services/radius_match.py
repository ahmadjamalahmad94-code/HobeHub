"""
radius_match — Beneficiary ↔ RADIUS match & sync engine (service layer).

Isolated, framework-agnostic logic used by the admin routes in
``app/legacy_parts/48az_radius_match_engine.py``.

Design notes
------------
* Read-only SCAN phase records candidate matches into ``radius_match_candidates``
  linked to a ``radius_match_runs`` row. It NEVER mutates beneficiaries/portal
  accounts — nothing changes before an explicit CONFIRM.
* The scan is chunked (``scan_step``) so a large fleet never blocks a single
  request; the page polls repeatedly. This keeps us within CLAUDE rule 7
  (no heavy logic in a single view) without pulling in Redis/Celery yet.
* All RADIUS access goes exclusively through ``get_radius_client()`` — this
  module never talks to the radius-module repo directly.
* When the RADIUS API is not live/ready the run degrades to ``needs_live``
  («قيد التطوير») instead of crashing.

``get_radius_client`` and ``is_api_under_development`` are referenced at module
scope so tests can monkeypatch them.
"""
from __future__ import annotations

from typing import Any

from app import db
from app.security.passwords import sha256_text
from app.services.radius_client import get_radius_client, is_api_under_development
from app.utils.text import clean_csv_value, normalize_phone

# ── Constants ────────────────────────────────────────────────────────────
SUBSCRIPTION_METHOD = "يوزر إنترنت"  # value that flips access_mode → username
DEFAULT_CHUNK_SIZE = 25
REVERSE_DIFF_LIMIT = 500

_ADMIN_BOOL_KEYS = ("is_admin", "isadmin", "is_manager", "ismanager", "is_reseller", "is_operator")
_ADMIN_ROLE_TOKENS = {
    "admin", "administrator", "manager", "sub_admin", "subadmin", "reseller",
    "operator", "superadmin", "super_admin", "owner", "staff", "sysadmin",
}
_ADMIN_USERNAMES = {"admin", "administrator", "manager", "root", "sysadmin", "superadmin", "operator"}
_DISABLED_STATES = {"disabled", "blocked", "inactive", "suspended", "expired", "banned", "deleted", "0", "false", "no"}
_ACTIVE_STATES = {"active", "enabled", "online", "ok", "1", "true", "yes"}


# ── Small helpers ────────────────────────────────────────────────────────
def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() in {"1", "true", "yes", "on", "y", "active", "enabled"}


def _first(u: dict, *keys: str) -> str:
    for k in keys:
        v = u.get(k)
        if v not in (None, ""):
            return str(v).strip()
    return ""


def _parse_radius_user(u: Any) -> dict:
    """Normalise a raw radius user dict into a stable shape (defensive)."""
    if not isinstance(u, dict):
        return {"username": str(u or "").strip(), "external_id": "", "phone": "", "is_active": True, "raw": {}}
    username = _first(
        u, "username", "user_name", "login", "name", "user",
        "account_username", "radius_username", "login_name", "user_login", "subscriber",
    )
    external_id = _first(u, "id", "user_id", "uid", "external_id", "userid", "user_ad_id")
    phone_raw = _first(u, "phone", "mobile", "msisdn", "tel", "phone_number", "cell")
    phone = normalize_phone(phone_raw) if phone_raw else ""
    # مشترك الريديوس المدعوم يسجّل الدخول بجوّاله؛ فإن غاب حقل اسم دخول صريح،
    # اعتمد الجوّال كاسم مستخدم (يصحّح العرض والاستيراد معًا).
    if not username and phone:
        username = phone
    return {
        "username": username,
        "external_id": external_id,
        "phone": phone,
        "is_active": _radius_is_active(u),
        "raw": u,
    }


def _radius_is_active(u: dict) -> bool:
    for k in ("disabled", "is_disabled", "blocked", "is_blocked", "suspended", "is_expired"):
        if _truthy(u.get(k)):
            return False
    for k in ("is_active", "active", "enabled"):
        if k in u:
            return _truthy(u.get(k))
    state = _first(u, "status", "state", "account_status").lower()
    if state in _DISABLED_STATES:
        return False
    if state in _ACTIVE_STATES:
        return True
    return True  # default: treat as active unless explicitly disabled


def _classify_radius_user(u: dict) -> tuple[str, bool]:
    """Return ('subscriber'|'admin_like', is_admin_like)."""
    for k in _ADMIN_BOOL_KEYS:
        if _truthy(u.get(k)):
            return "admin_like", True
    role = _first(
        u, "role", "type", "account_type", "user_type", "group", "group_name",
        "profile", "profile_name", "kind", "level",
    ).lower()
    for token in _ADMIN_ROLE_TOKENS:
        if token and token in role:
            return "admin_like", True
    uname = _first(u, "username", "user_name", "login", "name").lower()
    if uname in _ADMIN_USERNAMES or uname.startswith(("admin", "manager", "reseller", "operator")):
        return "admin_like", True
    return "subscriber", False


def _extract_users(result: Any) -> list[dict]:
    if isinstance(result, dict):
        if result.get("ok") is False and not result.get("data"):
            return []
        data = result.get("data") or result.get("users") or result.get("__list__") or []
    else:
        data = result or []
    return [u for u in data if isinstance(u, dict)] if isinstance(data, list) else []


# ── Availability ─────────────────────────────────────────────────────────
def radius_available() -> bool:
    """True only when the live API is ready AND exposes search_users."""
    try:
        if is_api_under_development():
            return False
        client = get_radius_client()
        return callable(getattr(client, "search_users", None))
    except Exception:
        return False


def _radius_mode() -> str:
    try:
        return get_radius_client().mode
    except Exception:
        return "manual"


# ── Run lifecycle ────────────────────────────────────────────────────────
def get_run(run_id: int) -> dict | None:
    return db.query_one("SELECT * FROM radius_match_runs WHERE id=%s", [int(run_id)])


def get_latest_run() -> dict | None:
    return db.query_one("SELECT * FROM radius_match_runs ORDER BY id DESC LIMIT 1")


def run_progress(run: dict) -> dict:
    total = int(run.get("total") or 0)
    processed = int(run.get("processed") or 0)
    percent = 100 if total <= 0 and run.get("status") == "done" else (
        int(round(processed * 100 / total)) if total > 0 else 0
    )
    return {
        "run_id": int(run["id"]),
        "status": run.get("status") or "",
        "total": total,
        "processed": processed,
        "percent": min(100, max(0, percent)),
        "matched_count": int(run.get("matched_count") or 0),
        "radius_only_count": int(run.get("radius_only_count") or 0),
        "admin_like_count": int(run.get("admin_like_count") or 0),
        "message": run.get("message") or "",
        "done": (run.get("status") in ("done", "failed", "needs_live")),
    }


def create_run(started_by_username: str = "", started_by_account_id: int | None = None) -> dict:
    """Create a new run. Does NOT scan yet (scan is driven by scan_step)."""
    mode = _radius_mode()
    if not radius_available():
        row = db.execute_sql(
            """
            INSERT INTO radius_match_runs
                (status, radius_mode, total, processed, message,
                 started_by_account_id, started_by_username, finished_at)
            VALUES ('needs_live', %s, 0, 0, %s, %s, %s, CURRENT_TIMESTAMP)
            RETURNING id
            """,
            [
                mode,
                "خدمة RADIUS غير مفعّلة بعد (قيد التطوير). لا يمكن تنفيذ المطابقة الآن.",
                started_by_account_id,
                clean_csv_value(started_by_username),
            ],
            fetchone=True,
        )
        return get_run(int(row["id"]))

    total = int((db.query_one(
        "SELECT COUNT(*) AS c FROM beneficiaries WHERE phone IS NOT NULL AND TRIM(phone) <> ''"
    ) or {}).get("c") or 0)
    row = db.execute_sql(
        """
        INSERT INTO radius_match_runs
            (status, radius_mode, total, processed, message,
             started_by_account_id, started_by_username)
        VALUES ('running', %s, %s, 0, %s, %s, %s)
        RETURNING id
        """,
        [mode, total, "جارٍ الفحص…", started_by_account_id, clean_csv_value(started_by_username)],
        fetchone=True,
    )
    return get_run(int(row["id"]))


# ── Scan (read-only) ─────────────────────────────────────────────────────
def scan_step(run_id: int, chunk_size: int = DEFAULT_CHUNK_SIZE) -> dict | None:
    """Process the next chunk of beneficiaries. Idempotent per (run, beneficiary)."""
    run = get_run(run_id)
    if not run:
        return None
    if (run.get("status") or "") != "running":
        return run_progress(run)

    total = int(run.get("total") or 0)
    processed = int(run.get("processed") or 0)
    client = get_radius_client()

    rows = db.query_all(
        """
        SELECT id, full_name, phone, user_type
        FROM beneficiaries
        WHERE phone IS NOT NULL AND TRIM(phone) <> ''
        ORDER BY id ASC
        LIMIT %s OFFSET %s
        """,
        [int(chunk_size), processed],
    )

    for ben in rows:
        phone = normalize_phone(ben.get("phone") or "")
        if phone:
            _scan_one_beneficiary(run_id, ben, phone, client)
        processed += 1

    db.execute_sql(
        "UPDATE radius_match_runs SET processed=%s, updated_at=CURRENT_TIMESTAMP WHERE id=%s",
        [processed, run_id],
    )

    if processed >= total:
        _finalize_run(run_id, client)

    return run_progress(get_run(run_id))


def _scan_one_beneficiary(run_id: int, ben: dict, phone: str, client) -> None:
    try:
        result = client.search_users(phone, limit=25)
    except Exception:
        return
    for raw in _extract_users(result):
        parsed = _parse_radius_user(raw)
        # only ACTIVE radius users are offered as matches
        if not parsed["is_active"]:
            continue
        # confirm the result really belongs to this phone when a phone is present
        if parsed["phone"] and parsed["phone"] != phone:
            continue
        classification, is_admin = _classify_radius_user(raw)
        # idempotent: one candidate per (run, beneficiary, radius identity)
        exists = db.query_one(
            """
            SELECT id FROM radius_match_candidates
            WHERE run_id=%s AND direction='hobehub_to_radius'
              AND beneficiary_id=%s AND radius_username=%s
            LIMIT 1
            """,
            [run_id, ben["id"], parsed["username"]],
        )
        if exists:
            continue
        db.execute_sql(
            """
            INSERT INTO radius_match_candidates
                (run_id, direction, beneficiary_id, beneficiary_name,
                 radius_username, radius_external_id, matched_phone,
                 radius_is_active, classification, is_admin_like,
                 suggested_action, selected_default)
            VALUES (%s, 'hobehub_to_radius', %s, %s, %s, %s, %s, TRUE, %s, %s, %s, %s)
            """,
            [
                run_id, ben["id"], clean_csv_value(ben.get("full_name")),
                parsed["username"], parsed["external_id"], phone,
                classification, bool(is_admin),
                "review" if is_admin else "link_subscription",
                (not is_admin),  # admin-like matches are pre-unchecked too
            ],
        )


def _finalize_run(run_id: int, client) -> None:
    """Compute the reverse diff (radius-only pull candidates) then mark done."""
    try:
        _scan_radius_only(run_id, client)
    except Exception:
        pass

    matched = int((db.query_one(
        "SELECT COUNT(*) AS c FROM radius_match_candidates WHERE run_id=%s AND direction='hobehub_to_radius'",
        [run_id],
    ) or {}).get("c") or 0)
    radius_only = int((db.query_one(
        "SELECT COUNT(*) AS c FROM radius_match_candidates WHERE run_id=%s AND direction='radius_only'",
        [run_id],
    ) or {}).get("c") or 0)
    admin_like = int((db.query_one(
        "SELECT COUNT(*) AS c FROM radius_match_candidates WHERE run_id=%s AND is_admin_like=TRUE",
        [run_id],
    ) or {}).get("c") or 0)

    message = (
        f"اكتمل الفحص: {matched} مطابقة لمشتركين حاليين، "
        f"{radius_only} مستخدم في RADIUS بلا مستفيد "
        f"(منهم {admin_like} حساب إداري مُستبعَد افتراضيًا)."
    )
    db.execute_sql(
        """
        UPDATE radius_match_runs
        SET status='done', matched_count=%s, radius_only_count=%s,
            admin_like_count=%s, message=%s,
            finished_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP
        WHERE id=%s
        """,
        [matched, radius_only, admin_like, message, run_id],
    )


def _scan_radius_only(run_id: int, client) -> None:
    try:
        result = client.search_users("", limit=REVERSE_DIFF_LIMIT)
    except Exception:
        return
    users = _extract_users(result)
    if not users:
        return

    existing_phones = {
        normalize_phone(r["phone"])
        for r in db.query_all("SELECT phone FROM beneficiaries WHERE phone IS NOT NULL AND TRIM(phone) <> ''")
        if r.get("phone")
    }
    linked_usernames = {
        (r.get("external_username") or "").strip().lower()
        for r in db.query_all("SELECT external_username FROM beneficiary_radius_accounts")
        if r.get("external_username")
    }

    seen: set[str] = set()
    for raw in users:
        parsed = _parse_radius_user(raw)
        if not parsed["is_active"]:
            continue
        uname = parsed["username"]
        key = (uname or parsed["external_id"] or parsed["phone"]).lower()
        if not key or key in seen:
            continue
        # already corresponds to a beneficiary → not a pull candidate
        if parsed["phone"] and parsed["phone"] in existing_phones:
            continue
        if uname and uname.lower() in linked_usernames:
            continue
        seen.add(key)
        classification, is_admin = _classify_radius_user(raw)
        db.execute_sql(
            """
            INSERT INTO radius_match_candidates
                (run_id, direction, beneficiary_id, beneficiary_name,
                 radius_username, radius_external_id, matched_phone,
                 radius_is_active, classification, is_admin_like,
                 suggested_action, selected_default)
            VALUES (%s, 'radius_only', NULL, '', %s, %s, %s, TRUE, %s, %s, %s, %s)
            """,
            [
                run_id, uname, parsed["external_id"], parsed["phone"],
                classification, bool(is_admin),
                "review" if is_admin else "import_subscription",
                (not is_admin),
            ],
        )


def run_scan_to_completion(run_id: int, chunk_size: int = DEFAULT_CHUNK_SIZE, max_steps: int = 100000) -> dict | None:
    """Convenience helper (used by tests) — drive scan_step until the run ends."""
    steps = 0
    progress = run_progress(get_run(run_id)) if get_run(run_id) else None
    while progress and not progress["done"] and steps < max_steps:
        progress = scan_step(run_id, chunk_size=chunk_size)
        steps += 1
    return progress


# ── Read helpers for the review page ─────────────────────────────────────
def get_run_candidates(run_id: int, direction: str = "") -> list[dict]:
    sql = "SELECT * FROM radius_match_candidates WHERE run_id=%s"
    params: list = [run_id]
    if direction:
        sql += " AND direction=%s"
        params.append(direction)
    sql += " ORDER BY is_admin_like ASC, id ASC"
    return db.query_all(sql, params)


# ── Confirm / apply (mutating, idempotent, selection-gated) ──────────────
def apply_confirm(run_id: int, candidate_ids, actor_username: str = "") -> dict:
    """Apply ONLY the selected candidate rows. Idempotent + transactional per row."""
    summary = {
        "linked": 0, "imported": 0, "portal_activated": 0,
        "skipped": 0, "already": 0, "errors": [],
    }
    ids = []
    for cid in (candidate_ids or []):
        try:
            ids.append(int(cid))
        except (TypeError, ValueError):
            continue
    for cid in ids:
        cand = db.query_one(
            "SELECT * FROM radius_match_candidates WHERE id=%s AND run_id=%s",
            [cid, run_id],
        )
        if not cand:
            summary["skipped"] += 1
            continue
        if _truthy(cand.get("applied")):
            summary["already"] += 1
            continue
        try:
            if cand.get("direction") == "hobehub_to_radius" and cand.get("beneficiary_id"):
                _apply_link_subscription(cand, actor_username, summary)
                summary["linked"] += 1
            elif cand.get("direction") == "radius_only":
                _apply_import_subscription(cand, actor_username, summary)
                summary["imported"] += 1
            else:
                summary["skipped"] += 1
                continue
            db.execute_sql(
                """
                UPDATE radius_match_candidates
                SET applied=TRUE, applied_at=CURRENT_TIMESTAMP, apply_result='ok'
                WHERE id=%s
                """,
                [cid],
            )
        except Exception as exc:  # noqa: BLE001 — record and continue
            summary["errors"].append(f"#{cid}: {exc}")
            db.execute_sql(
                "UPDATE radius_match_candidates SET apply_result=%s WHERE id=%s",
                [str(exc)[:300], cid],
            )
    return summary


def _set_subscription_mode(beneficiary_id: int, user_type: str) -> None:
    ut = (user_type or "").strip().lower()
    if ut == "university":
        db.execute_sql(
            "UPDATE beneficiaries SET university_internet_method=%s WHERE id=%s",
            [SUBSCRIPTION_METHOD, beneficiary_id],
        )
    elif ut == "freelancer":
        db.execute_sql(
            "UPDATE beneficiaries SET freelancer_internet_method=%s WHERE id=%s",
            [SUBSCRIPTION_METHOD, beneficiary_id],
        )
    else:
        # tawjihi/unknown cannot be a subscription per access rules → normalise
        # to freelancer (internet-account holder) so it becomes «اشتراك».
        db.execute_sql(
            "UPDATE beneficiaries SET user_type='freelancer', freelancer_internet_method=%s WHERE id=%s",
            [SUBSCRIPTION_METHOD, beneficiary_id],
        )


def _link_radius_identity(beneficiary_id: int, username: str, external_id: str) -> None:
    db.execute_sql(
        "UPDATE beneficiaries SET linked_radius_username=%s, linked_radius_external_id=%s WHERE id=%s",
        [clean_csv_value(username) or None, clean_csv_value(external_id) or None, beneficiary_id],
    )
    existing = db.query_one(
        "SELECT id FROM beneficiary_radius_accounts WHERE beneficiary_id=%s LIMIT 1",
        [beneficiary_id],
    )
    if existing:
        db.execute_sql(
            """
            UPDATE beneficiary_radius_accounts
            SET external_username=COALESCE(%s, external_username),
                external_user_id=COALESCE(%s, external_user_id),
                status='active', updated_at=CURRENT_TIMESTAMP
            WHERE beneficiary_id=%s
            """,
            [clean_csv_value(username) or None, clean_csv_value(external_id) or None, beneficiary_id],
        )
    else:
        db.execute_sql(
            """
            INSERT INTO beneficiary_radius_accounts
                (beneficiary_id, external_user_id, external_username, status)
            VALUES (%s, %s, %s, 'active')
            """,
            [beneficiary_id, clean_csv_value(external_id) or None, clean_csv_value(username) or None],
        )


def _activate_portal_account(beneficiary_id: int, desired_username: str, summary: dict) -> None:
    """Ensure an ACTIVE, activatable portal account exists. Never stores plaintext."""
    existing = db.query_one(
        "SELECT id FROM beneficiary_portal_accounts WHERE beneficiary_id=%s LIMIT 1",
        [beneficiary_id],
    )
    if existing:
        db.execute_sql(
            """
            UPDATE beneficiary_portal_accounts
            SET is_active=TRUE, portal_membership_active=TRUE,
                portal_access_state='active', updated_at=CURRENT_TIMESTAMP
            WHERE id=%s
            """,
            [existing["id"]],
        )
        summary["portal_activated"] += 1
        return

    import secrets as _secrets
    from datetime import timedelta

    try:
        from app.legacy import now_local
        expires_at = now_local() + timedelta(hours=72)
    except Exception:
        from datetime import datetime
        expires_at = datetime.utcnow() + timedelta(hours=72)

    username = _unique_portal_username(desired_username, beneficiary_id)
    code = str(_secrets.randbelow(900000) + 100000)
    db.execute_sql(
        """
        INSERT INTO beneficiary_portal_accounts
            (beneficiary_id, username, password_hash, is_active,
             portal_membership_active, portal_access_state, must_set_password,
             activation_code_hash, activation_code_expires_at)
        VALUES (%s, %s, '', TRUE, TRUE, 'active', TRUE, %s, %s)
        """,
        [beneficiary_id, username, sha256_text(code), expires_at],
    )
    summary["portal_activated"] += 1


def _unique_portal_username(desired: str, beneficiary_id: int) -> str:
    base = clean_csv_value(desired) or f"user{beneficiary_id}"
    candidates = [base, f"{base}_{beneficiary_id}", f"user{beneficiary_id}"]
    for cand in candidates:
        taken = db.query_one(
            "SELECT id FROM beneficiary_portal_accounts WHERE username=%s AND beneficiary_id<>%s LIMIT 1",
            [cand, beneficiary_id],
        )
        if not taken:
            return cand
    import secrets as _secrets
    return f"{base}_{_secrets.randbelow(9000) + 1000}"


def _apply_link_subscription(cand: dict, actor: str, summary: dict) -> None:
    bid = int(cand["beneficiary_id"])
    ben = db.query_one("SELECT id, user_type, phone FROM beneficiaries WHERE id=%s", [bid])
    if not ben:
        raise ValueError("المستفيد غير موجود")
    _set_subscription_mode(bid, ben.get("user_type") or "")
    _link_radius_identity(bid, cand.get("radius_username") or "", cand.get("radius_external_id") or "")
    _activate_portal_account(bid, cand.get("radius_username") or ben.get("phone") or "", summary)


def _apply_import_subscription(cand: dict, actor: str, summary: dict) -> None:
    phone = normalize_phone(cand.get("matched_phone") or "")
    username = cand.get("radius_username") or ""

    # idempotent: reuse an existing beneficiary with the same phone if present
    existing = None
    if phone:
        existing = db.query_one(
            "SELECT id, user_type FROM beneficiaries WHERE phone=%s LIMIT 1", [phone]
        )
    if existing:
        bid = int(existing["id"])
        _set_subscription_mode(bid, existing.get("user_type") or "")
        _link_radius_identity(bid, username, cand.get("radius_external_id") or "")
        _activate_portal_account(bid, username or phone, summary)
        return

    display_name = clean_csv_value(username) or (phone or "مشترك RADIUS")
    row = db.execute_sql(
        """
        INSERT INTO beneficiaries
            (user_type, first_name, full_name, search_name, phone,
             freelancer_internet_method, linked_radius_username, linked_radius_external_id,
             added_by_username, notes)
        VALUES ('freelancer', %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        [
            display_name, display_name, display_name, phone or None,
            SUBSCRIPTION_METHOD, clean_csv_value(username) or None,
            clean_csv_value(cand.get("radius_external_id")) or None,
            clean_csv_value(actor) or "radius-match",
            "أُنشئ عبر مطابقة RADIUS",
        ],
        fetchone=True,
    )
    bid = int(row["id"])
    _link_radius_identity(bid, username, cand.get("radius_external_id") or "")
    _activate_portal_account(bid, username or phone, summary)
