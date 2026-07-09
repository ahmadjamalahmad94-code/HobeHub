"""Tests for subscriber_radius_view — the live-RADIUS view-model for the
subscriber's own personal page (/user/account).

Uses an injected fake client + injected under_development flag so the pure
view-model logic is exercised without touching the real RADIUS API. The
module is importable in isolation (app deps are lazily imported inside the
public function only), so these tests run even where the full Flask app
cannot import.
"""
import pytest

from app.services import subscriber_radius_view as srv
from app.services.subscriber_radius_view import (
    build_subscriber_radius_view,
    fmt_bytes,
    fmt_duration_seconds,
    fmt_speed_kbps,
    fmt_speed_value,
    UNAVAILABLE_LABEL,
)


class FakeRadiusClient:
    """Minimal stand-in exposing the read methods the view-model calls."""

    mode = "live"

    def __init__(self, usage=None, bandwidth=None, sessions=None, profiles=None):
        self._usage = usage
        self._bandwidth = bandwidth
        self._sessions = sessions
        self._profiles = profiles or []

    def get_user_usage(self, user_id):
        return self._usage

    def get_user_bandwidth(self, user_id):
        return self._bandwidth

    def get_user_sessions(self, user_id):
        return self._sessions

    def get_profiles(self):
        return self._profiles


def _fields_by_key(view):
    return {f["key"]: f for f in view["fields"]}


# ── formatting helpers ────────────────────────────────────────────────
def test_fmt_speed_kbps():
    assert fmt_speed_kbps(20000) == "20 Mbps"
    assert fmt_speed_kbps(1500) == "1.5 Mbps"
    assert fmt_speed_kbps(512) == "512 Kbps"
    assert fmt_speed_kbps(0) == ""


def test_fmt_speed_value_trusts_strings():
    assert fmt_speed_value("20M/20M") == "20M/20M"
    assert fmt_speed_value("10000") == "10 Mbps"
    assert fmt_speed_value("") == ""


def test_fmt_bytes():
    assert fmt_bytes(0) == "0 B"
    assert fmt_bytes(1024) == "1 KB"
    assert fmt_bytes(1610612736) == "1.5 GB"


def test_fmt_duration_seconds():
    assert fmt_duration_seconds(3600 * 3 + 60 * 20) == "3س 20د"
    assert fmt_duration_seconds(60 * 45) == "45د"
    assert fmt_duration_seconds(0) == "0د"


# ── live view-model mapping ───────────────────────────────────────────
def test_live_view_maps_each_available_field():
    client = FakeRadiusClient(
        usage={
            "data": {
                "profile_name": "باقة 20 ميجا",
                "total_sessions": 12,
                "total_bytes_in": 1073741824,   # 1 GB
                "total_bytes_out": 536870912,   # 0.5 GB
                "total_seconds": 3600 * 3 + 60 * 20,
            }
        },
        bandwidth={"down_speed": "20M", "up_speed": "20M"},
        sessions={"data": [{"id": 1}, {"id": 2}]},
    )
    view = build_subscriber_radius_view(
        1, "netuser", client=client, local_account={}, under_development=False
    )
    assert view["state"] == "live"
    assert view["is_live"] is True
    f = _fields_by_key(view)
    assert f["plan"]["value"] == "باقة 20 ميجا" and f["plan"]["available"]
    assert f["speed_down"]["value"] == "20M"
    assert f["speed_up"]["value"] == "20M"
    assert f["sessions"]["value"] == "12"
    assert f["consumption"]["value"] == "1.5 GB"
    assert f["connection_time"]["value"] == "3س 20د"


def test_speed_falls_back_to_matched_profile_kbps():
    client = FakeRadiusClient(
        usage={"data": {"profile_id": "P1", "total_sessions": 1}},
        profiles=[{"external_id": "P1", "name": "P1", "speed_up_kbps": 5000, "speed_down_kbps": 20000}],
    )
    view = build_subscriber_radius_view(
        1, "netuser", client=client, local_account={"current_profile_id": "P1"},
        under_development=False,
    )
    f = _fields_by_key(view)
    assert f["speed_up"]["value"] == "5 Mbps"
    assert f["speed_down"]["value"] == "20 Mbps"


def test_sessions_count_from_session_list_when_no_total():
    client = FakeRadiusClient(
        usage={"data": {"profile_name": "x"}},
        sessions=[{"id": 1}, {"id": 2}, {"id": 3}],
    )
    view = build_subscriber_radius_view(
        1, "netuser", client=client, local_account={}, under_development=False
    )
    f = _fields_by_key(view)
    assert f["sessions"]["value"] == "3"


def test_unavailable_fields_show_placeholder():
    """المدة اليومية / وقت الدوام / الساعات المسحوبة لا ترجعها الـ DTOs الحالية."""
    client = FakeRadiusClient(usage={"data": {"profile_name": "x", "total_sessions": 1}})
    view = build_subscriber_radius_view(
        1, "netuser", client=client, local_account={}, under_development=False
    )
    f = _fields_by_key(view)
    for key in ("daily_duration", "work_schedule", "hours_used_remaining"):
        assert f[key]["available"] is False
        assert f[key]["value"] == UNAVAILABLE_LABEL


def test_defensive_read_of_optional_fields_when_present():
    """لو ظهرت هذه المفاتيح في الرد الخام مستقبلًا، تُعرض بدل الـ placeholder."""
    client = FakeRadiusClient(
        usage={
            "data": {
                "profile_name": "x",
                "daily_minutes": 120,
                "arr_days": "السبت-الخميس",
                "limit_from": "08:00",
                "limit_to": "16:00",
                "hours_used": 3,
                "hours_remaining": 5,
            }
        }
    )
    view = build_subscriber_radius_view(
        1, "netuser", client=client, local_account={}, under_development=False
    )
    f = _fields_by_key(view)
    assert f["daily_duration"]["available"] and f["daily_duration"]["value"] == "2س"
    assert f["work_schedule"]["available"]
    assert "السبت-الخميس" in f["work_schedule"]["value"]
    assert f["hours_used_remaining"]["available"]
    assert "3" in f["hours_used_remaining"]["value"] and "5" in f["hours_used_remaining"]["value"]


# ── graceful degradation ──────────────────────────────────────────────
def test_under_development_is_safe():
    view = build_subscriber_radius_view(
        1, "netuser", client=None, local_account={"current_profile_name": "باقة"},
        under_development=True,
    )
    assert view["state"] == "under_development"
    assert view["is_live"] is False
    f = _fields_by_key(view)
    # local plan name still surfaces; live-only fields become unavailable
    assert f["plan"]["value"] == "باقة"
    assert f["sessions"]["value"] == UNAVAILABLE_LABEL


def test_no_linked_id_is_safe():
    view = build_subscriber_radius_view(
        1, "", client=None, local_account={}, under_development=False
    )
    assert view["state"] == "unlinked"
    assert view["is_live"] is False
    # never crashes; all fields render as unavailable placeholders
    assert all(f["value"] == UNAVAILABLE_LABEL for f in view["fields"])


def test_client_exceptions_do_not_crash():
    class BoomClient:
        mode = "live"

        def get_user_usage(self, _):
            raise RuntimeError("boom")

        def get_user_bandwidth(self, _):
            raise RuntimeError("boom")

        def get_user_sessions(self, _):
            raise RuntimeError("boom")

        def get_profiles(self):
            raise RuntimeError("boom")

    view = build_subscriber_radius_view(
        1, "netuser", client=BoomClient(), local_account={}, under_development=False
    )
    assert view["state"] == "no_data"
    assert view["is_live"] is True
    assert all(not f["available"] for f in view["fields"])
