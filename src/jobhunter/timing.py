"""How long each apply-job step takes, and what slowed it (the user's ask, 2026-11-24: to find what to
speed up). The skill marks each step as it starts (`jobhunter timing mark <job> <step>`): a step lasts
until the next mark, so a forgotten "end" can't break the table. A snag (something went wrong) is
written when it happens and its time, until the next mark, counts as lost; a note (a puzzle or a
guess) costs no time. Everything is kept on disk, so a long run that loses its context still adds up.

One JSONL file under data/ (not in git) holds every run. Nothing but `jobhunter timing report` reads it:
it never feeds a job's status, score or stage.

The report also says (the user's ask, 2026-11-25), each from where it is already recorded:
- why jobs were skipped: the app's own skips in the run's window (the Skip button's reason), so a
  skip the skill forgot to mark still counts;
- minutes per form site: the `form` mark carries the form page (`--site`), since a job's stored link
  is often a job board's, not the form's;
- what the run cost: tool calls and tokens from Claude Code's session log (sessionlog.py), counted
  only inside working steps; the totals are kept in data/apply_timing_costs.json, since Claude Code
  deletes old session logs;
- how well mirroring worked: the posting's must-haves in the CV's top part before and after
  (skimzone.py scores them; `jobhunter timing mirror` writes them into the open run, never opening one)."""

from __future__ import annotations

import json
from bisect import bisect_left, bisect_right
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

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


# A form page's host -> the site's name. Anything else prints as its own host.
SITES = {
    "greenhouse.io": "Greenhouse", "lever.co": "Lever", "ashbyhq.com": "Ashby", "myworkdayjobs.com": "Workday",
    "workable.com": "Workable", "linkedin.com": "LinkedIn Easy Apply", "smartrecruiters.com": "SmartRecruiters",
    "dover.com": "Dover", "jobylon.com": "Jobylon", "careers-page.com": "Manatal", "bamboohr.com": "BambooHR",
    "teamtailor.com": "Teamtailor", "personio.de": "Personio", "personio.com": "Personio",
    "recruitee.com": "Recruitee", "successfactors.com": "SuccessFactors", "successfactors.eu": "SuccessFactors",
    "breezy.hr": "Breezy", "jazzhr.com": "JazzHR", "applytojob.com": "JazzHR", "icims.com": "iCIMS",
    "rippling.com": "Rippling", "pinpointhq.com": "Pinpoint", "join.com": "JOIN", "welcomekit.co": "Welcome to the Jungle",
}


def site_name(text: str | None) -> str | None:
    """The form's site from its page's URL or host ("https://jobs.lever.co/x/1" -> "Lever"); a plain
    name the skill typed ("greenhouse") is matched too, else kept as typed."""
    text = (text or "").strip()
    if not text:
        return None
    host = (urlparse(text if "//" in text else "//" + text).hostname or text).lower().removeprefix("www.")
    for domain, name in SITES.items():
        if host == domain or host.endswith("." + domain) or host == domain.split(".")[0] or name.lower() == host:
            return name
    return host


def log_file(root: Path) -> Path:
    return root / "data" / "apply_timing.jsonl"


def costs_file(root: Path) -> Path:
    return root / "data" / "apply_timing_costs.json"


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


def mark(path: Path, job: int | None, step: str, now: datetime, site: str | None = None) -> str:
    """`site`: the form page (its URL or host), on a `form` mark, for the minutes per form site."""
    if step not in STEPS:
        raise ValueError(f"unknown step {step!r}: one of {', '.join(STEPS)}")
    run, _ = _run_for(path, now)
    rec = {"run": run, "at": now, "kind": "mark", "job": job, "step": step}
    if name := site_name(site):
        rec["site"] = name
    _write(path, rec)
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


def mirror(path: Path, job: int, stage: str, terms: list[str], top: list[str], on_cv: list[str],
           now: datetime) -> str | None:
    """A mirror's score (`before` the edit or `after` the rebuild) into the open run. None, and nothing
    written, when no run is open: mirror-cv run on its own is not an apply-job run."""
    if stage not in ("before", "after"):
        raise ValueError(f"unknown stage {stage!r}: before or after")
    run = open_run(read(path), now)
    if run is not None:
        _write(path, {"run": run, "at": now, "kind": "mirror", "job": job, "stage": stage, "terms": terms,
                      "top": top, "on_cv": on_cv})
    return run


@dataclass
class Segment:
    job: int | None
    step: str
    start: datetime
    end: datetime
    snag: dict | None = None  # the snag this time was lost to
    site: str | None = None  # a form mark's site

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
                           rec if rec["kind"] == "snag" else None, rec.get("site")))
    return out


def run_lines(records: list[dict], run: str) -> list[dict]:
    return [r for r in records if r["run"] == run]


def run_segments(records: list[dict], run: str, now: datetime) -> list[Segment]:
    return segments(run_lines(records, run), now, newest=run == runs(records)[-1])


def window(records: list[dict], run: str, now: datetime) -> tuple[datetime, datetime]:
    """When the run began, and when its work ended: the end of its last working step (now, for the
    newest run while it works), never the time it then waits on the user. A card skipped by hand
    after the run, or a later reply in the same session, is not the run's."""
    lines = sorted(run_lines(records, run), key=lambda r: r["at"])
    working = [s for s in run_segments(records, run, now) if s.step != WAITING]
    return lines[0]["at"], (working[-1].end if working else lines[-1]["at"])


@dataclass
class Turn:
    """One model reply in the run's Claude Code session (sessionlog.py)."""
    at: datetime
    tool_calls: int
    tokens_in: int  # everything the reply read: fresh, written to the cache, read from it
    tokens_cached: int  # of those, read from the cache
    tokens_out: int
    marks: bool = False  # it calls `jobhunter timing mark`: its other calls are the new step's first action


@dataclass
class Cost:
    tool_calls: int = 0
    turns: int = 0
    tokens_in: int = 0
    tokens_cached: int = 0
    tokens_out: int = 0

    def add(self, t: Turn) -> None:
        self.tool_calls += t.tool_calls
        self.turns += 1
        self.tokens_in += t.tokens_in
        self.tokens_cached += t.tokens_cached
        self.tokens_out += t.tokens_out


MARK_LAG = timedelta(seconds=60)  # a reply is written before the mark it carries runs


def _working(segs: list[Segment], turns: list[Turn]) -> list[tuple[Segment, Turn]]:
    """Each reply inside a working step: not before the first mark, not while waiting on the user, not
    after the run's end (a report rewritten after the run is not the run's cost). A reply that carries
    a mark (with the step's first action, as the skill asks) belongs to the step it starts."""
    starts = [s.start for s in segs]
    out = []
    for t in turns:
        i = bisect_right(starts, t.at) - 1
        k = bisect_left(starts, t.at)
        if t.marks and k < len(segs) and segs[k].start - t.at <= MARK_LAG:
            i = k
        if i >= 0 and t.at <= segs[i].end and segs[i].step != WAITING:
            out.append((segs[i], t))
    return out


def cost(segs: list[Segment], turns: list[Turn]) -> Cost:
    c = Cost()
    for _, t in _working(segs, turns):
        c.add(t)
    return c


def load_costs(path: Path) -> dict[str, Cost]:
    try:
        return {run: Cost(**v) for run, v in json.loads(path.read_text()).items()}
    except (OSError, ValueError, TypeError):
        return {}


def save_costs(path: Path, costs: dict[str, Cost]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({run: asdict(c) for run, c in sorted(costs.items())}, indent=1) + "\n")


def cell(text: str) -> str:
    """A name in a Markdown table cell: a "|" in it would end the cell ("EMBL | EBI")."""
    return text.replace("|", "/")


def tokens(n: float) -> str:
    return f"{n / 1e6:.1f}M" if n >= 1e6 else f"{n / 1e3:.0f}k" if n >= 1e3 else f"{n:.0f}"


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


@dataclass
class _Run:
    """One run added up: the base of the report and of each Earlier runs row."""
    lines: list[dict]
    segs: list[Segment]
    totals: Totals
    per_job: dict[int, timedelta]
    steps_of: dict[int, set[str]]
    outcome: dict[int, str]  # every job the run touched, the app's skips included
    timed_skips: int  # skipped jobs with a mark of their own

    @property
    def ready(self) -> int:
        return sum(1 for v in self.outcome.values() if v != SKIPPED)


def _add_up(records: list[dict], run: str, now: datetime, app_skips: dict[int, tuple[str, str]]) -> _Run:
    lines = run_lines(records, run)
    segs = run_segments(records, run, now)
    per_job: dict[int, timedelta] = defaultdict(timedelta)
    steps_of: dict[int, set[str]] = defaultdict(set)
    for s in segs:
        if s.job is not None and s.step != WAITING:
            per_job[s.job] += s.length
            steps_of[s.job].add(s.step)
    # A job skipped in the app is skipped, whatever steps it got first (a form the posting's own
    # question ruled out); the app's skips with no mark count too: the skill's marks can miss one.
    outcome = {j: SKIPPED if j in app_skips else result(steps_of[j]) for j in per_job}
    outcome.update({j: SKIPPED for j in app_skips if j not in outcome})
    timed = sum(1 for j in per_job if outcome[j] == SKIPPED)
    return _Run(lines, segs, totals(segs), per_job, steps_of, outcome, timed)


def report(records: list[dict], now: datetime, run: str | None = None,
           labels: dict[int, str] | None = None, history: int = 5,
           skips: dict[str, dict[int, tuple[str, str]]] | None = None,
           turns: dict[str, list[Turn]] | None = None, costs: dict[str, Cost] | None = None) -> str:
    """A short summary of the run: one headline, what an application cost, where the time went (one
    row per step), the time each job took (skipped jobs on one row), why jobs were skipped, minutes
    per form site, mirroring before and after, the snags and notes, and earlier runs. Code does the
    sums; the skill pastes this into its report.

    `skips`: {run: {job: (reason, company)}}, the app's skips in each run's window. `turns`: {run: the
    replies in its window}, from the session log. `costs`: {run: Cost} kept from earlier reports, for
    runs whose session log is gone."""
    labels = labels or {}
    skips, turns, costs = skips or {}, turns or {}, costs or {}
    all_runs = runs(records)
    if not all_runs:
        return "No timing recorded yet (`jobhunter timing start`)."
    run = run or all_runs[-1]
    if run not in all_runs:
        raise ValueError(f"no run {run!r}: one of {', '.join(all_runs[-history:])}")
    app_skips = skips.get(run, {})
    r = _add_up(records, run, now, app_skips)
    lines, segs, t, outcome = r.lines, r.segs, r.totals, r.outcome

    def label(job: int | None) -> str:
        return "the run itself" if job is None else cell(labels.get(job, f"#{job}"))

    def cost_of(name: str, run_segs: list[Segment]) -> Cost | None:
        return cost(run_segs, turns[name]) if name in turns else costs.get(name)

    count = {k: sum(1 for v in outcome.values() if v == k) for k in (FILLED, READY, SKIPPED)}
    begun = lines[0]["at"]
    ended = segs[-1].end if segs else begun
    parts = [HEADLINE[k].format(n=count[k], s="s" * (count[k] != 1), v="s" * (count[k] == 1))
             for k in (FILLED, READY, SKIPPED) if count[k]]
    if count[SKIPPED] and r.timed_skips != count[SKIPPED]:
        parts[-1] += f" ({r.timed_skips} timed)"
    n = len(outcome)
    head = (f"**This run** ({begun:%Y-%m-%d %H:%M}-{ended:%H:%M} UTC): {minutes(t.working)} min of work for "
            f"{n} job{'s' * (n != 1)}{': ' + ', '.join(parts) if parts else ''}.")
    if t.lost:
        head += f" Snags cost {minutes(t.lost)} min."
    if t.waiting:
        head += f" Waiting on you: {minutes(t.waiting)} min (not counted)."
    out = [head, ""]

    c = cost_of(run, segs)
    if c:
        cached = f" ({round(100 * c.tokens_cached / c.tokens_in)}% from the cache)" if c.tokens_in else ""
        out += [f"**Cost**: {c.tool_calls} tool calls in {c.turns} replies, {tokens(c.tokens_in)} tokens read"
                f"{cached}, {tokens(c.tokens_out)} written.", ""]
    if r.ready:
        each = [f"{minutes(t.working / r.ready)} min"]
        if c:
            each += [f"{c.tool_calls / r.ready:.0f} tool calls", f"{tokens(c.tokens_in / r.ready)} tokens read"]
        out += [f"**Per application ready** ({r.ready}: forms filled or waiting on your sign-in): "
                f"{', '.join(each)}.", ""]

    per_step: dict[str, timedelta] = defaultdict(timedelta)
    for s in segs:
        if s.step != WAITING:
            per_step[s.step] += s.length
    calls: dict[str, int] = defaultdict(int)
    for s, turn in _working(segs, turns.get(run, [])):
        calls[s.step] += turn.tool_calls
    if per_step:
        with_calls = run in turns
        out += ["**Where the time went**", "",
                "| Step | Minutes | Share |" + (" Tool calls |" if with_calls else ""),
                "|---|---|---|" + ("---|" if with_calls else "")]
        for step, v in sorted(per_step.items(), key=lambda kv: kv[1], reverse=True):
            if v < timedelta(seconds=3):
                continue  # a step that took (almost) no time, such as the run's last mark, gets no row
            share = round(100 * v / t.working) if t.working else 0
            out.append(f"| {STEPS.get(step, step)} | {minutes(v)} | {share}% |"
                       + (f" {calls[step]} |" if with_calls else ""))
        out.append("")

    if outcome:
        out += ["**Time per job**", "", "| Job | Minutes | Result |", "|---|---|---|"]
        order = list(dict.fromkeys([*(s.job for s in segs if s.job is not None), *app_skips]))
        for j in order:
            if outcome[j] != SKIPPED:
                out.append(f"| {label(j)} | {minutes(r.per_job[j])} | {outcome[j]} |")
        skipped = [j for j in order if outcome[j] == SKIPPED]
        if skipped:
            timed = [j for j in skipped if j in r.per_job]
            total = sum((r.per_job[j] for j in timed), timedelta())
            name = f"{len(skipped)} skipped job{'s' * (len(skipped) != 1)}"
            if len(timed) != len(skipped):
                name += f" ({len(timed)} timed)"
            spent = f"{minutes(total)} ({minutes(total / len(timed))} each)" if timed else "-"
            out.append(f"| {name} | {spent} | {SKIPPED} |")
        out.append("")

    if app_skips:
        by_reason: dict[str, list[str]] = defaultdict(list)
        for reason, company in app_skips.values():
            by_reason[reason or "No reason given"].append(company)
        out += [f"**Why jobs were skipped** ({len(app_skips)} of {n} jobs looked at, "
                f"{round(100 * len(app_skips) / n)}%, from the app)", "",
                "| Reason | Jobs | Companies |", "|---|---|---|"]
        for reason, companies in sorted(by_reason.items(), key=lambda kv: (-len(kv[1]), kv[0])):
            out.append(f"| {reason} | {len(companies)} | {', '.join(cell(c) for c in companies)} |")
        out.append("")

    site_of = {s.job: s.site for s in segs if s.step == "form" and s.site}
    if site_of:
        form_time: dict[str, timedelta] = defaultdict(timedelta)
        forms: dict[str, set[int]] = defaultdict(set)
        for s in segs:
            if s.step == "form" and s.job is not None:
                site = site_of.get(s.job, "not recorded")
                form_time[site] += s.length
                forms[site].add(s.job)
        out += ["**Filling the form, by site**", "", "| Site | Forms | Minutes per form |", "|---|---|---|"]
        for site, v in sorted(form_time.items(), key=lambda kv: kv[1] / len(forms[kv[0]]), reverse=True):
            out.append(f"| {site} | {len(forms[site])} | {minutes(v / len(forms[site]))} |")
        out.append("")

    mirrors: dict[int, dict[str, dict]] = defaultdict(dict)
    for rec in lines:
        if rec["kind"] == "mirror":
            mirrors[rec["job"]][rec["stage"]] = rec  # the last of each stage wins
    if mirrors:
        out += ["**Mirroring** (the posting's must-haves in the CV's top part: the headline, the first 4 "
                "skills of each row, the newest role's first 3 bullets)", "",
                "| Job | Must-haves | Top part before | After | Not on the CV |", "|---|---|---|---|---|"]
        for j, st in mirrors.items():
            after, before = st.get("after"), st.get("before")
            base = after or before
            missing = [x for x in base["terms"] if x not in base["on_cv"]] if after else []
            out.append(f"| {label(j)} | {len(base['terms'])} | {len(before['top']) if before else '-'} | "
                       f"{len(after['top']) if after else '-'} | {', '.join(missing) or '-'} |")
        out.append("")

    snags = sorted((s for s in segs if s.snag), key=lambda s: s.length, reverse=True)
    if snags:
        out.append("**Snags** (what went wrong, the minutes it cost, the fix)")
        for s in snags:
            fix = f" Fix: {s.snag['fix']}" if s.snag.get("fix") else ""
            spent = f", {minutes(s.length)} min" if s.length >= timedelta(seconds=6) else ""
            out.append(f"- {label(s.job)}{spent}: {s.snag['text']}.{fix}")
        out.append("")
    notes = [x for x in lines if x["kind"] == "note"]
    if notes:
        out.append("**Notes** (puzzles and guesses)")
        out += [f"- {label(x.get('job'))}: {x['text']}" for x in notes]
        out.append("")

    past = all_runs[-history:]
    if len(past) > 1:
        out += ["**Earlier runs**", "",
                "| Run | Applications ready | Skipped | Minutes | Minutes each | Tool calls each |",
                "|---|---|---|---|---|---|"]
        for name in past:
            pr = _add_up(records, name, now, skips.get(name, {}))
            pc = cost_of(name, pr.segs)
            skipped = len(pr.outcome) - pr.ready
            out.append(f"| {name[:16].replace('T', ' ')} | {pr.ready} | {skipped} | {minutes(pr.totals.working)} | "
                       f"{minutes(pr.totals.working / pr.ready) if pr.ready else '-'} | "
                       f"{f'{pc.tool_calls / pr.ready:.0f}' if pc and pr.ready else '-'} |")
        out.append("")
    return "\n".join(out).rstrip() + "\n"
