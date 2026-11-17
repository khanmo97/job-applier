"""Shared helpers for job-applier scripts. Standard library only."""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

SKILL_DIR = Path(__file__).resolve().parent.parent
# Data can live outside the skill folder (e.g. when the skill is installed read-only).
HOME = Path(os.environ.get("JOB_APPLIER_HOME", SKILL_DIR)).expanduser()

STATUSES = [
    "To do", "Applied", "Assessment", "Recruiter screen", "Interviewing",
    "Offer", "Rejected", "Withdrawn", "No response",
]
RESPONSE_STATUSES = {"Assessment", "Recruiter screen", "Interviewing", "Offer", "Rejected"}
INTERVIEW_STATUSES = {"Recruiter screen", "Interviewing", "Offer"}


def die(msg: str, code: int = 1) -> None:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(code)


def load_json(path: Path | str):
    path = Path(path).expanduser()
    if not path.exists():
        die(f"{path} not found")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path | str, data) -> None:
    path = Path(path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    tmp.replace(path)


def profile_path(arg: str | None) -> Path:
    if arg:
        return Path(arg).expanduser()
    p = HOME / "profile.json"
    if not p.exists():
        die("profile.json not found. Run the skill's `setup` command, "
            "or pass --profile profile.example.json to try the example.")
    return p


def load_profile(arg: str | None = None) -> dict:
    return load_json(profile_path(arg))


# ---------- normalization ----------

TITLE_ABBREV = {
    r"\bsr\b": "senior", r"\bjr\b": "junior", r"\bswe\b": "software engineer",
    r"\beng\b": "engineer", r"\bmgr\b": "manager", r"\bdev\b": "developer",
    r"\bfullstack\b": "full stack", r"\bfull-stack\b": "full stack",
    r"\bback-end\b": "backend", r"\bfront-end\b": "frontend",
}


def norm_text(s: str) -> str:
    s = (s or "").lower()
    s = s.replace("&", " and ")
    for pat, rep in TITLE_ABBREV.items():
        s = re.sub(pat, rep, s)
    s = re.sub(r"[^a-z0-9+#]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


COMPANY_SUFFIX = re.compile(r"\b(inc|llc|ltd|corp|corporation|co|company|plc|gmbh|technologies|labs)\b")


def norm_company(s: str) -> str:
    s = norm_text(s)
    s = COMPANY_SUFFIX.sub("", s)
    return re.sub(r"\s+", " ", s).strip()


# Query params that identify a specific job on common boards / ATSs.
JOB_ID_PARAMS = ("currentjobid", "gh_jid", "jobid", "job_id", "jid", "reqid", "req_id", "lever-source")


def job_id_from_url(url: str) -> str | None:
    if not url:
        return None
    u = urlparse(url.strip())
    q = {k.lower(): v for k, v in parse_qs(u.query).items()}
    for k in ("currentjobid", "gh_jid", "jobid", "job_id", "jid", "reqid", "req_id"):
        if k in q and q[k]:
            return q[k][0]
    m = re.search(r"/jobs/view/(\d+)", u.path)  # LinkedIn
    if m:
        return m.group(1)
    m = re.search(r"/jobs/(\d{5,})", u.path)  # Greenhouse
    if m:
        return m.group(1)
    m = re.search(r"_(R?-?\d{4,})(?:/|$|-)", u.path)  # Workday ..._R12345
    if m:
        return m.group(1)
    return None


def norm_url(url: str) -> str:
    """Canonical form for comparing posting URLs."""
    if not url:
        return ""
    u = urlparse(url.strip())
    host = u.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    path = re.sub(r"/+$", "", u.path)
    q = {k.lower(): v for k, v in parse_qs(u.query).items()}
    keep = [f"{k}={q[k][0]}" for k in sorted(q) if k in JOB_ID_PARAMS and k != "lever-source"]
    return f"{host}{path}" + ("?" + "&".join(keep) if keep else "")


def safe_dirname(s: str) -> str:
    s = (s or "").replace("/", "-").replace("\\", "-").replace(":", " -")
    s = re.sub(r"[\x00-\x1f<>\"|?*]", "", s)
    return re.sub(r"\s+", " ", s).strip().rstrip(".") or "Untitled"


def archive_dir(profile: dict, company: str, title: str) -> Path:
    root = Path(profile.get("paths", {}).get("archive", "~/Downloads/Apps")).expanduser()
    return root / safe_dirname(company) / safe_dirname(title) / "resume"
