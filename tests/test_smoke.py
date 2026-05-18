from markupsafe import Markup
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit
import ast
import io
import re
from datetime import datetime, timezone
from uuid import uuid4

from app import db, legacy
from app.dashboard.services import (
    build_power_timer_status,
    get_beneficiary_access_label,
    get_beneficiary_access_mode,
    get_type_label,
    get_usage_label,
)
from app.imports.beneficiaries import (
    build_existing_lookup_maps,
    infer_user_type,
    normalize_import_row,
    split_import_operations,
)
from app.imports.tasks import ImportTaskStore
from app.security.passwords import admin_password_hash, sha256_text, verify_admin_password
from app.utils.text import clean_csv_value, full_name_from_parts, normalize_phone, normalize_search_ar, split_full_name

from conftest import extract_csrf, login_admin, visible_text


def login_beneficiary(client):
    for username, password in [
        ("0599123456", "demo12345"),
        ("0592383920", "12345"),
        ("fatema", "12345"),
        ("alaa", "2007"),
    ]:
        page = client.get("/login")
        token = extract_csrf(page.get_data(as_text=True))
        response = client.post(
            "/login/submit",
            data={"identifier": username, "password": password, "_csrf_token": token},
            follow_redirects=False,
        )
        payload = response.get_json(silent=True) or {}
        if response.status_code == 200 and payload.get("ok") and payload.get("redirect"):
            target_response = client.get(payload["redirect"], follow_redirects=False)
            location = target_response.headers.get("Location") or payload["redirect"]
            path = urlsplit(location).path
            if path in {"/user/account", "/card"}:
                return SimpleNamespace(status_code=302, headers={"Location": path}, json=payload)
    raise AssertionError("No known beneficiary test login worked")


def test_core_public_pages_render_clean_arabic(client):
    for path in ["/portal", "/login", "/user/register"]:
        response = client.get(path)
        assert response.status_code == 200
        text = visible_text(response.get_data(as_text=True))
        assert "Ø" not in text
        assert "Ù" not in text
        assert "Ã" not in text
        assert "Â" not in text

    for path in ["/user/login", "/card/login"]:
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 302
        assert response.headers["Location"].endswith("/login")


def test_portal_login_buttons_use_three_layer_paths(client):
    response = client.get("/portal")
    html = response.get_data(as_text=True)
    assert 'href="/login"' in html
    assert 'href="/user/login?mode=user"' not in html
    assert 'href="/card/login"' not in html

    for path in ["/user/login?mode=user", "/card/login"]:
        page = client.get(path, follow_redirects=False)
        assert page.status_code == 302
        assert page.headers["Location"].endswith("/login")


def test_portal_account_access_state_freeze_and_disable(client):
    login_admin(client)
    row = db.query_one(
        "SELECT id FROM beneficiary_portal_accounts WHERE username=%s LIMIT 1",
        ["0599123456"],
    )
    assert row
    portal_id = row["id"]

    def post_state(state):
        page = client.get("/admin/portal-accounts")
        token = extract_csrf(page.get_data(as_text=True))
        return client.post(
            f"/admin/portal-accounts/{portal_id}/access-state",
            data={"state": state, "_csrf_token": token},
            headers={"X-Requested-With": "XMLHttpRequest"},
        )

    try:
        response = post_state("frozen")
        assert response.status_code == 200
        assert response.get_json()["ok"] is True

        with client.session_transaction() as sess:
            sess.clear()
        page = client.get("/login")
        token = extract_csrf(page.get_data(as_text=True))
        login_response = client.post(
            "/login/submit",
            data={"identifier": "0599123456", "password": "demo12345", "_csrf_token": token},
            follow_redirects=False,
        )
        payload = login_response.get_json()
        assert login_response.status_code == 200
        assert payload["ok"] is True
        assert payload["redirect"].endswith("/user/profile")
        blocked = client.get("/user/account", follow_redirects=False)
        assert blocked.status_code == 302
        assert blocked.headers["Location"].endswith("/user/profile")

        with client.session_transaction() as sess:
            sess.clear()
        login_admin(client)
        response = post_state("disabled")
        assert response.status_code == 200
        assert response.get_json()["ok"] is True

        with client.session_transaction() as sess:
            sess.clear()
        page = client.get("/login")
        token = extract_csrf(page.get_data(as_text=True))
        disabled_login = client.post(
            "/login/submit",
            data={"identifier": "0599123456", "password": "demo12345", "_csrf_token": token},
            follow_redirects=False,
        )
        assert disabled_login.status_code == 403
        assert "حسابك معطل" in disabled_login.get_json()["message"]
    finally:
        with client.session_transaction() as sess:
            sess.clear()
        login_admin(client)
        post_state("active")


def test_admin_login_requires_csrf(client):
    response = client.post(
        "/login",
        data={"username": "admin", "password": "123456"},
        follow_redirects=False,
    )
    assert response.status_code in {302, 400}
    assert response.headers.get("Location") != "/dashboard"


def test_admin_login_and_dashboard(client):
    response = login_admin(client)
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "لوحة التحكم" in visible_text(html)
    assert '<aside class="d-sidebar"' in html
    assert "/admin/cards/import" in html
    assert "/admin/timer" in html


def test_admin_dashboard_canonical_page_renders(client):
    login_admin(client)
    response = client.get("/admin/dashboard")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert '<aside class="d-sidebar"' in html
    assert "/admin/cards/import" in html


def test_notification_centers_and_bell_links_render(client):
    login_admin(client)
    dashboard = client.get("/admin/dashboard")
    dashboard_html = dashboard.get_data(as_text=True)
    assert 'class="d-bell"' in dashboard_html
    assert 'class="d-notification-menu"' in dashboard_html
    assert 'href="/admin/notifications"' in dashboard_html
    assert 'href="/admin/notifications" data-label="الإشعارات"' in dashboard_html
    admin_page = client.get("/admin/notifications")
    assert admin_page.status_code == 200
    assert "notice-grid" in admin_page.get_data(as_text=True)
    admin_count = client.get("/admin/notifications/count")
    assert admin_count.status_code == 200
    assert admin_count.get_json()["ok"] is True
    assert isinstance(admin_count.get_json()["count"], int)

    with client.session_transaction() as sess:
        sess.clear()
    login_response = login_beneficiary(client)
    target = "/card/notifications" if login_response.headers["Location"] == "/card" else "/user/notifications"
    page = client.get(target)
    assert page.status_code == 200
    page_html = page.get_data(as_text=True)
    assert 'class="d-bell"' in page_html
    assert 'class="d-notification-menu"' in page_html
    assert "sub-notice-list" in page_html
    count_target = "/card/notifications/count" if target.startswith("/card") else "/user/notifications/count"
    count_page = client.get(count_target)
    assert count_page.status_code == 200
    assert count_page.get_json()["ok"] is True
    assert isinstance(count_page.get_json()["count"], int)


def test_notifications_can_be_created_and_marked_read(client):
    from app.services.notification_service import (
        create_admin_notification,
        create_beneficiary_notification,
        notification_count_for_session,
    )

    login_admin(client)
    admin_before = client.get("/admin/notifications/count").get_json()["count"]
    notification_id = create_admin_notification(
        title="pytest admin notice",
        body="admin body",
        event_type="pytest",
        status="pending",
        source_type="pytest",
        source_id=1,
        action_url="/admin/notifications",
    )
    try:
        assert notification_id > 0
        assert client.get("/admin/notifications/count").get_json()["count"] == admin_before + 1
        page = client.get("/admin/notifications")
        token = extract_csrf(page.get_data(as_text=True))
        response = client.post(
            f"/admin/notifications/{notification_id}/read",
            data={"_csrf_token": token},
            follow_redirects=False,
        )
        assert response.status_code == 302
        assert client.get("/admin/notifications/count").get_json()["count"] == admin_before
    finally:
        db.execute_sql("DELETE FROM notifications WHERE id=%s", [notification_id])

    with client.session_transaction() as sess:
        sess.clear()
    login_beneficiary(client)
    with client.session_transaction() as sess:
        beneficiary_id = int(sess["beneficiary_id"])
        subscriber_before = notification_count_for_session(sess)
    subscriber_id = create_beneficiary_notification(
        beneficiary_id,
        title="pytest subscriber notice",
        body="subscriber body",
        event_type="pytest",
        status="pending",
        source_type="pytest",
        source_id=2,
        action_url="/user/notifications",
    )
    try:
        assert subscriber_id > 0
        count_target = "/card/notifications/count" if client.get("/card").status_code == 200 else "/user/notifications/count"
        assert client.get(count_target).get_json()["count"] == subscriber_before + 1
    finally:
        db.execute_sql("DELETE FROM notifications WHERE id=%s", [subscriber_id])


def test_admin_profile_actions_create_notifications(client):
    login_admin(client)
    page = client.get("/admin/dashboard")
    token = extract_csrf(page.get_data(as_text=True))
    phone = f"0593{int(uuid4().hex[:8], 16) % 1_000_000:06d}"
    beneficiary_id = None
    attachment_id = None

    try:
        add_response = client.post(
            "/admin/beneficiaries/add-ajax",
            data={
                "_csrf_token": token,
                "user_type": "freelancer",
                "first_name": "Notify",
                "second_name": "Test",
                "third_name": "",
                "fourth_name": "User",
                "phone": phone,
                "freelancer_specialization": "QA",
                "freelancer_internet_method": "\u0646\u0638\u0627\u0645 \u0627\u0644\u0628\u0637\u0627\u0642\u0627\u062a",
                "notes": "pytest notifications",
            },
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        assert add_response.status_code == 200
        beneficiary_id = int(add_response.get_json()["id"])
        created_notice = db.query_one(
            """
            SELECT id FROM notifications
            WHERE recipient_type='admin' AND source_type='beneficiary'
              AND source_id=%s AND event_type='beneficiary_created'
            ORDER BY id DESC LIMIT 1
            """,
            [beneficiary_id],
        )
        assert created_notice is not None

        edit_response = client.post(
            f"/admin/beneficiaries/{beneficiary_id}/quick-edit",
            data={
                "_csrf_token": token,
                "user_type": "freelancer",
                "first_name": "Notify",
                "second_name": "Edited",
                "third_name": "",
                "fourth_name": "User",
                "phone": phone,
                "freelancer_specialization": "QA",
                "freelancer_internet_method": "\u0646\u0638\u0627\u0645 \u0627\u0644\u0628\u0637\u0627\u0642\u0627\u062a",
                "notes": "pytest edited",
            },
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        assert edit_response.status_code == 200
        assert edit_response.get_json()["ok"] is True
        assert db.query_one(
            """
            SELECT id FROM notifications
            WHERE recipient_type='admin' AND source_type='beneficiary'
              AND source_id=%s AND event_type='beneficiary_profile_updated'
            ORDER BY id DESC LIMIT 1
            """,
            [beneficiary_id],
        )
        assert db.query_one(
            """
            SELECT id FROM notifications
            WHERE recipient_type='beneficiary' AND recipient_id=%s
              AND event_type='beneficiary_profile_updated'
            ORDER BY id DESC LIMIT 1
            """,
            [beneficiary_id],
        )

        tier_response = client.post(
            f"/admin/users/{beneficiary_id}/set-tier",
            data={"_csrf_token": token, "tier": "standard"},
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        assert tier_response.status_code == 200
        assert db.query_one(
            """
            SELECT id FROM notifications
            WHERE recipient_type='beneficiary' AND recipient_id=%s
              AND event_type='beneficiary_tier_updated'
            ORDER BY id DESC LIMIT 1
            """,
            [beneficiary_id],
        )

        verification_response = client.post(
            f"/admin/users/{beneficiary_id}/set-verification",
            data={"_csrf_token": token, "status": "verified", "until": "2026-12-31"},
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        assert verification_response.status_code == 200
        assert db.query_one(
            """
            SELECT id FROM notifications
            WHERE recipient_type='beneficiary' AND recipient_id=%s
              AND event_type='beneficiary_verification_updated'
            ORDER BY id DESC LIMIT 1
            """,
            [beneficiary_id],
        )

        upload_response = client.post(
            f"/admin/users/{beneficiary_id}/attachments",
            data={
                "_csrf_token": token,
                "kind": "note",
                "label": "pytest file",
                "file": (io.BytesIO(b"pytest attachment"), "pytest-note.txt"),
            },
            headers={"X-Requested-With": "XMLHttpRequest"},
            content_type="multipart/form-data",
        )
        assert upload_response.status_code == 200
        attachment_id = int(upload_response.get_json()["id"])
        assert db.query_one(
            """
            SELECT id FROM notifications
            WHERE recipient_type='admin' AND source_type='user_attachment'
              AND source_id=%s AND event_type='beneficiary_attachment_uploaded'
            ORDER BY id DESC LIMIT 1
            """,
            [attachment_id],
        )

        message_response = client.post(
            f"/admin/users/{beneficiary_id}/messages",
            data={"_csrf_token": token, "kind": "warning", "body": "تحذير تجريبي للمشترك"},
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        assert message_response.status_code == 200
        message_id = int(message_response.get_json()["id"])
        assert db.query_one(
            """
            SELECT id FROM notifications
            WHERE recipient_type='beneficiary' AND recipient_id=%s
              AND source_type='user_message' AND source_id=%s
              AND event_type='beneficiary_message_added'
            ORDER BY id DESC LIMIT 1
            """,
            [beneficiary_id, message_id],
        )

        with client.session_transaction() as sess:
            sess.clear()
            sess["portal_type"] = "beneficiary"
            sess["beneficiary_id"] = beneficiary_id
            sess["beneficiary_full_name"] = "Notify Edited User"
            sess["beneficiary_access_mode"] = "cards"
        profile_page = client.get("/user/profile")
        assert profile_page.status_code == 200
        profile_html = profile_page.get_data(as_text=True)
        assert "تحذير تجريبي للمشترك" in profile_html
        assert "رسائل الإدارة" in profile_html
    finally:
        if beneficiary_id is not None:
            attachments = db.query_all(
                "SELECT id, stored_name FROM user_attachments WHERE beneficiary_id=%s",
                [beneficiary_id],
            )
            for attachment in attachments:
                try:
                    (Path(__file__).resolve().parents[1] / "app" / "uploads" / "user_attachments" / attachment["stored_name"]).unlink(missing_ok=True)
                except Exception:
                    pass
            db.execute_sql("DELETE FROM notifications WHERE source_type=%s AND source_id=%s", ["beneficiary", beneficiary_id])
            db.execute_sql("DELETE FROM notifications WHERE recipient_type=%s AND recipient_id=%s", ["beneficiary", beneficiary_id])
            db.execute_sql("DELETE FROM notifications WHERE source_type=%s AND source_id IN (SELECT id FROM user_attachments WHERE beneficiary_id=%s)", ["user_attachment", beneficiary_id])
            db.execute_sql("DELETE FROM notifications WHERE source_type=%s AND source_id IN (SELECT id FROM user_messages WHERE beneficiary_id=%s)", ["user_message", beneficiary_id])
            db.execute_sql("DELETE FROM user_messages WHERE beneficiary_id=%s", [beneficiary_id])
            db.execute_sql("DELETE FROM user_attachments WHERE beneficiary_id=%s", [beneficiary_id])
            db.execute_sql("DELETE FROM audit_logs WHERE target_type=%s AND target_id=%s", ["beneficiary", beneficiary_id])
            db.execute_sql("DELETE FROM beneficiaries WHERE id=%s", [beneficiary_id])


def test_dashboard_routes_keep_canonical_admin_redirects(app):
    assert app.view_functions["dashboard"].__module__ == "app.legacy"
    assert app.view_functions["admin_dashboard_alias"].__module__ == "app.legacy"


def test_university_beneficiary_saves_university_number(client):
    login_admin(client)
    page = client.get("/admin/beneficiaries/add?user_type=university")
    token = extract_csrf(page.get_data(as_text=True))
    assert 'name="university_number"' in page.get_data(as_text=True)
    phone = f"0599{int(uuid4().hex[:8], 16) % 1_000_000:06d}"

    response = client.post(
        "/admin/beneficiaries/add?user_type=university",
        data={
            "_csrf_token": token,
            "user_type": "university",
            "first_name": "طالب",
            "second_name": "جامعي",
            "third_name": "",
            "fourth_name": "تجربة",
            "phone": phone,
            "university_name": "جامعة الاختبار",
            "university_number": "U-2026-15",
            "university_college": "الهندسة",
            "university_specialization": "حاسوب",
        },
        follow_redirects=False,
    )
    assert response.status_code == 302
    row = db.query_one("SELECT university_number FROM beneficiaries WHERE phone=%s", [phone])
    assert row["university_number"] == "U-2026-15"


def test_admin_sidebar_exposes_core_pages(client):
    response = login_admin(client)
    html = response.get_data(as_text=True)
    sidebar = html.split('<aside class="d-sidebar"', 1)[1].split("</aside>", 1)[0]
    for href in [
        "/admin/beneficiaries",
        "/admin/portal-accounts",
        "/admin/users-account",
        "/admin/cards/inventory",
        "/admin/cards/import",
        "/admin/requests",
        "/admin/internet-requests",
        "/admin/users-account/requests",
        "/admin/cards/pending",
        "/admin/usage-archive",
        "/admin/timer",
    ]:
        assert href in sidebar
    for hidden_href in [
        "/admin/cards/settings",
        "/admin/cards/deliveries",
        "/admin/cards/audit",
        "/admin/radius/settings",
        "/admin/radius/online",
        "/admin/api/test",
        "/admin/radius/app-test",
        "/admin/radius/users-online",
        "/admin/archive",
        "/admin/backup-sql",
    ]:
        assert hidden_href not in sidebar

    import_page = client.get("/admin/cards/import")
    import_html = import_page.get_data(as_text=True)
    assert 'name="category_code"' in import_html
    assert 'name="duration_minutes"' not in import_html
    assert "رفع ملف بطاقات" in import_html


def test_admin_sidebar_links_render_successfully(client):
    response = login_admin(client)
    html = response.get_data(as_text=True)
    if '<aside class="d-sidebar"' in html:
        sidebar = html.split('<aside class="d-sidebar"', 1)[1].split("</aside>", 1)[0]
    else:
        sidebar = html.split('<aside class="sidebar"', 1)[1].split("</aside>", 1)[0]
    hrefs = []
    for href in re.findall(r'href="([^"]+)"', sidebar):
        if href.startswith(("http://", "https://", "mailto:", "#")):
            continue
        parsed = urlsplit(href)
        if parsed.path in {"", "/logout"}:
            continue
        url = parsed.path + (f"?{parsed.query}" if parsed.query else "")
        if url not in hrefs:
            hrefs.append(url)

    assert len(hrefs) >= 25
    for href in hrefs:
        page = client.get(href, follow_redirects=False)
        assert page.status_code == 200, href

    legacy_prefixes = (
        "/dashboard",
        "/beneficiaries",
        "/internet",
        "/backup_sql",
        "/cards",
        "/users",
        "/usage-logs",
        "/usage-archive",
    )
    assert not [href for href in hrefs if href.startswith(legacy_prefixes)]


def test_three_layer_namespace_redirects(client):
    login_admin(client)
    for old_path, new_path in {
        "/dashboard": "/admin/dashboard",
        "/beneficiaries": "/admin/beneficiaries",
        "/usage-logs": "/admin/usage-logs",
        "/exports": "/admin/exports",
        "/cards": "/card",
        "/cards/history": "/card/history",
        "/admin/archive": "/admin/usage-archive",
        "/admin/cards/overview": "/admin/cards",
        "/admin/cards/settings": "/admin/cards/policies",
        "/admin/users-account/overview": "/admin/users-account",
        "/admin/radius/users-online": "/admin/radius/online",
        "/timer": "/admin/timer",
        "/admin-control": "/admin/system-cleanup",
        "/users/account": "/user/account",
        "/users/change-password": "/user/account/change-password",
        "/internet/request": "/user/internet/request",
    }.items():
        response = client.get(old_path, follow_redirects=False)
        assert response.status_code in {302, 308}, old_path
        assert response.headers["Location"].endswith(new_path), old_path


def test_user_and_card_canonical_pages(client):
    response = login_beneficiary(client)
    assert response.headers["Location"] in {"/user/account", "/card"}

    for path in ["/user/account", "/user/account/change-password", "/user/account/requests", "/card", "/card/history"]:
        page = client.get(path, follow_redirects=False)
        assert page.status_code == 200, path
        html = page.get_data(as_text=True)
        assert 'href="/users' not in html
        assert 'href="/cards' not in html

    account_html = client.get("/user/account").get_data(as_text=True)
    card_html = client.get("/card").get_data(as_text=True)
    assert 'data-power-timer-viewer' in account_html
    assert 'data-power-timer-viewer' in card_html
    assert "/api/power-timer/start" not in account_html
    assert "/api/power-timer/start" not in card_html
    timer_response = client.get("/portal/power-timer/status")
    assert timer_response.status_code == 200
    timer_payload = timer_response.get_json()
    assert timer_payload["ok"] is True
    assert "display_remaining_seconds" in timer_payload
    assert 'href="#" title="تسجيل الخروج"' not in account_html
    assert 'href="#" title="تسجيل الخروج"' not in card_html
    assert 'href="/user/logout"' in account_html
    assert 'href="/card/logout"' in card_html

    response = client.get("/user/logout", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/login")

    login_beneficiary(client)
    response = client.get("/card/logout", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/login")


def test_user_profile_documents_schema_and_page_render(client):
    login_beneficiary(client)
    columns = {row["name"] for row in db.query_all("PRAGMA table_info(user_attachments)")}
    for column in ["file_size", "file_size_bytes", "mime_type", "note", "uploaded_by_kind"]:
        assert column in columns

    page = client.get("/user/profile")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert "file_size_bytes" not in html
    assert "sqlite3.OperationalError" not in html


def test_admin_page_guide_renders_for_key_pages(client):
    login_admin(client)
    for path in [
        "/admin/dashboard",
        "/admin/beneficiaries",
        "/admin/internet-requests",
        "/admin/cards/inventory",
        "/admin/radius/settings",
        "/admin/system-cleanup",
    ]:
        response = client.get(path, follow_redirects=path == "/admin/internet-requests")
        html = response.get_data(as_text=True)
        assert response.status_code == 200
        assert "<html" in html
        if 'class="page-guide"' in html:
            assert "طريقة الاستخدام" in html


def test_admin_user_card_conversion_requires_confirmation(client):
    login_admin(client)
    user_method = "\u064a\u0648\u0632\u0631 \u0625\u0646\u062a\u0631\u0646\u062a"
    cards_method = "\u0646\u0638\u0627\u0645 \u0627\u0644\u0628\u0637\u0627\u0642\u0627\u062a"
    phone = f"0598{int(uuid4().hex[:8], 16) % 1_000_000:06d}"
    beneficiary_id = None

    db.execute_sql(
        """
        INSERT INTO beneficiaries (
            user_type, first_name, full_name, search_name, phone,
            freelancer_internet_method, added_by_username
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        ["freelancer", "Conversion", "Conversion Test", "Conversion Test", phone, user_method, "pytest"],
    )
    row = db.query_one("SELECT id FROM beneficiaries WHERE phone=%s", [phone])
    beneficiary_id = row["id"]

    try:
        page = client.get("/admin/users-account/list")
        html = page.get_data(as_text=True)
        assert page.status_code == 200
        assert "confirmBeneficiaryConvert" in html
        assert 'name="confirm_convert"' in html

        token = extract_csrf(html)
        blocked = client.post(
            f"/admin/beneficiary/{beneficiary_id}/convert-access",
            data={"_csrf_token": token, "target_mode": "cards"},
            follow_redirects=False,
        )
        assert blocked.status_code == 302
        unchanged = db.query_one(
            "SELECT freelancer_internet_method FROM beneficiaries WHERE id=%s",
            [beneficiary_id],
        )
        assert unchanged["freelancer_internet_method"] == user_method

        converted = client.post(
            f"/admin/beneficiary/{beneficiary_id}/convert-access",
            data={"_csrf_token": token, "target_mode": "cards", "confirm_convert": "1"},
            follow_redirects=False,
        )
        assert converted.status_code == 302
        changed = db.query_one(
            "SELECT freelancer_internet_method FROM beneficiaries WHERE id=%s",
            [beneficiary_id],
        )
        assert changed["freelancer_internet_method"] == cards_method
    finally:
        if beneficiary_id is not None:
            db.execute_sql("DELETE FROM beneficiaries WHERE id=%s", [beneficiary_id])


def test_admin_users_account_can_create_internet_subscriber_modal(client):
    login_admin(client)
    page = client.get("/admin/users-account")
    html = page.get_data(as_text=True)
    token = extract_csrf(html)
    phone = f"0597{int(uuid4().hex[:8], 16) % 1_000_000:06d}"
    beneficiary_id = None

    assert page.status_code == 200
    assert "إضافة مشترك حساب إنترنت" in html
    assert "/admin/users-account/create" in html

    try:
        response = client.post(
            "/admin/users-account/create",
            data={
                "_csrf_token": token,
                "user_type": "university",
                "full_name": "مشترك إنترنت تجريبي",
                "phone": phone,
                "password": "netpass123",
                "university_name": "جامعة تجريبية",
                "university_number": "U12345",
            },
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        assert response.status_code == 200
        payload = response.get_json()
        assert payload["ok"] is True
        beneficiary_id = int(payload["id"])
        assert payload["username"] == phone

        beneficiary = db.query_one("SELECT * FROM beneficiaries WHERE id=%s", [beneficiary_id])
        assert beneficiary["user_type"] == "university"
        assert beneficiary["phone"] == phone
        assert beneficiary["university_internet_method"] == "يوزر إنترنت"

        portal = db.query_one(
            "SELECT username, password_plain, is_active FROM beneficiary_portal_accounts WHERE beneficiary_id=%s",
            [beneficiary_id],
        )
        assert portal["username"] == phone
        assert portal["password_plain"] == "netpass123"
        assert int(portal["is_active"]) == 1

        radius = db.query_one(
            "SELECT external_username, status FROM beneficiary_radius_accounts WHERE beneficiary_id=%s",
            [beneficiary_id],
        )
        assert radius["external_username"] == phone
        assert radius["status"] == "pending"

        pending = db.query_one(
            """
            SELECT id, payload_json FROM radius_pending_actions
            WHERE beneficiary_id=%s AND action_type='create_user'
            ORDER BY id DESC LIMIT 1
            """,
            [beneficiary_id],
        )
        assert pending is not None
        assert phone in (pending["payload_json"] or "")
    finally:
        if beneficiary_id is not None:
            db.execute_sql("DELETE FROM notifications WHERE source_type=%s AND source_id=%s", ["beneficiary", beneficiary_id])
            db.execute_sql("DELETE FROM radius_pending_actions WHERE beneficiary_id=%s", [beneficiary_id])
            db.execute_sql("DELETE FROM beneficiary_radius_accounts WHERE beneficiary_id=%s", [beneficiary_id])
            db.execute_sql("DELETE FROM beneficiary_portal_accounts WHERE beneficiary_id=%s", [beneficiary_id])
            db.execute_sql("DELETE FROM beneficiaries WHERE id=%s", [beneficiary_id])


def test_card_categories_are_limited_and_four_hours_is_special(client):
    from app.services.quota_engine import (
        check_quota,
        get_active_categories,
        get_available_categories_for_beneficiary,
    )

    login_admin(client)
    official_codes = ["half_hour", "one_hour", "two_hours", "three_hours", "four_hours"]
    active_codes = [row["code"] for row in get_active_categories()]
    assert active_codes == official_codes
    assert not db.query_all(
        """
        SELECT code FROM card_categories
        WHERE is_active=1 AND code NOT IN ('half_hour','one_hour','two_hours','three_hours','four_hours')
        """
    )

    phone = f"0597{int(uuid4().hex[:8], 16) % 1_000_000:06d}"
    beneficiary_id = None
    db.execute_sql(
        """
        INSERT INTO beneficiaries (
            user_type, first_name, full_name, search_name, phone,
            freelancer_internet_method, added_by_username
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        [
            "freelancer",
            "Card Policy",
            "Card Policy Test",
            "Card Policy Test",
            phone,
            "\u0646\u0638\u0627\u0645 \u0627\u0644\u0628\u0637\u0627\u0642\u0627\u062a",
            "pytest",
        ],
    )
    row = db.query_one("SELECT id FROM beneficiaries WHERE phone=%s", [phone])
    beneficiary_id = row["id"]

    try:
        default_codes = [row["code"] for row in get_available_categories_for_beneficiary(beneficiary_id)]
        assert default_codes == ["half_hour", "one_hour", "two_hours", "three_hours"]
        assert check_quota(beneficiary_id, "four_hours").allowed is False

        db.execute_sql(
            """
            INSERT INTO card_quota_policies
                (scope, target_id, daily_limit, weekly_limit, allowed_category_codes, priority, is_active, notes)
            VALUES ('user', %s, 1, NULL, 'four_hours', 1, 1, 'pytest four-hour special')
            """,
            [beneficiary_id],
        )
        special_codes = [row["code"] for row in get_available_categories_for_beneficiary(beneficiary_id)]
        assert special_codes == ["four_hours"]
        assert check_quota(beneficiary_id, "four_hours").allowed is True
    finally:
        if beneficiary_id is not None:
            db.execute_sql("DELETE FROM card_quota_policies WHERE scope='user' AND target_id=%s", [beneficiary_id])
            db.execute_sql("DELETE FROM beneficiaries WHERE id=%s", [beneficiary_id])


def test_card_quota_policy_can_limit_work_hours(client):
    from app.services.quota_engine import check_quota

    login_admin(client)
    phone = f"0596{int(uuid4().hex[:8], 16) % 1_000_000:06d}"
    beneficiary_id = None
    db.execute_sql(
        """
        INSERT INTO beneficiaries (
            user_type, first_name, full_name, search_name, phone,
            freelancer_internet_method, added_by_username
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        [
            "freelancer",
            "Work Hours",
            "Work Hours Test",
            "Work Hours Test",
            phone,
            "\u0646\u0638\u0627\u0645 \u0627\u0644\u0628\u0637\u0627\u0642\u0627\u062a",
            "pytest",
        ],
    )
    beneficiary_id = db.query_one("SELECT id FROM beneficiaries WHERE phone=%s", [phone])["id"]

    try:
        db.execute_sql(
            """
            INSERT INTO card_quota_policies
                (scope, target_id, daily_limit, weekly_limit, allowed_category_codes,
                 valid_time_from, valid_time_until, priority, is_active, notes)
            VALUES ('user', %s, 3, NULL, 'one_hour', '08:00', '14:00', 1, 1, 'pytest work hours')
            """,
            [beneficiary_id],
        )
        assert check_quota(beneficiary_id, "one_hour", now=datetime(2026, 5, 18, 9, 30)).allowed is True
        outside = check_quota(beneficiary_id, "one_hour", now=datetime(2026, 5, 18, 15, 0))
        assert outside.allowed is False
        assert "\u0633\u0627\u0639\u0627\u062a \u0627\u0644\u062f\u0648\u0627\u0645" in outside.reason
    finally:
        if beneficiary_id is not None:
            db.execute_sql("DELETE FROM card_quota_policies WHERE scope='user' AND target_id=%s", [beneficiary_id])
            db.execute_sql("DELETE FROM beneficiaries WHERE id=%s", [beneficiary_id])


def test_default_card_policy_limits_persist_after_schema_reload(client):
    login_admin(client)
    row = db.query_one(
        "SELECT * FROM card_quota_policies WHERE scope='default' ORDER BY priority ASC, id ASC LIMIT 1"
    )
    assert row is not None
    policy_id = row["id"]
    original = dict(row)

    page = client.get("/admin/cards/policies")
    token = extract_csrf(page.get_data(as_text=True))
    try:
        response = client.post(
            f"/admin/cards/policies/{policy_id}/edit",
            data={
                "_csrf_token": token,
                "scope": "default",
                "target_id": "",
                "daily_limit": "1",
                "weekly_limit": "3",
                "allowed_days": original.get("allowed_days") or "",
                "allowed_category_codes": original.get("allowed_category_codes") or "half_hour,one_hour,two_hours,three_hours",
                "valid_from": original.get("valid_from") or "",
                "valid_until": original.get("valid_until") or "",
                "valid_time_from": original.get("valid_time_from") or "",
                "valid_time_until": original.get("valid_time_until") or "",
                "priority": str(original.get("priority") or 1000),
                "notes": original.get("notes") or "pytest policy persistence",
            },
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        assert response.status_code == 200
        assert response.get_json()["ok"] is True

        updated = db.query_one("SELECT daily_limit, weekly_limit FROM card_quota_policies WHERE id=%s", [policy_id])
        assert updated["daily_limit"] == 1
        assert updated["weekly_limit"] == 3

        legacy.setup_database_sqlite()
        reloaded = db.query_one("SELECT daily_limit, weekly_limit FROM card_quota_policies WHERE id=%s", [policy_id])
        assert reloaded["daily_limit"] == 1
        assert reloaded["weekly_limit"] == 3
    finally:
        db.execute_sql(
            """
            UPDATE card_quota_policies
            SET target_id=%s, daily_limit=%s, weekly_limit=%s, allowed_days=%s,
                allowed_category_codes=%s, priority=%s, valid_from=%s, valid_until=%s,
                valid_time_from=%s, valid_time_until=%s, notes=%s,
                is_active=%s, updated_at=CURRENT_TIMESTAMP
            WHERE id=%s
            """,
            [
                original.get("target_id"),
                original.get("daily_limit"),
                original.get("weekly_limit"),
                original.get("allowed_days") or "",
                original.get("allowed_category_codes") or "",
                original.get("priority"),
                original.get("valid_from"),
                original.get("valid_until"),
                original.get("valid_time_from") or "",
                original.get("valid_time_until") or "",
                original.get("notes") or "",
                original.get("is_active"),
                policy_id,
            ],
        )


def test_card_request_falls_back_to_manual_when_radius_writes_disabled(monkeypatch, client):
    from app.services.card_dispatcher import request_card_via_radius
    from app.services.radius_client import reset_radius_client

    monkeypatch.setenv("RADIUS_MODE", "live")
    monkeypatch.setenv("RADIUS_API_READY", "1")
    monkeypatch.delenv("RADIUS_API_WRITES_ENABLED", raising=False)
    reset_radius_client()

    phone = f"0594{int(uuid4().hex[:8], 16) % 1_000_000:06d}"
    beneficiary_id = None
    pending_action_id = None

    db.execute_sql(
        """
        INSERT INTO beneficiaries (
            user_type, first_name, full_name, search_name, phone,
            freelancer_internet_method, added_by_username
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        [
            "freelancer",
            "Fallback",
            "Fallback Radius Writes",
            "Fallback Radius Writes",
            phone,
            "\u0646\u0638\u0627\u0645 \u0627\u0644\u0628\u0637\u0627\u0642\u0627\u062a",
            "pytest",
        ],
    )
    beneficiary_id = db.query_one("SELECT id FROM beneficiaries WHERE phone=%s", [phone])["id"]

    try:
        with client.application.test_request_context("/card/request"):
            result = request_card_via_radius(
                beneficiary_id,
                "one_hour",
                actor_username="pytest",
                skip_quota=True,
                notes="pytest fallback",
            )
        pending_action_id = result.pending_action_id

        assert result.ok is True
        assert pending_action_id
        row = db.query_one(
            "SELECT * FROM radius_pending_actions WHERE id=%s",
            [pending_action_id],
        )
        assert row is not None
        assert row["action_type"] == "generate_user_cards"
        assert row["beneficiary_id"] == beneficiary_id
        assert row["status"] == "pending"
        assert row["attempted_by_mode"] == "manual"
        assert "pytest fallback" in (row["notes"] or "")
        assert "\u062a\u0646\u0641\u064a\u0630" in (row["notes"] or "")
        assert "\u064a\u062f\u0648\u064a" in (row["notes"] or "")

        audit = db.query_one(
            "SELECT event_type, details_json FROM card_audit_log WHERE related_pending_action_id=%s",
            [pending_action_id],
        )
        assert audit is not None
        assert audit["event_type"] == "card_request_queued"
        assert "RADIUS_API_WRITES_ENABLED" in (audit["details_json"] or "")
    finally:
        if pending_action_id is not None:
            db.execute_sql("DELETE FROM notifications WHERE source_type=%s AND source_id=%s", ["radius_pending_actions", pending_action_id])
            db.execute_sql("DELETE FROM card_audit_log WHERE related_pending_action_id=%s", [pending_action_id])
            db.execute_sql("DELETE FROM radius_pending_actions WHERE id=%s", [pending_action_id])
        if beneficiary_id is not None:
            db.execute_sql("DELETE FROM beneficiaries WHERE id=%s", [beneficiary_id])
        reset_radius_client()


def test_user_card_connect_flow_requires_owner_and_encodes_hotspot_url(client):
    import os

    previous_url = os.environ.get("MIKROTIK_HOTSPOT_URL")
    os.environ["MIKROTIK_HOTSPOT_URL"] = "http://hotspot.local"
    login_beneficiary(client)
    with client.session_transaction() as sess:
        beneficiary_id = int(sess["beneficiary_id"])

    card_password = "p@ss&= 123"
    own_card = db.execute_sql(
        """
        INSERT INTO beneficiary_issued_cards (
            beneficiary_id, duration_minutes, card_username, card_password, issued_by
        )
        VALUES (%s, 60, %s, %s, 'pytest')
        RETURNING id
        """,
        [beneficiary_id, "card user", card_password],
        fetchone=True,
    )
    other_phone = f"0596{int(uuid4().hex[:8], 16) % 1_000_000:06d}"
    other_card_id = None

    try:
        db.execute_sql(
            """
            INSERT INTO beneficiaries (user_type, first_name, full_name, search_name, phone, added_by_username)
            VALUES ('freelancer', 'Other', 'Other Card Owner', 'Other Card Owner', %s, 'pytest')
            """,
            [other_phone],
        )
        other_beneficiary = db.query_one("SELECT id FROM beneficiaries WHERE phone=%s", [other_phone])
        other_card = db.execute_sql(
            """
            INSERT INTO beneficiary_issued_cards (
                beneficiary_id, duration_minutes, card_username, card_password, issued_by
            )
            VALUES (%s, 60, 'other-card', 'other-secret', 'pytest')
            RETURNING id
            """,
            [other_beneficiary["id"]],
            fetchone=True,
        )
        other_card_id = other_card["id"]

        response = client.get(f"/user/cards/connect/{own_card['id']}")
        html = response.get_data(as_text=True)
        assert response.status_code == 200
        assert response.headers["Cache-Control"].startswith("no-store")
        assert "جارٍ تجهيز اتصالك..." in html
        assert 'src="http://hotspot.local/logout"' in html
        assert "http://hotspot.local/login?username=card+user" in html
        assert "password=p%40ss%26%3D+123" in html
        assert card_password not in html

        status_response = client.get(f"/card/status/{own_card['id']}")
        assert status_response.status_code == 200
        assert status_response.headers["Cache-Control"].startswith("no-store")
        status_payload = status_response.get_json()
        assert status_payload["ok"] is True
        assert status_payload["status"]["status"] == "api_unavailable"
        assert card_password not in str(status_payload)

        card_page = client.get("/card")
        card_html = card_page.get_data(as_text=True)
        assert f'data-card-refresh="{own_card["id"]}"' in card_html
        assert card_html.count(f'data-card-status-card="{own_card["id"]}"') == 1
        assert "الوقت المستخدم" in card_html
        assert "الوقت المتبقي" in card_html
        assert "آخر ظهور" in card_html

        blocked = client.get(f"/user/cards/connect/{other_card_id}", follow_redirects=False)
        assert blocked.status_code == 302
        assert blocked.headers["Location"].endswith("/user/cards/history")

    finally:
        db.execute_sql("DELETE FROM beneficiary_issued_cards WHERE id=%s", [own_card["id"]])
        if other_card_id is not None:
            db.execute_sql("DELETE FROM beneficiary_issued_cards WHERE id=%s", [other_card_id])
        db.execute_sql("DELETE FROM beneficiaries WHERE phone=%s", [other_phone])
        if previous_url is None:
            os.environ.pop("MIKROTIK_HOTSPOT_URL", None)
        else:
            os.environ["MIKROTIK_HOTSPOT_URL"] = previous_url


def test_card_status_service_calculates_online_remaining(monkeypatch):
    from app.services import card_status_service as service

    class FakeRadiusClient:
        def get_online_users(self):
            return [
                {
                    "username": "CARD-1",
                    "running_sec": 600,
                    "framed_ip": "10.0.0.50",
                    "calling_station_id": "AA:BB",
                }
            ]

    monkeypatch.setattr(service, "is_api_under_development", lambda: False)
    monkeypatch.setattr(service, "get_radius_client", lambda: FakeRadiusClient())

    status = service.get_card_status(
        {"id": 77, "card_username": "card-1", "duration_minutes": 30}
    )

    assert status["status"] == "online"
    assert status["is_online"] is True
    assert status["used_seconds"] == 600
    assert status["remaining_seconds"] == 1200
    assert status["framed_ip"] == "10.0.0.50"


def test_admin_card_inventory_deduplicates_categories_and_shows_issued(client):
    login_admin(client)
    username = f"INV{uuid4().hex[:8]}"
    password = "secret123"
    available_id = None
    issued_id = None
    beneficiary_id = None

    db.execute_sql(
        """
        INSERT INTO manual_access_cards (
            duration_minutes, card_username, card_password, source_file, imported_by_username
        )
        VALUES (60, %s, %s, 'pytest', 'pytest')
        """,
        [username, password],
    )
    available = db.query_one("SELECT id FROM manual_access_cards WHERE card_username=%s", [username])
    available_id = available["id"]

    phone = f"0595{int(uuid4().hex[:8], 16) % 1_000_000:06d}"
    db.execute_sql(
        """
        INSERT INTO beneficiaries (user_type, first_name, full_name, search_name, phone, added_by_username)
        VALUES ('freelancer', 'Inventory', 'Inventory Owner', 'Inventory Owner', %s, 'pytest')
        """,
        [phone],
    )
    beneficiary_id = db.query_one("SELECT id FROM beneficiaries WHERE phone=%s", [phone])["id"]
    issued = db.execute_sql(
        """
        INSERT INTO beneficiary_issued_cards (
            beneficiary_id, duration_minutes, card_username, card_password, issued_by
        )
        VALUES (%s, 60, %s, %s, 'pytest')
        RETURNING id
        """,
        [beneficiary_id, f"{username}-issued", password],
        fetchone=True,
    )
    issued_id = issued["id"]

    try:
        html = client.get(f"/admin/cards/inventory?q={username}").get_data(as_text=True)
        assert html.count(f'data-inventory-row="available:{available_id}"') == 1
        assert html.count(f'data-inventory-row="issued:{issued_id}"') == 1
        assert "متاحة للصرف" in html
        assert "تم الإصدار" in html
        assert "Inventory Owner" in html
        assert "تحميل:" in html
        assert "متبقي:" in html
    finally:
        if available_id is not None:
            db.execute_sql("DELETE FROM manual_access_cards WHERE id=%s", [available_id])
        if issued_id is not None:
            db.execute_sql("DELETE FROM beneficiary_issued_cards WHERE id=%s", [issued_id])
        if beneficiary_id is not None:
            db.execute_sql("DELETE FROM beneficiaries WHERE id=%s", [beneficiary_id])


def test_import_manual_cards_rejects_duplicates(client):
    login_admin(client)
    existing_username = f"DUP{uuid4().hex[:8]}"
    db.execute_sql(
        """
        INSERT INTO manual_access_cards (
            duration_minutes, card_username, card_password, source_file, imported_by_username
        )
        VALUES (60, %s, 'old-pass', 'pytest', 'pytest')
        """,
        [existing_username],
    )

    class Upload:
        filename = "cards.csv"

        def __init__(self, text):
            self.stream = io.BytesIO(text.encode("utf-8"))

    try:
        try:
            legacy.import_manual_access_cards(60, Upload("same,111\nsame,222\n"), "cards.csv", "pytest")
        except ValueError as exc:
            assert "مكررة" in str(exc)
        else:
            raise AssertionError("duplicate cards inside file were accepted")

        before = db.query_one("SELECT COUNT(*) AS c FROM manual_access_cards WHERE card_username=%s", [existing_username])["c"]
        try:
            legacy.import_manual_access_cards(60, Upload(f" {existing_username.lower()} ,new-pass\n"), "cards.csv", "pytest")
        except ValueError as exc:
            assert "مكررة مسبقاً" in str(exc)
        else:
            raise AssertionError("normalized duplicate existing card was accepted")
        after = db.query_one("SELECT COUNT(*) AS c FROM manual_access_cards WHERE card_username=%s", [existing_username])["c"]
        assert after == before
    finally:
        db.execute_sql("DELETE FROM manual_access_cards WHERE card_username=%s", [existing_username])


def test_post_api_requires_csrf_and_accepts_header(client):
    login_admin(client)
    page = client.get("/admin/dashboard")
    token = extract_csrf(page.get_data(as_text=True))
    assert token

    rejected = client.post("/api/power-timer/start", data={"minutes": "5"})
    assert rejected.status_code == 400

    accepted = client.post(
        "/api/power-timer/start",
        data={"minutes": "5"},
        headers={"X-CSRFToken": token, "X-Requested-With": "XMLHttpRequest"},
    )
    assert accepted.status_code == 200
    assert accepted.get_json()["ok"] is True


def test_safe_escapes_html():
    escaped = legacy.safe('<script>alert("x")</script>')
    assert isinstance(escaped, Markup)
    assert "<script>" not in str(escaped)
    assert "&lt;script&gt;" in str(escaped)


def test_db_query_helpers_are_available_outside_legacy():
    row = db.query_one("SELECT 7 AS value")
    assert row["value"] == 7
    assert str(db.safe("<b>")) == "&lt;b&gt;"


def test_admin_password_hashing_supports_current_and_legacy_hashes():
    hashed = admin_password_hash("  secret ")
    assert verify_admin_password(hashed, "secret") is True
    assert verify_admin_password(hashed, "wrong") is False

    legacy_hash = sha256_text("secret")
    assert verify_admin_password(legacy_hash, "secret") is True


def test_text_helpers_normalize_common_import_values():
    assert clean_csv_value(" null ") == ""
    assert normalize_phone("599123456.0") == "0599123456"
    assert normalize_search_ar("أحمد   علي") == "احمد علي"
    assert split_full_name("محمد أحمد علي حسن") == ("محمد", "أحمد", "علي", "حسن")
    assert full_name_from_parts(" محمد ", "أحمد", "", "حسن") == "محمد أحمد حسن"
    assert legacy.normalize_search_ar("أحمد   علي") == "احمد علي"


def test_import_helpers_normalize_and_split_operations():
    row = {
        "first_name": " أحمد ",
        "second_name": "علي",
        "third_name": "",
        "fourth_name": "حسن",
        "phone": "599123456.0",
        "university_name": "جامعة",
    }
    columns = ["first_name", "second_name", "third_name", "fourth_name", "phone", "university_name", "user_type"]
    normalized = normalize_import_row(row, columns, "2026-05-11")

    assert infer_user_type(normalized) == "university"
    assert normalized["phone"] == "0599123456"
    assert normalized["full_name"] == "أحمد علي حسن"
    assert normalized["search_name"] == "احمد علي حسن"

    phone_map, name_map = build_existing_lookup_maps(
        [{"id": 5, "phone": "0599000000", "full_name": "قديم", "user_type": "freelancer"}]
    )
    inserts, updates = split_import_operations([(2, normalized), (3, {"phone": "0599000000", "full_name": "قديم", "user_type": "freelancer"})], phone_map, name_map)

    assert [row_num for row_num, _ in inserts] == [2]
    assert [row_num for row_num, _ in updates] == [3]
    assert updates[0][1]["id"] == 5


def test_import_task_store_tracks_progress_logs_and_errors():
    store = ImportTaskStore(log_limit=2, now_text=lambda: "2026-05-15 21:30:00")
    task_id = store.create("admin", 1, "users.csv")
    store.update(task_id, total=4, processed=2)
    store.append_log(task_id, "first")
    store.append_log(task_id, "second")
    store.append_log(task_id, "third", is_error=True)
    store.finalize(task_id, "completed", "done")

    task = store.get(task_id)
    assert task["percent"] == 50
    assert task["status"] == "completed"
    assert task["logs"] == ["[2026-05-15 21:30:00] second", "[2026-05-15 21:30:00] third"]
    assert task["error_count"] == 1


def test_dashboard_service_helpers_are_module_backed():
    card_user = {
        "user_type": "freelancer",
        "freelancer_internet_method": "نظام البطاقات",
        "weekly_usage_count": 2,
    }
    assert get_type_label("university") == "جامعة"
    assert get_usage_label(card_user) == ("2 / 3", True, 2)
    assert get_beneficiary_access_mode(card_user) == "cards"
    assert get_beneficiary_access_label(card_user) == "بطاقات استخدام"
    status = build_power_timer_status(
        {
            "duration_minutes": 1,
            "auto_restart_delay_seconds": 10,
            "state": "running",
            "paused_remaining_seconds": None,
            "cycle_started_at": "2026-05-15 21:30:00",
            "updated_by_username": "admin",
        },
        now=datetime(2026, 5, 15, 21, 30, 30, tzinfo=timezone.utc),
    )
    assert status["state"] == "running"
    assert status["display_remaining_seconds"] == 30


def test_critical_routes_exist(app):
    routes = {rule.rule for rule in app.url_map.iter_rules()}
    for route in [
        "/healthz",
        "/admin/dashboard",
        "/admin/beneficiaries",
        "/admin/radius/settings",
        "/admin/cards/inventory",
        "/user/account",
        "/card",
    ]:
        assert route in routes


def test_healthz_reports_database(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert data["checks"]["database"] is True


def test_security_headers_are_present(client):
    response = client.get("/portal")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "same-origin"


def test_legacy_loader_stays_split_and_small():
    root = Path(__file__).resolve().parents[1]
    legacy_loader = root / "app" / "legacy.py"
    legacy_parts = sorted((root / "app" / "legacy_parts").glob("*.py"))
    code_parts = [path for path in legacy_parts if path.name != "__init__.py"]
    template_parts = sorted((root / "app" / "legacy_templates").glob("*.html"))

    assert len(legacy_loader.read_text(encoding="utf-8").splitlines()) <= 150
    assert len(code_parts) >= 90
    assert len(template_parts) >= 7
    assert max(len(path.read_text(encoding="utf-8").splitlines()) for path in code_parts) <= 500


def test_legacy_parts_manifest_is_sorted():
    root = Path(__file__).resolve().parents[1]
    module = ast.parse((root / "app" / "legacy.py").read_text(encoding="utf-8"))
    legacy_parts = None
    for node in module.body:
        if not isinstance(node, ast.Assign):
            continue
        if any(isinstance(target, ast.Name) and target.id == "_LEGACY_PARTS" for target in node.targets):
            legacy_parts = ast.literal_eval(node.value)
            break

    assert legacy_parts is not None
    assert len(legacy_parts) == len(set(legacy_parts))
    for part in legacy_parts:
        assert (root / "app" / "legacy_parts" / part).exists()
