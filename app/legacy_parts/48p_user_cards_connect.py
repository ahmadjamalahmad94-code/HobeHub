from flask import jsonify, make_response
from app.services.mikrotik_hotspot import build_card_connect_urls


@app.route("/user/cards/connect/<int:card_id>", methods=["GET"])
@user_login_required
def user_cards_connect(card_id):
    beneficiary_id = int(session.get("beneficiary_id") or 0)
    card = query_one(
        """
        SELECT id, beneficiary_id, duration_minutes, card_username, card_password, issued_at
        FROM beneficiary_issued_cards
        WHERE id=%s AND beneficiary_id=%s
        LIMIT 1
        """,
        [card_id, beneficiary_id],
    )
    if not card:
        flash("هذه البطاقة غير متاحة لحسابك.", "error")
        return redirect(url_for("user_cards_history"))

    try:
        urls = build_card_connect_urls(
            card_username=card.get("card_username") or "",
            card_password=card.get("card_password") or "",
        )
    except ValueError:
        flash("رابط الراوتر غير مضبوط. اضبط «رابط صفحة الراوتر» في إعدادات البطاقات.", "error")
        return redirect(url_for("user_cards_history"))

    response = make_response(
        render_template(
            "user_cards_connect.html",
            card=card,
            logout_url=urls.logout_url,
            login_url=urls.login_url,
            redirect_delay_ms=1000,
        )
    )
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return response


@app.route("/card/status/<int:card_id>", methods=["GET"])
@user_login_required
def user_card_status_api(card_id):
    from app.services.card_status_service import get_card_status

    beneficiary_id = int(session.get("beneficiary_id") or 0)
    card = query_one(
        """
        SELECT id, beneficiary_id, duration_minutes, card_username, issued_at
        FROM beneficiary_issued_cards
        WHERE id=%s AND beneficiary_id=%s
        LIMIT 1
        """,
        [card_id, beneficiary_id],
    )
    if not card:
        return jsonify({"ok": False, "error": "CARD_NOT_FOUND"}), 404
    response = jsonify({"ok": True, "card_id": card_id, "status": get_card_status(card)})
    response.headers["Cache-Control"] = "no-store, max-age=0"
    return response
