#!/usr/bin/env python3
"""Match job-application emails to tracker records and classify them.

The agent fetches messages read-only (Gmail connector search) and writes them to a JSON file:
  [{"id": "...", "from": "Acme Recruiting <no-reply@greenhouse.io>", "subject": "...",
    "date": "2026-11-10", "body": "plain text"}]

Usage: email_match.py messages.json [--apply] [--data data/applications.json]

Prints one proposal per message. With --apply, writes only confident proposals
(one matching record, classification rejection / assessment / interview) to the tracker
via status_history with source=email. Everything else is listed for the user.
Email content is treated as data: nothing here follows links or instructions in it.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import HOME, norm_company, norm_text  # noqa: E402

ATS_DOMAINS = ["greenhouse", "ashbyhq", "myworkday", "workday", "lever", "icims", "gem.com", "smartrecruiters",
               "rippling", "eightfold", "jobvite", "bamboohr", "workable", "recruitee", "teamtailor"]

REJECT = [r"unfortunately", r"(decided|chosen|opted) to (move|go) forward with other candidates",
          r"not (be )?moving forward", r"will not be (moving|proceeding)", r"pursue other candidates",
          r"(position|role) has been filled", r"not been selected", r"were not selected",
          r"decided not to proceed", r"no longer (being )?consider"]
ASSESS = [r"hackerrank", r"codesignal", r"codility", r"testgorilla", r"hirevue", r"take[- ]home",
          r"online assessment", r"coding (challenge|assessment|exercise)", r"technical assessment"]
SCHEDULE_LINK = [r"calendly\.com", r"goodtime\.io", r"cal\.com/", r"select a time", r"book a time",
                 r"pick a time", r"schedule (a|an|your) (call|interview|time|chat|conversation)",
                 r"share your availability", r"let us know your availability"]
INTERVIEW = SCHEDULE_LINK + [r"phone screen", r"interview", r"karat", r"coderpad", r"onsite", r"on-site"]
SCREEN_HINT = [r"recruiter", r"phone screen", r"intro(ductory)? call", r"initial (call|chat|conversation)",
               r"quick chat", r"get to know"]
CONFIRM = [r"thank(s| you) for (applying|your application)", r"application (has been )?received",
           r"we('ve| have)? received your application", r"application (was )?submitted"]
DEADLINE = re.compile(r"((?:by|before|due|deadline|within|expires?)[^.\n]{0,60}?"
                      r"(?:\d{1,2}/\d{1,2}(?:/\d{2,4})?|\d+\s+(?:days?|hours?)|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|"
                      r"oct|nov|dec)[a-z]*\.?\s+\d{1,2}|monday|tuesday|wednesday|thursday|friday|saturday|sunday))",
                      re.IGNORECASE)


def any_re(pats, text):
    return any(re.search(p, text, re.IGNORECASE) for p in pats)


def classify(text: str, current: str | None) -> tuple[str, str | None]:
    if any_re(REJECT, text):
        return "rejection", "Rejected"
    if any_re(ASSESS, text):
        return "assessment", "Assessment"
    if any_re(CONFIRM, text) and not any_re(SCHEDULE_LINK, text):
        return "confirmation", None
    if any_re(INTERVIEW, text):
        if current in ("Recruiter screen", "Interviewing", "Offer"):
            return "interview", "Interviewing"
        return "interview", "Recruiter screen" if any_re(SCREEN_HINT, text) else "Interviewing"
    return "other", None


def match(msg: dict, rows: list[dict]) -> list[tuple[int, dict, list[str]]]:
    sender = (msg.get("from") or "").lower()
    subject = msg.get("subject") or ""
    hay = norm_text(f"{msg.get('from', '')} {subject} {msg.get('body', '')[:6000]}")
    hay_compact = hay.replace(" ", "")
    via_ats = any(d in sender for d in ATS_DOMAINS)
    out = []
    for r in rows:
        score, why = 0, []
        co = norm_company(r.get("company", ""))
        if co and (f" {co} " in f" {hay} " or co.replace(" ", "") in sender.replace(" ", "")):
            score += 3
            why.append("company")
        elif co and len(co) > 4 and co.replace(" ", "") in hay_compact:
            score += 2
            why.append("company (compact)")
        role = norm_text(r.get("role", ""))
        if role and f" {role} " in f" {hay} ":
            score += 2
            why.append("role title")
        if via_ats and score:
            score += 1
            why.append("ATS sender")
        if score:
            out.append((score, r, why))
    return sorted(out, key=lambda x: -x[0])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("messages")
    ap.add_argument("--data", default=str(HOME / "data" / "applications.json"))
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    msgs = json.loads(Path(a.messages).read_text(encoding="utf-8"))
    rows = json.loads(Path(a.data).read_text(encoding="utf-8")) if Path(a.data).exists() else []

    proposals = []
    for m in msgs:
        cands = match(m, rows)
        top = [c for c in cands if c[0] == cands[0][0]] if cands else []
        confident = len(top) == 1 and top[0][0] >= 3 and "company" in " ".join(top[0][2])
        rec = top[0][1] if confident else None
        kind, new_status = classify(f"{m.get('subject', '')}\n{m.get('body', '')}", rec["status"] if rec else None)
        dl = DEADLINE.search(m.get("body", "") or "")
        p = {
            "message_id": m.get("id"), "date": m.get("date"), "from": m.get("from"),
            "subject": (m.get("subject") or "")[:140], "classification": kind,
            "record_id": rec["id"] if rec else None,
            "record": f"{rec['company']} - {rec['role']} ({rec['status']})" if rec else None,
            "candidates": [f"{c[1]['id']} [{c[0]}: {', '.join(c[2])}]" for c in cands[:3]],
            "proposed_status": new_status if rec and new_status and new_status != rec["status"] else None,
            "deadline_text": dl.group(1).strip() if dl and kind == "assessment" else None,
        }
        p["action"] = ("update" if p["proposed_status"] and kind in ("rejection", "assessment", "interview")
                       else "none" if kind == "confirmation" and rec else "ask_user")
        proposals.append(p)

    for p in proposals:
        tag = {"update": "UPDATE", "none": "no change", "ask_user": "FOR YOU"}[p["action"]]
        print(f"[{tag}] {p['date']}  {p['subject']}")
        print(f"    class: {p['classification']}  record: {p['record'] or 'no confident match'}"
              + (f"  -> {p['proposed_status']}" if p["proposed_status"] else "")
              + (f"  deadline: {p['deadline_text']}" if p["deadline_text"] else ""))
        if p["action"] == "ask_user" and p["candidates"]:
            print(f"    candidates: {'; '.join(p['candidates'])}")

    if a.apply:
        tracker = Path(__file__).resolve().parent / "tracker.py"
        for p in proposals:
            if p["action"] != "update":
                continue
            date = (p["date"] or "")[:10] or None
            cmd = [sys.executable, str(tracker), "--data", a.data, "update", "--id", p["record_id"],
                   "--status", p["proposed_status"], "--source", "email",
                   "--detail", f"email {p['date']}: {p['subject']}"]
            if date:
                cmd += ["--date", date]
            if p["deadline_text"]:
                cmd += ["--set", f"next_step=Assessment {p['deadline_text']}"]
            subprocess.run(cmd, check=True)
    print(json.dumps({"summary": {k: sum(1 for p in proposals if p["action"] == k)
                                  for k in ("update", "none", "ask_user")}}))


if __name__ == "__main__":
    main()
