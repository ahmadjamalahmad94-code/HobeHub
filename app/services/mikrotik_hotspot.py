from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlencode

from app.config import MIKROTIK_HOTSPOT_URL


@dataclass(frozen=True)
class HotspotConnectUrls:
    logout_url: str
    login_url: str


def hotspot_base_url() -> str:
    """رابط بوابة المايكروتك الأساس. الأولويّة لمتغيّر البيئة، ثمّ الرابط المحفوظ
    في «إعدادات البطاقات» (radius_api_settings.router_login_url) — فيكفي ضبطه من
    الواجهة دون متغيّر بيئة. يُضاف //:http إن غاب المخطّط، وتُزال لاحقة /login."""
    base = (os.getenv("MIKROTIK_HOTSPOT_URL") or MIKROTIK_HOTSPOT_URL or "").strip()
    if not base:
        try:
            from app import legacy
            row = legacy.query_one(
                "SELECT router_login_url FROM radius_api_settings WHERE id=1"
            )
            base = str((row or {}).get("router_login_url") or "").strip()
        except Exception:
            base = ""
    base = base.rstrip("/")
    if not base:
        return ""
    if "://" not in base:
        base = "http://" + base  # كي يتنقّل المتصفّح إليه
    # الأساس لا يتضمّن /login (تُضاف عبر hotspot_url) — أزِلها إن أدرجها المستخدم
    if base.lower().endswith("/login"):
        base = base[: -len("/login")]
    return base.rstrip("/")


def hotspot_url(path: str, params: dict[str, str] | None = None) -> str:
    base_url = hotspot_base_url()
    if not base_url:
        raise ValueError("MIKROTIK_HOTSPOT_URL is not configured.")

    url = f"{base_url}/{path.lstrip('/')}"
    if params:
        url = f"{url}?{urlencode(params)}"
    return url


def hotspot_login_url() -> str:
    base_url = hotspot_base_url()
    return f"{base_url}/login" if base_url else ""


def build_card_connect_urls(*, card_username: str, card_password: str) -> HotspotConnectUrls:
    return HotspotConnectUrls(
        logout_url=hotspot_url("logout"),
        login_url=hotspot_url(
            "login",
            {
                "username": card_username or "",
                "password": card_password or "",
            },
        ),
    )
