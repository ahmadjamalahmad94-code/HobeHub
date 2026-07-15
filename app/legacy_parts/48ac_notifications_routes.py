from flask import jsonify, redirect, render_template, request, session, url_for

from app.services.notification_service import (
    action_label,
    admin_notification_center,
    mark_all_read,
    mark_notification_read,
    notification_count_for_session,
    notification_preview_for_session,
    status_label,
    subscriber_notification_center as build_subscriber_notification_center,
)


@app.context_processor
def _notification_badge_context():
    return {
        "notification_count": notification_count_for_session(session),
        "notification_preview": notification_preview_for_session(session, limit=10),
    }


@app.route("/admin/notifications", methods=["GET"])
@admin_login_required
def admin_notifications_center():
    mark_all_read("admin")
    data = admin_notification_center()
    return render_template(
        "admin/notifications.html",
        rows=data["rows"],
        pending=data["pending"],
        recent=data["recent"],
        unread_count=data["unread_count"],
        read_count=data["read_count"],
        status_label=status_label,
        action_label=action_label,
    )


@app.route("/admin/notifications/count", methods=["GET"])
@admin_login_required
def admin_notifications_count():
    return jsonify({"ok": True, "count": notification_count_for_session(session)})


@app.route("/admin/notifications/list", methods=["GET"])
@admin_login_required
def admin_notifications_list():
    return jsonify({
        "ok": True,
        "count": notification_count_for_session(session),
        "items": notification_preview_for_session(session, limit=10),
    })


@app.route("/admin/notifications/seen", methods=["POST"])
@admin_login_required
def admin_notifications_seen():
    marked = mark_all_read("admin")
    return jsonify({"ok": True, "count": 0, "marked": marked})


@app.route("/admin/notifications/<int:notification_id>/read", methods=["POST"])
@admin_login_required
def admin_notification_mark_read(notification_id):
    mark_notification_read(notification_id, "admin", read=True)
    return redirect(request.referrer or url_for("admin_notifications_center"))


@app.route("/admin/notifications/<int:notification_id>/unread", methods=["POST"])
@admin_login_required
def admin_notification_mark_unread(notification_id):
    mark_notification_read(notification_id, "admin", read=False)
    return redirect(request.referrer or url_for("admin_notifications_center"))


@app.route("/admin/notifications/read-all", methods=["POST"])
@admin_login_required
def admin_notifications_mark_all_read():
    mark_all_read("admin")
    return redirect(request.referrer or url_for("admin_notifications_center"))


@app.route("/user/notifications", methods=["GET"])
@app.route("/card/notifications", methods=["GET"])
@user_login_required
def subscriber_notifications_center():
    beneficiary_id = int(session.get("beneficiary_id") or 0)
    beneficiary = get_current_portal_beneficiary() or {}
    mark_all_read("beneficiary", beneficiary_id)
    data = build_subscriber_notification_center(beneficiary_id)
    portal_kind = "cards" if session.get("beneficiary_access_mode") == "cards" or session.get("portal_entry") == "card" or request.path.startswith("/card") else "user"
    return render_template(
        "portal/notifications.html",
        rows=data["rows"],
        portal_kind=portal_kind,
        beneficiary_full_name=beneficiary.get("full_name") or session.get("beneficiary_full_name", ""),
        pending_count=data["pending_count"],
        done_count=data["done_count"],
        my_pending_count=data["pending_count"],
        status_label=status_label,
        action_label=action_label,
    )


@app.route("/user/notifications/count", methods=["GET"])
@app.route("/card/notifications/count", methods=["GET"])
@user_login_required
def subscriber_notifications_count():
    return jsonify({"ok": True, "count": notification_count_for_session(session)})


@app.route("/user/notifications/list", methods=["GET"])
@app.route("/card/notifications/list", methods=["GET"])
@user_login_required
def subscriber_notifications_list():
    return jsonify({
        "ok": True,
        "count": notification_count_for_session(session),
        "items": notification_preview_for_session(session, limit=10),
    })


@app.route("/user/notifications/seen", methods=["POST"])
@app.route("/card/notifications/seen", methods=["POST"])
@user_login_required
def subscriber_notifications_seen():
    beneficiary_id = int(session.get("beneficiary_id") or 0)
    marked = mark_all_read("beneficiary", beneficiary_id)
    return jsonify({"ok": True, "count": 0, "marked": marked})


@app.route("/user/notifications/<int:notification_id>/read", methods=["POST"])
@app.route("/card/notifications/<int:notification_id>/read", methods=["POST"])
@user_login_required
def subscriber_notification_mark_read(notification_id):
    beneficiary_id = int(session.get("beneficiary_id") or 0)
    mark_notification_read(notification_id, "beneficiary", beneficiary_id, read=True)
    return redirect(request.referrer or ("/card/notifications" if request.path.startswith("/card") else "/user/notifications"))


@app.route("/user/notifications/<int:notification_id>/unread", methods=["POST"])
@app.route("/card/notifications/<int:notification_id>/unread", methods=["POST"])
@user_login_required
def subscriber_notification_mark_unread(notification_id):
    beneficiary_id = int(session.get("beneficiary_id") or 0)
    mark_notification_read(notification_id, "beneficiary", beneficiary_id, read=False)
    return redirect(request.referrer or ("/card/notifications" if request.path.startswith("/card") else "/user/notifications"))


@app.route("/user/notifications/read-all", methods=["POST"])
@app.route("/card/notifications/read-all", methods=["POST"])
@user_login_required
def subscriber_notifications_mark_all_read():
    beneficiary_id = int(session.get("beneficiary_id") or 0)
    mark_all_read("beneficiary", beneficiary_id)
    return redirect(request.referrer or ("/card/notifications" if request.path.startswith("/card") else "/user/notifications"))
