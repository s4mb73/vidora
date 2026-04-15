"""
Populate the database with realistic-looking demo leads so you can click
around the dashboard before running the real pipeline.

Usage:
    python -m dashboard.seed
"""

from datetime import datetime, timedelta
from pathlib import Path

from . import db
from .pdf_audit import generate_audit

DEMO_LEADS = [
    {
        "username": "northernbarbershop",
        "scores": {"lighting": 3, "composition": 4, "editing_colour": 3,
                   "brand_consistency": 4, "content_production": 3, "overall": 3},
        "overall_score": 3.3, "lead_grade": "A", "priority_flag": True,
        "top_weaknesses": [
            "Single ceiling bulb creates harsh top-down shadows on every chair shot",
            "Phone-camera images shot vertically with cluttered mirror backgrounds",
            "No consistent colour grade - half the feed is warm, half is cold flash",
        ],
        "strengths": ["Strong client before/after content", "Consistent posting cadence"],
        "personalised_pitch": (
            "Love the craft on display - the fades and line-ups speak for themselves. "
            "The reason your reach plateaus is purely lighting: a softbox and a clean "
            "backdrop would turn these posts into portfolio-grade work in an afternoon. "
            "Happy to pop in and show you what a one-day shoot could look like?"
        ),
        "upgrade_potential": "high", "estimated_audience_size": "small",
        "sales_notes": "Ready buyer - book list visible in bio, active stories.",
        "business_intent_score": 9, "business_type": "barbershop",
        "location_match": True, "screenshot_count": 7,
        "location_signals": ["Manchester in bio", "NQ location tag"],
        "selling_signals": ["booking link", "DM to book", "price list"],
    },
    {
        "username": "maya.pt.manchester",
        "scores": {"lighting": 4, "composition": 5, "editing_colour": 4,
                   "brand_consistency": 5, "content_production": 4, "overall": 4},
        "overall_score": 4.3, "lead_grade": "A", "priority_flag": True,
        "top_weaknesses": [
            "Gym mirror reflections and harsh overhead fluorescents in every workout clip",
            "Captions do the storytelling but reels have no supered text or pace",
            "No defined brand colours - each post is visually disconnected",
        ],
        "strengths": ["Confident on-camera delivery", "Clear niche (postpartum PT)"],
        "personalised_pitch": (
            "Your client transformations tell a brilliant story - the weak link is the "
            "gym itself showing up as visual noise. A one-hour cinematic shoot each "
            "month would give you assets that actually match the quality of your "
            "coaching. Want to see how other PTs have used us to 3x enquiries?"
        ),
        "upgrade_potential": "high", "estimated_audience_size": "mid",
        "sales_notes": "Premium coach - open to monthly retainers.",
        "business_intent_score": 8, "business_type": "personal trainer",
        "location_match": True, "screenshot_count": 7,
        "location_signals": ["Manchester UK in bio"],
        "selling_signals": ["coaching enquiries link", "waitlist CTA"],
    },
    {
        "username": "the.hollow.salon",
        "scores": {"lighting": 5, "composition": 6, "editing_colour": 5,
                   "brand_consistency": 6, "content_production": 5, "overall": 5},
        "overall_score": 5.3, "lead_grade": "B", "priority_flag": True,
        "top_weaknesses": [
            "Inconsistent white balance - warm window light vs cold overhead LEDs",
            "Hair-transformation posts are stills only, no motion or reel",
            "Feed grid has no rhythm - client shots mixed with memes",
        ],
        "strengths": ["Great stylist talent", "Recognisable salon interior"],
        "personalised_pitch": (
            "Your cuts are genuinely editorial but the phone snaps don't do them "
            "justice. A short monthly shoot in your salon would give you a tight "
            "content bank and unlock reels that actually pop. Worth a 15-minute "
            "chat this week?"
        ),
        "upgrade_potential": "medium", "estimated_audience_size": "mid",
        "sales_notes": "Owner-led - decision maker visible.",
        "business_intent_score": 7, "business_type": "hair salon",
        "location_match": True, "screenshot_count": 6,
        "location_signals": ["Ancoats tag", "M4 Manchester"],
        "selling_signals": ["book online", "services in bio"],
    },
    {
        "username": "brick.coffee.mcr",
        "scores": {"lighting": 5, "composition": 5, "editing_colour": 5,
                   "brand_consistency": 7, "content_production": 5, "overall": 5},
        "overall_score": 5.3, "lead_grade": "B", "priority_flag": True,
        "top_weaknesses": [
            "Top-down latte shots on same wood counter - zero variation",
            "No people or story in the feed, feels like a product catalogue",
            "Reels cut awkwardly without music sync",
        ],
        "strengths": ["Strong brand palette", "Consistent grid aesthetic"],
        "personalised_pitch": (
            "The brand work you've done is already half the battle - the gap is story. "
            "Your regulars, baristas and the neighbourhood are the hook, not more latte "
            "art. A two-hour documentary-style shoot would give you reels that travel. "
            "Curious to see how we'd frame it?"
        ),
        "upgrade_potential": "medium", "estimated_audience_size": "small",
        "sales_notes": "Independent cafe, likely tight budget - lead with a pilot.",
        "business_intent_score": 6, "business_type": "coffee shop",
        "location_match": True, "screenshot_count": 7,
        "location_signals": ["Manchester city centre", "#mcrfood"],
        "selling_signals": ["online shop link"],
    },
    {
        "username": "quinn.tattoo.studio",
        "scores": {"lighting": 4, "composition": 5, "editing_colour": 4,
                   "brand_consistency": 5, "content_production": 4, "overall": 4},
        "overall_score": 4.3, "lead_grade": "B", "priority_flag": True,
        "top_weaknesses": [
            "Healed-tattoo shots are washed out by salon LEDs",
            "No portfolio posts of the artist at work - pure outcomes",
            "Text overlays cover key parts of each design",
        ],
        "strengths": ["Strong linework artistry", "Clear booking funnel"],
        "personalised_pitch": (
            "The artistry is clearly there - the presentation just doesn't match it yet. "
            "A tighter lighting set and a few behind-the-process reels would turn each "
            "booking into 2-3 pieces of content. Want me to mock up a shot list?"
        ),
        "upgrade_potential": "high", "estimated_audience_size": "small",
        "sales_notes": "Books out months ahead - premium positioning.",
        "business_intent_score": 8, "business_type": "tattoo studio",
        "location_match": True, "screenshot_count": 6,
        "location_signals": ["NQ Manchester"],
        "selling_signals": ["waitlist form", "email in bio"],
    },
    {
        "username": "velvetline.interiors",
        "scores": {"lighting": 6, "composition": 7, "editing_colour": 7,
                   "brand_consistency": 7, "content_production": 7, "overall": 7},
        "overall_score": 6.8, "lead_grade": "C", "priority_flag": False,
        "top_weaknesses": [
            "Staged rooms look great but reels have no movement or depth",
            "No founder voice - the brand feels faceless",
            "Gallery-style feed with no story arcs between projects",
        ],
        "strengths": ["Strong interior photography", "Cohesive brand palette"],
        "personalised_pitch": (
            "Your stills already do heavy lifting - the conversion gap is video. "
            "Short founder-led walkthroughs of each project would create the trust "
            "signal buyers need. Happy to suggest a simple monthly cadence if useful."
        ),
        "upgrade_potential": "medium", "estimated_audience_size": "mid",
        "sales_notes": "Established brand - retainer candidate.",
        "business_intent_score": 6, "business_type": "interior design",
        "location_match": True, "screenshot_count": 7,
        "location_signals": ["Manchester showroom"],
        "selling_signals": ["portfolio link", "consultation form"],
    },
    {
        "username": "oak.barbers.didsbury",
        "scores": {"lighting": 5, "composition": 5, "editing_colour": 4,
                   "brand_consistency": 5, "content_production": 4, "overall": 5},
        "overall_score": 4.7, "lead_grade": "B", "priority_flag": True,
        "top_weaknesses": [
            "Natural window light gets blown out in half the shots",
            "Walk-in clients shot from awkward overhead angle",
            "Logo inconsistently placed on post overlays",
        ],
        "strengths": ["Warm personality in captions", "Loyal repeat clientele"],
        "personalised_pitch": (
            "Didsbury's a tight community and you're clearly well-known - the feed "
            "just doesn't show that warmth yet. A story-led half-day shoot would "
            "change the perception immediately. Worth a chat over a coffee?"
        ),
        "upgrade_potential": "medium", "estimated_audience_size": "small",
        "sales_notes": "Hot lead - recently hired a second barber.",
        "business_intent_score": 8, "business_type": "barbershop",
        "location_match": True, "screenshot_count": 6,
        "location_signals": ["Didsbury Manchester"],
        "selling_signals": ["book via Fresha", "phone in bio"],
    },
    {
        "username": "random.meme.acct",
        "scores": {"lighting": 2, "composition": 3, "editing_colour": 2,
                   "brand_consistency": 2, "content_production": 2, "overall": 2},
        "overall_score": 2.2, "lead_grade": "D", "priority_flag": False,
        "top_weaknesses": [
            "Reposted content only, no original production",
            "No business signals whatsoever",
            "No location indication",
        ],
        "strengths": [],
        "personalised_pitch": "Not a fit - personal meme account with no business intent.",
        "upgrade_potential": "low", "estimated_audience_size": "small",
        "sales_notes": "Skip.", "business_intent_score": 1,
        "business_type": "unknown", "location_match": False,
        "screenshot_count": 3,
        "location_signals": [], "selling_signals": [],
    },
]


def run():
    db.init_db()
    audits_dir = Path(__file__).resolve().parent / "data" / "audits"
    audits_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now()
    for i, result in enumerate(DEMO_LEADS):
        analysed_at = (now - timedelta(hours=i * 3)).strftime("%Y-%m-%d %H:%M")
        result["analysed_at"] = analysed_at
        lead_id = db.upsert_lead_from_pipeline(result)
        lead = db.get_lead(lead_id)
        if lead is None:
            continue
        try:
            path = generate_audit(lead, audits_dir)
            db.update_lead_fields(lead_id, {"audit_path": str(path)})
        except Exception as exc:  # noqa: BLE001
            print(f"  PDF failed for @{lead['username']}: {exc}")
        print(f"  seeded @{lead['username']} (grade {lead['lead_grade']})")
    print(f"\nSeed complete: {len(DEMO_LEADS)} leads.")


if __name__ == "__main__":
    run()
