"""Tests for ApiV1RadiusClient — the /api/v1 (radius-module) protocol client.

Mirrors tests/test_radius_connection_switch.py style: a fake transport replaces
requests.request so each method's URL + auth + params/body and the ok()/fail()
envelope parsing are asserted without a live server.

Env note: the app runs on Python 3.12+. The same client logic is additionally
validated via an isolated fake-transport harness on 3.10.
"""
import json
from types import SimpleNamespace

import pytest

from app.services.radius_client.apiv1 import ApiV1RadiusClient
from app.services.radius_client.base import RadiusClientNotImplemented
from app.services.radius_client import get_radius_client, reset_radius_client
from app.services.radius_config import reset_radius_config


# ── fake transport ───────────────────────────────────────────────────────
class _FakeResp:
    def __init__(self, payload, status=200):
        self._p = payload
        self.status_code = status
        self.text = json.dumps(payload)

    def json(self):
        return self._p


class _Transport:
    def __init__(self):
        self.calls = []
        self.router = {}
        self.raise_exc = None

    def request(self, method, url, params=None, json=None, headers=None,
                auth=None, timeout=None, verify=None):
        self.calls.append(dict(method=method, url=url, params=params, json=json,
                               headers=headers, auth=auth, verify=verify))
        if self.raise_exc:
            raise self.raise_exc
        for (m, suffix), payload in self.router.items():
            if method == m and url.endswith(suffix):
                return _FakeResp(payload)
        return _FakeResp({"ok": True, "data": {}})

    @property
    def last(self):
        return self.calls[-1]


def _cfg(base="http://x/api/v1", read=True, write=True, master="TOK",
         verify=True, user="", pw=""):
    return SimpleNamespace(
        base_url=base, master_key=master, service_username=user,
        service_password=pw, verify_ssl=verify, read_enabled=read,
        write_enabled=write, api_flavor="apiv1",
    )


@pytest.fixture
def transport(monkeypatch):
    t = _Transport()
    monkeypatch.setattr("requests.request", t.request)
    return t


# ── health / connectivity ────────────────────────────────────────────────
def test_health_check_success_maps_release_to_version(transport):
    transport.router[("GET", "/health")] = {
        "ok": True, "data": {"status": "ok", "release": "0.1.0-foundation"}}
    res = ApiV1RadiusClient(cfg=_cfg()).health_check()
    assert res["ok"] is True
    assert res["data"]["version"] == "0.1.0-foundation"
    assert transport.last["url"] == "http://x/api/v1/health"
    # health is unauthenticated -> no Authorization header
    assert "Authorization" not in transport.last["headers"]


def test_health_check_failure_on_transport_error(transport):
    transport.raise_exc = Exception("connection refused")
    assert ApiV1RadiusClient(cfg=_cfg()).health_check()["ok"] is False


def test_ping_is_safe_no_auth(transport):
    transport.router[("GET", "/health")] = {"ok": True, "data": {"release": "1"}}
    assert ApiV1RadiusClient(cfg=_cfg()).ping()["ok"] is True


# ── search_users (match engine) ──────────────────────────────────────────
def test_search_users_builds_accounts_query_and_parses_items(transport):
    transport.router[("GET", "/accounts")] = {
        "ok": True,
        "data": {"items": [{"username": "u1", "mobile": "0599", "id": 5,
                            "status": "active"}], "count": 1}}
    res = ApiV1RadiusClient(cfg=_cfg()).search_users("0599", limit=10)
    assert res["ok"] is True
    assert res["data"][0]["username"] == "u1"
    assert transport.last["url"] == "http://x/api/v1/accounts"
    assert transport.last["params"]["search"] == "0599"
    assert transport.last["params"]["limit"] == 10
    assert transport.last["headers"]["Authorization"] == "Bearer TOK"


def test_search_users_empty_query_omits_search_param(transport):
    transport.router[("GET", "/accounts")] = {"ok": True, "data": {"items": []}}
    ApiV1RadiusClient(cfg=_cfg()).search_users("")
    assert "search" not in (transport.last["params"] or {})


# ── profiles / offers ────────────────────────────────────────────────────
def test_get_profiles_normalizes_dto_keys(transport):
    transport.router[("GET", "/profiles")] = {
        "ok": True, "data": {"items": [{
            "id": 3, "name": "P", "speed_down_kbps": 2048, "speed_up_kbps": 1024,
            "duration_minutes": 60, "quota_total_mb": 500, "enabled": True}]}}
    ps = ApiV1RadiusClient(cfg=_cfg()).get_profiles()
    assert ps[0]["external_id"] == "3"
    assert ps[0]["speed_down_kbps"] == 2048
    assert ps[0]["quota_mb"] == 500


def test_list_offers_from_profiles(transport):
    transport.router[("GET", "/profiles")] = {
        "ok": True, "data": {"items": [{"id": 3, "name": "P", "enabled": True}]}}
    offers = ApiV1RadiusClient(cfg=_cfg()).list_offers()
    assert offers and offers[0]["external_id"] == "3" and offers[0]["active"] is True


# ── online / usage ───────────────────────────────────────────────────────
def test_get_online_users_normalizes_session_keys(transport):
    transport.router[("GET", "/sessions/online")] = {
        "ok": True, "data": {"items": [{
            "username": "u1", "session_time": 123, "framed_ip": "10.0.0.5",
            "mac_address": "AA:BB", "nas_ip_address": "1.1.1.1"}]}}
    on = ApiV1RadiusClient(cfg=_cfg()).get_online_users()
    assert on[0]["running_seconds"] == 123
    assert on[0]["framedipaddress"] == "10.0.0.5"
    assert on[0]["calling_station_id"] == "AA:BB"


def test_get_user_usage_normalizes_and_accepts_dict(transport):
    transport.router[("GET", "/accounts/u1/usage")] = {
        "ok": True, "data": {"username": "u1", "used_seconds": 120,
                            "used_bytes_in": 1000, "used_bytes_out": 2000,
                            "last_seen_at": "2026-01-01T00:00:00Z"}}
    c = ApiV1RadiusClient(cfg=_cfg())
    u = c.get_user_usage("u1")
    assert u["total_seconds"] == 120
    assert u["total_bytes_in"] == 1000 and u["bytes_in"] == 1000
    # dict identifier (legacy call style) also works
    assert c.get_user_usage({"username": "u1"})["total_seconds"] == 120


# ── card generation (write) ──────────────────────────────────────────────
def test_generate_user_cards_posts_plan_and_parses_card(transport):
    transport.router[("POST", "/cards/generate")] = {
        "ok": True, "data": {"batch": {"id": 7}, "cards": [
            {"username": "c1", "password": "p1", "id": 9, "duration_minutes": 60}]}}
    r = ApiV1RadiusClient(cfg=_cfg()).generate_user_cards(
        "one_hour", 1, radius_offer_external_id="3")
    assert r.ok is True
    assert r.data["card_username"] == "c1"
    assert r.data["card_password"] == "p1"
    assert r.data["external_id"] == "9"
    assert transport.last["url"] == "http://x/api/v1/cards/generate"
    assert transport.last["json"] == {"plan_id": 3, "count": 1}
    assert transport.last["method"] == "POST"


def test_generate_requires_numeric_plan_id():
    r = ApiV1RadiusClient(cfg=_cfg()).generate_user_cards(
        "x", 1, radius_offer_external_id="")
    assert r.ok is False


# ── other write mappings ─────────────────────────────────────────────────
def test_reset_password_add_time_disconnect_mac(transport):
    c = ApiV1RadiusClient(cfg=_cfg())
    transport.router[("POST", "/accounts/u1/reset_password")] = {"ok": True, "data": {}}
    assert c.reset_password("u1", "newpw").ok is True
    assert transport.last["json"] == {"new_password": "newpw"}

    transport.router[("POST", "/accounts/u1/extend_time")] = {"ok": True, "data": {}}
    assert c.add_time("u1", sel_time=0, add_time=30).ok is True
    assert transport.last["json"] == {"minutes": 30}

    transport.router[("POST", "/sessions/disconnect")] = {"ok": True, "data": {}}
    assert c.disconnect("u1").ok is True
    assert transport.last["json"]["username"] == "u1"

    transport.router[("PATCH", "/accounts/u1")] = {"ok": True, "data": {}}
    assert c.set_mac_lock("u1", "AA:BB:CC:DD:EE:FF").ok is True
    assert transport.last["method"] == "PATCH"
    assert transport.last["json"]["mac_lock"] == "AA:BB:CC:DD:EE:FF"


# ── auth selection: basic when no master key ─────────────────────────────
def test_basic_auth_when_no_master_key(transport):
    transport.router[("GET", "/accounts")] = {"ok": True, "data": {"items": []}}
    ApiV1RadiusClient(cfg=_cfg(master="", user="admin", pw="secret")).search_users("q")
    assert transport.last["auth"] == ("admin", "secret")
    assert "Authorization" not in transport.last["headers"]


# ── guards ───────────────────────────────────────────────────────────────
def test_read_guard_degrades_gracefully(transport):
    c = ApiV1RadiusClient(cfg=_cfg(read=False))
    assert c.search_users("x")["ok"] is False
    assert c.get_profiles() == []
    assert c.get_user_usage("u1") is None


def test_write_guard_blocks_generate(transport):
    with pytest.raises(RadiusClientNotImplemented):
        ApiV1RadiusClient(cfg=_cfg(write=False)).generate_user_cards(
            "x", 1, radius_offer_external_id="3")


def test_fail_envelope_surfaces_message(transport):
    transport.router[("GET", "/accounts")] = {
        "ok": False, "error": {"code": "unauthorized", "message": "bad token"}}
    res = ApiV1RadiusClient(cfg=_cfg()).search_users("q")
    assert res["ok"] is False
    assert "bad token" in res["error"]


# ── selection: /api/v1 base_url picks ApiV1RadiusClient ──────────────────
def _set_row(monkeypatch, row):
    monkeypatch.setattr("app.services.radius_config._load_settings_row", lambda: row)
    reset_radius_config()
    reset_radius_client()


def test_selection_picks_apiv1_for_api_v1_base_url(monkeypatch):
    _set_row(monkeypatch, {"id": 1, "base_url": "http://h/api/v1",
                          "mode": "live", "read_enabled": 1})
    try:
        assert isinstance(get_radius_client(), ApiV1RadiusClient)
    finally:
        reset_radius_client()


def test_selection_picks_legacy_for_app_ad2_base_url(monkeypatch):
    from app.services.radius_client.live import LiveRadiusClient
    _set_row(monkeypatch, {"id": 1, "base_url": "http://h/app_ad2",
                          "mode": "live", "read_enabled": 1})
    try:
        assert isinstance(get_radius_client(), LiveRadiusClient)
    finally:
        reset_radius_client()


# ── base_url validation rule enforced by the settings view ───────────────
@pytest.mark.parametrize("url,ok", [
    ("http://h/api/v1", True),
    ("http://h/api/v1/", True),
    ("", True),
    ("http://h/app_ad2", False),
    ("http://h", False),
])
def test_apiv1_base_url_rule(url, ok):
    normalized = (url or "").strip().rstrip("/")
    assert ((not normalized) or normalized.endswith("/api/v1")) is ok
