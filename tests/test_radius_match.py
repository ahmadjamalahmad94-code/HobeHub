"""Tests for the Beneficiary ↔ RADIUS match & sync engine."""
from uuid import uuid4

import pytest

from app import db
from app.services import radius_match

from conftest import login_admin


SUBSCRIPTION = "يوزر إنترنت"
CARDS = "نظام البطاقات"


class FakeRadiusClient:
    """Minimal stand-in for LiveRadiusClient.search_users."""

    mode = "live"

    def __init__(self, users_by_phone):
        # phone -> raw radius user dict
        self.users_by_phone = users_by_phone

    def search_users(self, q="", limit=50):
        if not q:
            return {"ok": True, "data": list(self.users_by_phone.values())}
        user = self.users_by_phone.get(q)
        return {"ok": True, "data": [user] if user else []}


def _make_phone():
    return f"0591{int(uuid4().hex[:8], 16) % 1_000_000:06d}"


def _insert_beneficiary(phone, method=CARDS, user_type="freelancer", name="Match Test"):
    db.execute_sql(
        """
        INSERT INTO beneficiaries (user_type, first_name, full_name, search_name, phone,
                                   freelancer_internet_method, added_by_username)
        VALUES (%s, %s, %s, %s, %s, %s, 'pytest')
        """,
        [user_type, name, name, name, phone, method],
    )
    return db.query_one("SELECT id FROM beneficiaries WHERE phone=%s", [phone])["id"]


def _cleanup(run_id=None, beneficiary_ids=(), phones=()):
    for phone in phones:
        row = db.query_one("SELECT id FROM beneficiaries WHERE phone=%s", [phone])
        if row:
            beneficiary_ids = tuple(beneficiary_ids) + (row["id"],)
    for bid in set(beneficiary_ids):
        db.execute_sql("DELETE FROM beneficiary_portal_accounts WHERE beneficiary_id=%s", [bid])
        db.execute_sql("DELETE FROM beneficiary_radius_accounts WHERE beneficiary_id=%s", [bid])
        db.execute_sql("DELETE FROM beneficiaries WHERE id=%s", [bid])
    if run_id is not None:
        db.execute_sql("DELETE FROM radius_match_candidates WHERE run_id=%s", [run_id])
        db.execute_sql("DELETE FROM radius_match_runs WHERE id=%s", [run_id])


def _patch_live(monkeypatch, client):
    monkeypatch.setattr(radius_match, "is_api_under_development", lambda: False)
    monkeypatch.setattr(radius_match, "get_radius_client", lambda: client)


# ════════════════════════════════════════════════════════════════════════
def test_scan_records_candidates_without_mutating(monkeypatch):
    phone_active = _make_phone()
    phone_disabled = _make_phone()
    bid_active = _insert_beneficiary(phone_active, method=CARDS)
    bid_disabled = _insert_beneficiary(phone_disabled, method=CARDS)
    run_id = None
    try:
        client = FakeRadiusClient({
            phone_active: {"username": "cardsub1", "id": "101", "phone": phone_active, "status": "active"},
            phone_disabled: {"username": "disabledsub", "id": "102", "phone": phone_disabled, "status": "disabled"},
        })
        _patch_live(monkeypatch, client)

        run = radius_match.create_run("admin", 1)
        run_id = int(run["id"])
        assert run["status"] == "running"
        progress = radius_match.run_scan_to_completion(run_id)
        assert progress["status"] == "done"

        fwd = radius_match.get_run_candidates(run_id, "hobehub_to_radius")
        matched = [c for c in fwd if c["beneficiary_id"] == bid_active]
        assert len(matched) == 1
        assert matched[0]["radius_username"] == "cardsub1"
        assert matched[0]["radius_external_id"] == "101"

        # disabled radius user is NOT offered
        assert not [c for c in fwd if c["beneficiary_id"] == bid_disabled]

        # NOTHING mutated: beneficiary still in cards mode, no portal/radius link
        beneficiary = db.query_one("SELECT * FROM beneficiaries WHERE id=%s", [bid_active])
        assert beneficiary["freelancer_internet_method"] == CARDS
        assert not beneficiary["linked_radius_username"]
        assert db.query_one("SELECT id FROM beneficiary_portal_accounts WHERE beneficiary_id=%s", [bid_active]) is None
        assert db.query_one("SELECT id FROM beneficiary_radius_accounts WHERE beneficiary_id=%s", [bid_active]) is None
    finally:
        _cleanup(run_id, beneficiary_ids=(bid_active, bid_disabled))


def test_active_match_confirm_reclassifies_activates_and_links(monkeypatch):
    phone = _make_phone()
    bid = _insert_beneficiary(phone, method=CARDS)
    run_id = None
    try:
        client = FakeRadiusClient({phone: {"username": "netuser", "id": "555", "phone": phone, "status": "active"}})
        _patch_live(monkeypatch, client)
        run = radius_match.create_run("admin", 1)
        run_id = int(run["id"])
        radius_match.run_scan_to_completion(run_id)

        cand = db.query_one(
            "SELECT id FROM radius_match_candidates WHERE run_id=%s AND beneficiary_id=%s",
            [run_id, bid],
        )
        assert cand is not None
        summary = radius_match.apply_confirm(run_id, [cand["id"]], actor_username="admin")
        assert summary["linked"] == 1
        assert summary["portal_activated"] == 1

        beneficiary = db.query_one("SELECT * FROM beneficiaries WHERE id=%s", [bid])
        assert beneficiary["freelancer_internet_method"] == SUBSCRIPTION  # اشتراك
        assert beneficiary["linked_radius_username"] == "netuser"
        assert beneficiary["linked_radius_external_id"] == "555"

        radius_row = db.query_one("SELECT * FROM beneficiary_radius_accounts WHERE beneficiary_id=%s", [bid])
        assert radius_row["external_username"] == "netuser"
        assert radius_row["status"] == "active"

        portal = db.query_one("SELECT * FROM beneficiary_portal_accounts WHERE beneficiary_id=%s", [bid])
        assert portal is not None
        assert int(portal["is_active"]) == 1
        assert int(portal["portal_membership_active"]) == 1
        # never stores plaintext password
        assert (portal["password_hash"] or "") == ""

        applied = db.query_one("SELECT applied FROM radius_match_candidates WHERE id=%s", [cand["id"]])
        assert int(applied["applied"]) == 1
    finally:
        _cleanup(run_id, beneficiary_ids=(bid,))


def test_radius_only_admin_like_is_flagged_and_pre_excluded(monkeypatch):
    phone_sub = _make_phone()
    phone_admin = _make_phone()
    run_id = None
    try:
        client = FakeRadiusClient({
            phone_sub: {"username": "orphan_sub", "id": "201", "phone": phone_sub, "status": "active"},
            phone_admin: {"username": "boss", "id": "202", "phone": phone_admin, "role": "manager", "status": "active"},
        })
        _patch_live(monkeypatch, client)
        run = radius_match.create_run("admin", 1)
        run_id = int(run["id"])
        radius_match.run_scan_to_completion(run_id)

        only = radius_match.get_run_candidates(run_id, "radius_only")
        by_user = {c["radius_username"]: c for c in only}
        assert "orphan_sub" in by_user
        assert "boss" in by_user

        assert int(by_user["orphan_sub"]["is_admin_like"]) == 0
        assert int(by_user["orphan_sub"]["selected_default"]) == 1

        assert by_user["boss"]["classification"] == "admin_like"
        assert int(by_user["boss"]["is_admin_like"]) == 1
        assert int(by_user["boss"]["selected_default"]) == 0  # pre-unchecked
    finally:
        _cleanup(run_id, phones=(phone_sub, phone_admin))


def test_confirm_applies_only_selected_rows(monkeypatch):
    phone_match = _make_phone()
    phone_orphan = _make_phone()
    phone_admin = _make_phone()
    bid_match = _insert_beneficiary(phone_match, method=CARDS)
    run_id = None
    try:
        client = FakeRadiusClient({
            phone_match: {"username": "keepme", "id": "301", "phone": phone_match, "status": "active"},
            phone_orphan: {"username": "orphan2", "id": "302", "phone": phone_orphan, "status": "active"},
            phone_admin: {"username": "administrator", "id": "303", "phone": phone_admin, "status": "active"},
        })
        _patch_live(monkeypatch, client)
        run = radius_match.create_run("admin", 1)
        run_id = int(run["id"])
        radius_match.run_scan_to_completion(run_id)

        only = radius_match.get_run_candidates(run_id, "radius_only")
        orphan_cand = next(c for c in only if c["radius_username"] == "orphan2")

        # apply ONLY the orphan import
        summary = radius_match.apply_confirm(run_id, [orphan_cand["id"]], actor_username="admin")
        assert summary["imported"] == 1

        # orphan imported as new subscription beneficiary
        new_ben = db.query_one("SELECT * FROM beneficiaries WHERE phone=%s", [phone_orphan])
        assert new_ben is not None
        assert new_ben["freelancer_internet_method"] == SUBSCRIPTION
        assert new_ben["linked_radius_username"] == "orphan2"

        # admin-like NOT imported (not selected)
        assert db.query_one("SELECT id FROM beneficiaries WHERE phone=%s", [phone_admin]) is None
        # matched beneficiary NOT touched (not selected)
        untouched = db.query_one("SELECT * FROM beneficiaries WHERE id=%s", [bid_match])
        assert untouched["freelancer_internet_method"] == CARDS
        assert not untouched["linked_radius_username"]
    finally:
        _cleanup(run_id, beneficiary_ids=(bid_match,), phones=(phone_orphan, phone_admin))


def test_apply_confirm_is_idempotent(monkeypatch):
    phone = _make_phone()
    bid = _insert_beneficiary(phone, method=CARDS)
    run_id = None
    try:
        client = FakeRadiusClient({phone: {"username": "idem", "id": "401", "phone": phone, "status": "active"}})
        _patch_live(monkeypatch, client)
        run = radius_match.create_run("admin", 1)
        run_id = int(run["id"])
        radius_match.run_scan_to_completion(run_id)
        cand = db.query_one(
            "SELECT id FROM radius_match_candidates WHERE run_id=%s AND beneficiary_id=%s", [run_id, bid]
        )

        first = radius_match.apply_confirm(run_id, [cand["id"]], actor_username="admin")
        assert first["linked"] == 1
        second = radius_match.apply_confirm(run_id, [cand["id"]], actor_username="admin")
        assert second["already"] == 1
        assert second["linked"] == 0

        # exactly one portal + one radius link (no duplication)
        portal_count = db.query_one(
            "SELECT COUNT(*) AS c FROM beneficiary_portal_accounts WHERE beneficiary_id=%s", [bid]
        )["c"]
        radius_count = db.query_one(
            "SELECT COUNT(*) AS c FROM beneficiary_radius_accounts WHERE beneficiary_id=%s", [bid]
        )["c"]
        assert int(portal_count) == 1
        assert int(radius_count) == 1
    finally:
        _cleanup(run_id, beneficiary_ids=(bid,))


def test_run_degrades_safely_when_radius_not_live(client):
    # No monkeypatch → manual mode → under development → needs_live.
    run = radius_match.create_run("admin", 1)
    run_id = int(run["id"])
    try:
        assert run["status"] == "needs_live"
        assert int(run["total"]) == 0
        progress = radius_match.run_scan_to_completion(run_id)
        assert progress["status"] == "needs_live"
        assert progress["done"] is True
        assert radius_match.get_run_candidates(run_id) == []
    finally:
        db.execute_sql("DELETE FROM radius_match_candidates WHERE run_id=%s", [run_id])
        db.execute_sql("DELETE FROM radius_match_runs WHERE id=%s", [run_id])


def test_match_page_and_button_render(client):
    login_admin(client)
    # button on the beneficiaries page
    beneficiaries = client.get("/admin/beneficiaries")
    assert beneficiaries.status_code == 200
    assert "/admin/radius/match" in beneficiaries.get_data(as_text=True)

    # the match engine page renders
    page = client.get("/admin/radius/match")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert "مطابقة" in html
    assert "بدء جولة مطابقة" in html


def test_match_start_endpoint_reports_needs_live(client):
    login_admin(client)
    page = client.get("/admin/radius/match")
    from conftest import extract_csrf

    token = extract_csrf(page.get_data(as_text=True))
    response = client.post(
        "/admin/radius/match/start",
        data={"_csrf_token": token},
        headers={"X-CSRFToken": token, "X-Requested-With": "XMLHttpRequest"},
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["status"] == "needs_live"
    db.execute_sql("DELETE FROM radius_match_runs WHERE id=%s", [payload["run_id"]])
