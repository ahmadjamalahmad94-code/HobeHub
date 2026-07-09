"""Tests for the HobeHub↔RADIUS card-offer LINK feature.

Covers:
* live ``list_offers`` response parsing (``_extract_offers`` / ``_normalize_offer``).
* manual ``list_offers`` offline stub (keeps the UI working when not live).
* save / read a link (``card_offer_links``).
* the «ربط العروض» admin page renders safely when RADIUS is not live
  (shows saved links + «قيد التطوير», never crashes), incl. the live-refresh JSON.
"""
from uuid import uuid4

from app import db
from app.services import card_offer_links
from app.services.radius_client import live
from app.services.radius_client.manual import ManualRadiusClient

from conftest import login_admin


# ── list_offers parsing (live normalizer, no network) ────────────────────
def test_extract_offers_parses_profiles_shape():
    body = {
        "profiles": [
            {"id": "77", "name": "ساعة", "duration_minutes": 60, "speed": "6M/6M", "price": "2", "status": "active"},
            {"profile_id": "78", "profile_name": "ساعتين", "duration": 120, "is_active": False},
            {"name": "no-id-skip", "duration_minutes": 30},  # must be skipped (no external_id)
        ]
    }
    offers = live._extract_offers(body)
    assert len(offers) == 2
    by_id = {o["external_id"]: o for o in offers}
    assert "77" in by_id and "78" in by_id
    assert by_id["77"]["name"] == "ساعة"
    assert by_id["77"]["duration_label"] == "60 دقيقة"
    assert by_id["77"]["speed"] == "6M/6M"
    assert by_id["77"]["price"] == "2"
    assert by_id["77"]["active"] is True
    assert by_id["78"]["active"] is False


def test_extract_offers_supports_offers_and_data_and_dict_keys():
    assert live._extract_offers({"offers": [{"offer_id": "9", "offer_name": "A"}]})[0]["external_id"] == "9"
    assert live._extract_offers({"data": [{"external_id": "12", "title": "B"}]})[0]["name"] == "B"
    # dict-of-dicts container
    got = live._extract_offers({"batches": {"row1": {"batch_id": "5", "batch_name": "C"}}})
    assert got and got[0]["external_id"] == "5" and got[0]["name"] == "C"
    # empty / unknown shape → []
    assert live._extract_offers({"error": True}) == []


def test_manual_list_offers_returns_offline_stub():
    offers = ManualRadiusClient().list_offers()
    assert isinstance(offers, list) and len(offers) >= 1
    first = offers[0]
    for key in ("external_id", "name", "duration_label", "speed", "price", "active"):
        assert key in first


# ── save / read a link ───────────────────────────────────────────────────
def test_set_and_get_link_roundtrip():
    code = f"pytest_cat_{uuid4().hex[:6]}"
    try:
        assert card_offer_links.get_link(code) is None
        assert card_offer_links.get_linked_external_id(code) == ""

        res = card_offer_links.set_link(code, "rad-42", radius_offer_name="Offer 42",
                                        radius_duration_label="60 دقيقة", updated_by="pytest")
        assert res["ok"] and res.get("created")

        row = card_offer_links.get_link(code)
        assert row is not None
        assert row["radius_external_id"] == "rad-42"
        assert row["radius_offer_name"] == "Offer 42"
        assert card_offer_links.get_linked_external_id(code) == "rad-42"

        # update (idempotent, no duplicate row)
        res2 = card_offer_links.set_link(code, "rad-99", updated_by="pytest")
        assert res2["ok"] and res2.get("updated")
        assert card_offer_links.get_linked_external_id(code) == "rad-99"
        cnt = db.query_one("SELECT COUNT(*) AS c FROM card_offer_radius_links WHERE category_code=%s", [code])["c"]
        assert int(cnt) == 1

        # clear
        card_offer_links.clear_link(code, updated_by="pytest")
        assert card_offer_links.get_linked_external_id(code) == ""
    finally:
        db.execute_sql("DELETE FROM card_offer_radius_links WHERE category_code=%s", [code])


# ── admin page renders safely when not live ──────────────────────────────
def test_radius_links_page_renders_under_development(client):
    login_admin(client)
    page = client.get("/admin/cards/radius-links")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert "ربط العروض" in html
    # not live in the test env → the «قيد التطوير» notice must show, no crash
    assert "قيد التطوير" in html


def test_radius_links_offers_endpoint_is_safe_json(client):
    login_admin(client)
    resp = client.get("/admin/cards/radius-links/offers")
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["ok"] is True
    assert payload["under_dev"] is True          # manual mode in tests
    assert isinstance(payload["offers"], list)   # manual stub, UI stays functional


def test_radius_links_save_persists_and_shows_current(client):
    login_admin(client)
    from conftest import extract_csrf

    code = f"pytest_cat_{uuid4().hex[:6]}"
    page = client.get("/admin/cards/radius-links")
    token = extract_csrf(page.get_data(as_text=True))
    try:
        resp = client.post(
            "/admin/cards/radius-links/save",
            data={
                "_csrf_token": token,
                "category_code": code,
                "radius_external_id": "rad-777",
                "radius_offer_name": "Linked Offer",
                "radius_duration_label": "60 دقيقة",
            },
            headers={"X-CSRFToken": token, "X-Requested-With": "XMLHttpRequest"},
        )
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True
        assert card_offer_links.get_linked_external_id(code) == "rad-777"
    finally:
        db.execute_sql("DELETE FROM card_offer_radius_links WHERE category_code=%s", [code])
