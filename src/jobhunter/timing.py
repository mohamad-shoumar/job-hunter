"""How long each apply-job step takes, and what slowed it (the user's ask, 2026-11-24: to find what to
speed up). The skill marks each step as it starts (`jobhunter timing mark <job> <step>`): a step lasts
until the next mark, so a forgotten "end" can't break the table. A snag (something went wrong) is
written when it happens and its time, until the next mark, counts as lost; a note (a puzzle or a
guess) costs no time. Everything is kept on disk, so a long run that loses its context still adds up.

One JSONL file under data/ (not in git) holds every run. Nothing but `jobhunter timing report` reads it:
it never feeds a job's status, score or stage."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

STEPS = {  # the skill's steps, in the order the table shows them
    "setup": "Setup",
    "posting": "Posting",  # 1. check you can apply
    "tailor": "Tailor wait",  # 2. Tailor CV pressed, waiting for it
    "cv": "CV check",  # 2. checking it, the one-page fix
    "mirror": "Mirror",  # 2. the mirror-cv skill
    "form": "Form",  # 3.
    "linkedin": "LinkedIn",  # 4.
    "cover": "Cover letter",  # 5.
    "report": "Report",
    "waiting": "Waiting on you",  # never counted as working time
}
WAITING = "waiting"
STALE = timedelta(hours=12)  # a mark this long after a run's last line starts a new run (a forgotten `start`)


def log_file(root: Path) -> Path:
    return root / "data" / "apply_timing.jsonl"


def read(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        try:
            rec = json.loads(line)
            rec["at"] = datetime.fromisoformat(rec["at"])
        except (ValueError, KeyError, TypeError):
            continue  # a broken line costs only itself
        out.append(rec)
    return out


def _write(path: Path, rec: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps({**rec, "at": rec["at"].isoformat()}) + "\n")


def open_run(records: list[dict], now: datetime) -> str | None:
    """The run the next line belongs to: the newest one, unless it has been quiet for STALE."""
    if not records or now - records[-1]["at"] > STALE:
        return None
    return records[-1]["run"]


def start(path: Path, now: datetime) -> str:
    run = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    _write(path, {"run": run, "at": now, "kind": "start"})
    return run


def _run_for(path: Path, now: datetime) -> tuple[str, list[dict]]:
    records = read(path)
    run = open_run(records, now) or start(path, now)
    return run, [r for r in records if r["run"] == run]


def mark(path: Path, job: int | None, step: str, now: datetime) -> str:
    if step not in STEPS:
        raise ValueError(f"unknown step {step!r}: one of {', '.join(STEPS)}")
    run, _ = _run_for(path, now)
    _write(path, {"run": run, "at": now, "kind": "mark", "job": job, "step": step})
    return run


def _current_step(lines: list[dict], job: int | None) -> str | None:
    """The step the run is in: the last mark's, for the same job when there is one."""
    marks = [r for r in lines if r["kind"] in ("mark", "snag") and r.get("step")]
    same = [r for r in marks if r.get("job") == job]
    return (same or marks or [{}])[-1].get("step")


def snag(path: Path, job: int | None, text: str, fix: str | None, now: datetime) -> str:
    run, lines = _run_for(path, now)
    _write(path, {"run": run, "at": now, "kind": "snag", "job": job, "step": _current_step(lines, job),
                  "text": text.strip(), "fix": (fix or "").strip() or None})
    return run


def note(path: Path, job: int | None, text: str, now: datetime) -> str:
    run, lines = _run_for(path, now)
    _write(path, {"run": run, "at": now, "kind": "note", "job": job, "step": _current_step(lines, job),
                  "text": text.strip()})
    return run


@dataclass
class Segment:
    job: int | None
    step: str
    start: datetime
    end: datetime
    snag: dict | None = None  # the snag this time was lost to

    @property
    def length(self) -> timedelta:
        return self.end - self.start


def segments(lines: list[dict], now: datetime) -> list[Segment]:
    """Each mark or snag runs until the next one. The last runs until now while the run is open, else
    it ends at the run's last line (a report on an old run must not count the days since)."""
    lines = sorted(lines, key=lambda r: r["at"])
    if not lines:
        return []
    last = now if now - lines[-1]["at"] <= STALE else lines[-1]["at"]
    out: list[Segment] = []
    for rec in lines:
        if rec["kind"] not in ("mark", "snag"):
            continue
        if out:
            out[-1].end = rec["at"]
        out.append(Segment(rec.get("job"), rec.get("step") or "setup", rec["at"], last,
                           rec if rec["kind"] == "snag" else None))
    return out


def minutes(td: timedelta) -> str:
    secs = td.total_seconds()
    if secs <= 0:
        return ""
    if secs < 30:
        return "<1"
    return str(round(secs / 60))


def duration(td: timedelta) -> str:
    total = round(td.total_seconds() / 60)
    return f"{total // 60}h {total % 60:02d}m" if total >= 60 else f"{total}m"


def runs(records: list[dict]) -> list[str]:
    seen: dict[str, None] = {}
    for r in records:
        seen.setdefault(r["run"], None)
    return list(seen)


@dataclass
class Totals:
    working: timedelta
    waiting: timedelta
    lost: timedelta
    jobs: int


def totals(segs: list[Segment]) -> Totals:
    zero = timedelta()
    working = sum((s.length for s in segs if s.step != WAITING), zero)
    waiting = sum((s.length for s in segs if s.step == WAITING), zero)
    lost = sum((s.length for s in segs if s.snag and s.step != WAITING), zero)
    jobs = len({s.job for s in segs if s.job is not None})
    return Totals(working, waiting, lost, jobs)


def report(records: list[dict], now: datetime, run: str | None = None,
           labels: dict[int, str] | None = None, history: int = 5) -> str:
    """The run's job x step table in minutes, where the time went, its snags and notes, and the last
    few runs side by side. Code does the sums; the skill pastes this into its report."""
    labels = labels or {}
    all_runs = runs(records)
    if not all_runs:
        return "No timing recorded yet (`jobhunter timing start`)."
    run = run or all_runs[-1]
    if run not in all_runs:
        raise ValueError(f"no run {run!r}: one of {', '.join(all_runs[-history:])}")
    lines = [r for r in records if r["run"] == run]
    segs = segments(lines, now)
    t = totals(segs)

    def label(job: int | None) -> str:
        return "Run (no job)" if job is None else labels.get(job, f"#{job}")

    cell: dict[tuple, timedelta] = defaultdict(timedelta)
    lost: dict[int | None, timedelta] = defaultdict(timedelta)
    order: list[int | None] = []
    for s in segs:
        if s.step == WAITING:
            continue
        if s.job not in order:
            order.append(s.job)
        cell[s.job, s.step] += s.length
        if s.snag:
            lost[s.job] += s.length
    order.sort(key=lambda j: j is None)  # the run's own row (setup, report) last
    cols = [k for k in STEPS if k != WAITING and any(cell.get((j, k)) for j in order)]

    begun = lines[0]["at"]
    ended = segs[-1].end if segs else begun
    per_job = sum((v for (j, _), v in cell.items() if j is not None), timedelta())
    head = (f"**Run {begun:%Y-%m-%d %H:%M}-{ended:%H:%M} UTC:** {duration(t.working)} working"
            f"{f', {duration(t.waiting)} waiting on you' if t.waiting else ''}"
            f"{f', {duration(t.lost)} lost to snags' if t.lost else ''}; {t.jobs} job{'s' * (t.jobs != 1)}"
            f"{f', {duration(per_job / t.jobs)} a job' if t.jobs else ''}.")
    out = [head, ""]
    if order:
        out.append("Minutes per step:")
        out.append("")
        out.append("| Job | " + " | ".join(STEPS[c] for c in cols) + " | Lost | Total |")
        out.append("|---" * (len(cols) + 3) + "|")
        for j in order:
            row_total = sum((cell[j, c] for c in cols), timedelta())
            out.append(f"| {label(j)} | " + " | ".join(minutes(cell[j, c]) for c in cols)
                       + f" | {minutes(lost[j])} | {minutes(row_total)} |")
        by_step = {c: sum((cell[j, c] for j in order), timedelta()) for c in cols}
        out.append("| **Total** | " + " | ".join(minutes(by_step[c]) for c in cols)
                   + f" | {minutes(t.lost)} | {minutes(t.working)} |")
        out.append("")
        top = sorted(by_step.items(), key=lambda kv: kv[1], reverse=True)[:3]
        if t.working:
            out.append("Where the time went: " + ", ".join(
                f"{STEPS[c]} {duration(v)} ({round(100 * v / t.working)}%)" for c, v in top if v) + ".")
            out.append("")

    snags = [s for s in segs if s.snag]
    if snags:
        out.append("**Snags** (time until the next mark counts as lost):")
        for s in sorted(snags, key=lambda s: s.length, reverse=True):
            fix = f" → fix: {s.snag['fix']}" if s.snag.get("fix") else ""
            out.append(f"- {label(s.job)}, {STEPS.get(s.step, s.step)}, {minutes(s.length) or '0'} min: "
                       f"{s.snag['text']}{fix}")
        out.append("")
    notes = [r for r in lines if r["kind"] == "note"]
    if notes:
        out.append("**Notes** (puzzles and guesses):")
        for r in notes:
            out.append(f"- {label(r.get('job'))}, {STEPS.get(r.get('step'), r.get('step') or '-')}: {r['text']}")
        out.append("")

    past = all_runs[-history:]
    if len(past) > 1:
        out.append("Last runs:")
        out.append("")
        out.append("| Run | Jobs | Working | A job | Lost |")
        out.append("|---|---|---|---|---|")
        for r in past:
            rs = segments([x for x in records if x["run"] == r], now)
            rt = totals(rs)
            job_time = sum((s.length for s in rs if s.job is not None and s.step != WAITING), timedelta())
            out.append(f"| {r[:16].replace('T', ' ')} | {rt.jobs} | {duration(rt.working)} | "
                       f"{duration(job_time / rt.jobs) if rt.jobs else '-'} | {duration(rt.lost)} |")
        out.append("")
    return "\n".join(out).rstrip() + "\n"
