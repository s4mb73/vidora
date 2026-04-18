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

from . import db, outreach, pipeline
from .discord import notify_send_failed, notify_run_complete, send_weekly_report, test_webhook
from .imap_monitor import start_monitor
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
    outreach.start_scheduler()
    start_monitor()

    app.jinja_env.filters["humanise_freq"] = outreach.humanise_frequency
    app.jinja_env.filters["humanise_eng"]  = lambda v, followers=None: outreach.humanise_engagement(v, followers)

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
        top = db.list_leads(order_by="overall_score DESC", limit=5)
        runs = db.list_runs(limit=5)
        queue = db.action_queue()
        return render_template(
            "home.html",
            stats=stats,
            top=top,
            runs=runs,
            queue=queue,
            active_page="home",
        )

    @app.route("/analytics")
    def analytics_page():
        reply_breakdown = db.reply_label_breakdown()
        funnel = db.conversion_funnel()
        grade_table = db.grade_conversion()
        seq_rates = db.sequence_day_reply_rates()
        return render_template(
            "analytics.html",
            reply_breakdown=reply_breakdown,
            funnel=funnel,
            grade_table=grade_table,
            seq_rates=seq_rates,
            active_page="analytics",
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
        pipeline_stats = db.leads_pipeline_stats()
        return render_template(
            "leads.html",
            leads=items,
            business_types=db.business_types(),
            pipeline_stats=pipeline_stats,
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
        settings = db.get_settings()
        outreach_log = db.get_outreach_log(lead_id)
        followup_queue = db.get_followup_queue(lead_id)
        days_sent = db.sequence_days_sent(lead_id)
        preview_subject = outreach.build_subject(lead, settings)
        preview_body = outreach.build_body(lead, settings)
        d3_subj, d3_body = outreach.build_followup_day3(lead, settings)
        d7_subj, d7_body = outreach.build_followup_day7(lead, settings)
        return render_template(
            "lead_detail.html",
            lead=lead,
            outreach_log=outreach_log,
            followup_queue=followup_queue,
            days_sent=days_sent,
            preview_subject=preview_subject,
            preview_body=preview_body,
            d3_subject=d3_subj,
            d3_body=d3_body,
            d7_subject=d7_subj,
            d7_body=d7_body,
            active_page="leads",
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
        lead = db.get_lead(lead_id)
        if lead:
            _delete_lead_with_pdf(lead)
        flash("Lead deleted.", "success")
        return redirect(url_for("leads"))

    @app.route("/leads/bulk-delete", methods=["POST"])
    def leads_bulk_delete():
        raw_ids = request.form.getlist("lead_ids")
        deleted = 0
        for raw in raw_ids:
            try:
                lead_id = int(raw)
            except (ValueError, TypeError):
                continue
            lead = db.get_lead(lead_id)
            if lead:
                _delete_lead_with_pdf(lead)
                deleted += 1
        if deleted:
            flash(f"{deleted} lead{'s' if deleted != 1 else ''} deleted.", "success")
        return redirect(url_for("leads"))

    @app.route("/leads/<int:lead_id>/send-email", methods=["POST"])
    def lead_send_email(lead_id: int):
        lead = db.get_lead(lead_id)
        if not lead:
            abort(404)
        # Allow overriding the stored email from the form
        override_email = (request.form.get("email") or "").strip()
        if override_email:
            db.update_lead_fields(lead_id, {"email": override_email})
            lead["email"] = override_email
        result = outreach.send_lead_email(lead_id)
        if result["ok"]:
            flash(result["message"], "success")
        else:
            flash(result["message"], "error")
            lead = db.get_lead(lead_id)
            if lead:
                notify_send_failed(lead, 1, result["message"])
        return redirect(url_for("lead_detail", lead_id=lead_id))

    @app.route("/leads/<int:lead_id>/send-followup/<int:day>", methods=["POST"])
    def lead_send_followup(lead_id: int, day: int):
        if not db.get_lead(lead_id):
            abort(404)
        result = outreach.send_followup(lead_id, day)
        flash(result["message"], "success" if result["ok"] else "error")
        return redirect(url_for("lead_detail", lead_id=lead_id))

    @app.route("/leads/<int:lead_id>/save-email", methods=["POST"])
    def lead_save_email(lead_id: int):
        """Save email address (and optional subject) without sending."""
        if not db.get_lead(lead_id):
            abort(404)
        updates = {}
        email = (request.form.get("email") or "").strip()
        if email:
            updates["email"] = email
        subject = (request.form.get("email_subject") or "").strip()
        if subject:
            updates["email_subject"] = subject
        if updates:
            db.update_lead_fields(lead_id, updates)
            flash("Email details saved.", "success")
        return redirect(url_for("lead_detail", lead_id=lead_id))

    @app.route("/leads/export-csv")
    def leads_export_csv():
        import csv, io
        from flask import Response
        grade   = request.args.get("grade") or None
        status  = request.args.get("status") or None
        search  = request.args.get("q") or None
        order   = request.args.get("order") or "overall_score DESC"
        items   = db.list_leads(grade=grade, status=status, search=search, order_by=order)
        fields  = [
            "username","business_name","lead_grade","overall_score","business_intent_score",
            "business_type","status","followers","engagement_rate","posting_frequency",
            "maps_review_count","maps_rating","maps_address","maps_phone","maps_website",
            "email","personalised_pitch","sales_notes","analysed_at",
        ]
        out = io.StringIO()
        w = csv.DictWriter(out, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for lead in items:
            w.writerow({f: lead.get(f, "") for f in fields})
        return Response(
            out.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=vidora-leads.csv"},
        )

    @app.route("/leads/<int:lead_id>/audit")
    def lead_audit(lead_id: int):
        lead = db.get_lead(lead_id)
        if not lead:
            abort(404)
        path = Path(lead.get("audit_path") or "")
        if not path.exists():
            # Regenerate on demand (useful after CSV imports).
            settings = db.get_settings()
            path = generate_audit(lead, AUDITS_DIR, settings=settings)
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
    # Replies (classified inbound replies to outreach)
    # -----------------------------------------------------------------------
    @app.route("/replies")
    def replies_page():
        label = request.args.get("label") or None
        items = db.list_replies(label=label, limit=500)
        counts = db.reply_counts()
        return render_template(
            "replies.html",
            replies=items,
            counts=counts,
            active_label=label or "",
            active_page="replies",
        )

    # -----------------------------------------------------------------------
    # Patterns — winning components extracted from interested replies
    # -----------------------------------------------------------------------
    @app.route("/patterns")
    def patterns_page():
        status = request.args.get("status") or "pending"
        items = db.list_patterns(status=status, limit=500)
        counts = db.pattern_counts()
        return render_template(
            "patterns.html",
            patterns=items,
            counts=counts,
            active_status=status,
            active_page="patterns",
        )

    @app.route("/patterns/<int:pattern_id>/<action>", methods=["POST"])
    def pattern_action(pattern_id: int, action: str):
        target = {
            "approve":  "approved",
            "archive":  "archived",
            "pending":  "pending",
        }.get(action)
        if target is None:
            flash("Unknown action.", "error")
        else:
            db.set_pattern_status(pattern_id, target)
            flash(f"Pattern {target}.", "success")
        return_to = request.form.get("return_to") or url_for("patterns_page")
        return redirect(return_to)

    # -----------------------------------------------------------------------
    # Settings — hub + 5 sub-pages
    # -----------------------------------------------------------------------

    def _settings_status(settings: dict) -> dict:
        """Return a {section: (status, message)} map used by the hub page.

        status is 'ready' | 'warn' | 'empty'. The hub shows a badge per card.
        """
        def has(key: str) -> bool:
            return bool((settings.get(key) or "").strip())

        account_missing = [k for k in ("anthropic_api_key", "sender_name",
                                       "sender_email", "sender_address") if not has(k)]
        pipeline_missing = [k for k in ("default_location",) if not has(k)]

        return {
            "account": (
                ("warn", f"Missing: {', '.join(account_missing)}")
                if account_missing else ("ready", "All credentials and sender details set.")
            ),
            "emails": (
                ("ready", "Business context and voice set.")
                if (has("business_context") and has("email_voice_guidance"))
                else ("warn", "Add your business context — Claude writes better emails with it.")
                if not has("business_context")
                else ("ready", "Voice set. Consider adding business context for more specificity.")
            ),
            "followups": (
                ("ready", "Custom follow-up copy set.")
                if (has("followup_day3_body") or has("followup_day7_body"))
                else ("empty", "Using built-in follow-up templates.")
            ),
            "pipeline": (
                ("warn", f"Missing: {', '.join(pipeline_missing)}")
                if pipeline_missing
                else ("ready", f"Default city: {settings.get('default_location')}.")
            ),
            "advanced": ("ready", "File paths, CSV import, and system info."),
        }

    def _save_fields(fields: tuple, dest: str) -> None:
        """Apply POSTed form fields (by name) to settings, then redirect."""
        updates = {k: request.form[k] for k in fields if k in request.form}
        api_key = (request.form.get("anthropic_api_key") or "").strip()
        if api_key and not api_key.startswith("*"):
            updates["anthropic_api_key"] = api_key
        if updates:
            db.update_settings(updates)
            flash("Saved.", "success")

    @app.route("/settings")
    def settings_page():
        settings = db.get_settings()
        status = _settings_status(settings)
        return render_template(
            "settings_index.html",
            settings=settings,
            status=status,
            active_page="settings",
        )

    @app.route("/settings/account", methods=["GET", "POST"])
    def settings_account():
        if request.method == "POST":
            _save_fields(
                ("sender_name", "sender_title", "sender_email", "sender_website",
                 "sender_address", "client_company"),
                dest="account",
            )
            return redirect(url_for("settings_account"))
        settings = db.get_settings()
        masked_key = _mask(settings.get("anthropic_api_key", ""))
        from pathlib import Path as _Path
        _wh = _Path("C:/vidora/discord_webhook.txt")
        discord_webhook = _wh.read_text(encoding="utf-8").strip() if _wh.exists() else ""
        return render_template(
            "settings_account.html",
            settings=settings,
            masked_key=masked_key,
            discord_webhook=discord_webhook,
            active_page="settings",
        )

    @app.route("/settings/emails", methods=["GET", "POST"])
    def settings_emails():
        if request.method == "POST":
            _save_fields(("email_voice_guidance", "business_context"), dest="emails")
            return redirect(url_for("settings_emails"))
        return render_template(
            "settings_emails.html",
            settings=db.get_settings(),
            active_page="settings",
        )

    @app.route("/settings/followups", methods=["GET", "POST"])
    def settings_followups():
        if request.method == "POST":
            _save_fields(
                ("followup_day3_subject", "followup_day3_body",
                 "followup_day7_subject", "followup_day7_body"),
                dest="followups",
            )
            return redirect(url_for("settings_followups"))
        return render_template(
            "settings_followups.html",
            settings=db.get_settings(),
            active_page="settings",
        )

    @app.route("/settings/pipeline", methods=["GET", "POST"])
    def settings_pipeline():
        if request.method == "POST":
            _save_fields(
                ("company_name", "company_tagline", "default_location",
                 "default_leads_per_run", "cold_send_start_date"),
                dest="pipeline",
            )
            return redirect(url_for("settings_pipeline"))
        return render_template(
            "settings_pipeline.html",
            settings=db.get_settings(),
            active_page="settings",
        )

    @app.route("/settings/advanced", methods=["GET", "POST"])
    def settings_advanced():
        if request.method == "POST":
            _save_fields(
                ("who_we_are", "instagram_username",
                 "email_subject_template", "email_greeting", "email_intro",
                 "social_proof", "email_cta"),
                dest="advanced",
            )
            return redirect(url_for("settings_advanced"))
        return render_template(
            "settings_advanced.html",
            settings=db.get_settings(),
            active_page="settings",
        )

    @app.route("/settings/import-csv", methods=["POST"])
    def settings_import():
        file = request.files.get("csv_file")
        if not file or not file.filename:
            flash("Pick a CSV file to import.", "error")
            return redirect(url_for("settings_advanced"))
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
        return redirect(url_for("settings_advanced"))

    # -----------------------------------------------------------------------
    # API endpoints (called by n8n workflows)
    # -----------------------------------------------------------------------

    @app.route("/api/weekly-report", methods=["POST"])
    def api_weekly_report():
        """n8n Workflow 4: POST here on Monday morning to trigger Discord report."""
        secret = request.headers.get("X-Vidora-Key") or request.args.get("key")
        if secret != (os.environ.get("VIDORA_SECRET", "vidora-dev-secret-change-me")):
            return {"ok": False, "error": "unauthorized"}, 401
        stats = db.weekly_stats()
        ok = send_weekly_report(stats)
        return {"ok": ok, "stats": stats}

    @app.route("/api/check-replies", methods=["POST"])
    def api_check_replies():
        """n8n Workflow 3: POST here to trigger an immediate inbox check."""
        secret = request.headers.get("X-Vidora-Key") or request.args.get("key")
        if secret != (os.environ.get("VIDORA_SECRET", "vidora-dev-secret-change-me")):
            return {"ok": False, "error": "unauthorized"}, 401
        from .imap_monitor import check_inbox_for_replies
        found = check_inbox_for_replies()
        return {"ok": True, "replies_found": found}

    @app.route("/api/discord-test", methods=["POST"])
    def api_discord_test():
        """Send a test message to the Discord webhook."""
        ok = test_webhook()
        flash("Discord test message sent." if ok else "Discord webhook failed — check the URL.", "success" if ok else "error")
        return redirect(url_for("settings_page"))

    @app.route("/api/run-status")
    def api_run_status():
        """n8n Workflow 1: returns current pipeline state as JSON."""
        active = db.active_run()
        return {
            "running": pipeline.is_running(),
            "active_run": dict(active) if active else None,
        }

    @app.errorhandler(404)
    def not_found(_):
        return render_template("404.html"), 404

    return app


def _delete_lead_with_pdf(lead: dict) -> None:
    """Delete a lead from DB and remove its audit PDF if it exists."""
    audit = lead.get("audit_path")
    if audit:
        try:
            Path(audit).unlink(missing_ok=True)
        except Exception:
            pass
    db.delete_lead(lead["id"])


def _mask(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return value[:4] + "*" * (len(value) - 8) + value[-4:]


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False)
