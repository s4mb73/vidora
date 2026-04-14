"""
Batch Analyser — run multiple creators in one go.

Folder structure expected:
    screenshots/
        @creator1/
            post1.jpg
            post2.jpg
        @creator2/
            post1.png
            ...

Usage:
    python batch.py --root ./screenshots --output leads.csv
"""

import anthropic
import argparse
import os
import sys
from pathlib import Path
from analyser import analyse_creator, print_report, save_to_csv


def main():
    parser = argparse.ArgumentParser(description="Batch analyse multiple Instagram creators")
    parser.add_argument("--root", required=True, help="Root folder containing one subfolder per creator")
    parser.add_argument("--output", default="leads.csv", help="CSV output path")
    parser.add_argument("--api-key", default=None, help="Anthropic API key")
    parser.add_argument("--grade-filter", default=None, help="Only export leads of this grade or above (A/B/C)")
    args = parser.parse_args()

    api_key = args.api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: No API key found. Set ANTHROPIC_API_KEY or pass --api-key")
        sys.exit(1)

    root = Path(args.root)
    if not root.exists():
        print(f"ERROR: Root folder not found: {root}")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)

    creator_folders = [f for f in sorted(root.iterdir()) if f.is_dir()]
    if not creator_folders:
        print("No creator subfolders found.")
        sys.exit(1)

    print(f"\nFound {len(creator_folders)} creator(s) to analyse.\n")

    results = []
    grade_order = {"A": 0, "B": 1, "C": 2, "D": 3}
    filter_grade = args.grade_filter.upper() if args.grade_filter else None

    for folder in creator_folders:
        username = folder.name
        print(f"Processing {username}...")
        try:
            result = analyse_creator(username, folder, client)
            if result:
                print_report(result)
                if filter_grade is None or grade_order.get(result.get("lead_grade", "D"), 3) <= grade_order.get(filter_grade, 3):
                    results.append(result)
        except Exception as e:
            print(f"  ERROR analysing {username}: {e}")

    if results:
        save_to_csv(results, args.output)
        priority = [r for r in results if r.get("priority_flag")]
        print(f"\nSummary: {len(results)} leads exported | {len(priority)} high priority (A/B grade)")
    else:
        print("\nNo results to export.")


if __name__ == "__main__":
    main()
