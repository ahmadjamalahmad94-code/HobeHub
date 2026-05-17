# 48at_segment_redirects.py
# Keeps safe legacy redirects for pages that were replaced by unified views.

from flask import redirect


if "admin_cards_subscribers_page" in app.view_functions:
    def _cards_subscribers_redirect():
        return redirect("/admin/beneficiaries?segment=cards", code=302)

    _cards_subscribers_redirect = login_required(_cards_subscribers_redirect)
    app.view_functions["admin_cards_subscribers_page"] = _cards_subscribers_redirect
