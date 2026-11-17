#!/usr/bin/env python3
"""Write dashboard/data.js from the tracker so dashboard/index.html works from disk (no server).

Usage: build_dashboard.py [--data data/applications.json]
       build_dashboard.py --example   (rebuilds dashboard/example-data.js from examples/)
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import HOME, SKILL_DIR  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default=str(HOME / "data" / "applications.json"))
    ap.add_argument("--example", action="store_true")
    a = ap.parse_args()
    if a.example:
        src, out, var = SKILL_DIR / "examples" / "applications.example.json", SKILL_DIR / "dashboard" / "example-data.js", "EXAMPLE_APPLICATIONS"
    else:
        src, out, var = Path(a.data).expanduser(), SKILL_DIR / "dashboard" / "data.js", "APPLICATIONS"
    rows = json.loads(src.read_text(encoding="utf-8")) if src.exists() else []
    if not a.example:  # absolute folder path so the table can link to it (never done for the committed example)
        for r in rows:
            if r.get("resume_path"):
                r["_resume_dir"] = str(Path(r["resume_path"]).expanduser().parent)
    payload = json.dumps(rows, ensure_ascii=False, indent=1).replace("</", "<\\/")
    out.write_text(f"// Generated {datetime.now().isoformat(timespec='seconds')} by build_dashboard.py. Do not edit.\n"
                   f"window.{var} = {payload};\n", encoding="utf-8")
    print(f"wrote {len(rows)} application(s) to {out}")
    print(f"open: file://{(SKILL_DIR / 'dashboard' / 'index.html').resolve()}")


if __name__ == "__main__":
    main()
