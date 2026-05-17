# Auto-split from app/legacy.py lines 11011-11015. Loaded by app.legacy.
import os


@app.before_request
def _enforce_admin_namespace_auth():
    path = request.path or ""
    if path != "/admin" and not path.startswith("/admin/"):
        return None
    if session.get("portal_type") == "beneficiary":
        flash("هذه الصفحة مخصصة للإدارة فقط.", "error")
        return redirect(url_for("user_dashboard"))
    if session.get("account_id"):
        session["portal_type"] = "admin"
        return None
    return redirect("/h0be-vault-9k2x7p/master-gateway")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
