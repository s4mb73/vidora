"""
Premium PDF audit generator — Vidora / Innovite Digital Intelligence Report.

Sections:
  Cover page (dark, full-bleed)
  1. Executive Summary
  2. Business Overview
  3. Content Analysis (with bar charts)
  4. Website Analysis
  5. Competitor Intelligence
  6. Revenue Gap
  7. Recommended Next Steps
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.graphics.shapes import Drawing, Rect, String, Line
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    FrameBreak,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

# ── Colour palette ─────────────────────────────────────────────────────────────
COVER_BG   = colors.HexColor("#0d0d0d")
HEADER_BG  = colors.HexColor("#0d0d0d")
GOLD       = colors.HexColor("#c9a84c")
WHITE      = colors.HexColor("#ffffff")
OFF_WHITE  = colors.HexColor("#f7f6f4")
TEXT_DARK  = colors.HexColor("#1a1a1a")
TEXT_MUTED = colors.HexColor("#6b6b6b")
BORDER     = colors.HexColor("#e0ddd8")
GREEN      = colors.HexColor("#16a34a")
RED        = colors.HexColor("#dc2626")
AMBER      = colors.HexColor("#d97706")

PAGE_W, PAGE_H = A4
MARGIN = 18 * mm


# ── Styles ─────────────────────────────────────────────────────────────────────

def _styles() -> dict:
    base = getSampleStyleSheet()
    return {
        # Cover page
        "cover_tag": ParagraphStyle("cover_tag", parent=base["Normal"],
            fontName="Helvetica", fontSize=9, textColor=GOLD,
            spaceAfter=6, letterSpacing=2),
        "cover_title": ParagraphStyle("cover_title", parent=base["Normal"],
            fontName="Helvetica-Bold", fontSize=32, leading=38,
            textColor=WHITE, spaceAfter=6),
        "cover_sub": ParagraphStyle("cover_sub", parent=base["Normal"],
            fontName="Helvetica", fontSize=13, leading=18,
            textColor=colors.HexColor("#cccccc"), spaceAfter=4),
        "cover_date": ParagraphStyle("cover_date", parent=base["Normal"],
            fontName="Helvetica", fontSize=10, textColor=TEXT_MUTED,
            spaceAfter=4),
        # Section headers
        "section_label": ParagraphStyle("section_label", parent=base["Normal"],
            fontName="Helvetica", fontSize=8, textColor=GOLD,
            spaceAfter=2, letterSpacing=1.5),
        "section_title": ParagraphStyle("section_title", parent=base["Normal"],
            fontName="Helvetica-Bold", fontSize=15, leading=19,
            textColor=WHITE, spaceAfter=0),
        # Body
        "h3": ParagraphStyle("h3", parent=base["Normal"],
            fontName="Helvetica-Bold", fontSize=11, textColor=TEXT_DARK,
            spaceBefore=10, spaceAfter=4),
        "body": ParagraphStyle("body", parent=base["BodyText"],
            fontName="Helvetica", fontSize=10, leading=15,
            textColor=TEXT_DARK, spaceAfter=4),
        "muted": ParagraphStyle("muted", parent=base["Normal"],
            fontName="Helvetica", fontSize=9, leading=13,
            textColor=TEXT_MUTED, spaceAfter=2),
        "bullet": ParagraphStyle("bullet", parent=base["BodyText"],
            fontName="Helvetica", fontSize=10, leading=15,
            textColor=TEXT_DARK, leftIndent=14, bulletIndent=2, spaceAfter=3),
        "kv_label": ParagraphStyle("kv_label", parent=base["Normal"],
            fontName="Helvetica-Bold", fontSize=9, textColor=TEXT_MUTED,
            spaceAfter=1),
        "kv_value": ParagraphStyle("kv_value", parent=base["Normal"],
            fontName="Helvetica-Bold", fontSize=14, leading=17,
            textColor=TEXT_DARK, spaceAfter=6),
        "kv_value_gold": ParagraphStyle("kv_value_gold", parent=base["Normal"],
            fontName="Helvetica-Bold", fontSize=14, leading=17,
            textColor=GOLD, spaceAfter=6),
    }


# ── Drawing helpers ────────────────────────────────────────────────────────────

def _score_bar(score: float | int | None, max_val: int = 10,
               width: float = 120, height: float = 8) -> Drawing:
    """Horizontal filled bar for a score."""
    score = score or 0
    frac = min(score / max_val, 1.0)
    d = Drawing(width, height)
    # Background track
    d.add(Rect(0, 0, width, height, fillColor=colors.HexColor("#e8e5e0"),
               strokeColor=None))
    # Filled portion
    if score >= max_val * 0.7:
        fill = GREEN
    elif score >= max_val * 0.4:
        fill = GOLD
    else:
        fill = RED
    d.add(Rect(0, 0, width * frac, height, fillColor=fill, strokeColor=None))
    return d


def _section_header_canvas(canvas, y: float, label: str, title: str,
                            page_w: float = PAGE_W, margin: float = MARGIN):
    """Draw a dark full-width section header band."""
    band_h = 32
    canvas.saveState()
    canvas.setFillColor(HEADER_BG)
    canvas.rect(0, y - band_h, page_w, band_h, stroke=0, fill=1)
    # Gold accent left strip
    canvas.setFillColor(GOLD)
    canvas.rect(0, y - band_h, 4, band_h, stroke=0, fill=1)
    # Label (small caps above title)
    canvas.setFillColor(GOLD)
    canvas.setFont("Helvetica", 7)
    canvas.drawString(margin, y - 12, label.upper())
    # Title
    canvas.setFillColor(WHITE)
    canvas.setFont("Helvetica-Bold", 13)
    canvas.drawString(margin, y - 26, title)
    canvas.restoreState()
    return band_h


# ── Page callbacks ─────────────────────────────────────────────────────────────

def _cover_page(canvas, doc):
    """Full-bleed dark cover page."""
    canvas.saveState()
    w, h = doc.pagesize

    # Background
    canvas.setFillColor(COVER_BG)
    canvas.rect(0, 0, w, h, stroke=0, fill=1)

    # Gold top bar
    canvas.setFillColor(GOLD)
    canvas.rect(0, h - 5, w, 5, stroke=0, fill=1)

    # Gold left accent strip
    canvas.setFillColor(GOLD)
    canvas.rect(0, 0, 4, h, stroke=0, fill=1)

    # "INNOVITE" wordmark top left
    canvas.setFillColor(GOLD)
    canvas.setFont("Helvetica-Bold", 11)
    canvas.drawString(MARGIN + 6, h - 22, "INNOVITE")

    # "DIGITAL INTELLIGENCE REPORT" tag
    canvas.setFillColor(colors.HexColor("#888888"))
    canvas.setFont("Helvetica", 8)
    canvas.drawString(MARGIN + 6, h - 36, "DIGITAL INTELLIGENCE REPORT")

    # Thin gold divider
    canvas.setStrokeColor(GOLD)
    canvas.setLineWidth(0.5)
    canvas.line(MARGIN, h - 45, w - MARGIN, h - 45)

    # Business name — large, white, centre-left
    biz = doc._biz_name or "Business"
    canvas.setFillColor(WHITE)
    canvas.setFont("Helvetica-Bold", 36)
    # wrap long names
    if len(biz) > 22:
        canvas.setFont("Helvetica-Bold", 26)
    canvas.drawString(MARGIN, h * 0.52, biz)

    # Username below
    username = doc._username or ""
    canvas.setFillColor(GOLD)
    canvas.setFont("Helvetica", 13)
    canvas.drawString(MARGIN, h * 0.52 - 22, f"@{username}")

    # Grade badge
    grade = doc._grade or "?"
    grade_colours = {"A": GREEN, "B": GOLD, "C": AMBER, "D": RED}
    gc = grade_colours.get(grade, colors.HexColor("#888888"))
    canvas.setFillColor(gc)
    canvas.roundRect(MARGIN, h * 0.52 - 54, 40, 22, 4, stroke=0, fill=1)
    canvas.setFillColor(WHITE)
    canvas.setFont("Helvetica-Bold", 13)
    canvas.drawCentredString(MARGIN + 20, h * 0.52 - 46, f"Grade {grade}")

    # Date generated
    date_str = datetime.now().strftime("%d %B %Y")
    canvas.setFillColor(colors.HexColor("#666666"))
    canvas.setFont("Helvetica", 9)
    canvas.drawString(MARGIN, h * 0.52 - 76, f"Generated {date_str}")

    # Divider line above footer area
    canvas.setStrokeColor(colors.HexColor("#2a2a2a"))
    canvas.setLineWidth(0.5)
    canvas.line(MARGIN, 60, w - MARGIN, 60)

    # "CONFIDENTIAL" bottom right
    canvas.setFillColor(colors.HexColor("#444444"))
    canvas.setFont("Helvetica", 8)
    canvas.drawRightString(w - MARGIN, 46, "CONFIDENTIAL")

    # Footer bottom left
    canvas.setFillColor(colors.HexColor("#444444"))
    canvas.setFont("Helvetica", 8)
    canvas.drawString(MARGIN, 46, "Innovite  |  innovite.io")

    canvas.restoreState()


def _content_page(canvas, doc):
    """Header + footer for content pages."""
    canvas.saveState()
    w, h = doc.pagesize

    # White background (default, just ensure it)
    canvas.setFillColor(WHITE)
    canvas.rect(0, 0, w, h, stroke=0, fill=1)

    # Dark top bar
    canvas.setFillColor(HEADER_BG)
    canvas.rect(0, h - 22, w, 22, stroke=0, fill=1)

    # Wordmark in header
    canvas.setFillColor(GOLD)
    canvas.setFont("Helvetica-Bold", 8)
    canvas.drawString(MARGIN, h - 14, "INNOVITE")

    # Business name in header (right side)
    biz = doc._biz_name or ""
    canvas.setFillColor(colors.HexColor("#888888"))
    canvas.setFont("Helvetica", 8)
    canvas.drawRightString(w - MARGIN, h - 14, biz)

    # Footer line
    canvas.setStrokeColor(BORDER)
    canvas.setLineWidth(0.4)
    canvas.line(MARGIN, 24, w - MARGIN, 24)

    # Footer text
    canvas.setFillColor(TEXT_MUTED)
    canvas.setFont("Helvetica", 7.5)
    canvas.drawString(MARGIN, 12, "Innovite  |  innovite.io  |  Confidential")

    # Page number bottom right
    canvas.drawRightString(w - MARGIN, 12, f"Page {doc.page - 1}")

    canvas.restoreState()


# ── Section header flowable ────────────────────────────────────────────────────

class SectionHeader:
    """Draws a dark full-width section header. Used as a flowable placeholder."""
    def __init__(self, label: str, title: str):
        self.label = label
        self.title = title
        self.height = 36

    def wrap(self, availW, availH):
        return availW, self.height

    def draw(self):
        pass  # drawn via _section_header_canvas in actual render


from reportlab.platypus.flowables import Flowable

class _SectionBand(Flowable):
    def __init__(self, label: str, title: str):
        super().__init__()
        self.label = label
        self.title = title
        self._height = 38

    def wrap(self, availW, availH):
        self._width = availW
        return availW, self._height

    def draw(self):
        c = self.canv
        w = self._width + MARGIN * 2  # extend to page edge
        x0 = -MARGIN
        c.saveState()
        # Dark band
        c.setFillColor(HEADER_BG)
        c.rect(x0, -4, w, self._height, stroke=0, fill=1)
        # Gold left strip
        c.setFillColor(GOLD)
        c.rect(x0, -4, 4, self._height, stroke=0, fill=1)
        # Label
        c.setFillColor(GOLD)
        c.setFont("Helvetica", 7)
        c.drawString(2, 20, self.label.upper())
        # Title
        c.setFillColor(WHITE)
        c.setFont("Helvetica-Bold", 13)
        c.drawString(2, 6, self.title)
        c.restoreState()


# ── Score bar flowable ─────────────────────────────────────────────────────────

def _inline_bar(score, max_val=10, width_mm=80, height_mm=4.5):
    """Return a Drawing for embedding inline as a score bar."""
    w = width_mm * mm
    h = height_mm * mm
    frac = min((score or 0) / max_val, 1.0)
    if (score or 0) >= max_val * 0.7:
        fill = GREEN
    elif (score or 0) >= max_val * 0.4:
        fill = GOLD
    else:
        fill = RED
    d = Drawing(w, h)
    d.add(Rect(0, 0, w, h, fillColor=colors.HexColor("#e8e5e0"), strokeColor=None))
    if frac > 0:
        d.add(Rect(0, 0, w * frac, h, fillColor=fill, strokeColor=None))
    return d


# ── Revenue gap estimator ──────────────────────────────────────────────────────

def _estimate_revenue_gap(lead: dict) -> dict:
    """Estimate monthly revenue being missed from weak social presence."""
    biz_type = (lead.get("business_type") or "").lower()
    followers = lead.get("followers") or 0
    er = (lead.get("engagement_rate") or 0)
    if er > 1:
        er = er / 100  # already percent

    # Average treatment value by industry
    if any(w in biz_type for w in ["aesthetic", "cosmetic", "filler", "botox"]):
        avg_value = 350
        industry = "aesthetics"
        industry_er = 0.035
    elif any(w in biz_type for w in ["dental", "dentist", "orthodon"]):
        avg_value = 450
        industry = "dental"
        industry_er = 0.025
    elif any(w in biz_type for w in ["physio", "sport", "rehab"]):
        avg_value = 150
        industry = "physiotherapy"
        industry_er = 0.030
    elif any(w in biz_type for w in ["salon", "hair", "beauty", "nail"]):
        avg_value = 80
        industry = "beauty"
        industry_er = 0.045
    else:
        avg_value = 200
        industry = "professional services"
        industry_er = 0.030

    # ER gap: how much engagement is being lost vs industry average
    er_gap = max(0, industry_er - er)
    missed_engagements = int(followers * er_gap)

    # Assume 3% of engaged users convert to enquiries, 30% close
    enquiry_rate = 0.03
    close_rate = 0.30
    missed_bookings = int(missed_engagements * enquiry_rate * close_rate)
    missed_revenue = missed_bookings * avg_value

    # Posting gap
    posting_raw = lead.get("posting_frequency") or ""
    import re
    pm = re.search(r"([\d.]+)", posting_raw)
    posts_pw = float(pm.group(1)) if pm else 0
    ideal_posts_pw = 3
    posting_gap = max(0, ideal_posts_pw - posts_pw)

    return {
        "industry": industry,
        "avg_value": avg_value,
        "industry_er": round(industry_er * 100, 1),
        "current_er": round(er * 100, 2),
        "missed_bookings": max(1, missed_bookings),
        "missed_revenue": max(avg_value, missed_revenue),
        "posting_gap": round(posting_gap, 1),
        "posts_pw": posts_pw,
    }


# ── Main generator ─────────────────────────────────────────────────────────────

def generate_audit(lead: dict, out_dir: Path,
                   company_name: str = "Vidora",
                   settings: dict | None = None) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{lead['username']}.pdf"

    s = settings or {}
    biz_name = lead.get("business_name") or f"@{lead.get('username', '')}"
    username = lead.get("username") or ""
    grade = lead.get("lead_grade") or "?"
    generated = datetime.now().strftime("%d %B %Y")

    st = _styles()

    # ── Document setup ──────────────────────────────────────────────────────
    doc = BaseDocTemplate(
        str(out_path),
        pagesize=A4,
        title=f"Digital Intelligence Report — {biz_name}",
        author="Innovite",
    )
    doc._biz_name = biz_name
    doc._username = username
    doc._grade = grade

    cover_frame = Frame(0, 0, PAGE_W, PAGE_H, leftPadding=0, rightPadding=0,
                        topPadding=0, bottomPadding=0, id="cover")
    content_frame = Frame(MARGIN, 28, PAGE_W - 2 * MARGIN,
                          PAGE_H - 22 - 36, id="content")

    doc.addPageTemplates([
        PageTemplate(id="Cover",   frames=[cover_frame], onPage=_cover_page),
        PageTemplate(id="Content", frames=[content_frame], onPage=_content_page),
    ])

    story = []

    # ── COVER PAGE ──────────────────────────────────────────────────────────
    # (drawn entirely by _cover_page canvas callback — we just need a page break)
    story.append(NextPageTemplate("Content"))
    story.append(PageBreak())

    # ─────────────────────────────────────────────────────────────────────────
    # SECTION 1 — EXECUTIVE SUMMARY
    # ─────────────────────────────────────────────────────────────────────────
    story.append(_SectionBand("Section 1", "Executive Summary"))
    story.append(Spacer(1, 10))

    weaknesses = lead.get("weaknesses") or []
    strengths  = lead.get("strengths") or []
    bench      = lead.get("competitor_benchmark") or {}
    wa         = lead.get("website_analysis") or {}
    rev_gap    = _estimate_revenue_gap(lead)

    # Derive 3 sharp bullet points from real data
    exec_bullets = []

    # Bullet 1 — content gap
    if weaknesses:
        exec_bullets.append(weaknesses[0])
    else:
        exec_bullets.append(
            f"{biz_name} is posting at {lead.get('posting_frequency') or 'a very low rate'}, "
            "limiting organic reach and visibility to new patients."
        )

    # Bullet 2 — competitor threat
    top_comp = bench.get("top_competitor_name")
    top_rev  = bench.get("top_competitor_maps_reviews")
    own_rev  = lead.get("maps_review_count")
    if top_comp and top_rev:
        exec_bullets.append(
            f"{top_comp} leads the local market with {top_rev} Google reviews "
            f"vs {biz_name}'s {own_rev or 'fewer'} — a visible credibility gap when patients search."
        )
    elif weaknesses and len(weaknesses) > 1:
        exec_bullets.append(weaknesses[1])

    # Bullet 3 — revenue opportunity
    exec_bullets.append(
        f"Based on current engagement rate ({rev_gap['current_er']}%) vs the {rev_gap['industry']} "
        f"industry average ({rev_gap['industry_er']}%), an estimated "
        f"£{rev_gap['missed_revenue']:,}/month in bookings is not being converted from the "
        f"existing {lead.get('followers') or 0:,}-follower audience."
    )

    for b in exec_bullets[:3]:
        story.append(Paragraph(f"<bullet>&bull;</bullet> {b}", st["bullet"]))
        story.append(Spacer(1, 4))

    story.append(Spacer(1, 8))

    # ─────────────────────────────────────────────────────────────────────────
    # SECTION 2 — BUSINESS OVERVIEW
    # ─────────────────────────────────────────────────────────────────────────
    story.append(_SectionBand("Section 2", "Business Overview"))
    story.append(Spacer(1, 10))

    def _kv_row(label, val, gold=False):
        style = st["kv_value_gold"] if gold else st["kv_value"]
        return [Paragraph(label, st["kv_label"]), Paragraph(str(val), style)]

    er_val = lead.get("engagement_rate")
    er_str = f"{er_val}%" if er_val is not None else "—"
    followers = lead.get("followers")
    followers_str = f"{followers:,}" if followers else "—"
    ws = wa.get("website_score")
    ws_str = f"{ws}/10" if ws is not None else "—"
    rating = lead.get("maps_rating") or "—"
    reviews = lead.get("maps_review_count") or "—"
    pf = lead.get("posting_frequency") or "—"
    lpd = (lead.get("last_post_date") or "—")[:10]

    overview_data = [
        [Paragraph("Google Reviews", st["kv_label"]),
         Paragraph("Instagram Followers", st["kv_label"]),
         Paragraph("Engagement Rate", st["kv_label"]),
         Paragraph("Website Score", st["kv_label"])],
        [Paragraph(str(reviews), st["kv_value_gold"]),
         Paragraph(followers_str, st["kv_value_gold"]),
         Paragraph(er_str, st["kv_value_gold"] if er_val and er_val >= 3 else st["kv_value"]),
         Paragraph(ws_str, st["kv_value_gold"] if ws and ws >= 7 else st["kv_value"])],
        [Paragraph("Google Rating", st["kv_label"]),
         Paragraph("Posts per Week", st["kv_label"]),
         Paragraph("Last Post", st["kv_label"]),
         Paragraph("Business Type", st["kv_label"])],
        [Paragraph(f"{rating}★" if rating != "—" else "—", st["kv_value"]),
         Paragraph(pf, st["kv_value"]),
         Paragraph(lpd, st["kv_value"]),
         Paragraph(lead.get("business_type") or "—", st["muted"])],
    ]
    col_w = (PAGE_W - 2 * MARGIN) / 4
    ov_tbl = Table(overview_data, colWidths=[col_w] * 4)
    ov_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), OFF_WHITE),
        ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LINEBELOW", (0, 1), (-1, 1), 0.5, BORDER),
    ]))
    story.append(ov_tbl)
    story.append(Spacer(1, 10))

    # Maps address
    addr = lead.get("maps_address")
    if addr:
        story.append(Paragraph(f"Location: {addr}", st["muted"]))
    story.append(Spacer(1, 8))

    # ─────────────────────────────────────────────────────────────────────────
    # SECTION 3 — CONTENT ANALYSIS
    # ─────────────────────────────────────────────────────────────────────────
    story.append(_SectionBand("Section 3", "Content Analysis"))
    story.append(Spacer(1, 10))

    score_dims = [
        ("Lighting",           lead.get("lighting")),
        ("Composition",        lead.get("composition")),
        ("Editing & Colour",   lead.get("editing_colour")),
        ("Brand Consistency",  lead.get("brand_consistency")),
        ("Production Value",   lead.get("content_production")),
        ("Overall Judgment",   lead.get("overall")),
    ]

    bar_w = 110  # mm
    score_rows = []
    for label, val in score_dims:
        v = val or 0
        bar = _inline_bar(v, width_mm=bar_w, height_mm=4)
        score_rows.append([
            Paragraph(label, st["body"]),
            bar,
            Paragraph(f"<b>{v}/10</b>", st["body"]),
        ])

    score_tbl = Table(score_rows, colWidths=[50*mm, bar_w*mm, 18*mm])
    score_tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LINEBELOW", (0, 0), (-1, -2), 0.3, BORDER),
        ("BACKGROUND", (0, 0), (-1, -1), WHITE),
    ]))
    story.append(score_tbl)
    story.append(Spacer(1, 8))

    # Overall score highlight
    overall_score = lead.get("overall_score") or 0
    story.append(Paragraph(
        f"<b>Overall content score: {overall_score}/10</b>",
        st["h3"]
    ))

    # Top 3 weaknesses
    if weaknesses:
        story.append(Paragraph("Specific weaknesses observed:", st["h3"]))
        for w in weaknesses[:3]:
            story.append(Paragraph(f"<bullet>&bull;</bullet> {w}", st["bullet"]))
    story.append(Spacer(1, 6))

    # Written analysis paragraph (from pitch or sales_notes)
    pitch = lead.get("personalised_pitch")
    if pitch:
        story.append(Paragraph("Analysis:", st["h3"]))
        story.append(Paragraph(pitch, st["body"]))
    story.append(Spacer(1, 8))

    # ─────────────────────────────────────────────────────────────────────────
    # SECTION 4 — WEBSITE ANALYSIS
    # ─────────────────────────────────────────────────────────────────────────
    story.append(_SectionBand("Section 4", "Website Analysis"))
    story.append(Spacer(1, 10))

    if wa and wa.get("website_score") is not None:
        ws_score = wa.get("website_score", 0)

        # Score bar
        story.append(Paragraph(f"Website score: <b>{ws_score}/10</b>", st["h3"]))
        story.append(_inline_bar(ws_score, width_mm=PAGE_W/mm - 2*MARGIN/mm - 10))
        story.append(Spacer(1, 8))

        def _yn(v):
            return "Yes" if v else "No"

        web_data = [
            ["Metric", "Status"],
            ["SSL Certificate (HTTPS)",    _yn(wa.get("has_ssl"))],
            ["Mobile-Friendly Viewport",   _yn(wa.get("has_mobile_viewport"))],
            ["Page Load Time",             f"{wa.get('load_time_ms','—')}ms"],
            ["Clear CTA Button",           _yn(wa.get("has_cta"))],
            ["Contact Info Visible",       _yn(wa.get("has_contact_info"))],
            ["Title Tag Present",          _yn(wa.get("has_title_tag"))],
            ["Meta Description Present",   _yn(wa.get("has_meta_description"))],
            ["Homepage Word Count",        str(wa.get("word_count", 0))],
        ]
        col_w2 = (PAGE_W - 2*MARGIN) / 2
        web_tbl = Table(web_data, colWidths=[col_w2, col_w2])
        web_style = [
            ("BACKGROUND", (0, 0), (-1, 0), HEADER_BG),
            ("TEXTCOLOR", (0, 0), (-1, 0), GOLD),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 10),
            ("TEXTCOLOR", (0, 1), (-1, -1), TEXT_DARK),
            ("BACKGROUND", (0, 1), (-1, -1), WHITE),
            ("GRID", (0, 0), (-1, -1), 0.3, BORDER),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]
        # Colour No cells red, Yes cells green
        for ri, row in enumerate(web_data[1:], 1):
            val = row[1]
            if val == "No":
                web_style.append(("TEXTCOLOR", (1, ri), (1, ri), RED))
                web_style.append(("FONTNAME", (1, ri), (1, ri), "Helvetica-Bold"))
            elif val == "Yes":
                web_style.append(("TEXTCOLOR", (1, ri), (1, ri), GREEN))
                web_style.append(("FONTNAME", (1, ri), (1, ri), "Helvetica-Bold"))
        web_tbl.setStyle(TableStyle(web_style))
        story.append(web_tbl)
        story.append(Spacer(1, 8))

        # Top 2 website weaknesses
        web_weak = wa.get("top_weaknesses") or []
        if web_weak:
            story.append(Paragraph("Top website weaknesses:", st["h3"]))
            for ww in web_weak[:2]:
                story.append(Paragraph(f"<bullet>&bull;</bullet> {ww}", st["bullet"]))
    else:
        story.append(Paragraph("Website analysis not available for this lead.", st["muted"]))

    story.append(Spacer(1, 8))

    # ─────────────────────────────────────────────────────────────────────────
    # SECTION 5 — COMPETITOR INTELLIGENCE
    # ─────────────────────────────────────────────────────────────────────────
    story.append(_SectionBand("Section 5", "Competitor Intelligence"))
    story.append(Spacer(1, 10))

    ranking_table = bench.get("ranking_table") or []
    if ranking_table:
        target_row = next((r for r in ranking_table if r.get("is_target")), None)
        comp_rows  = [r for r in ranking_table if not r.get("is_target")][:3]

        def _fv(v, suffix=""):
            if v is None: return "—"
            if isinstance(v, float) and v == int(v): v = int(v)
            return f"{v}{suffix}"

        def _fi(v):
            if v is None: return "—"
            try: return f"{int(v):,}"
            except: return str(v)

        n_comps = len(comp_rows)
        headers = ["Dimension", biz_name[:18]] + [
            (r.get("name") or r.get("username") or f"Comp {i+1}")[:14]
            for i, r in enumerate(comp_rows)
        ]
        tgt = target_row or {}

        rows_data = [headers]
        dims = [
            ("Content Score", lambda r: _fv(r.get("content_score"), "/10")),
            ("Website Score",  lambda r: _fv(r.get("website_score"), "/10")),
            ("Google Rating",  lambda r: _fv(r.get("maps_rating"), "★")),
            ("Google Reviews", lambda r: _fi(r.get("maps_review_count"))),
            ("IG Followers",   lambda r: _fi(r.get("ig_followers"))),
            ("Rank",           lambda r: f"#{r.get('rank', '—')}"),
        ]
        for dim_label, fn in dims:
            row = [dim_label, fn(tgt)] + [fn(c) for c in comp_rows]
            rows_data.append(row)

        total_w = PAGE_W - 2 * MARGIN
        dim_w = 40 * mm
        rest_w = (total_w - dim_w) / (1 + n_comps)
        col_widths = [dim_w] + [rest_w] * (1 + n_comps)

        comp_tbl = Table(rows_data, colWidths=col_widths)
        comp_style = [
            # Header row — dark
            ("BACKGROUND", (0, 0), (-1, 0), HEADER_BG),
            ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            # Target column gold
            ("TEXTCOLOR", (1, 1), (1, -1), GOLD),
            ("FONTNAME", (1, 1), (1, -1), "Helvetica-Bold"),
            # Target header gold
            ("TEXTCOLOR", (1, 0), (1, 0), GOLD),
            # Body
            ("TEXTCOLOR", (0, 1), (0, -1), TEXT_MUTED),
            ("TEXTCOLOR", (2, 1), (-1, -1), TEXT_DARK),
            ("BACKGROUND", (0, 1), (-1, -1), WHITE),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, OFF_WHITE]),
            ("GRID", (0, 0), (-1, -1), 0.3, BORDER),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ]
        comp_tbl.setStyle(TableStyle(comp_style))
        story.append(comp_tbl)
        story.append(Spacer(1, 8))

        top_name = bench.get("top_competitor_name")
        gap      = bench.get("gap_to_top") or 0
        adv_dim  = bench.get("biggest_advantage_dimension")
        rank     = bench.get("target_rank")
        if top_name:
            gap_text = (
                f"{biz_name} currently ranks #{rank} in this local market. "
                f"The primary gap to {top_name} is in <b>{adv_dim}</b>." if adv_dim
                else f"{biz_name} currently ranks #{rank} in this local market."
            )
            story.append(Paragraph(gap_text, st["body"]))
    else:
        competitors = lead.get("competitors") or []
        if competitors:
            story.append(Paragraph(
                f"Competitors identified: {', '.join(c.get('business_name') or c.get('username','?') for c in competitors[:3])}",
                st["body"]
            ))
        else:
            story.append(Paragraph("Competitor data not yet collected for this lead.", st["muted"]))

    story.append(Spacer(1, 8))

    # ─────────────────────────────────────────────────────────────────────────
    # SECTION 6 — REVENUE GAP
    # ─────────────────────────────────────────────────────────────────────────
    story.append(_SectionBand("Section 6", "Revenue Gap"))
    story.append(Spacer(1, 10))

    rg = rev_gap
    story.append(Paragraph(
        f"Based on {rg['industry']} industry benchmarks and {biz_name}'s current social presence:",
        st["body"]
    ))
    story.append(Spacer(1, 6))

    rg_data = [
        ["Metric", "Current", "Industry Average", "Gap"],
        ["Engagement Rate",
         f"{rg['current_er']}%",
         f"{rg['industry_er']}%",
         f"{round(rg['industry_er'] - rg['current_er'], 1)}%"],
        ["Posts per Week",
         str(rg["posts_pw"]),
         "3.0",
         f"{rg['posting_gap']}"],
        ["Est. avg treatment value",
         f"£{rg['avg_value']}",
         "—",
         "—"],
        ["Estimated missed bookings/mo",
         "—",
         f"{rg['missed_bookings']} bookings",
         "—"],
    ]
    col_w4 = (PAGE_W - 2 * MARGIN) / 4
    rg_tbl = Table(rg_data, colWidths=[col_w4 * 1.4, col_w4 * 0.9, col_w4 * 1.1, col_w4 * 0.6])
    rg_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), GOLD),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TEXTCOLOR", (0, 1), (-1, -1), TEXT_DARK),
        ("BACKGROUND", (0, 1), (-1, -1), WHITE),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, OFF_WHITE]),
        ("GRID", (0, 0), (-1, -1), 0.3, BORDER),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(rg_tbl)
    story.append(Spacer(1, 8))

    story.append(Paragraph(
        f"<b>Estimated monthly revenue gap: £{rg['missed_revenue']:,}</b>",
        st["h3"]
    ))
    story.append(Paragraph(
        f"This estimate is based on {rg['industry']} industry conversion rates "
        f"(enquiry rate ~3%, close rate ~30%, average treatment value £{rg['avg_value']}). "
        f"The gap is driven primarily by below-average engagement and low posting frequency — "
        "both addressable through consistent, high-quality content production.",
        st["muted"]
    ))
    story.append(Spacer(1, 8))

    # ─────────────────────────────────────────────────────────────────────────
    # SECTION 7 — RECOMMENDED NEXT STEPS
    # ─────────────────────────────────────────────────────────────────────────
    story.append(_SectionBand("Section 7", "Recommended Next Steps"))
    story.append(Spacer(1, 10))

    # Derive 3 specific, actionable steps from the lead's actual data
    steps = []
    top_name = bench.get("top_competitor_name")
    adv_dim  = bench.get("biggest_advantage_dimension")

    # Step 1 — content production (always highest priority)
    posting_str = lead.get("posting_frequency") or "infrequently"
    steps.append(
        f"Increase production cadence from {posting_str} to a minimum of 3 posts per week using "
        "professionally lit and colour-graded video content. Even a single monthly shoot "
        "with a professional crew produces enough material for 12–16 posts."
    )

    # Step 2 — specific weakness fix or competitor gap
    if adv_dim and top_name:
        steps.append(
            f"Close the {adv_dim} gap with {top_name}. Their visual finish is the primary "
            "reason they outperform in local search and on social. A professional colour grade "
            "and consistent lighting setup across all video content would address this directly."
        )
    elif weaknesses and len(weaknesses) > 1:
        steps.append(
            f"Address the identified production gap: {weaknesses[1]}"
        )
    else:
        steps.append(
            "Develop a consistent visual identity across all content — same colour palette, "
            "lighting style, and on-screen branding — to build the premium aesthetic that "
            "justifies premium pricing."
        )

    # Step 3 — website or instagram specific
    if wa.get("website_score") and wa["website_score"] >= 7:
        steps.append(
            f"The website scores {wa['website_score']}/10 — technically strong. "
            "The next step is aligning Instagram content quality with the website's premium "
            "positioning. Patients who discover you on social and then visit the site "
            "should feel the same level of quality at both touchpoints."
        )
    else:
        web_w = (wa.get("top_weaknesses") or ["No clear CTA or contact info on the homepage"])[0]
        steps.append(
            f"Fix the primary website gap: {web_w}. "
            "A well-optimised website is the conversion layer beneath all social activity — "
            "it should be as strong as the content driving traffic to it."
        )

    for i, step in enumerate(steps[:3], 1):
        story.append(Paragraph(f"<b>{i}.</b>  {step}", st["bullet"]))
        story.append(Spacer(1, 6))

    story.append(Spacer(1, 12))

    # Footer note
    who_we_are = s.get("who_we_are") or (
        "Innovite is a content intelligence system used by Vidora Media to identify high-potential "
        "clients across Manchester. This report is the same evaluation run on every prospective client."
    )
    story.append(Paragraph(who_we_are, st["muted"]))

    # Build
    doc.build(story)
    return out_path
