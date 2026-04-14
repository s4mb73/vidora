"""
Video Frame Capture Module
---------------------------
Uses ADB to capture frames from videos playing in the Android emulator.
Works alongside the main analyser to give Claude real video content to evaluate.

Requirements:
    - ADB installed and in PATH (comes with Android Studio)
    - Emulator running and connected (check with: adb devices)
    - pip install opencv-python-headless

Usage (standalone test):
    python video_capture.py --duration 30 --output ./frames/creator1
"""

import subprocess
import time
import os
import argparse
from pathlib import Path
from datetime import datetime


def run_adb(args: list[str], timeout: int = 10) -> tuple[str, str]:
    """Run an ADB command and return stdout, stderr."""
    result = subprocess.run(
        ["adb"] + args,
        capture_output=True,
        text=True,
        timeout=timeout
    )
    return result.stdout.strip(), result.stderr.strip()


def check_adb_connection() -> bool:
    """Check if an emulator is connected via ADB."""
    stdout, _ = run_adb(["devices"])
    lines = [l for l in stdout.splitlines() if "emulator" in l and "device" in l]
    if not lines:
        print("  ERROR: No emulator found. Start your emulator and check 'adb devices'")
        return False
    print(f"  Connected: {lines[0].split()[0]}")
    return True


def capture_frame(output_path: Path, frame_index: int) -> Path | None:
    """Capture a single screenshot from the emulator screen."""
    filename = output_path / f"frame_{frame_index:04d}.png"
    device_path = f"/sdcard/frame_{frame_index:04d}.png"

    # Take screenshot on device
    stdout, stderr = run_adb(["shell", "screencap", "-p", device_path])
    if stderr and "error" in stderr.lower():
        print(f"  Screenshot error: {stderr}")
        return None

    # Pull to local machine
    stdout, stderr = run_adb(["pull", device_path, str(filename)], timeout=15)
    if stderr and "error" in stderr.lower():
        print(f"  Pull error: {stderr}")
        return None

    # Clean up device storage
    run_adb(["shell", "rm", device_path])

    return filename if filename.exists() else None


def capture_frames_during_playback(
    output_dir: Path,
    duration_seconds: int = 30,
    interval_seconds: float = 2.5,
    label: str = "video"
) -> list[Path]:
    """
    Capture frames at regular intervals while a video plays in the emulator.

    Call this AFTER you've started the video playing in the emulator.
    The function will capture frames for `duration_seconds` seconds.

    Args:
        output_dir: Where to save frame images
        duration_seconds: How long to capture (match to video length)
        interval_seconds: Time between captures (2-3s recommended)
        label: Label for progress output

    Returns:
        List of captured frame file paths
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    total_frames = int(duration_seconds / interval_seconds)
    captured = []

    print(f"\n  Capturing {label} — {total_frames} frames over {duration_seconds}s")
    print(f"  Interval: every {interval_seconds}s  |  Started: {datetime.now().strftime('%H:%M:%S')}")

    start_time = time.time()

    for i in range(total_frames):
        elapsed = time.time() - start_time
        remaining = duration_seconds - elapsed
        print(f"  Frame {i+1}/{total_frames}  [{elapsed:.1f}s elapsed, {remaining:.1f}s remaining]", end="\r")

        frame_path = capture_frame(output_dir, i)
        if frame_path:
            captured.append(frame_path)

        # Wait for next interval, accounting for capture time
        capture_time = time.time() - start_time - elapsed
        sleep_time = max(0, interval_seconds - capture_time)
        time.sleep(sleep_time)

    print(f"\n  Captured {len(captured)} frames successfully")
    return captured


def extract_key_frames(video_frames: list[Path], max_frames: int = 12) -> list[Path]:
    """
    Intelligently subsample frames to stay within Claude's image limit.
    Picks frames evenly spread across the video timeline.
    """
    if len(video_frames) <= max_frames:
        return video_frames

    step = len(video_frames) / max_frames
    selected = [video_frames[int(i * step)] for i in range(max_frames)]
    print(f"  Subsampled to {len(selected)} key frames from {len(video_frames)} total")
    return selected


def detect_scene_changes(frames: list[Path], threshold: float = 30.0) -> list[Path]:
    """
    Use OpenCV to detect significant scene changes and return only those frames.
    Falls back to even sampling if OpenCV unavailable.
    """
    try:
        import cv2
        import numpy as np

        key_frames = [frames[0]]  # Always include first frame
        prev_gray = None

        for frame_path in frames:
            img = cv2.imread(str(frame_path))
            if img is None:
                continue
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

            if prev_gray is not None:
                diff = cv2.absdiff(gray, prev_gray)
                score = np.mean(diff)
                if score > threshold:
                    key_frames.append(frame_path)

            prev_gray = gray

        # Always include last frame
        if frames[-1] not in key_frames:
            key_frames.append(frames[-1])

        print(f"  Scene detection: {len(key_frames)} key frames from {len(frames)} total")
        return key_frames

    except ImportError:
        print("  OpenCV not available — using even sampling instead")
        return extract_key_frames(frames, max_frames=12)


class VideoCapturePipeline:
    """
    High-level pipeline for capturing and preparing video frames for Claude.

    Typical usage with Appium:
        pipeline = VideoCapturePipeline(output_root=Path("./frames"))

        # Start video in Appium, then:
        frames = pipeline.capture(
            username="@creatorname",
            video_index=1,
            duration=30
        )

        # Pass frames to analyser
        encoded = pipeline.encode_frames(frames)
    """

    def __init__(self, output_root: Path = Path("./video_frames")):
        self.output_root = output_root

    def capture(
        self,
        username: str,
        video_index: int,
        duration: int = 30,
        interval: float = 2.5,
        smart_sampling: bool = True
    ) -> list[Path]:
        """
        Capture frames for one video.

        Call this after Appium has started playing the video.
        """
        safe_name = username.replace("@", "").replace("/", "_")
        output_dir = self.output_root / safe_name / f"video_{video_index:02d}"

        raw_frames = capture_frames_during_playback(
            output_dir=output_dir,
            duration_seconds=duration,
            interval_seconds=interval,
            label=f"{username} video {video_index}"
        )

        if not raw_frames:
            return []

        if smart_sampling:
            return detect_scene_changes(raw_frames)
        else:
            return extract_key_frames(raw_frames, max_frames=12)

    def encode_frames(self, frame_paths: list[Path]) -> list[dict]:
        """Encode frame images as base64 for Claude Vision API."""
        import base64
        encoded = []
        for path in frame_paths:
            if path.exists():
                with open(path, "rb") as f:
                    data = base64.standard_b64encode(f.read()).decode("utf-8")
                encoded.append({
                    "type": "image",
                    "source": {"type": "base64", "media_type": "image/png", "data": data}
                })
        return encoded


def main():
    parser = argparse.ArgumentParser(description="Capture video frames from Android emulator")
    parser.add_argument("--duration", type=int, default=30, help="Video duration in seconds")
    parser.add_argument("--interval", type=float, default=2.5, help="Seconds between frames")
    parser.add_argument("--output", default="./frames/test", help="Output directory for frames")
    parser.add_argument("--smart", action="store_true", help="Use scene-change detection")
    args = parser.parse_args()

    print("\nChecking ADB connection...")
    if not check_adb_connection():
        return

    output_dir = Path(args.output)
    print(f"\nStarting capture — play your video in the emulator NOW")
    print(f"Capturing for {args.duration} seconds...")

    frames = capture_frames_during_playback(
        output_dir=output_dir,
        duration_seconds=args.duration,
        interval_seconds=args.interval
    )

    if args.smart and frames:
        frames = detect_scene_changes(frames)

    print(f"\nDone. {len(frames)} frames saved to {output_dir}")


if __name__ == "__main__":
    main()
