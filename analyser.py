"""
Instagram Content Quality Analyser — with Video Support
---------------------------------------------------------
Analyses both photo posts and video content (Reels/Stories).
Videos are evaluated from captured frames — see video_capture.py.

Usage:
    # Photos only
    python analyser.py --folder ./screenshots/@creator --username @creator

    # Photos + video frames
    python analyser.py --folder ./screenshots/@creator --username @creator \
                       --video-frames ./video_frames/@creator

    # Export to CSV
    python analyser.py --folder ./screenshots/@creator --username @creator \
                       --video-frames ./video_frames/@creator --output leads.csv
"""

import anthropic
import base64
import json
import csv
import argparse
import os
import sys
from pathlib import Path
from datetime import datetime


SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}

PHOTO_PROMPT = """You are an expert media production consultant evaluating an Instagram creator's photo content on behalf of a professional media production company.

Analyse these {n} photo screenshots from @{username}'s Instagram feed.

Score each dimension 1-10 (10 = broadcast/editorial quality, 1 = extremely poor):

1. LIGHTING QUALITY — Natural vs artificial, consistency, shadows, exposure
2. COMPOSITION — Framing, rule of thirds, background clutter, headroom
3. EDITING & COLOUR — Grading consistency, intentionality, skin tones, white balance
4. BRAND CONSISTENCY — Coherent visual identity, palette, style, tone across posts
5. OVERALL PHOTO PRODUCTION — Holistic quality as a media professional would judge

Identify the TOP 3 SPECIFIC WEAKNESSES — be precise. Instead of "bad lighting" say "harsh overhead phone torch creates raccoon-eye shadows in every close-up selfie."

Respond ONLY in this exact JSON:
{
  "photo_scores": {
    "lighting": <1-10>,
    "composition": <1-10>,
    "editing_colour": <1-10>,
    "brand_consistency": <1-10>,
    "overall_photo": <1-10>
  },
  "photo_weaknesses": ["<specific 1>", "<specific 2>", "<specific 3>"],
  "photo_strengths": ["<strength 1>", "<strength 2>"],
  "photo_notes": "<any relevant observations>"
}"""

VIDEO_PROMPT = """You are an expert video production consultant evaluating an Instagram creator's video content quality from captured frames.

These {n} frames were extracted at regular intervals while a Reel/video played. Treat them as a sequence showing the video over time — analyse the progression, not just individual frames.

Score each dimension 1-10:

1. CAMERA STABILITY — Handheld shake, smooth movement, tripod vs handheld
2. LIGHTING CONSISTENCY — Does lighting hold across the video or fluctuate badly?
3. PRODUCTION SETUP — Evidence of proper gear: external mic, ring light, backdrop, camera vs phone
4. EDITING SOPHISTICATION — Jump cuts, transitions, text overlays, graphics, pacing quality
5. FRAMING & DIRECTION — Shot variety, talking head vs dynamic, b-roll usage
6. OVERALL VIDEO PRODUCTION — Holistic score

Identify TOP 3 SPECIFIC VIDEO WEAKNESSES — be precise and technical.

Respond ONLY in this exact JSON:
{
  "video_scores": {
    "stability": <1-10>,
    "lighting_consistency": <1-10>,
    "production_setup": <1-10>,
    "editing_sophistication": <1-10>,
    "framing_direction": <1-10>,
    "overall_video": <1-10>
  },
  "video_weaknesses": ["<specific 1>", "<specific 2>", "<specific 3>"],
  "video_strengths": ["<strength 1>", "<strength 2>"],
  "production_setup_observed": "<describe what gear/setup is visible in frames>",
  "upgrade_potential": "<high/medium/low>",
  "video_notes": "<any relevant observations>"
}"""

PITCH_PROMPT = """You are a senior business development manager at a media production company.

Based on this creator analysis, write a SHORT personalised outreach pitch (3-4 sentences max).

Creator: @{username}
Photo weaknesses: {photo_weaknesses}
Video weaknesses: {video_weaknesses}
Production setup observed: {production_setup}
Upgrade potential: {upgrade_potential}

Rules:
- Reference 1-2 SPECIFIC issues you observed — make it clear you've watched their content
- Frame weaknesses as opportunities, not criticism
- Sound human, not corporate
- End with a soft call to action
- Do NOT mention AI analysis

Respond ONLY in JSON:
{{
  "personalised_pitch": "<3-4 sentence pitch>",
  "lead_grade": "<A/B/C/D — A=clear need + good audience, D=already strong or tiny audience>",
  "overall_score": <combined average 1-10, 1 decimal>,
  "priority_flag": <true if grade A or B>,
  "sales_notes": "<internal notes for your sales team>"
}}"""


def load_images_from_folder(folder: Path) -> list[dict]:
    images = []
    for f in sorted(folder.iterdir()):
        if f.suffix.lower() in SUPPORTED_EXTENSIONS:
            ext = f.suffix.lower().replace(".", "")
            media_type = f"image/{'jpeg' if ext in ('jpg', 'jpeg') else ext}"
            with open(f, "rb") as img_file:
                data = base64.standard_b64encode(img_file.read()).decode("utf-8")
            images.append({"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}})
    return images


def load_video_frames(video_dir: Path, max_frames: int = 12) -> list[dict]:
    frame_files = sorted(video_dir.rglob("frame_*.png"))
    if not frame_files:
        frame_files = sorted(video_dir.rglob("*.png"))
    if not frame_files:
        return []

    if len(frame_files) > max_frames:
        step = len(frame_files) / max_frames
        frame_files = [frame_files[int(i * step)] for i in range(max_frames)]

    frames = []
    for f in frame_files:
        with open(f, "rb") as img_file:
            data = base64.standard_b64encode(img_file.read()).decode("utf-8")
        frames.append({"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": data}})
    return frames


def parse_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        parts = text.split("```")
        text = parts[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text.strip())


def analyse_photos(username: str, images: list[dict], client: anthropic.Anthropic) -> dict:
    print(f"  Analysing {len(images)} photos...")
    content = images + [{"type": "text", "text": PHOTO_PROMPT.format(n=len(images), username=username)}]
    response = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=1000,
        messages=[{"role": "user", "content": content}]
    )
    return parse_json(response.content[0].text)


def analyse_video_frames(frames: list[dict], client: anthropic.Anthropic) -> dict:
    print(f"  Analysing {len(frames)} video frames...")
    content = frames + [{"type": "text", "text": VIDEO_PROMPT.format(n=len(frames))}]
    response = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=1000,
        messages=[{"role": "user", "content": content}]
    )
    return parse_json(response.content[0].text)


def generate_pitch(username: str, photo_result: dict, video_result: dict | None, client: anthropic.Anthropic) -> dict:
    print(f"  Generating personalised pitch...")
    pw = photo_result.get("photo_weaknesses", [])
    vw = video_result.get("video_weaknesses", []) if video_result else []
    setup = video_result.get("production_setup_observed", "not assessed") if video_result else "not assessed"
    potential = video_result.get("upgrade_potential", "unknown") if video_result else "unknown"

    prompt = PITCH_PROMPT.format(
        username=username,
        photo_weaknesses=", ".join(pw),
        video_weaknesses=", ".join(vw) if vw else "not assessed",
        production_setup=setup,
        upgrade_potential=potential
    )
    response = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=600,
        messages=[{"role": "user", "content": prompt}]
    )
    return parse_json(response.content[0].text)


def analyse_creator(
    username: str,
    photo_folder: Path,
    client: anthropic.Anthropic,
    video_frames_dir: Path | None = None
) -> dict | None:
    photo_images = load_images_from_folder(photo_folder)
    if not photo_images:
        print(f"  No photos found in {photo_folder}")
        return None

    video_frames = []
    if video_frames_dir and video_frames_dir.exists():
        video_frames = load_video_frames(video_frames_dir)
        print(f"  Found {len(video_frames)} video frames")

    photo_result = analyse_photos(username, photo_images, client)
    video_result = analyse_video_frames(video_frames, client) if video_frames else None
    pitch_result = generate_pitch(username, photo_result, video_result, client)

    return {
        "username": username,
        "analysed_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "photo_count": len(photo_images),
        "video_frames_count": len(video_frames),
        "has_video_analysis": video_result is not None,
        **photo_result,
        **(video_result or {}),
        **pitch_result
    }


def print_report(r: dict):
    grade_colours = {"A": "\033[92m", "B": "\033[94m", "C": "\033[93m", "D": "\033[91m"}
    reset = "\033[0m"
    grade = r.get("lead_grade", "?")
    colour = grade_colours.get(grade, "")

    print(f"\n{'='*62}")
    print(f"  LEAD REPORT — {r['username']}")
    print(f"  {r['analysed_at']}  |  {r['photo_count']} photos  |  {r['video_frames_count']} video frames")
    print(f"{'='*62}")
    print(f"\n  GRADE: {colour}{grade}{reset}   Score: {r.get('overall_score','?')}/10   Priority: {'YES' if r.get('priority_flag') else 'No'}")

    print(f"\n  PHOTO SCORES:")
    for key, label in [("lighting","Lighting"),("composition","Composition"),("editing_colour","Editing & colour"),("brand_consistency","Brand consistency"),("overall_photo","Overall photo")]:
        s = r.get("photo_scores", {}).get(key, 0)
        print(f"    {label:<22} {'█'*s}{'░'*(10-s)}  {s}/10")

    if r.get("has_video_analysis"):
        print(f"\n  VIDEO SCORES:")
        for key, label in [("stability","Stability"),("lighting_consistency","Lighting"),("production_setup","Setup"),("editing_sophistication","Editing"),("framing_direction","Framing"),("overall_video","Overall video")]:
            s = r.get("video_scores", {}).get(key, 0)
            print(f"    {label:<22} {'█'*s}{'░'*(10-s)}  {s}/10")
        print(f"\n  SETUP OBSERVED:    {r.get('production_setup_observed','—')}")
        print(f"  UPGRADE POTENTIAL: {r.get('upgrade_potential','—').upper()}")

    print(f"\n  PHOTO WEAKNESSES:")
    for i, w in enumerate(r.get("photo_weaknesses", []), 1):
        print(f"    {i}. {w}")

    if r.get("has_video_analysis"):
        print(f"\n  VIDEO WEAKNESSES:")
        for i, w in enumerate(r.get("video_weaknesses", []), 1):
            print(f"    {i}. {w}")

    print(f"\n  PERSONALISED PITCH:")
    words = r.get("personalised_pitch", "").split()
    line = "    "
    for word in words:
        if len(line) + len(word) > 60:
            print(line)
            line = "    " + word + " "
        else:
            line += word + " "
    if line.strip():
        print(line)

    if r.get("sales_notes"):
        print(f"\n  SALES NOTES: {r['sales_notes']}")
    print(f"\n{'='*62}\n")


def save_to_csv(results: list[dict], output_path: str):
    if not results:
        return
    fieldnames = [
        "username","analysed_at","lead_grade","overall_score","priority_flag",
        "photo_count","video_frames_count","has_video_analysis",
        "photo_lighting","photo_composition","photo_editing","photo_brand","photo_overall",
        "video_stability","video_lighting","video_setup","video_editing","video_framing","video_overall",
        "production_setup_observed","upgrade_potential",
        "photo_weakness_1","photo_weakness_2","photo_weakness_3",
        "video_weakness_1","video_weakness_2","video_weakness_3",
        "personalised_pitch","sales_notes"
    ]
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in results:
            ps = r.get("photo_scores", {})
            vs = r.get("video_scores", {})
            pw = r.get("photo_weaknesses", [])
            vw = r.get("video_weaknesses", [])
            writer.writerow({
                "username": r.get("username"),
                "analysed_at": r.get("analysed_at"),
                "lead_grade": r.get("lead_grade"),
                "overall_score": r.get("overall_score"),
                "priority_flag": r.get("priority_flag"),
                "photo_count": r.get("photo_count"),
                "video_frames_count": r.get("video_frames_count"),
                "has_video_analysis": r.get("has_video_analysis"),
                "photo_lighting": ps.get("lighting"),
                "photo_composition": ps.get("composition"),
                "photo_editing": ps.get("editing_colour"),
                "photo_brand": ps.get("brand_consistency"),
                "photo_overall": ps.get("overall_photo"),
                "video_stability": vs.get("stability"),
                "video_lighting": vs.get("lighting_consistency"),
                "video_setup": vs.get("production_setup"),
                "video_editing": vs.get("editing_sophistication"),
                "video_framing": vs.get("framing_direction"),
                "video_overall": vs.get("overall_video"),
                "production_setup_observed": r.get("production_setup_observed",""),
                "upgrade_potential": r.get("upgrade_potential",""),
                "photo_weakness_1": pw[0] if len(pw) > 0 else "",
                "photo_weakness_2": pw[1] if len(pw) > 1 else "",
                "photo_weakness_3": pw[2] if len(pw) > 2 else "",
                "video_weakness_1": vw[0] if len(vw) > 0 else "",
                "video_weakness_2": vw[1] if len(vw) > 1 else "",
                "video_weakness_3": vw[2] if len(vw) > 2 else "",
                "personalised_pitch": r.get("personalised_pitch"),
                "sales_notes": r.get("sales_notes","")
            })
    print(f"  Exported {len(results)} lead(s) to {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Analyse Instagram creator content — photos and video")
    parser.add_argument("--folder", required=True, help="Folder with photo screenshots")
    parser.add_argument("--username", required=True, help="e.g. @creatorname")
    parser.add_argument("--video-frames", default=None, help="Folder with captured video frames")
    parser.add_argument("--output", default=None, help="CSV output path")
    parser.add_argument("--api-key", default=None)
    args = parser.parse_args()

    api_key = args.api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: Set ANTHROPIC_API_KEY or pass --api-key")
        sys.exit(1)

    photo_folder = Path(args.folder)
    if not photo_folder.exists():
        print(f"ERROR: Folder not found: {photo_folder}")
        sys.exit(1)

    video_frames_dir = Path(args.video_frames) if args.video_frames else None
    client = anthropic.Anthropic(api_key=api_key)

    print(f"\nAnalysing {args.username}...")
    result = analyse_creator(args.username, photo_folder, client, video_frames_dir)

    if result:
        print_report(result)
        if args.output:
            save_to_csv([result], args.output)
    else:
        print("No content found to analyse.")


if __name__ == "__main__":
    main()
