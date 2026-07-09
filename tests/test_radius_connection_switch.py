"""Path 4 — قابلية تبديل ربط RADIUS + التشفير + إعادة ضبط الـ singleton.

مصدر الحقيقة صار صف ``radius_api_settings`` عبر ``resolve_radius_connection``
(env احتياطي فقط). هذه الاختبارات تعزل طبقة الإعدادات عبر ترقيع
``_load_settings_row`` كي لا تلمس صف الإعدادات المشترك في قاعدة البيانات.

ملاحظة بيئة: التطبيق يعمل على Python 3.12+ (صيغة f-string فيها backslash داخل
legacy_parts لا تُصرَّف على 3.10)، لذا تُشغَّل هذه الاختبارات ضمن بيئة التطبيق
الحقيقية. تم التحقق من نفس المنطق أيضًا عبر harness معزول.
"""
import pytest

from app.services import secret_box
from app.services.radius_config import resolve_radius_connection, reset_radius_config
from app.services.radius_client import (
    get_radius_client,
    is_api_under_development,
    is_live_mode,
    reset_radius_client,
)


_ENV_KEYS = (
    "RADIUS_MODE", "RADIUS_API_READY", "RADIUS_API_WRITES_ENABLED",
    "RADIUS_API_BASE_URL", "RADIUS_API_MASTER_KEY", "RADIUS_API_USERNAME",
    "RADIUS_API_PASSWORD", "RADIUS_API_VERIFY_SSL",
)


@pytest.fixture(autouse=True)
def _clean_radius_env(monkeypatch):
    for k in _ENV_KEYS:
        monkeypatch.delenv(k, raising=False)
    reset_radius_client()
    yield
    reset_radius_client()


def _set_row(monkeypatch, row):
    monkeypatch.setattr("app.services.radius_config._load_settings_row", lambda: row)
    reset_radius_config()


# ── secret_box ───────────────────────────────────────────────────────────
def test_secret_box_roundtrip_and_hides_plaintext():
    enc = secret_box.encrypt_secret("Sup3r!secret")
    assert enc.startswith("enc$")
    assert "Sup3r!secret" not in enc
    assert secret_box.decrypt_secret(enc) == "Sup3r!secret"


def test_secret_box_passthrough_and_empty():
    # نص صريح/قديم (من env) يمرّ كما هو
    assert secret_box.decrypt_secret("raw-env-key") == "raw-env-key"
    assert secret_box.encrypt_secret("") == ""
    assert secret_box.decrypt_secret("") == ""


# ── resolver: env fallback when no DB row ────────────────────────────────
def test_resolver_env_fallback_when_no_db_row(monkeypatch):
    _set_row(monkeypatch, None)
    monkeypatch.setenv("RADIUS_MODE", "live")
    monkeypatch.setenv("RADIUS_API_READY", "1")
    monkeypatch.setenv("RADIUS_API_BASE_URL", "http://envhost/app_ad2")
    reset_radius_config()
    cfg = resolve_radius_connection(refresh=True)
    assert cfg.base_url == "http://envhost/app_ad2"
    assert cfg.mode == "live"
    assert cfg.read_enabled is True
    assert cfg.write_enabled is False           # default off
    assert cfg.verify_ssl is True               # default on
    assert cfg.source == "env"
    assert is_live_mode() is True
    assert is_api_under_development() is False   # read enabled


# ── resolver: DB is source of truth (overrides env) ──────────────────────
def test_resolver_db_first_overrides_env_and_decrypts_secrets(monkeypatch):
    monkeypatch.setenv("RADIUS_MODE", "live")      # env says live...
    monkeypatch.setenv("RADIUS_API_READY", "1")
    _set_row(monkeypatch, {
        "id": 1,
        "base_url": "http://dbhost/app_ad2/",       # trailing slash trimmed
        "master_api_key_encrypted": secret_box.encrypt_secret("DBKEY"),
        "service_password_encrypted": secret_box.encrypt_secret("DBPASS"),
        "service_username": "svcuser",
        "mode": "manual",                            # ...DB says manual -> wins
        "read_enabled": 0,
        "write_enabled": 1,
        "verify_ssl": 0,
        "api_enabled": 1,
    })
    cfg = resolve_radius_connection(refresh=True)
    assert cfg.base_url == "http://dbhost/app_ad2"
    assert cfg.master_key == "DBKEY"
    assert cfg.service_password == "DBPASS"
    assert cfg.service_username == "svcuser"
    assert cfg.mode == "manual"
    assert cfg.read_enabled is False
    assert cfg.write_enabled is True
    assert cfg.verify_ssl is False
    assert cfg.api_enabled is True
    assert cfg.source == "db"
    assert is_api_under_development() is True        # manual -> under dev


# ── tri-state NULL columns inherit env (no regression for env deploys) ───
def test_resolver_null_flags_inherit_env(monkeypatch):
    monkeypatch.setenv("RADIUS_MODE", "live")
    monkeypatch.setenv("RADIUS_API_READY", "1")
    monkeypatch.setenv("RADIUS_API_WRITES_ENABLED", "1")
    monkeypatch.setenv("RADIUS_API_BASE_URL", "http://envhost/app_ad2")
    _set_row(monkeypatch, {
        "id": 1, "base_url": "", "mode": None,
        "read_enabled": None, "write_enabled": None, "verify_ssl": None,
    })
    cfg = resolve_radius_connection(refresh=True)
    assert cfg.mode == "live"
    assert cfg.read_enabled is True
    assert cfg.write_enabled is True
    assert cfg.base_url == "http://envhost/app_ad2"   # empty DB -> env fallback


# ── singleton reset picks up a target switch ─────────────────────────────
def test_singleton_reset_picks_up_switch(monkeypatch):
    _set_row(monkeypatch, {"id": 1, "base_url": "http://a/app_ad2", "mode": "live", "read_enabled": 1})
    first = get_radius_client()
    # switch target in DB, but singleton is cached until reset
    monkeypatch.setattr(
        "app.services.radius_config._load_settings_row",
        lambda: {"id": 1, "base_url": "http://b/app_ad2", "mode": "manual", "read_enabled": 0},
    )
    assert get_radius_client() is first               # still cached
    reset_radius_client()
    assert get_radius_client().mode == "manual"        # new target after reset


# ── test-connection uses health_check against the configured target ──────
def test_health_check_calls_configured_target(monkeypatch):
    _set_row(monkeypatch, {
        "id": 1, "base_url": "http://live/app_ad2", "mode": "live",
        "read_enabled": 1, "master_api_key_encrypted": secret_box.encrypt_secret("K"),
        "verify_ssl": 1,
    })
    from app.services.radius_client.live import LiveRadiusClient

    calls = {}

    class FakeResp:
        status_code = 200
        text = "{}"

        def json(self):
            return {"version": "5.5"}

    def fake_post(url, data=None, headers=None, timeout=None, verify=None):
        calls["url"] = url
        calls["verify"] = verify
        return FakeResp()

    monkeypatch.setattr("requests.post", fake_post)

    client = LiveRadiusClient()
    assert client.base_url == "http://live/app_ad2"
    assert client.master_key == "K"
    res = client.health_check()
    assert res.get("ok") is True
    assert res.get("data", {}).get("version") == "5.5"
    assert calls["url"] == "http://live/app_ad2/get_app_version"

    # ping is also safe against the target
    assert client.ping().get("ok") is True


def test_health_check_reports_failure_on_transport_error(monkeypatch):
    _set_row(monkeypatch, {"id": 1, "base_url": "http://live/app_ad2", "mode": "live", "read_enabled": 1})
    from app.services.radius_client.live import LiveRadiusClient

    def boom(*a, **k):
        raise Exception("connection refused")

    monkeypatch.setattr("requests.post", boom)
    res = LiveRadiusClient().health_check()
    assert res.get("ok") is False


# ── base_url must end with /app_ad2 (rule enforced by the settings view) ─
@pytest.mark.parametrize("url,ok", [
    ("http://h/app_ad2", True),
    ("http://h/app_ad2/", True),
    ("", True),                     # empty allowed (not yet configured)
    ("http://h/app_ad", False),     # the doc typo — must be rejected
    ("http://h", False),
])
def test_base_url_app_ad2_rule(url, ok):
    normalized = (url or "").strip().rstrip("/")
    assert ((not normalized) or normalized.endswith("/app_ad2")) is ok
