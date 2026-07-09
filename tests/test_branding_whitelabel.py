"""Path 4 — هوية النسخة (white-label): الاسم القابل للضبط يصل إلى قوالب الـ chrome.

نتحقق من طبقتين:
1) خدمة branding تقرأ الاسم/الوسم من app_branding مع الافتراضي "Hobe Hub".
2) الـ context processor يحقن ``brand_name``/``brand_tagline`` في كل قالب (وهو
   ما يغذّي عنوان الصفحة وترويسة اللوحة في dashboard/_layout.html و auth/_layout.html).
"""
import os

from flask import render_template_string

from app.services import branding as branding_mod


def test_branding_default_is_hobe_hub(monkeypatch):
    monkeypatch.setattr(branding_mod, "_load_row", lambda: None)
    branding_mod.reset_branding_cache()
    b = branding_mod.get_branding(refresh=True)
    assert b.brand_name == "Hobe Hub"
    assert b.tagline  # default tagline present
    branding_mod.reset_branding_cache()


def test_branding_custom_name_from_db(monkeypatch):
    monkeypatch.setattr(
        branding_mod, "_load_row",
        lambda: {"id": 1, "brand_name": "NetPro", "tagline": "إنترنت أسرع"},
    )
    branding_mod.reset_branding_cache()
    b = branding_mod.get_branding(refresh=True)
    assert b.brand_name == "NetPro"
    assert b.tagline == "إنترنت أسرع"
    branding_mod.reset_branding_cache()


def test_context_processor_injects_custom_brand(monkeypatch, app):
    """الاسم المضبوط يصل لكل قالب عبر الـ context processor (يغذّي العنوان/الترويسة)."""
    monkeypatch.setattr(
        branding_mod, "_load_row",
        lambda: {"id": 1, "brand_name": "NetProBrand", "tagline": "شعار مخصص"},
    )
    branding_mod.reset_branding_cache()
    try:
        with app.test_request_context("/"):
            out = render_template_string("{{ brand_name }}|{{ brand_tagline }}")
        assert out == "NetProBrand|شعار مخصص"
    finally:
        branding_mod.reset_branding_cache()


def test_context_processor_defaults_when_unset(monkeypatch, app):
    monkeypatch.setattr(branding_mod, "_load_row", lambda: None)
    branding_mod.reset_branding_cache()
    try:
        with app.test_request_context("/"):
            out = render_template_string("{{ brand_name }}")
        assert out == "Hobe Hub"
    finally:
        branding_mod.reset_branding_cache()


def test_layout_templates_are_wired_to_brand_name():
    """القوالب الأساسية تستهلك brand_name (وليس نصًّا مثبّتًا)."""
    base = os.path.join(os.path.dirname(__file__), "..", "app", "templates")
    for rel in ("dashboard/_layout.html", "auth/_layout.html"):
        with open(os.path.join(base, rel), encoding="utf-8") as fh:
            assert "brand_name" in fh.read(), rel
