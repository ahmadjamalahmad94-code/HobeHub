"""Tests for the instant card-generation flow (Path 3).

The cards-subscriber request path GENERATES a card instantly from the RADIUS
offer LINKED to the HobeHub category (``card_offer_radius_links``) via
``generate_user_cards`` — not a guessed category, not a new offer. These tests
mirror the FakeRadiusClient style in ``tests/test_radius_match.py``:

* link configured + writes ENABLED  → real generated card, persisted+delivered,
  and the LINKED radius external_id (not the raw category) is forwarded.
* link configured + writes DISABLED  → graceful pending, never a fabricated card.
* NO link configured + no inventory   → graceful admin-facing error, RADIUS never called.
* ineligible subscriber              → blocked before RADIUS is ever called.
* password safety                    → the card password is never written to the audit log.
"""
from uuid import uuid4

from app import db
from app.services import card_dispatcher
from app.services import card_offer_links
from app.services.radius_client.base import RadiusClientNotImplemented
from app.services.radius_client.dtos import Result


CARDS = "نظام البطاقات"


# ── Fakes ────────────────────────────────────────────────────────────────
class FakeLiveCardClient:
    """Returns a real generated card (as a live client would once writes are on)."""

    mode = "live"

    def __init__(self, password="SuperSecret_pw!42"):
        self.calls = []
        self._password = password

    def generate_user_cards(self, category_code, count=1, *, radius_offer_external_id="",
                            beneficiary_id=None, requested_by="", notes=""):
        self.calls.append({
            "category_code": category_code,
            "count": count,
            "radius_offer_external_id": radius_offer_external_id,
            "beneficiary_id": beneficiary_id,
            "requested_by": requested_by,
        })
        return Result.success(
            "generated",
            card_username=f"gen_{category_code}_user",
            card_password=self._password,
            external_id="rad-777",
        )


class FakeWritesDisabledClient:
    """Live read but writes still gated → raises NotImplemented like LiveRadiusClient."""

    mode = "live"

    def __init__(self):
        self.calls = []

    def generate_user_cards(self, category_code, count=1, *, radius_offer_external_id="",
                            beneficiary_id=None, requested_by="", notes=""):
        self.calls.append(category_code)
        raise RadiusClientNotImplemented(
            "\U0001f6a7 عمليات الكتابة "
            "RADIUS_API_WRITES_ENABLED=1"
        )


class FakeNeverCalledClient:
    """Fails the test if generate_user_cards is ever invoked."""

    mode = "live"

    def __init__(self):
        self.called = False

    def generate_user_cards(self, *a, **k):
        self.called = True
        raise AssertionError("generate_user_cards must not be called")


# ── Helpers ──────────────────────────────────────────────────────────────
def _make_phone():
    return f"0593{int(uuid4().hex[:8], 16) % 1_000_000:06d}"


def _insert_beneficiary(phone, user_type="freelancer", name="Instant Card Test"):
    db.execute_sql(
        """
        INSERT INTO beneficiaries (
            user_type, first_name, full_name, search_name, phone,
            freelancer_internet_method, added_by_username
        )
        VALUES (%s, %s, %s, %s, %s, %s, 'pytest')
        """,
        [user_type, name, name, name, phone, CARDS],
    )
    return db.query_one("SELECT id FROM beneficiaries WHERE phone=%s", [phone])["id"]


def _link(category_code, external_id, name="Offer"):
    card_offer_links.set_link(category_code, external_id, radius_offer_name=name, updated_by="pytest")


def _cleanup(beneficiary_id, *category_codes):
    db.execute_sql("DELETE FROM card_audit_log WHERE beneficiary_id=%s", [beneficiary_id])
    db.execute_sql("DELETE FROM beneficiary_issued_cards WHERE beneficiary_id=%s", [beneficiary_id])
    db.execute_sql("DELETE FROM radius_pending_actions WHERE beneficiary_id=%s", [beneficiary_id])
    db.execute_sql("DELETE FROM beneficiaries WHERE id=%s", [beneficiary_id])
    for code in category_codes:
        db.execute_sql("DELETE FROM card_offer_radius_links WHERE category_code=%s", [code])


# ════════════════════════════════════════════════════════════════════════
def test_instant_generation_delivers_and_links_real_card(monkeypatch, client):
    phone = _make_phone()
    bid = _insert_beneficiary(phone)
    _link("three_hours", "rad-offer-3h", name="3h Offer")
    fake = FakeLiveCardClient()
    monkeypatch.setattr(card_dispatcher, "get_radius_client", lambda: fake)
    try:
        with client.application.test_request_context("/card/request"):
            result = card_dispatcher.request_card_via_radius(
                bid, "three_hours", actor_username="pytest", skip_quota=True,
            )

        assert result.ok is True
        assert result.pending_action_id is None
        assert result.issued_card_id
        assert result.card_username == "gen_three_hours_user"
        assert result.card_password == "SuperSecret_pw!42"

        # the LINKED radius offer external_id was forwarded to generation
        assert len(fake.calls) == 1
        assert fake.calls[0]["radius_offer_external_id"] == "rad-offer-3h"

        row = db.query_one(
            "SELECT * FROM beneficiary_issued_cards WHERE id=%s", [result.issued_card_id]
        )
        assert row is not None
        assert row["beneficiary_id"] == bid
        assert row["card_username"] == "gen_three_hours_user"

        audit = db.query_one(
            "SELECT event_type, details_json FROM card_audit_log "
            "WHERE beneficiary_id=%s ORDER BY id DESC LIMIT 1",
            [bid],
        )
        assert audit is not None
        assert audit["event_type"] == "card_generated_via_radius"
        assert "SuperSecret_pw!42" not in (audit["details_json"] or "")
        assert "gen_three_hours_user" in (audit["details_json"] or "")
    finally:
        _cleanup(bid, "three_hours")


def test_linked_external_id_not_raw_category_is_forwarded(monkeypatch, client):
    phone = _make_phone()
    bid = _insert_beneficiary(phone)
    _link("two_hours", "rad-offer-2h", name="2h Offer")
    fake = FakeLiveCardClient()
    monkeypatch.setattr(card_dispatcher, "get_radius_client", lambda: fake)
    try:
        with client.application.test_request_context("/card/request"):
            card_dispatcher.request_card_via_radius(
                bid, "two_hours", actor_username="pytest", skip_quota=True,
            )
        assert len(fake.calls) == 1
        assert fake.calls[0]["category_code"] == "two_hours"
        assert fake.calls[0]["radius_offer_external_id"] == "rad-offer-2h"
        assert fake.calls[0]["count"] == 1
        assert fake.calls[0]["beneficiary_id"] == bid
    finally:
        _cleanup(bid, "two_hours")


def test_writes_disabled_degrades_to_pending_without_fake_card(monkeypatch, client):
    phone = _make_phone()
    bid = _insert_beneficiary(phone)
    _link("one_hour", "rad-offer-1h")
    fake = FakeWritesDisabledClient()
    monkeypatch.setattr(card_dispatcher, "get_radius_client", lambda: fake)
    try:
        with client.application.test_request_context("/card/request"):
            result = card_dispatcher.request_card_via_radius(
                bid, "one_hour", actor_username="pytest", skip_quota=True,
                notes="pytest instant",
            )

        assert result.ok is True
        assert result.pending_action_id
        assert not result.card_username
        assert not result.card_password
        assert result.issued_card_id is None

        assert db.query_one(
            "SELECT id FROM beneficiary_issued_cards WHERE beneficiary_id=%s", [bid]
        ) is None

        pending = db.query_one(
            "SELECT * FROM radius_pending_actions WHERE id=%s", [result.pending_action_id]
        )
        assert pending["action_type"] == "generate_user_cards"
        assert pending["status"] == "pending"
        assert "rad-offer-1h" in (pending["payload_json"] or "")

        audit = db.query_one(
            "SELECT event_type, details_json FROM card_audit_log "
            "WHERE related_pending_action_id=%s",
            [result.pending_action_id],
        )
        assert audit["event_type"] == "card_request_queued"
        assert "RADIUS_API_WRITES_ENABLED" in (audit["details_json"] or "")
    finally:
        _cleanup(bid, "one_hour")


def test_unlinked_offer_returns_graceful_error_and_never_calls_radius(monkeypatch, client):
    phone = _make_phone()
    bid = _insert_beneficiary(phone)
    db.execute_sql("DELETE FROM card_offer_radius_links WHERE category_code=%s", ["two_hours"])
    fake = FakeNeverCalledClient()
    monkeypatch.setattr(card_dispatcher, "get_radius_client", lambda: fake)
    try:
        with client.application.test_request_context("/card/request"):
            result = card_dispatcher.request_card_via_radius(
                bid, "two_hours", actor_username="pytest", skip_quota=True,
            )
        assert result.ok is False
        assert "غير مربوط" in result.message
        assert fake.called is False
        assert result.issued_card_id is None
        assert db.query_one(
            "SELECT id FROM beneficiary_issued_cards WHERE beneficiary_id=%s", [bid]
        ) is None
    finally:
        _cleanup(bid, "two_hours")


def test_ineligible_user_is_blocked_before_radius(monkeypatch, client):
    phone = _make_phone()
    bid = _insert_beneficiary(phone, user_type="tawjihi")
    _link("three_hours", "rad-offer-3h")
    fake = FakeNeverCalledClient()
    monkeypatch.setattr(card_dispatcher, "get_radius_client", lambda: fake)
    try:
        with client.application.test_request_context("/card/request"):
            result = card_dispatcher.request_card_via_radius(
                bid, "three_hours", actor_username="pytest", skip_quota=True,
            )
        assert result.ok is False
        assert fake.called is False
        assert result.issued_card_id is None
        assert db.query_one(
            "SELECT id FROM beneficiary_issued_cards WHERE beneficiary_id=%s", [bid]
        ) is None
    finally:
        _cleanup(bid, "three_hours")
