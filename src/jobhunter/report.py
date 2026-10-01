"""reports/<YYYY-MM-DD>.md, one file per day. Output only - the database is the memory.

A day's file is rendered from every job whose report_date is that day (see
store.py), so it can be rebuilt at any time and a second run on the same day
simply adds to it.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime
from pathlib import Path

from .models import ELIGIBLE, LIKELY, NEEDS_REVIEW, REJECTED, SHORTLISTED
from .store import JobStore

_ELIGIBILITY_ORDER = {ELIGIBLE: 0, LIKELY: 1}

# Rejection groups, in report order: (code, heading, explanation).
_REJECT_GROUPS = [
    ("title_excluded", "Title has an excluded word",
     "The word is in `title_exclude` or `title_exclude_single_role` in `config/filters.json`."),
    ("other_stack", "Role built on another language",
     "The title names a language from `title_exclude_unless_python` and does not mention Python."),
    ("title_not_target", "Not a target role",
     "The title has none of the `title_include` keywords in `config/filters.json` "
     "(backend, software engineer, python, AI engineer, full stack, ...)."),
    ("too_senior", "Asks for too many years", "At or above `reject_if_required_yoe_at_least`."),
    ("not_remote", "Not remote", "Onsite or hybrid."),
    ("location_restricted", "Location does not include Lebanon", "The places the posting allows."),
    ("residency_required", "Description requires living elsewhere", "Quoted from the description."),
    ("timezone_restricted", "Time zones exclude Lebanon", "Lebanon is UTC+2 / UTC+3."),
    ("ai_cannot_hire", "AI check: cannot hire from Lebanon",
     "The rules could not tell, so Claude searched the web. Its quote was found word for word on the linked page; "
     "open the link if the job looks worth it."),
]
_KNOWN_CODES = {code for code, _, _ in _REJECT_GROUPS} | {"too_old"}


def _cell(text) -> str:
    return " ".join(str(text or "").split()).replace("|", "\\|")


def _salary(row: sqlite3.Row) -> str | None:
    low, high = row["salary_min"], row["salary_max"]
    if low or high:
        def fmt(v):
            return f"{v / 1000:.0f}k" if v and v >= 1000 else f"{v:g}" if v else "?"
        period = f"/{row['salary_period']}" if row["salary_period"] else ""
        return f"{row['salary_currency'] or ''} {fmt(low)}–{fmt(high)}{period}".strip()
    return row["salary_raw"]


def _job_block(n: int, row: sqlite3.Row, sightings: list[sqlite3.Row]) -> str:
    reasons = json.loads(row["eligibility_reasons_json"])
    relevance = json.loads(row["relevance_reasons_json"])
    skills = json.loads(row["skills_json"])
    contract = json.loads(row["contract_info_json"])
    details = [row["remote_status"]]
    if row["employment_type"]:
        details.append(row["employment_type"].replace("_", "-"))
    salary = _salary(row)
    if salary:
        details.append(salary)
    if row["required_yoe"]:
        details.append(f"{row['required_yoe']}+ yrs")
    details.append(f"posted {row['posted_at'][:10]}" if row["posted_at"] else "no posting date")
    details.append(f"found {row['first_seen'][:10]}")
    seen_on = ", ".join(dict.fromkeys(f"[{s['source']}]({s['source_url']})" for s in sightings if s["source_url"]))
    lines = [
        f"### {n}. {row['title']} — {row['company']}",
        f"- **Can hire from Lebanon:** {row['eligibility']} — {reasons[0] if reasons else ''}",
    ]
    lines += [f"  - {r}" for r in reasons[1:]]
    lines.append(f"- **Fit:** {row['fit_score']} · {'; '.join(relevance)}" + (f" · {', '.join(skills[:10])}" if skills else ""))
    lines.append(f"- **Details:** {' · '.join(details)}")
    if row["location_raw"]:
        lines.append(f"- **Location as posted:** {row['location_raw']}")
    if contract:
        lines.append(f"- **Hiring model hints:** {', '.join(contract)}")
    lines.append(f"- **Apply:** {row['application_url'] or row['source_url']}")
    lines.append(f"- **Seen on:** {seen_on or row['source']} · job #{row['id']}")
    return "\n".join(lines)


def _sort_key(row: sqlite3.Row):
    return (_ELIGIBILITY_ORDER.get(row["eligibility"], 2), -row["fit_score"], row["posted_at"] or "")


def _rejected_section(rows: list[sqlite3.Row], max_age: int | None) -> list[str]:
    out = [f"## Rejected ({len(rows)})", ""]
    if not rows:
        return out + ["_None._", ""]
    out += ["Kept in the database so they never come back as new. `jobhunter show <id>` prints the full reasoning.", ""]
    by_code: dict[str, list[sqlite3.Row]] = {}
    for row in rows:
        code = row["reject_code"] if row["reject_code"] in _KNOWN_CODES else "other"
        by_code.setdefault(code, []).append(row)
    for code, heading, explanation in _REJECT_GROUPS + [("other", "Other", "")]:
        group = sorted(by_code.get(code, []), key=lambda r: (r["reject_reason"] or "", r["title"]))
        if not group:
            continue
        out += [f"### {heading} ({len(group)})", ""]
        if explanation:
            out += [explanation, ""]
        show_reason = code != "title_not_target"  # the reason is identical for every row there
        out.append("| # | job | company | why |" if show_reason else "| # | job | company |")
        out.append("| --- | --- | --- | --- |" if show_reason else "| --- | --- | --- |")
        for row in group:
            link = row["application_url"] or row["source_url"]
            job = f"[{_cell(row['title'])}]({link})" if link else _cell(row["title"])
            cells = [str(row["id"]), job, _cell(row["company"])]
            if show_reason:
                cells.append(_cell(row["reject_reason"]))
            out.append("| " + " | ".join(cells) + " |")
        out.append("")
    too_old = by_code.get("too_old", [])
    if too_old:
        limit = f"{max_age} days" if max_age else "the age limit"
        out += [
            f"### Posted too long ago ({len(too_old)})",
            "",
            f"Posted more than {limit} before they were found. Not listed one by one; "
            "`jobhunter run --from <date>` covers an older range.",
            "",
        ]
    return out


def render(day: str, rows: list[sqlite3.Row], sightings: dict[int, list[sqlite3.Row]], summary: dict | None,
           generated_at: datetime, max_age: int | None = None) -> str:
    shortlisted = sorted((r for r in rows if r["status"] == SHORTLISTED), key=_sort_key)
    review = sorted((r for r in rows if r["status"] == NEEDS_REVIEW), key=_sort_key)
    rejected = [r for r in rows if r["status"] == REJECTED]

    out = [f"# Jobs — {date.fromisoformat(day):%A %d %B %Y}", ""]
    out += [f"{len(shortlisted)} shortlisted · {len(review)} need review · {len(rejected)} rejected", ""]
    stamp = f"Updated {generated_at.astimezone():%Y-%m-%d %H:%M}"
    if summary:
        stamp += f" by run {summary['run_id']}"
    out += [stamp + ". A job appears in one daily file only.", ""]

    out += [f"## Shortlisted ({len(shortlisted)})", ""]
    out += ["A target role, and the posting says (or strongly suggests) it can hire from Lebanon.", ""]
    out += [_job_block(i, r, sightings.get(r["id"], [])) + "\n" for i, r in enumerate(shortlisted, 1)] or ["_None._", ""]

    out += [f"## Needs review ({len(review)})", ""]
    out += ["A target role, but the posting does not say clearly whether Lebanon is allowed, or has no posting date. Check before applying.", ""]
    out += [_job_block(i, r, sightings.get(r["id"], [])) + "\n" for i, r in enumerate(review, 1)] or ["_None._", ""]

    out += _rejected_section(rejected, max_age)

    if summary:
        out += [f"## Sources (run {summary['run_id']})", "", "| source | listings | new | errors |", "| --- | --- | --- | --- |"]
        for name, s in sorted(summary.get("sources", {}).items()):
            out.append(f"| {name} | {s['fetched']} | {s['new']} | {len(s['errors'])} |")
        out.append("")
        ai = summary.get("ai_check")
        if ai:
            verdicts = ", ".join(f"{n} {v.replace('_', ' ')}" for v, n in sorted(ai["verdicts"].items())) or "none"
            out += [f"**AI check** ({ai['model']}): {ai['checked']} checked ({verdicts}), about ${ai['cost_usd']:.2f}", ""]
            out += [f"- {_cell(line)}" for line in ai["notes"] + ai["errors"]]
            out += [""] if ai["notes"] or ai["errors"] else []
        outreach = summary.get("outreach")
        if outreach:
            parts = []
            if outreach.get("contacts"):
                c = outreach["contacts"]
                parts.append(f"{c['found']} contacts found for {c['looked_up']} companies "
                             f"({c['credits']:g} Hunter credits, about ${c['cost_usd']:.2f})")
            if outreach.get("drafts"):
                parts.append(f"{len(outreach['drafts'])} email drafts")
            if outreach.get("cvs"):
                parts.append(f"{len(outreach['cvs'])} CVs tailored")
            if outreach.get("inbox"):
                i = outreach["inbox"]
                parts.append(f"inbox: {i['replies'] + i['probable']} replies, {i['bounces']} bounces")
            out += [f"**Outreach** (open `jobhunter serve`): {'; '.join(parts) or 'nothing new'}", ""]
            lines = outreach.get("notes", []) + outreach.get("errors", [])
            out += [f"- {_cell(line)}" for line in lines] + ([""] if lines else [])
        problems = [(name, e) for name, s in summary["sources"].items() for e in s["errors"]]
        notes = [(name, n) for name, s in summary["sources"].items() for n in s["notes"]]
        if problems:
            out += ["**Errors**", ""] + [f"- {name}: {_cell(e)}" for name, e in problems] + [""]
        if notes or summary.get("config_notes"):
            out += ["**Notes**", ""] + [f"- {name}: {n}" for name, n in notes]
            out += [f"- config: {n}" for n in summary.get("config_notes", [])] + [""]
    return "\n".join(out).rstrip() + "\n"


def write_report(store: JobStore, reports_dir: Path, day: str, summary: dict | None, now: datetime,
                 max_age: int | None = 30) -> Path:
    """(Re)write reports/<day>.md and mark its relevant jobs as reported."""
    rows = store.jobs_for_report(day)
    text = render(day, rows, store.sightings_for([r["id"] for r in rows]), summary, now, max_age)
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / f"{day}.md"
    path.write_text(text)
    store.mark_reported([r["id"] for r in rows if r["status"] in (SHORTLISTED, NEEDS_REVIEW)], now)
    return path
