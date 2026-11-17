#!/usr/bin/env python3
"""Copy a passed resume (PDF + .tex + score.json + posting.json) into the per-role archive.

Usage: archive.py --work work/<slug> --company "Company" --title "Job Title" [--profile profile.json]
Destination: <paths.archive>/<Company>/<Job Title>/resume/   ("/" in names becomes "-")
Refuses to overwrite a folder that already holds a resume (that resume was sent somewhere).
Refuses to archive unless score.json says pass.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import archive_dir, die, load_profile  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", required=True)
    ap.add_argument("--company", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--profile")
    ap.add_argument("--allow-existing", action="store_true",
                    help="only when the user confirms the earlier resume in this folder was never submitted")
    a = ap.parse_args()
    profile = load_profile(a.profile)
    name = profile["identity"]["resume_file_name"]
    work = Path(a.work).expanduser()
    pdf, tex, score = work / f"{name}.pdf", work / f"{name}.tex", work / "score.json"
    for f in (pdf, tex, score):
        if not f.exists():
            die(f"missing {f}")
    if not json.loads(score.read_text()).get("pass"):
        die("score.json is below threshold; not archiving")
    dest = archive_dir(profile, a.company, a.title)
    if (dest / pdf.name).exists() and not a.allow_existing:
        die(f"{dest} already has a resume. Same role applied before? Check the tracker.", 3)
    dest.mkdir(parents=True, exist_ok=True)
    for f in (pdf, tex, score, work / "posting.json", work / "audit.json"):
        if f.exists():
            shutil.copy2(f, dest / f.name)
    print(f"saved: {dest / pdf.name}")


if __name__ == "__main__":
    main()
