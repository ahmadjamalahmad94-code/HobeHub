# 48az_radius_match_engine.py
# Beneficiary ↔ RADIUS match & sync engine — admin routes.
# Reached from /admin/beneficiaries via the «مطابقة مع RADIUS» button.
#
# Flow: start (create run) → poll /step (chunked read-only scan) → review page
# → confirm (apply only the selected rows). Core logic lives in the modular
# service app/services/radius_match.py so it stays testable and framework-free.

from flask import jsonify, redirect, render_template, request, url_for

from app.services import radius_match as _match


def _match_progress_payload(run):
    return _match.run_progress(run) if run else None


# ════════════════════════════════════════════════════════════════════════
# GET /admin/radius/match — intro / live progress / review report
# ════════════════════════════════════════════════════════════════════════
@app.route("/admin/radius/match", methods=["GET"], endpoint="admin_radius_match_page")
@login_required
@permission_required("manage_user_accounts")
def admin_radius_match_page():
    run = None
    run_arg = (request.args.get("run") or "").strip()
    if run_arg.isdigit():
        run = _match.get_run(int(run_arg))
    if run is None:
        run = _match.get_latest_run()

    forward_candidates = []
    radius_only_candidates = []
    if run and (run.get("status") == "done"):
        forward_candidates = _match.get_run_candidates(int(run["id"]), "hobehub_to_radius")
        radius_only_candidates = _match.get_run_candidates(int(run["id"]), "radius_only")

    return render_template(
        "admin/radius_match/index.html",
        run=run,
        progress=_match_progress_payload(run),
        radius_available=_match.radius_available(),
        forward_candidates=forward_candidates,
        radius_only_candidates=radius_only_candidates,
    )


# ════════════════════════════════════════════════════════════════════════
# POST /admin/radius/match/start — create a run (does not scan yet)
# ════════════════════════════════════════════════════════════════════════
@app.route("/admin/radius/match/start", methods=["POST"], endpoint="admin_radius_match_start")
@login_required
@permission_required("manage_user_accounts")
def admin_radius_match_start():
    run = _match.create_run(
        started_by_username=session.get("username") or "",
        started_by_account_id=session.get("account_id"),
    )
    try:
        log_action(
            "radius_match_run_started", "radius_match_run", int(run["id"]),
            f"بدء مطابقة RADIUS — الحالة {run.get('status')}، الإجمالي {run.get('total')}",
        )
    except Exception:
        pass
    payload = _match.run_progress(run)
    payload["ok"] = True
    return jsonify(payload)


# ════════════════════════════════════════════════════════════════════════
# POST /admin/radius/match/<run_id>/step — process the next scan chunk
# ════════════════════════════════════════════════════════════════════════
@app.route("/admin/radius/match/<int:run_id>/step", methods=["POST"], endpoint="admin_radius_match_step")
@login_required
@permission_required("manage_user_accounts")
def admin_radius_match_step(run_id):
    progress = _match.scan_step(run_id)
    if progress is None:
        return jsonify({"ok": False, "message": "جولة المطابقة غير موجودة."}), 404
    progress["ok"] = True
    return jsonify(progress)


# ════════════════════════════════════════════════════════════════════════
# GET /admin/radius/match/<run_id>/status — poll progress (read-only)
# ════════════════════════════════════════════════════════════════════════
@app.route("/admin/radius/match/<int:run_id>/status", methods=["GET"], endpoint="admin_radius_match_status")
@login_required
@permission_required("manage_user_accounts")
def admin_radius_match_status(run_id):
    run = _match.get_run(run_id)
    if not run:
        return jsonify({"ok": False, "message": "جولة المطابقة غير موجودة."}), 404
    progress = _match.run_progress(run)
    progress["ok"] = True
    return jsonify(progress)


# ════════════════════════════════════════════════════════════════════════
# POST /admin/radius/match/<run_id>/confirm — apply ONLY the selected rows
# ════════════════════════════════════════════════════════════════════════
@app.route("/admin/radius/match/<int:run_id>/confirm", methods=["POST"], endpoint="admin_radius_match_confirm")
@login_required
@permission_required("manage_user_accounts")
def admin_radius_match_confirm(run_id):
    run = _match.get_run(run_id)
    if not run:
        return jsonify({"ok": False, "message": "جولة المطابقة غير موجودة."}), 404
    if run.get("status") != "done":
        return jsonify({"ok": False, "message": "لا يمكن التطبيق قبل اكتمال الفحص."}), 400

    ids = request.form.getlist("candidate_ids")
    if not ids:
        return jsonify({"ok": False, "message": "لم تُحدَّد أي صفوف للتطبيق."}), 400

    summary = _match.apply_confirm(run_id, ids, actor_username=session.get("username") or "")
    try:
        log_action(
            "radius_match_confirm", "radius_match_run", int(run_id),
            f"تطبيق المطابقة: ربط {summary['linked']}، استيراد {summary['imported']}، "
            f"تفعيل بوابة {summary['portal_activated']}، تم مسبقًا {summary['already']}",
        )
    except Exception:
        pass
    summary["ok"] = True
    summary["message"] = (
        f"تم التطبيق: {summary['linked']} ربط، {summary['imported']} استيراد، "
        f"{summary['portal_activated']} تفعيل بوابة."
    )
    return jsonify(summary)
