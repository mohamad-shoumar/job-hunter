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

STEPS = {  # the skill's steps, in its order, with the plain name the report prints
    "setup": "Setup",
    "posting": "Checking the posting",  # 1. check you can apply
    "tailor": "Waiting for Tailor CV",  # 2. Tailor CV pressed
    "cv": "Checking the CV",  # 2. the one-page fix
    "mirror": "Mirroring the CV",  # 2. the mirror-cv skill
    "form": "Filling the form",  # 3.
    "linkedin": "Finding the LinkedIn contact",  # 4.
    "cover": "Writing the cover letter",  # 5.
    "report": "Writing the report",
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


def segments(lines: list[dict], now: datetime, newest: bool = True) -> list[Segment]:
    """Each mark or snag runs until the next one. The last runs until now only in the newest run, while
    it is open; any other run ends at its own last line (a morning run cut off mid-form must not count
    the hours until the next run, nor a report on an old run the days since)."""
    lines = sorted(lines, key=lambda r: r["at"])
    if not lines:
        return []
    last = now if newest and now - lines[-1]["at"] <= STALE else lines[-1]["at"]
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
    """Minutes with one decimal ("2.5"), so a short step reads as a number, not "<1"."""
    return f"{max(td.total_seconds(), 0) / 60:.1f}"


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


FILLED, READY, SKIPPED = "form filled", "needs your sign-in", "skipped"
HEADLINE = {FILLED: "{n} form{s} filled", READY: "{n} need{v} your sign-in", SKIPPED: "{n} skipped"}


def result(steps: set[str]) -> str:
    """What happened to a job, from the steps it got: a form filled, a CV and contact ready for a form
    only the user can open (a sign-in), or skipped at the posting check."""
    if "form" in steps:
        return FILLED
    if steps <= {"posting"}:
        return SKIPPED
    return READY


def report(records: list[dict], now: datetime, run: str | None = None,
           labels: dict[int, str] | None = None, history: int = 5) -> str:
    """A short summary of the run: one headline, where the time went (one row per step), the time each
    job took (skipped jobs on one row), the snags with their fixes, the notes, and earlier runs. Code
    does the sums; the skill pastes this into its report."""
    labels = labels or {}
    all_runs = runs(records)
    if not all_runs:
        return "No timing recorded yet (`jobhunter timing start`)."
    run = run or all_runs[-1]
    if run not in all_runs:
        raise ValueError(f"no run {run!r}: one of {', '.join(all_runs[-history:])}")
    lines = [r for r in records if r["run"] == run]
    segs = segments(lines, now, newest=run == all_runs[-1])
    t = totals(segs)

    def label(job: int | None) -> str:
        return "the run itself" if job is None else labels.get(job, f"#{job}")

    per_step: dict[str, timedelta] = defaultdict(timedelta)
    per_job: dict[int, timedelta] = defaultdict(timedelta)
    steps_of: dict[int, set[str]] = defaultdict(set)
    for s in segs:
        if s.step == WAITING:
            continue
        per_step[s.step] += s.length
        if s.job is not None:
            per_job[s.job] += s.length
            steps_of[s.job].add(s.step)
    outcome = {j: result(steps_of[j]) for j in per_job}
    count = {r: sum(1 for v in outcome.values() if v == r) for r in (FILLED, READY, SKIPPED)}

    begun = lines[0]["at"]
    ended = segs[-1].end if segs else begun
    parts = [HEADLINE[r].format(n=count[r], s="s" * (count[r] != 1), v="s" * (count[r] == 1))
             for r in (FILLED, READY, SKIPPED) if count[r]]
    head = (f"**This run** ({begun:%Y-%m-%d %H:%M}-{ended:%H:%M} UTC): {minutes(t.working)} min of work for "
            f"{t.jobs} job{'s' * (t.jobs != 1)}{': ' + ', '.join(parts) if parts else ''}.")
    if t.lost:
        head += f" Snags cost {minutes(t.lost)} min."
    if t.waiting:
        head += f" Waiting on you: {minutes(t.waiting)} min (not counted)."
    out = [head, ""]

    if per_step:
        out += ["**Where the time went**", "", "| Step | Minutes | Share |", "|---|---|---|"]
        for step, v in sorted(per_step.items(), key=lambda kv: kv[1], reverse=True):
            if not v:
                continue  # a step that took no time (the run's last mark) gets no row
            share = round(100 * v / t.working) if t.working else 0
            out.append(f"| {STEPS.get(step, step)} | {minutes(v)} | {share}% |")
        out.append("")

    if per_job:
        out += ["**Time per job**", "", "| Job | Minutes | Result |", "|---|---|---|"]
        order = [j for j in dict.fromkeys(s.job for s in segs if s.job is not None)]
        for j in order:
            if outcome[j] != SKIPPED:
                out.append(f"| {label(j)} | {minutes(per_job[j])} | {outcome[j]} |")
        skipped = [j for j in order if outcome[j] == SKIPPED]
        if skipped:
            total = sum((per_job[j] for j in skipped), timedelta())
            out.append(f"| {len(skipped)} skipped job{'s' * (len(skipped) != 1)} | {minutes(total)} "
                       f"({minutes(total / len(skipped))} each) | {SKIPPED} |")
        out.append("")

    snags = sorted((s for s in segs if s.snag), key=lambda s: s.length, reverse=True)
    if snags:
        out.append("**Snags** (what went wrong, the minutes it cost, the fix)")
        for s in snags:
            fix = f" Fix: {s.snag['fix']}" if s.snag.get("fix") else ""
            cost = f", {minutes(s.length)} min" if s.length >= timedelta(seconds=6) else ""
            out.append(f"- {label(s.job)}{cost}: {s.snag['text']}.{fix}")
        out.append("")
    notes = [r for r in lines if r["kind"] == "note"]
    if notes:
        out.append("**Notes** (puzzles and guesses)")
        out += [f"- {label(r.get('job'))}: {r['text']}" for r in notes]
        out.append("")

    past = all_runs[-history:]
    if len(past) > 1:
        out += ["**Earlier runs**", "", "| Run | Jobs | Minutes | Minutes a job |", "|---|---|---|---|"]
        for r in past:
            rs = segments([x for x in records if x["run"] == r], now, newest=r == all_runs[-1])
            rt = totals(rs)
            job_time = sum((s.length for s in rs if s.job is not None and s.step != WAITING), timedelta())
            out.append(f"| {r[:16].replace('T', ' ')} | {rt.jobs} | {minutes(rt.working)} | "
                       f"{minutes(job_time / rt.jobs) if rt.jobs else '-'} |")
        out.append("")
    return "\n".join(out).rstrip() + "\n"
