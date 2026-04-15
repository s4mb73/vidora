"""
Generate a branded PDF audit for a single lead.

Uses reportlab so it works without any system dependencies. The audit
mirrors the outreach material a media production studio would send:
scores, top weaknesses, personalised pitch, business intent summary.
"""

from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
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
            fontSize=24,
            leading=28,
            textColor=GOLD,
            spaceAfter=4,
        ),
        "subtitle": ParagraphStyle(
            "subtitle",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=11,
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


def _meta_table(lead: dict):
    rows = [
        ["Lead grade", lead.get("lead_grade") or "-"],
        ["Overall score", f"{lead.get('overall_score') or 0}/10"],
        ["Business type", lead.get("business_type") or "unknown"],
        [
            "Business intent",
            f"{lead.get('business_intent_score') or 0}/10",
        ],
        [
            "Location match",
            "yes" if lead.get("location_match") else "no",
        ],
        ["Audience", lead.get("estimated_audience_size") or "-"],
        ["Upgrade potential", lead.get("upgrade_potential") or "-"],
        [
            "Priority",
            "HIGH" if lead.get("priority_flag") else "standard",
        ],
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


def _draw_background(canvas, doc):
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
        f"Vidora  |  Content audit  |  page {doc.page}",
    )
    canvas.restoreState()


def generate_audit(lead: dict, out_dir: Path, company_name: str = "Vidora") -> Path:
    """Render the audit PDF and return its path."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{lead['username']}.pdf"

    styles = _styles()
    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=A4,
        topMargin=22 * mm,
        bottomMargin=18 * mm,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        title=f"Content audit - @{lead['username']}",
        author=company_name,
    )

    story = []
    story.append(Paragraph(f"Content audit  |  @{lead['username']}", styles["title"]))
    generated = datetime.now().strftime("%d %b %Y")
    story.append(
        Paragraph(
            f"Prepared by {company_name}  &middot;  {generated}",
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
        for s in strengths:
            story.append(Paragraph(f"&bull;&nbsp; {s}", styles["bullet"]))

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
                Paragraph(
                    "<b>Selling:</b> " + ", ".join(selling), styles["body"]
                )
            )
        if location:
            story.append(
                Paragraph(
                    "<b>Location:</b> " + ", ".join(location), styles["body"]
                )
            )

    if lead.get("sales_notes"):
        story.append(Paragraph("Internal sales notes", styles["h2"]))
        story.append(Paragraph(lead["sales_notes"], styles["body"]))

    story.append(Spacer(1, 8))
    doc.build(story, onFirstPage=_draw_background, onLaterPages=_draw_background)
    return out_path
