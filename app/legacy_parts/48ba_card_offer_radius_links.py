# 48ba_card_offer_radius_links.py
# صفحة «ربط العروض»: تربط كل فئة/عرض بطاقات في HobeHub بعرض/باقة RADIUS محدّد،
# مختار من قائمة منسدلة حيّة تُملأ من RadiusClient.list_offers(). أي طلب بطاقة
# تحت فئة HobeHub يولّد البطاقة داخل العرض المربوط (يقرأه card_dispatcher).

from flask import jsonify, render_template, request, session


def _load_offers():
    """يجلب **باقات السوق الإلكترونيّ** (كل باقة بمعرّف فريد ومدّتها الخاصّة).
    كلّ باقة تُميَّز بـ external_id = معرّف الباقة الفريد، وتحمل plan_id + المدّة
    ليُولَّد الكرت داخل الخطّة الصحيحة وبمدّة الباقة. لا يرمي مهما كان خطأ الاتصال."""
    from app.services.radius_client import get_radius_client, is_api_under_development

    offers, error = [], ""
    try:
        client = get_radius_client()
        raw = client.get_marketplace_offers() if hasattr(client, "get_marketplace_offers") else []
        seen = set()
        for p in (raw or []):
            if not isinstance(p, dict):
                continue
            ext = str(p.get("external_id") or "").strip()
            if not ext or ext in seen:
                continue
            seen.add(ext)
            offers.append({
                "external_id": ext,
                "name": p.get("name") or ext,
                "duration_label": p.get("duration_label") or "",
                "speed": p.get("speed") or "",
                "price": p.get("price") or "",
                "active": bool(p.get("active", True)),
            })
    except Exception as exc:  # لا نُسقط الصفحة مهما كان خطأ الاتصال
        error = str(exc)
    return offers, is_api_under_development(), error


# ─── GET /admin/cards/radius-links ─────────────────────────────────────
@app.route("/admin/cards/radius-links", methods=["GET"])
@admin_login_required
def admin_cards_radius_links_page():
    from app.services.card_offer_links import get_all_links

    categories = query_all(
        """
        SELECT * FROM card_categories
        WHERE is_active=TRUE
        ORDER BY display_order ASC, duration_minutes ASC
        """
    )
    links = get_all_links()
    offers, under_dev, offers_error = _load_offers()
    return render_template(
        "admin/cards/radius_links.html",
        categories=categories,
        links=links,
        offers=offers,
        under_dev=under_dev,
        offers_error=offers_error,
    )


# ─── GET /admin/cards/radius-links/offers (تحديث حي للقائمة) ────────────
@app.route("/admin/cards/radius-links/offers", methods=["GET"])
@admin_login_required
def admin_cards_radius_links_offers():
    offers, under_dev, error = _load_offers()
    return jsonify({"ok": True, "under_dev": under_dev, "offers": offers, "error": error})


# ─── POST /admin/cards/radius-links/save ───────────────────────────────
@app.route("/admin/cards/radius-links/save", methods=["POST"])
@admin_login_required
def admin_cards_radius_links_save():
    from app.services.card_offer_links import set_link

    category_code = clean_csv_value(request.form.get("category_code") or "")
    radius_external_id = clean_csv_value(request.form.get("radius_external_id") or "")
    radius_offer_name = clean_csv_value(request.form.get("radius_offer_name") or "")
    radius_duration_label = clean_csv_value(request.form.get("radius_duration_label") or "")
    if not category_code:
        return jsonify({"ok": False, "message": "الفئة غير محددة."}), 400

    actor = session.get("username") or ""
    res = set_link(
        category_code,
        radius_external_id,
        radius_offer_name=radius_offer_name,
        radius_duration_label=radius_duration_label,
        updated_by=actor,
    )
    if not res.get("ok"):
        return jsonify({"ok": False, "message": res.get("error") or "تعذّر الحفظ."}), 400

    log_action(
        "save_card_offer_link",
        "card_offer_radius_links",
        0,
        f"category={category_code} offer={radius_external_id or '—'}",
    )
    return jsonify({
        "ok": True,
        "message": "تم حفظ الربط." if radius_external_id else "تم مسح الربط.",
        "radius_external_id": radius_external_id,
        "radius_offer_name": radius_offer_name,
        "radius_duration_label": radius_duration_label,
    })
