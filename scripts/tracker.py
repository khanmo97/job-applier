#!/usr/bin/env python3
"""Application tracker: data/applications.json.

Commands
  add             --company --role [--status Applied] [--posting-url --apply-url --job-id ...]
                  (or --json record.json). Refuses duplicates unless --force.
  update          --id ID | --company C [--role R]; --status S [--source manual|email]
                  [--date YYYY-MM-DD] [--detail "email subject"] [--set key=value ...] [--note text]
  find-duplicate  [--url U] [--job-id J] [--company C --role R]   exit 3 when a match is found
  mark-stale      [--days 30]   Applied with no change for N days -> No response
  status          summary by status + recent activity
  list            [--status S] [--company C]
  export-csv      out.csv
  email-state     get | set [--date ISO]   last time the email monitor ran

Records are never deleted or replaced. Status changes append to status_history.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (HOME, STATUSES, die, job_id_from_url, norm_company, norm_text,  # noqa: E402
                    norm_url, write_json)

FIELDS = [
    "id", "company", "role", "category", "status", "applied_date", "next_step", "pay_range",
    "location", "work_mode", "resume_path", "optional_roles_included", "job_id", "posting_url",
    "apply_url", "ats_score", "fit_score", "notes", "status_history", "created", "updated",
]
LOCKED = {"id", "status", "status_history", "created", "updated"}


def today() -> str:
    return date.today().isoformat()


def data_path(arg: str | None) -> Path:
    return Path(arg).expanduser() if arg else HOME / "data" / "applications.json"


def load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else data.get("applications", [])


def save(path: Path, rows: list[dict]) -> None:
    write_json(path, rows)


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40]


def check_status(s: str) -> str:
    for st in STATUSES:
        if st.lower() == (s or "").lower():
            return st
    die(f"unknown status '{s}'. Use one of: {', '.join(STATUSES)}")


def ids_for(rec: dict) -> set[str]:
    out = set()
    if rec.get("job_id"):
        out.add(str(rec["job_id"]).strip().lower())
    for k in ("posting_url", "apply_url"):
        j = job_id_from_url(rec.get(k) or "")
        if j:
            out.add(j.lower())
    return out


def find_dups(rows: list[dict], url=None, job_id=None, company=None, role=None) -> list[dict]:
    q = {"posting_url": url, "job_id": job_id}
    q_ids = ids_for(q)
    q_url = norm_url(url) if url else ""
    q_co, q_role = norm_company(company or ""), norm_text(role or "")
    matches = []
    for r in rows:
        reasons = []
        if q_ids & ids_for(r):
            reasons.append("job id")
        if q_url and q_url in {norm_url(r.get("posting_url") or ""), norm_url(r.get("apply_url") or "")}:
            reasons.append("url")
        if q_co and q_role and norm_company(r.get("company", "")) == q_co and norm_text(r.get("role", "")) == q_role:
            reasons.append("company + title")
        if reasons:
            matches.append({"id": r["id"], "company": r["company"], "role": r["role"], "status": r["status"],
                            "applied_date": r.get("applied_date"), "matched_on": reasons,
                            "resume_path": r.get("resume_path")})
    return matches


def pick(rows: list[dict], rid=None, company=None, role=None) -> dict:
    if rid:
        for r in rows:
            if r["id"] == rid:
                return r
        die(f"no record with id {rid}")
    cands = [r for r in rows if norm_company(r["company"]) == norm_company(company or "")]
    if role:
        exact = [r for r in cands if norm_text(r["role"]) == norm_text(role)]
        cands = exact or [r for r in cands if norm_text(role) in norm_text(r["role"])]
    if not cands:
        die(f"no record for company '{company}'" + (f" / role '{role}'" if role else ""))
    if len(cands) > 1:
        lines = "\n".join(f"  {r['id']}: {r['role']} ({r['status']})" for r in cands)
        die(f"{len(cands)} records match; pass --id or --role:\n{lines}")
    return cands[0]


def parse_value(v: str):
    if v.lower() in ("true", "false"):
        return v.lower() == "true"
    try:
        return float(v) if "." in v else int(v)
    except ValueError:
        pass
    if v.startswith("[") or v.startswith("{"):
        try:
            return json.loads(v)
        except json.JSONDecodeError:
            pass
    return v


# ---------- commands ----------

def cmd_add(a, rows, path):
    rec = {}
    if a.json:
        rec = json.loads(Path(a.json).read_text(encoding="utf-8"))
    for k in FIELDS:
        v = getattr(a, k, None)
        if v is not None:
            rec[k] = v
    for k in ("company", "role"):
        if not rec.get(k):
            die(f"--{k} is required")
    rec["status"] = check_status(rec.get("status") or "Applied")
    dups = find_dups(rows, rec.get("posting_url"), rec.get("job_id"), rec["company"], rec["role"])
    if dups and not a.force:
        print(json.dumps({"duplicate": True, "matches": dups}, indent=2))
        die("possible duplicate; use `update` on the existing record or pass --force", 3)
    if not rec.get("job_id"):
        rec["job_id"] = job_id_from_url(rec.get("posting_url") or "") or job_id_from_url(rec.get("apply_url") or "")
    d = a.date or today()
    base = f"{d}-{slug(rec['company'])}-{slug(rec['role'])}"
    rid, n = base, 2
    existing = {r["id"] for r in rows}
    while rid in existing:
        rid, n = f"{base}-{n}", n + 1
    rec["id"] = rid
    if rec["status"] == "Applied" and not rec.get("applied_date"):
        rec["applied_date"] = d
    rec["status_history"] = [{"date": d, "status": rec["status"], "source": "manual", "detail": "created"}]
    rec["created"] = rec["updated"] = datetime.now().isoformat(timespec="seconds")
    rows.append({k: rec.get(k) for k in FIELDS} | {k: v for k, v in rec.items() if k not in FIELDS})
    save(path, rows)
    print(f"added {rid} ({rec['status']})")


def cmd_update(a, rows, path):
    r = pick(rows, a.id, a.company, a.role)
    changed = []
    for kv in a.set or []:
        if "=" not in kv:
            die(f"--set expects key=value, got '{kv}'")
        k, v = kv.split("=", 1)
        if k in LOCKED:
            die(f"'{k}' can't be set directly")
        r[k] = parse_value(v)
        changed.append(k)
    if a.note:
        r["notes"] = ((r.get("notes") or "") + ("\n" if r.get("notes") else "") + f"[{a.date or today()}] {a.note}")
        changed.append("notes")
    if a.status:
        st = check_status(a.status)
        if st != r["status"]:
            r["status_history"].append({"date": a.date or today(), "status": st, "source": a.source,
                                        "detail": a.detail or ""})
            if st == "Applied" and not r.get("applied_date"):
                r["applied_date"] = a.date or today()
            r["status"] = st
            changed.append(f"status -> {st}")
        else:
            print(f"{r['id']} is already {st}")
    if changed:
        r["updated"] = datetime.now().isoformat(timespec="seconds")
        save(path, rows)
        print(f"updated {r['id']}: {', '.join(changed)}")


def cmd_find(a, rows, _):
    if not (a.url or a.job_id or (a.company and a.role)):
        die("give --url, --job-id, or --company with --role")
    m = find_dups(rows, a.url, a.job_id, a.company, a.role)
    print(json.dumps({"duplicate": bool(m), "matches": m}, indent=2))
    sys.exit(3 if m else 0)


def last_change(r: dict) -> str:
    h = r.get("status_history") or []
    return max([x["date"] for x in h] + [r.get("applied_date") or "0000"])


def cmd_stale(a, rows, path):
    cutoff = (date.fromisoformat(a.today or today()) - timedelta(days=a.days)).isoformat()
    n = 0
    for r in rows:
        if r["status"] == "Applied" and last_change(r) <= cutoff:
            r["status_history"].append({"date": a.today or today(), "status": "No response", "source": "manual",
                                        "detail": f"no change for {a.days}+ days"})
            r["status"] = "No response"
            r["updated"] = datetime.now().isoformat(timespec="seconds")
            n += 1
            print(f"  {r['company']} - {r['role']} (applied {r.get('applied_date')})")
    if n:
        save(path, rows)
    print(f"marked {n} application(s) as No response")


def cmd_status(a, rows, _):
    print(f"{len(rows)} application record(s)")
    for st in STATUSES:
        c = sum(1 for r in rows if r["status"] == st)
        if c:
            print(f"  {st:<17}{c}")
    active = [r for r in rows if r["status"] in ("Assessment", "Recruiter screen", "Interviewing", "Offer")]
    if active:
        print("Active:")
        for r in active:
            print(f"  {r['company']} - {r['role']}: {r['status']}" + (f" | next: {r['next_step']}" if r.get("next_step") else ""))
    recent = sorted(rows, key=last_change, reverse=True)[:5]
    if recent:
        print("Recent:")
        for r in recent:
            print(f"  {last_change(r)}  {r['company']} - {r['role']}: {r['status']}")


def cmd_list(a, rows, _):
    for r in rows:
        if a.status and r["status"].lower() != a.status.lower():
            continue
        if a.company and norm_company(r["company"]) != norm_company(a.company):
            continue
        print(f"{r['id']}\t{r['status']}\t{r.get('applied_date') or ''}\t{r['company']}\t{r['role']}")


def cmd_csv(a, rows, _):
    cols = [f for f in FIELDS if f != "status_history"] + ["status_history"]
    with open(a.out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in rows:
            vals = []
            for c in cols:
                v = r.get(c)
                if c == "status_history":
                    v = "; ".join(f"{h['date']} {h['status']} ({h['source']})" for h in v or [])
                elif isinstance(v, (list, dict)):
                    v = json.dumps(v)
                vals.append("" if v is None else v)
            w.writerow(vals)
    print(f"wrote {len(rows)} rows to {a.out}")


def cmd_email_state(a, _rows, path):
    sp = path.parent / "state.json"
    state = json.loads(sp.read_text()) if sp.exists() else {}
    if a.action == "get":
        print(state.get("email_last_checked") or "never")
    else:
        state["email_last_checked"] = a.date or datetime.now().isoformat(timespec="seconds")
        write_json(sp, state)
        print(f"email_last_checked = {state['email_last_checked']}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", help="path to applications.json (default: data/applications.json)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("add")
    p.add_argument("--json")
    for k in FIELDS:
        if k not in LOCKED or k == "status":
            p.add_argument("--" + k.replace("_", "-"), dest=k)
    p.add_argument("--date")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_add)

    p = sub.add_parser("update")
    p.add_argument("--id")
    p.add_argument("--company")
    p.add_argument("--role")
    p.add_argument("--status")
    p.add_argument("--source", choices=["manual", "email"], default="manual")
    p.add_argument("--date")
    p.add_argument("--detail")
    p.add_argument("--set", action="append")
    p.add_argument("--note")
    p.set_defaults(fn=cmd_update)

    p = sub.add_parser("find-duplicate")
    p.add_argument("--url")
    p.add_argument("--job-id")
    p.add_argument("--company")
    p.add_argument("--role")
    p.set_defaults(fn=cmd_find)

    p = sub.add_parser("mark-stale")
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--today")
    p.set_defaults(fn=cmd_stale)

    sub.add_parser("status").set_defaults(fn=cmd_status)

    p = sub.add_parser("list")
    p.add_argument("--status")
    p.add_argument("--company")
    p.set_defaults(fn=cmd_list)

    p = sub.add_parser("export-csv")
    p.add_argument("out")
    p.set_defaults(fn=cmd_csv)

    p = sub.add_parser("email-state")
    p.add_argument("action", choices=["get", "set"])
    p.add_argument("--date")
    p.set_defaults(fn=cmd_email_state)

    a = ap.parse_args()
    path = data_path(a.data)
    a.fn(a, load(path), path)


if __name__ == "__main__":
    main()
