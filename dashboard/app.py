"""
Vidora dashboard - Flask web UI for reviewing and managing leads.

Run with:
    python -m dashboard.app
or
    flask --app dashboard.app run --port 8080
"""

from __future__ import annotations

import os
from pathlib import Path

from flask import (
    Flask,
    abort,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)

from . import db, pipeline
from .pdf_audit import generate_audit

DASHBOARD_DIR = Path(__file__).resolve().parent
AUDITS_DIR = Path("C:/vidora/audits")


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder=str(DASHBOARD_DIR / "templates"),
        static_folder=str(DASHBOARD_DIR / "static"),
    )
    app.secret_key = os.environ.get("VIDORA_SECRET", "vidora-dev-secret-change-me")

    db.init_db()

    @app.context_processor
    def inject_globals():
        settings = db.get_settings()
        return {
            "company_name": settings.get("company_name", "Vidora"),
            "company_tagline": settings.get(
                "company_tagline", "AI lead generation for media production"
            ),
            "is_running": pipeline.is_running(),
        }

    # -----------------------------------------------------------------------
    # Home
    # -----------------------------------------------------------------------
    @app.route("/")
    def home():
        stats = db.dashboard_stats()
        recent = db.list_leads(order_by="analysed_at DESC", limit=8)
        top = db.list_leads(order_by="overall_score DESC", limit=5)
        runs = db.list_runs(limit=5)
        return render_template(
            "home.html",
            stats=stats,
            recent=recent,
            top=top,
            runs=runs,
            active_page="home",
        )

    # -----------------------------------------------------------------------
    # Leads list
    # -----------------------------------------------------------------------
    @app.route("/leads")
    def leads():
        grade = request.args.get("grade") or None
        priority_only = request.args.get("priority") == "1"
        status = request.args.get("status") or None
        business_type = request.args.get("business_type") or None
        search = request.args.get("q") or None
        order_by = request.args.get("order") or "overall_score DESC"

        items = db.list_leads(
            grade=grade,
            priority_only=priority_only,
            status=status,
            business_type=business_type,
            search=search,
            order_by=order_by,
        )
        return render_template(
            "leads.html",
            leads=items,
            business_types=db.business_types(),
            filters={
                "grade": grade or "",
                "priority": "1" if priority_only else "",
                "status": status or "",
                "business_type": business_type or "",
                "q": search or "",
                "order": order_by,
            },
            active_page="leads",
        )

    # -----------------------------------------------------------------------
    # Lead detail
    # -----------------------------------------------------------------------
    @app.route("/leads/<int:lead_id>")
    def lead_detail(lead_id: int):
        lead = db.get_lead(lead_id)
        if not lead:
            abort(404)
        return render_template(
            "lead_detail.html", lead=lead, active_page="leads"
        )

    @app.route("/leads/<int:lead_id>/update", methods=["POST"])
    def lead_update(lead_id: int):
        lead = db.get_lead(lead_id)
        if not lead:
            abort(404)
        updates = {}
        status = request.form.get("status")
        if status:
            updates["status"] = status
        notes = request.form.get("notes")
        if notes is not None:
            updates["notes"] = notes
        db.update_lead_fields(lead_id, updates)
        flash("Lead updated.", "success")
        return redirect(url_for("lead_detail", lead_id=lead_id))

    @app.route("/leads/<int:lead_id>/delete", methods=["POST"])
    def lead_delete(lead_id: int):
        db.delete_lead(lead_id)
        flash("Lead deleted.", "success")
        return redirect(url_for("leads"))

    @app.route("/leads/<int:lead_id>/audit")
    def lead_audit(lead_id: int):
        lead = db.get_lead(lead_id)
        if not lead:
            abort(404)
        path = Path(lead.get("audit_path") or "")
        if not path.exists():
            # Regenerate on demand (useful after CSV imports).
            company = db.get_setting("company_name", "Vidora")
            path = generate_audit(lead, AUDITS_DIR, company_name=company)
            db.update_lead_fields(lead_id, {"audit_path": str(path)})
        return send_file(
            path,
            as_attachment=True,
            download_name=f"vidora-audit-{lead['username']}.pdf",
            mimetype="application/pdf",
        )

    # -----------------------------------------------------------------------
    # Run the pipeline
    # -----------------------------------------------------------------------
    @app.route("/run", methods=["GET", "POST"])
    def run():
        settings = db.get_settings()
        if request.method == "POST":
            if pipeline.is_running():
                flash("A run is already in progress.", "error")
                return redirect(url_for("run"))
            try:
                leads_target = max(1, int(request.form.get("leads", 10)))
            except ValueError:
                leads_target = 10
            location = (request.form.get("location") or "").strip() or None
            source = (request.form.get("source") or "maps").strip()
            query = (request.form.get("query") or "").strip() or None
            api_key = (
                request.form.get("api_key")
                or settings.get("anthropic_api_key")
                or os.environ.get("ANTHROPIC_API_KEY")
                or ""
            ).strip()
            if not api_key:
                flash(
                    "Anthropic API key is missing. Add it in Settings.", "error"
                )
                return redirect(url_for("run"))
            run_id = pipeline.start_run(leads_target, location, api_key,
                                        source=source, query=query)
            if run_id is None:
                flash("Another run is already in progress.", "error")
            else:
                flash(f"Run #{run_id} started.", "success")
            return redirect(url_for("run"))

        runs = db.list_runs(limit=15)
        active = db.active_run()
        return render_template(
            "run.html",
            runs=runs,
            active=active,
            default_leads=settings.get("default_leads_per_run", "10"),
            default_location=settings.get("default_location", "manchester"),
            has_api_key=bool(settings.get("anthropic_api_key")),
            active_page="run",
        )

    @app.route("/runs/<int:run_id>")
    def run_detail(run_id: int):
        run_row = db.get_run(run_id)
        if not run_row:
            abort(404)
        return render_template(
            "run_detail.html", run=run_row, active_page="run"
        )

    # -----------------------------------------------------------------------
    # Settings
    # -----------------------------------------------------------------------
    @app.route("/settings", methods=["GET", "POST"])
    def settings_page():
        if request.method == "POST":
            updates = {}
            for key in (
                "company_name",
                "company_tagline",
                "default_location",
                "default_leads_per_run",
                "instagram_username",
            ):
                if key in request.form:
                    updates[key] = request.form[key].strip()
            api_key = (request.form.get("anthropic_api_key") or "").strip()
            if api_key and not api_key.startswith("*"):
                updates["anthropic_api_key"] = api_key
            db.update_settings(updates)
            flash("Settings saved.", "success")
            return redirect(url_for("settings_page"))

        settings = db.get_settings()
        masked_key = _mask(settings.get("anthropic_api_key", ""))
        return render_template(
            "settings.html",
            settings=settings,
            masked_key=masked_key,
            active_page="settings",
        )

    @app.route("/settings/import-csv", methods=["POST"])
    def settings_import():
        file = request.files.get("csv_file")
        if not file or not file.filename:
            flash("Pick a CSV file to import.", "error")
            return redirect(url_for("settings_page"))
        tmp = DASHBOARD_DIR / "data" / "_import.csv"
        file.save(tmp)
        try:
            n = pipeline.import_csv(tmp)
            flash(f"Imported {n} lead(s) from {file.filename}.", "success")
        except Exception as exc:  # noqa: BLE001
            flash(f"Import failed: {exc}", "error")
        finally:
            try:
                tmp.unlink()
            except Exception:
                pass
        return redirect(url_for("settings_page"))

    @app.errorhandler(404)
    def not_found(_):
        return render_template("404.html"), 404

    return app


def _mask(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return value[:4] + "*" * (len(value) - 8) + value[-4:]


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False)
