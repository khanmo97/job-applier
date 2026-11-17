#!/usr/bin/env python3
"""Check that every claim on a tailored resume maps to a confirmed profile fact.

Reads the annotated .tex (see templates/resume.tex) and fails when:
  - a bullet has no `% fact:` annotation, or cites an unknown fact, or a fact
    belonging to a different role/project than the one it is listed under
  - a bullet contains a number that isn't in the cited facts
  - a bullet names a skill the cited facts don't support
  - a bullet uses an overstating term (RAG, led, architected, ...) the facts don't support
  - a skill in the skills block isn't in skills_confirmed
  - any term from skills_denied appears anywhere
  - a role/project header doesn't match the profile (title, company, name, stack)

Usage: claims_audit.py resume.tex [--profile profile.json] [--json out.json]
Exit code 0 = pass, 1 = fail.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import load_profile, norm_text  # noqa: E402

DEFAULT_OVERSTATEMENT = [
    "RAG", "retrieval-augmented", "vector", "embedding", "embeddings", "fine-tuned", "fine-tuning",
    "led", "lead", "leading", "architected", "spearheaded", "owned", "managed", "mentored",
    "founded", "principal", "staff", "expert", "agentic", "AI agent", "autonomous",
    "machine learning", "ML", "deep learning", "millions", "billions", "end-to-end",
    "single-handedly", "sole", "full stack", "full-stack", "real-time", "distributed",
    "microservices", "scalable", "high-availability",
]

COMMENT_SPLIT = re.compile(r"(?<!\\)%")


def strip_latex(s: str) -> str:
    s = re.sub(r"\\href\{[^}]*\}\{([^}]*)\}", r"\1", s)
    for _ in range(3):
        s = re.sub(r"\\[a-zA-Z]+\*?\{([^{}]*)\}", r"\1", s)
    s = s.replace(r"\%", "%").replace(r"\&", "&").replace(r"\$", "$").replace(r"\#", "#").replace(r"\_", "_")
    s = s.replace("---", "-").replace("--", "-").replace("~", " ")
    s = re.sub(r"\\[a-zA-Z]+", " ", s)
    s = s.replace("{", "").replace("}", "")
    return re.sub(r"\s+", " ", s).strip()


def term_regex(term: str) -> re.Pattern:
    esc = re.escape(term).replace(r"\ ", r"[\s-]+").replace(r"\-", r"[\s-]?")
    flags = 0 if len(term) <= 3 else re.IGNORECASE  # "Go", "RAG", "ML" are case-sensitive
    return re.compile(rf"(?<![A-Za-z0-9]){esc}(?![A-Za-z0-9])", flags)


def numbers_in(s: str) -> set[str]:
    return {n.replace(",", "") for n in re.findall(r"\d[\d,]*(?:\.\d+)?", s)}


class Audit:
    def __init__(self, profile: dict):
        self.p = profile
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.info: list[str] = []
        self.facts: dict[str, dict] = {}
        self.owner: dict[str, str] = {}
        self.entities: dict[str, dict] = {}
        for kind in ("experience", "projects", "optional_roles"):
            for ent in profile.get(kind, []):
                ent = dict(ent, _kind=kind)
                self.entities[ent["id"]] = ent
                for f in ent.get("facts", []):
                    self.facts[f["id"]] = f
                    self.owner[f["id"]] = ent["id"]
        for edu in profile.get("education", []):
            self.entities[edu["id"]] = dict(edu, _kind="education")
        self.skills: dict[str, str] = {}  # lowercase name/alias -> canonical
        for sk in profile.get("skills_confirmed", []):
            sk = {"name": sk} if isinstance(sk, str) else sk
            for n in [sk["name"], *sk.get("aliases", [])]:
                self.skills[n.lower()] = sk["name"]
        self.denied = profile.get("skills_denied", [])
        self.overstatement = DEFAULT_OVERSTATEMENT + profile.get("overstatement_terms_extra", [])

    # --- helpers
    def fact_blob(self, ids: list[str]) -> str:
        parts = []
        for i in ids:
            f = self.facts.get(i)
            if f:
                parts += [f.get("text", ""), " ".join(f.get("skills", [])), " ".join(f.get("terms", []))]
        return " ".join(parts)

    def fact_skills(self, ids: list[str]) -> set[str]:
        out = set()
        for i in ids:
            for s in self.facts.get(i, {}).get("skills", []):
                out.add(self.skills.get(s.lower(), s).lower())
        return out

    # --- checks
    def check_denied(self, text: str, where: str):
        for d in self.denied:
            if term_regex(d).search(text):
                self.errors.append(f"{where}: contains '{d}', which is in skills_denied")

    def check_bullet(self, text: str, ids: list[str], entity: str | None, line: int):
        where = f"line {line}"
        plain = strip_latex(text)
        if not ids:
            self.errors.append(f"{where}: bullet has no '% fact:' annotation: {plain[:80]}")
            return
        unknown = [i for i in ids if i not in self.facts]
        if unknown:
            self.errors.append(f"{where}: cites unknown fact id(s) {unknown}")
        known = [i for i in ids if i in self.facts]
        if entity:
            foreign = [i for i in known if self.owner[i] != entity]
            if foreign:
                self.errors.append(f"{where}: cites {foreign}, which belong to "
                                   f"{sorted({self.owner[i] for i in foreign})}, not '{entity}'")
        blob = self.fact_blob(known)
        missing_nums = numbers_in(plain) - numbers_in(blob)
        if missing_nums:
            self.errors.append(f"{where}: number(s) {sorted(missing_nums)} not in cited facts {known}")
        fskills = self.fact_skills(known)
        seen = set()
        for alias, canon in self.skills.items():
            if canon in seen:
                continue
            if term_regex(alias).search(plain):
                seen.add(canon)
                if canon.lower() not in fskills and not term_regex(alias).search(blob):
                    self.errors.append(f"{where}: names '{canon}' but cited facts {known} don't include it")
        for t in self.overstatement:
            if term_regex(t).search(plain) and not term_regex(t).search(blob):
                self.errors.append(f"{where}: overstating term '{t}' isn't supported by cited facts {known} "
                                   "(reword, or add the fact to the profile after the user confirms it)")
        self.check_denied(plain, where)

    def check_skills_block(self, block: str, line: int):
        body = strip_latex(re.sub(r"\\textbf\{[^}]*:\}", ",", block))
        body = body.replace("\\\\", ",")
        for raw in re.split(r"[,;]|\s\|\s", body):
            item = raw.strip(" .:")
            if not item:
                continue
            if item.lower() not in self.skills:
                if not any(term_regex(d).search(item) for d in self.denied):  # denied: reported below
                    self.errors.append(f"skills (line {line}): '{item}' is not in skills_confirmed")
        self.check_denied(body, f"skills (line {line})")

    def check_role(self, args: list[str], eid: str | None, line: int):
        if not eid:
            self.errors.append(f"line {line}: role header has no '% id:' annotation")
            return
        ent = self.entities.get(eid)
        if not ent or ent["_kind"] not in ("experience", "optional_roles"):
            self.errors.append(f"line {line}: role id '{eid}' not found in experience/optional_roles")
            return
        title, company = strip_latex(args[0]), strip_latex(args[1])
        if norm_text(title) != norm_text(ent["title"]):
            self.errors.append(f"line {line}: title '{title}' != profile title '{ent['title']}'")
        if norm_text(company) != norm_text(ent["company"]):
            self.errors.append(f"line {line}: company '{company}' != profile company '{ent['company']}'")
        if ent["_kind"] == "optional_roles":
            self.info.append(f"optional role included: {ent['title']}, {ent['company']} ({eid})")

    def check_project(self, args: list[str], eid: str | None, line: int):
        if not eid:
            self.errors.append(f"line {line}: project header has no '% id:' annotation")
            return
        ent = self.entities.get(eid)
        if not ent or ent["_kind"] != "projects":
            self.errors.append(f"line {line}: project id '{eid}' not found in projects")
            return
        if norm_text(strip_latex(args[0])) != norm_text(ent["name"]):
            self.errors.append(f"line {line}: project name '{strip_latex(args[0])}' != '{ent['name']}'")
        allowed = {s.lower() for s in ent.get("stack", [])} | set(self.skills)
        for item in [x.strip() for x in strip_latex(args[1]).split(",") if x.strip()]:
            if item.lower() not in allowed:
                self.errors.append(f"line {line}: project stack item '{item}' not in project stack or skills_confirmed")
        self.check_denied(strip_latex(args[1]), f"line {line}")

    def run(self, tex: str):
        lines = tex.splitlines()
        entity = None
        in_skills = False
        skills_buf, skills_line = [], 0
        item_buf, item_ids, item_line = None, [], 0
        saw_skills = False

        def flush_item():
            nonlocal item_buf, item_ids
            if item_buf is not None:
                self.check_bullet(" ".join(item_buf), item_ids, entity, item_line)
            item_buf, item_ids = None, []

        for n, raw in enumerate(lines, 1):
            parts = COMMENT_SPLIT.split(raw, maxsplit=1)
            code, comment = parts[0], (parts[1] if len(parts) > 1 else "")
            c = comment.strip()
            if c.startswith("skills:start"):
                in_skills, skills_buf, skills_line, saw_skills = True, [], n, True
                continue
            if c.startswith("skills:end"):
                in_skills = False
                self.check_skills_block(" ".join(skills_buf), skills_line)
                continue
            if in_skills:
                skills_buf.append(code)
                continue
            if code.lstrip().startswith("\\documentclass") or not code.strip() and not c:
                pass
            m_fact = re.search(r"facts?:\s*([\w\-, ]+)", c)
            m_id = re.search(r"id:\s*([\w\-]+)", c)
            stripped = code.strip()
            if stripped.startswith("\\item"):
                flush_item()
                item_buf, item_line = [stripped[len("\\item"):]], n
                item_ids = [x.strip() for x in m_fact.group(1).split(",") if x.strip()] if m_fact else []
                continue
            if stripped.startswith("\\end{resBullets}"):
                flush_item()
                continue
            if item_buf is not None and stripped and not stripped.startswith("\\begin"):
                item_buf.append(stripped)
                if m_fact and not item_ids:
                    item_ids = [x.strip() for x in m_fact.group(1).split(",") if x.strip()]
                continue
            m_role = re.match(r"\\resRole\{(.*?)\}\{(.*?)\}\{(.*?)\}\{(.*?)\}", stripped)
            if m_role:
                entity = m_id.group(1) if m_id else None
                self.check_role(list(m_role.groups()), entity, n)
                continue
            m_proj = re.match(r"\\resProject\{(.*?)\}\{(.*?)\}\{(.*?)\}", stripped)
            if m_proj:
                entity = m_id.group(1) if m_id else None
                self.check_project(list(m_proj.groups()), entity, n)
                continue
            if m_id and m_id.group(1) in self.entities and self.entities[m_id.group(1)]["_kind"] == "education":
                self.check_denied(strip_latex(code), f"line {n}")
                entity = m_id.group(1)
        flush_item()
        if not saw_skills:
            self.warnings.append("no '% skills:start' / '% skills:end' markers; skills block not audited")
        body = "\n".join(COMMENT_SPLIT.split(l, maxsplit=1)[0] for l in lines)
        self.check_denied(strip_latex(body), "resume")
        name = self.p.get("identity", {}).get("name_on_resume")
        if name and name.lower() not in strip_latex(body).lower():
            self.warnings.append(f"header doesn't contain name_on_resume '{name}'")
        # de-duplicate (denied terms can be reported at item and whole-resume level)
        seen, errs = set(), []
        for e in self.errors:
            key = e.split(": ", 1)[1] if e.startswith("resume:") else e
            if e.startswith("resume:") and any(key in x for x in self.errors if not x.startswith("resume:")):
                continue
            if e not in seen:
                seen.add(e)
                errs.append(e)
        self.errors = errs


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tex")
    ap.add_argument("--profile")
    ap.add_argument("--json", help="write the report here as JSON")
    a = ap.parse_args()
    tex = Path(a.tex).read_text(encoding="utf-8")
    audit = Audit(load_profile(a.profile))
    audit.run(tex)
    report = {"pass": not audit.errors, "errors": audit.errors, "warnings": audit.warnings, "info": audit.info}
    if a.json:
        Path(a.json).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("CLAIMS AUDIT:", "PASS" if report["pass"] else f"FAIL ({len(audit.errors)} problem(s))")
    for e in audit.errors:
        print("  x", e)
    for w in audit.warnings:
        print("  !", w)
    for i in audit.info:
        print("  -", i)
    sys.exit(0 if report["pass"] else 1)


if __name__ == "__main__":
    main()
