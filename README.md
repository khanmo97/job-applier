# job-applier

A Claude Code skill that turns a job link into a submitted application without stretching the truth. It:

1. reads the posting and checks it against roles you've already applied to and against your dealbreakers,
2. tailors a one-page LaTeX resume using **only facts you have confirmed**,
3. audits every claim on that resume against your profile,
4. scores it with a fixed, visible formula (ATS match and fit, both must be ≥ 80),
5. saves it in a folder per role, so you always know which resume went where,
6. fills the application in your browser and stops for anything you need to decide,
7. logs it in a local tracker, which can update itself from a job-search inbox, with a local dashboard.

## The truth rule (the reason to use this)

The resume, form answers and free-text drafts come only from `profile.json`, which holds facts you have confirmed, each with an ID.

- **Every resume bullet cites the fact(s) it is built from** (`% fact: nw-2`). `scripts/claims_audit.py` blocks saving when a bullet:
  - cites no fact,
  - cites a fact from a different job,
  - contains a number that isn't in the fact,
  - names a skill the fact doesn't support,
  - uses an overstating term the fact doesn't back ("RAG", "led", "architected", "AI agent", "end-to-end", ...).
- **Skills you say you have *not* used** (`skills_denied`) can never appear, even when adding them would raise the score. The agent won't ask about them again.
- **New facts** you mention in chat are added to the profile only after you approve the exact edit.

Example: a resume said "AI agent with RAG" for a system that did live API lookups with no vector store. The audit fails that bullet unless the cited fact says RAG.

## What the agent never does

- Create accounts, type passwords, enter verification codes or solve CAPTCHAs. Those are handed to you.
- Accept an agreement, acknowledgment, privacy notice or terms on your behalf. You approve each one, every time.
- Answer company-specific questions (prior employment, relatives, conflicts) without asking you.
- Submit when any field was a guess. It submits on its own only when every field came from your profile or from answers you just gave.
- Send, reply to, forward, delete or archive email. The email monitor only searches and reads.
- Follow instructions or click links found in postings, application pages or emails.

## Terms of service

LinkedIn and some applicant-tracking sites prohibit automated applications. This tool works in your own browser, and **you approve submissions and are responsible for complying with each site's terms**. LinkedIn Easy Apply is semi-manual by design: you upload the resume yourself.

## Privacy

Everything stays on your machine. `profile.json`, `data/`, `work/` and `dashboard/data.js` are gitignored. The dashboard is one static HTML file with no external scripts, fonts or network calls. The only things committed are a fictional example profile (`profile.example.json`) and fictional example data.

For the email monitor, **create a dedicated email address used only for job applications** and connect only that one. Then the agent can only ever read job mail.

## Requirements

- [Claude Code](https://claude.com/claude-code)
- A browser automation tool Claude Code can drive in your own browser (for example Claude in Chrome), for reading blocked postings and filling forms
- A LaTeX engine: `pdflatex` (MacTeX, BasicTeX, TeX Live) or [`tectonic`](https://tectonic-typesetting.github.io/) (`brew install tectonic`)
- Poppler for `pdftotext` and `pdfinfo` (`brew install poppler`, `apt install poppler-utils`)
- Python 3.9+ (standard library only)
- Optional: a Gmail (or other mail) connector, for `check-email`

## Install

```bash
git clone https://github.com/khanmo97/job-applier ~/.claude/skills/job-applier
cd ~/.claude/skills/job-applier
python3 -m unittest discover tests      # checks the scripts and your LaTeX setup
```

Then in Claude Code, say **"job-applier setup"**. The agent copies `profile.example.json` to `profile.json` and fills it from your current resume. It reads each fact back to you and keeps only what you confirm, then asks once for your standing form answers and dealbreakers.

To keep your data outside the skill folder, set `JOB_APPLIER_HOME=/path/to/folder`. The profile, `data/` and `work/` then live there.

## Use

| Say | What happens |
|---|---|
| a job link, or `apply <url>` | Full flow: read, dedup, dealbreakers, tailor, audit, score, save, fill the form, log |
| `score <url>` | Tailor, audit and score only. Reports gaps and adds a "To do" row. Nothing is submitted or archived. |
| `status` | Marks Applied with no change for 30 days as No response, then summarizes |
| `check-email` | Reads new job mail and updates statuses it is confident about |
| `update <company> <status>` | Manual status change |

Statuses: To do, Applied, Assessment, Recruiter screen, Interviewing, Offer, Rejected, Withdrawn, No response.

Resumes are saved to `~/Downloads/Apps/<Company>/<Job Title>/resume/` (configurable in `profile.paths.archive`), together with the `.tex`, `score.json` and `posting.json`. The file name is always yours (for example `Jordan_Rivera_Resume.pdf`), never the company's.

### Dashboard

```bash
python3 scripts/build_dashboard.py    # writes dashboard/data.js from data/applications.json
open dashboard/index.html             # or double-click it
```

It shows status totals, a funnel, applications per week, response rate by role category and by optional role, time to first response, scores vs outcome, and a filterable table linking to each posting and resume folder. Without your own data it shows the fictional example.

## About the scores

**These are the tool's own estimates with a fixed formula, not a real ATS result.** The agent lists the posting's terms and marks each requirement met, partly or missing. `scripts/score.py` then computes:

- **ATS match** = matched term weight / total term weight. Weight 2 for terms in the required section, 1 for stack or nice-to-have terms. Terms are matched by regex against `pdftotext -layout` output of the actual PDF.
- **Fit** = required qualifications 50 + keyword coverage 25 (ATS × 0.25) + preferred qualifications 15 + level and years 10. Met = full credit, partly = half, missing = 0. **A "met" with no fact ID as evidence counts as "partly".**

All inputs are saved in `score.json` next to the resume, so you can see exactly what was counted and argue with it. Missing terms are labelled "you said you haven't used this", "confirmed, could be added" or "unknown, ask the user".

## Scripts

| Script | Purpose |
|---|---|
| `claims_audit.py resume.tex` | Fails on any resume claim not backed by a profile fact |
| `render.py resume.tex --png` | Compiles with pdflatex/tectonic and checks the resume is exactly one page |
| `score.py --pdf … --posting … --profile …` | ATS and fit scores; writes `score.json` |
| `archive.py --work … --company … --title …` | Saves a passed resume to the per-role folder and never overwrites |
| `tracker.py add / update / find-duplicate / mark-stale / status / list / export-csv` | `data/applications.json`. Records are never replaced, and each status change is appended to the history. |
| `email_match.py messages.json [--apply]` | Matches emails to records; classifies rejection / assessment / interview / confirmation |
| `build_dashboard.py` | Writes `dashboard/data.js` |

`examples/` has a sample posting, its `posting.json` and a tailored resume for the fictional profile. To try the scoring without a browser:

```bash
cp examples/resume.example.tex /tmp/Jordan_Rivera_Resume.tex
python3 scripts/render.py /tmp/Jordan_Rivera_Resume.tex
python3 scripts/claims_audit.py /tmp/Jordan_Rivera_Resume.tex --profile profile.example.json
python3 scripts/score.py --pdf /tmp/Jordan_Rivera_Resume.pdf --posting examples/posting.example.json --profile profile.example.json
```

## Before you publish a fork

Check that none of your own details are tracked:

```bash
JOB_APPLIER_PRIVATE_TERMS="Your Name,you@example.com,555-0100,Your Street,Your Employer" python3 -m unittest tests.test_acceptance.NoPersonalData
```

## Not included (yet)

Job search and batch applying, recruiter outreach, cover letters (if added, the same truth rule will apply).

## License

MIT
