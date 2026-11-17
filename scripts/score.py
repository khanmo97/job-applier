#!/usr/bin/env python3
"""Deterministic ATS-match and fit scores for a tailored resume.

These are the tool's own estimates with a fixed formula, NOT a real ATS result.

Inputs
  --pdf resume.pdf       (text extracted with `pdftotext -layout`), or --text resume.txt
  --posting posting.json with:
      terms:     [{"term": "React", "weight": 2, "pattern": "optional regex"}]
                 weight 2 = from the required section, 1 = stack / nice-to-have
      required:  [{"text": "...", "status": "met|partly|missing", "evidence": ["fact-or-role-id"]}]
      preferred: same shape as required
      level_fit: {"status": "met|partly|missing", "note": "...", "evidence": [...]}
  --profile profile.json  (recommended) checks evidence ids exist and sorts missing terms into
                          "confirmed but not on resume", "denied", and "unknown: ask the user".

Rules
  ATS  = matched weight / total weight * 100
  Fit  = required 50 (met 1, partly 0.5, missing 0)
       + keyword coverage 25 (ATS * 0.25)
       + preferred 15 (same credit; full 15 if the posting lists none)
       + level and years 10 (same credit)
  A "met" with no valid evidence id counts as "partly", so the score can't rest on an unbacked claim.

Writes score.json (inputs + results) next to the resume. Exit 0 if both >= threshold, 2 if not.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import load_json, load_profile  # noqa: E402

CREDIT = {"met": 1.0, "partly": 0.5, "missing": 0.0}


def default_pattern(term: str) -> str:
    esc = re.escape(term).replace(r"\ ", r"[\s-]+")
    return rf"(?<![A-Za-z0-9]){esc}(?![A-Za-z0-9])"


def resume_text(pdf: str | None, text: str | None) -> str:
    if text:
        return Path(text).read_text(encoding="utf-8")
    r = subprocess.run(["pdftotext", "-layout", pdf, "-"], capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"error: pdftotext failed: {r.stderr.strip()}")
    return r.stdout


def known_ids(profile: dict | None) -> set[str] | None:
    if profile is None:
        return None
    ids = set()
    for kind in ("experience", "projects", "optional_roles"):
        for ent in profile.get(kind, []):
            ids.add(ent["id"])
            ids.update(f["id"] for f in ent.get("facts", []))
    ids.update(e["id"] for e in profile.get("education", []))
    return ids


def grade(items: list[dict], ids: set[str] | None, notes: list[str], label: str) -> tuple[float, list[dict]]:
    if not items:
        return 1.0, []
    out, total = [], 0.0
    for it in items:
        status = it.get("status", "missing")
        if status not in CREDIT:
            sys.exit(f"error: {label} '{it.get('text')}' has status '{status}' (use met/partly/missing)")
        ev = it.get("evidence", []) or []
        if ids is not None:
            bad = [e for e in ev if e not in ids]
            if bad:
                notes.append(f"{label} '{it.get('text')}': unknown evidence ids {bad}")
            ev = [e for e in ev if e in ids]
        counted = status
        if status == "met" and not ev:
            counted = "partly"
            notes.append(f"{label} '{it.get('text')}': marked met without evidence; counted as partly")
        total += CREDIT[counted]
        out.append({**it, "counted_as": counted})
    return total / len(items), out


def classify_missing(term: str, profile: dict | None) -> str:
    if profile is None:
        return "unknown"
    t = term.lower()
    for d in profile.get("skills_denied", []):
        if d.lower() == t:
            return "denied"
    for sk in profile.get("skills_confirmed", []):
        sk = {"name": sk} if isinstance(sk, str) else sk
        if t in [n.lower() for n in [sk["name"], *sk.get("aliases", [])]]:
            return "confirmed_not_on_resume"
    return "unknown"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--pdf")
    src.add_argument("--text")
    ap.add_argument("--posting", required=True)
    ap.add_argument("--profile")
    ap.add_argument("--out", help="default: score.json next to the resume")
    ap.add_argument("--threshold", type=float, default=80)
    a = ap.parse_args()

    posting = load_json(a.posting)
    profile = load_profile(a.profile) if a.profile else None
    ids = known_ids(profile)
    text = resume_text(a.pdf, a.text)
    notes: list[str] = []

    terms_out, got, total = [], 0.0, 0.0
    for t in posting.get("terms", []):
        w = float(t.get("weight", 1))
        pat = t.get("pattern") or default_pattern(t["term"])
        hit = re.search(pat, text, re.IGNORECASE) is not None
        total += w
        got += w if hit else 0
        terms_out.append({"term": t["term"], "weight": w, "pattern": pat, "matched": hit})
    if total == 0:
        sys.exit("error: posting has no terms")
    ats = round(got / total * 100, 1)

    req, req_items = grade(posting.get("required", []), ids, notes, "required")
    pref, pref_items = grade(posting.get("preferred", []), ids, notes, "preferred")
    lvl_in = posting.get("level_fit")
    lvl, lvl_items = grade([lvl_in] if lvl_in else [], ids, notes, "level")
    if not posting.get("required"):
        notes.append("posting has no required qualifications listed; required credit set to full")
    fit = round(50 * req + 0.25 * ats + 15 * pref + 10 * lvl, 1)

    missing = [t for t in terms_out if not t["matched"]]
    for m in missing:
        m["gap"] = classify_missing(m["term"], profile)
    result = {
        "ats_score": ats,
        "fit_score": fit,
        "threshold": a.threshold,
        "pass": ats >= a.threshold and fit >= a.threshold,
        "breakdown": {
            "ats": f"{got:g}/{total:g} weight matched",
            "required": round(50 * req, 1), "keywords": round(0.25 * ats, 1),
            "preferred": round(15 * pref, 1), "level": round(10 * lvl, 1),
        },
        "missing_terms": [{"term": m["term"], "weight": m["weight"], "gap": m["gap"]} for m in missing],
        "unmet": [i for i in req_items + pref_items + lvl_items if i["counted_as"] != "met"],
        "notes": notes,
        "inputs": {"resume": a.pdf or a.text, "posting": posting, "terms": terms_out},
        "disclaimer": "Tool estimate with a fixed formula; not a real ATS result.",
    }
    out = Path(a.out) if a.out else Path(a.pdf or a.text).expanduser().resolve().parent / "score.json"
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"ATS match: {ats}   Fit: {fit}   ({'PASS' if result['pass'] else 'BELOW ' + str(int(a.threshold))})")
    b = result["breakdown"]
    print(f"  fit = required {b['required']}/50 + keywords {b['keywords']}/25 + preferred {b['preferred']}/15 + level {b['level']}/10")
    if missing:
        print("  missing terms:")
        label = {"denied": "you said you haven't used this",
                 "confirmed_not_on_resume": "confirmed; could be added if true for a cited fact",
                 "unknown": "unknown; ask the user"}
        for m in missing:
            print(f"    - {m['term']} (w{m['weight']:g}): {label[m['gap']]}")
    for u in result["unmet"]:
        print(f"  {u['counted_as']}: {u.get('text') or u.get('note')}")
    for n in notes:
        print(f"  note: {n}")
    print(f"  saved: {out}")
    sys.exit(0 if result["pass"] else 2)


if __name__ == "__main__":
    main()
