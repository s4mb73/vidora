"""
Generate a branded PDF audit for a single lead.

Uses reportlab so it works without any system dependencies. The audit is
branded as an Innovite Content Evaluation Report prepared for Vidora Media.
"""

from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.graphics.shapes import Drawing, Rect, String, Line
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

GOLD = colors.HexColor("#c9a84c")
DARK = colors.HexColor("#121212")
MID = colors.HexColor("#1e1e1e")
LIGHT = colors.HexColor("#e8e6e1")
MUTED = colors.HexColor("#8a8880")


def _styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "title",
            parent=base["Title"],
            fontName="Helvetica-Bold",
            fontSize=22,
            leading=26,
            textColor=GOLD,
            spaceAfter=2,
        ),
        "subtitle": ParagraphStyle(
            "subtitle",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=10,
            textColor=MUTED,
            spaceAfter=14,
        ),
        "h2": ParagraphStyle(
            "h2",
            parent=base["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=13,
            textColor=GOLD,
            spaceBefore=14,
            spaceAfter=6,
        ),
        "body": ParagraphStyle(
            "body",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=10.5,
            leading=15,
            textColor=LIGHT,
        ),
        "bullet": ParagraphStyle(
            "bullet",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=10.5,
            leading=15,
            leftIndent=14,
            bulletIndent=2,
            textColor=LIGHT,
        ),
        "pitch": ParagraphStyle(
            "pitch",
            parent=base["BodyText"],
            fontName="Helvetica-Oblique",
            fontSize=11,
            leading=16,
            textColor=LIGHT,
        ),
        "who_we_are": ParagraphStyle(
            "who_we_are",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=10,
            leading=15,
            textColor=MUTED,
        ),
        "footer": ParagraphStyle(
            "footer",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=8.5,
            textColor=MUTED,
            alignment=1,
        ),
    }


def _score_table(lead: dict):
    labels = [
        ("Lighting", "lighting"),
        ("Composition", "composition"),
        ("Editing & colour", "editing_colour"),
        ("Brand consistency", "brand_consistency"),
        ("Production value", "content_production"),
        ("Overall judgment", "overall"),
    ]
    data = [["Dimension", "Score", ""]]
    for label, key in labels:
        s = lead.get(key) or 0
        bar = "\u25a0" * int(s) + "\u00b7" * (10 - int(s))
        data.append([label, f"{s}/10", bar])

    tbl = Table(data, colWidths=[70 * mm, 25 * mm, 60 * mm])
    tbl.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), MID),
                ("TEXTCOLOR", (0, 0), (-1, 0), GOLD),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("TEXTCOLOR", (0, 1), (-1, -1), LIGHT),
                ("TEXTCOLOR", (2, 1), (2, -1), GOLD),
                ("BACKGROUND", (0, 1), (-1, -1), DARK),
                ("GRID", (0, 0), (-1, -1), 0.3, MID),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return tbl


def _trend_arrow(trend: str) -> str:
    return {"improving": "↑ improving", "declining": "↓ declining", "stable": "→ stable"}.get(
        (trend or "").lower(), trend or "—"
    )


def _meta_table(lead: dict):
    er = lead.get("engagement_rate")
    er_str = f"{er}%" if er is not None else "-"
    pf = lead.get("posting_frequency") or "-"
    trend = _trend_arrow(lead.get("trend") or "")
    last_post = lead.get("last_post_date") or "-"
    followers = lead.get("followers")
    followers_str = f"{followers:,}" if followers else "-"

    rows = [
        ["Lead grade", lead.get("lead_grade") or "-"],
        ["Overall score", f"{lead.get('overall_score') or 0}/10"],
        ["Engagement rate", er_str],
        ["Posting frequency", pf],
        ["Engagement trend", trend],
        ["Followers", followers_str],
        ["Last post", last_post],
        ["Business type", lead.get("business_type") or "unknown"],
        ["Business intent", f"{lead.get('business_intent_score') or 0}/10"],
        ["Location match", "yes" if lead.get("location_match") else "no"],
        ["Upgrade potential", lead.get("upgrade_potential") or "-"],
        ["Priority", "HIGH" if lead.get("priority_flag") else "standard"],
    ]
    tbl = Table(rows, colWidths=[55 * mm, 100 * mm])
    tbl.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("TEXTCOLOR", (0, 0), (0, -1), GOLD),
                ("TEXTCOLOR", (1, 0), (1, -1), LIGHT),
                ("BACKGROUND", (0, 0), (-1, -1), DARK),
                ("LINEBELOW", (0, 0), (-1, -1), 0.25, MID),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return tbl


def _competitor_bar_chart(client_username: str, client_score: float,
                          competitors: list, comp_avg: float | None) -> Drawing:
    """Return a ReportLab Drawing with a horizontal bar chart comparing scores."""
    bar_h = 18
    gap = 8
    label_w = 90
    chart_w = 290
    max_score = 10

    # Build rows: (label, score, is_client)
    rows = [(f"@{client_username}  (you)", client_score, True)]
    for c in competitors:
        s = c.get("overall_score")
        if s is not None:
            rows.append((f"@{c.get('username', '?')}", s, False))
    if comp_avg is not None:
        rows.append(("Competitor avg", comp_avg, False))

    total_h = len(rows) * (bar_h + gap) + gap + 20  # +20 for x-axis labels
    d = Drawing(label_w + chart_w + 10, total_h)

    # X-axis reference lines (0, 5, 10)
    for tick in (0, 5, 10):
        x = label_w + (tick / max_score) * chart_w
        # Light vertical grid line
        line = Line(x, 0, x, total_h - 20, strokeColor=colors.HexColor("#2a2a2a"), strokeWidth=0.5)
        d.add(line)
        lbl = String(x, 4, str(tick), fontSize=7,
                     fillColor=colors.HexColor("#8a8880"), textAnchor="middle")
        d.add(lbl)

    y = total_h - 20
    for label, score, is_client in rows:
        y -= (bar_h + gap)
        bar_color = GOLD if is_client else colors.HexColor("#3a3a3a")
        bar_len = (score / max_score) * chart_w

        # Bar background
        bg = Rect(label_w, y, chart_w, bar_h,
                  fillColor=colors.HexColor("#1e1e1e"), strokeColor=None)
        d.add(bg)

        # Filled bar
        fill = Rect(label_w, y, bar_len, bar_h,
                    fillColor=bar_color, strokeColor=None)
        d.add(fill)

        # Label (left of bar)
        lbl_color = GOLD if is_client else colors.HexColor("#e8e6e1")
        lbl_str = String(label_w - 4, y + bar_h / 2 - 4, label,
                         fontSize=8, fillColor=lbl_color, textAnchor="end")
        d.add(lbl_str)

        # Score text inside/after bar
        score_str = String(label_w + bar_len + 4, y + bar_h / 2 - 4,
                           f"{score}/10", fontSize=8,
                           fillColor=GOLD if is_client else LIGHT, textAnchor="start")
        d.add(score_str)

    return d


def _make_background(sender_label: str, client_label: str):
    """Return a page-drawing callback with the correct footer text."""
    def _draw(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(DARK)
        canvas.rect(0, 0, doc.pagesize[0], doc.pagesize[1], stroke=0, fill=1)
        # Gold accent bar at top
        canvas.setFillColor(GOLD)
        canvas.rect(0, doc.pagesize[1] - 6, doc.pagesize[0], 6, stroke=0, fill=1)
        # Footer
        canvas.setFillColor(MUTED)
        canvas.setFont("Helvetica", 8)
        canvas.drawCentredString(
            doc.pagesize[0] / 2,
            12,
            f"Powered by Innovite  -  innovite.io  |  Content Evaluation Report  |  Prepared for {client_label}  |  page {doc.page}",
        )
        canvas.restoreState()
    return _draw


def generate_audit(lead: dict, out_dir: Path, company_name: str = "Vidora", settings: dict | None = None) -> Path:
    """Render the audit PDF and return its path."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{lead['username']}.pdf"

    s = settings or {}
    sender_label = "Innovite"
    client_label = s.get("client_company", "Vidora Media")
    who_we_are_text = s.get(
        "who_we_are",
        (
            "Innovite is a content intelligence system used by media production agencies "
            "to identify high potential clients. Vidora Media uses our platform to evaluate "
            "Instagram content across Manchester businesses. Your business was flagged as "
            "high potential — strong presence but with production gaps limiting growth. "
            "This report is the same evaluation Vidora Media runs on every prospective client."
        ),
    )

    styles = _styles()
    background_fn = _make_background(sender_label, client_label)

    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=A4,
        topMargin=22 * mm,
        bottomMargin=18 * mm,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        title=f"Content Evaluation Report - @{lead['username']}",
        author=sender_label,
    )

    story = []

    # Title
    story.append(Paragraph(f"Content Evaluation Report  |  @{lead['username']}", styles["title"]))
    generated = datetime.now().strftime("%d %b %Y")
    story.append(
        Paragraph(
            f"Prepared by {sender_label} for {client_label}  &middot;  {generated}",
            styles["subtitle"],
        )
    )

    story.append(Paragraph("Headline", styles["h2"]))
    story.append(_meta_table(lead))

    story.append(Paragraph("Score breakdown", styles["h2"]))
    story.append(_score_table(lead))

    story.append(Paragraph("What is holding the feed back", styles["h2"]))
    weaknesses = lead.get("weaknesses") or []
    if weaknesses:
        for w in weaknesses:
            story.append(Paragraph(f"&bull;&nbsp; {w}", styles["bullet"]))
    else:
        story.append(Paragraph("No specific weaknesses recorded.", styles["body"]))

    strengths = lead.get("strengths") or []
    if strengths:
        story.append(Paragraph("What is already working", styles["h2"]))
        for s_item in strengths:
            story.append(Paragraph(f"&bull;&nbsp; {s_item}", styles["bullet"]))

    story.append(Paragraph("Recommended conversation", styles["h2"]))
    pitch = lead.get("personalised_pitch") or ""
    if pitch:
        story.append(Paragraph(pitch, styles["pitch"]))
    else:
        story.append(Paragraph("No pitch generated.", styles["body"]))

    selling = lead.get("selling_signals") or []
    location = lead.get("location_signals") or []
    if selling or location:
        story.append(Paragraph("Business intent signals", styles["h2"]))
        if selling:
            story.append(
                Paragraph("<b>Selling:</b> " + ", ".join(selling), styles["body"])
            )
        if location:
            story.append(
                Paragraph("<b>Location:</b> " + ", ".join(location), styles["body"])
            )

    if lead.get("sales_notes"):
        story.append(Paragraph("Internal sales notes", styles["h2"]))
        story.append(Paragraph(lead["sales_notes"], styles["body"]))

    # Competitor comparison — side-by-side table (preferred) or bar chart fallback
    bench = lead.get("competitor_benchmark") or {}
    ranking_table = bench.get("ranking_table") or []
    competitors = lead.get("competitors") or []
    comp_avg = lead.get("competitor_avg_score")
    client_score = lead.get("overall_score") or 0

    if ranking_table:
        story.append(Paragraph("Competitor comparison", styles["h2"]))

        # Build column headers: Dimension | Target | Comp 1 | Comp 2 | Comp 3
        target_row = next((r for r in ranking_table if r.get("is_target")), None)
        comp_rows = [r for r in ranking_table if not r.get("is_target")]

        col_headers = ["Dimension", "Target"]
        for ci, cr in enumerate(comp_rows[:3], 1):
            col_headers.append(f"Comp {ci}")

        def _fmtv(v, suffix=""):
            return f"{v}{suffix}" if v is not None else "-"

        def _fmtf(v):
            if v is None:
                return "-"
            if isinstance(v, int):
                return f"{v:,}"
            return str(v)

        def _row(label, tgt_val, comp_vals):
            return [label, tgt_val] + [comp_vals[i] if i < len(comp_vals) else "-" for i in range(min(3, len(comp_rows)))]

        tgt = target_row or {}
        cvals = comp_rows[:3]

        table_data = [col_headers]
        table_data.append(_row(
            "Content Score",
            _fmtv(tgt.get("content_score"), "/10"),
            [_fmtv(c.get("content_score"), "/10") for c in cvals],
        ))
        table_data.append(_row(
            "Website Score",
            _fmtv(tgt.get("website_score"), "/10"),
            [_fmtv(c.get("website_score"), "/10") for c in cvals],
        ))
        table_data.append(_row(
            "Google Rating",
            _fmtv(tgt.get("maps_rating"), "★"),
            [_fmtv(c.get("maps_rating"), "★") for c in cvals],
        ))
        table_data.append(_row(
            "Google Reviews",
            _fmtf(tgt.get("maps_review_count")),
            [_fmtf(c.get("maps_review_count")) for c in cvals],
        ))
        table_data.append(_row(
            "IG Followers",
            _fmtf(tgt.get("ig_followers")),
            [_fmtf(c.get("ig_followers")) for c in cvals],
        ))
        table_data.append(_row(
            "Rank",
            f"{bench.get('target_rank', '-')}/4",
            [
                f"{next((i+1 for i, r in enumerate(ranking_table) if r.get('username') == c.get('username')), '-')}/4"
                for c in cvals
            ],
        ))

        n_cols = len(col_headers)
        col_w = 155 / n_cols  # distribute across ~155mm
        col_widths = [45 * mm] + [col_w * mm] * (n_cols - 1)

        comp_tbl = Table(table_data, colWidths=col_widths)
        tbl_style = [
            ("BACKGROUND", (0, 0), (-1, 0), MID),
            ("TEXTCOLOR", (0, 0), (-1, 0), GOLD),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("TEXTCOLOR", (0, 1), (-1, -1), LIGHT),
            # Target column in GOLD
            ("TEXTCOLOR", (1, 1), (1, -1), GOLD),
            ("BACKGROUND", (0, 1), (-1, -1), DARK),
            ("GRID", (0, 0), (-1, -1), 0.3, MID),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("FONTNAME", (0, 1), (0, -1), "Helvetica-Bold"),
            ("TEXTCOLOR", (0, 1), (0, -1), MUTED),
        ]
        comp_tbl.setStyle(TableStyle(tbl_style))
        story.append(comp_tbl)
        story.append(Spacer(1, 6))

        # Summary sentence below table
        top_name = bench.get("top_competitor_name")
        gap_to_top = bench.get("gap_to_top") or 0
        if top_name and gap_to_top > 0:
            summary = (
                f"Your nearest competitor {top_name} outscores you by "
                f"{round(gap_to_top, 1)} points overall."
            )
            story.append(Paragraph(summary, styles["body"]))

    elif competitors or comp_avg is not None:
        # Fallback: old bar chart
        story.append(Paragraph("Competitor comparison", styles["h2"]))
        chart = _competitor_bar_chart(
            lead.get("username", ""),
            client_score,
            competitors,
            comp_avg,
        )
        story.append(chart)
        if comp_avg is not None:
            gap = round(client_score - comp_avg, 1)
            if gap < 0:
                interp = (f"This client scores {abs(gap)} points below the local competitor average. "
                          "There is a clear production gap to address.")
            elif gap > 0:
                interp = (f"This client already scores {gap} points above the local competitor average "
                          "— good baseline, but production quality gaps still limit growth.")
            else:
                interp = "This client is level with the local competitor average."
            story.append(Spacer(1, 6))
            story.append(Paragraph(interp, styles["body"]))

    # Digital Presence — website analysis section
    wa = lead.get("website_analysis") or {}
    if wa and not wa.get("error") and wa.get("website_score") is not None:
        story.append(Paragraph("Digital Presence", styles["h2"]))

        def _yn(v):
            return "Yes" if v else "No"

        web_rows = [
            ["Dimension", "Result"],
            ["Website score",        f"{wa.get('website_score', '-')}/10"],
            ["SSL certificate",      _yn(wa.get("has_ssl"))],
            ["Mobile-friendly",      _yn(wa.get("has_mobile_viewport"))],
            ["Load time",            f"{wa.get('load_time_ms', '-')}ms"],
            ["Contact info visible", _yn(wa.get("has_contact_info"))],
            ["Clear CTA button",     _yn(wa.get("has_cta"))],
            ["Meta title + desc",    _yn(wa.get("has_title_tag") and wa.get("has_meta_description"))],
            ["Homepage word count",  str(wa.get("word_count", 0))],
        ]
        web_tbl = Table(web_rows, colWidths=[80 * mm, 75 * mm])
        web_tbl.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), MID),
                    ("TEXTCOLOR", (0, 0), (-1, 0), GOLD),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 10),
                    ("TEXTCOLOR", (0, 1), (-1, -1), LIGHT),
                    ("BACKGROUND", (0, 1), (-1, -1), DARK),
                    ("GRID", (0, 0), (-1, -1), 0.3, MID),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]
            )
        )
        story.append(web_tbl)
        story.append(Spacer(1, 6))

        # Top 2 website weaknesses
        web_weak = wa.get("top_weaknesses") or []
        if web_weak:
            story.append(Paragraph("Website weaknesses identified:", styles["body"]))
            for ww in web_weak:
                story.append(Paragraph(f"&bull;&nbsp; {ww}", styles["bullet"]))
            story.append(Spacer(1, 4))

        # Benchmark note
        ws = wa.get("website_score", 0)
        if ws < 6:
            ws_note = (
                "A high-performing competitor site in this space would score 8-9/10: fast HTTPS load, "
                "mobile-responsive design, prominent CTA above the fold, clear contact options, and "
                "200+ words of content. This site falls short on multiple counts."
            )
        elif ws < 8:
            ws_note = (
                "The site meets basic standards but lacks the conversion-focused design "
                "of top-performing local competitors: optimised CTAs, trust signals, and "
                "rich content that drives enquiries."
            )
        else:
            ws_note = (
                "The website is technically strong. Instagram content quality is the primary "
                "gap holding this business back."
            )
        story.append(Paragraph(ws_note, styles["who_we_are"]))

    # WHO WE ARE section at the end
    story.append(Spacer(1, 10))
    story.append(Paragraph("Who we are", styles["h2"]))
    story.append(Paragraph(who_we_are_text, styles["who_we_are"]))

    story.append(Spacer(1, 8))
    doc.build(story, onFirstPage=background_fn, onLaterPages=background_fn)
    return out_path
