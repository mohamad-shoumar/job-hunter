# job-hunter

Finds newly posted remote software and AI jobs that can hire someone **living in
Lebanon**. It runs once a day, stores every job it sees in SQLite (rejected ones
too, so they never come back as "new"), and writes one Markdown report per day,
`reports/<YYYY-MM-DD>.md`, with the jobs you have not seen yet.

## Quick start

The project lives in `~/job-hunter` (`~/Desktop/job-hunter` is a shortcut to it;
see "Run it daily" for why it is not on the Desktop itself).

```sh
cd ~/job-hunter
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
cp .env.example .env          # optional: SERPAPI_API_KEY (Google Jobs), ANTHROPIC_API_KEY (AI check)
.venv/bin/jobhunter run       # about a minute
open reports/$(date +%F).md
```

| command | what it does |
| --- | --- |
| `jobhunter run` | fetch every source, store, classify new jobs, write today's `reports/<date>.md` |
| `jobhunter run --from 2026-09-20 --to 2026-09-27` | one report per day for that range (see below) |
| `jobhunter run --days 7` | the same for the last 7 days, today included |
| `jobhunter run --sources himalayas,lever` | only some sources |
| `jobhunter run --no-ai` | skip the AI check this time |
| `jobhunter check` | AI-check waiting "needs review" jobs, newest first (`--limit N`, `--recheck`, or job ids) |
| `jobhunter show <id>` | everything stored about one job and why it got its status (`-d` adds the description) |
| `jobhunter reclassify` | re-apply the rules to every stored job after you edit `config/filters.json`, and rebuild the day files that changed |
| `jobhunter report --date 2026-09-25` | rebuild one day's file from the database |
| `jobhunter stats` / `jobhunter sources` | counts by status and source / which sources are on |

## Reports

One file per day: `reports/2026-09-27.md`. It has three parts:

- **Shortlisted** and **Needs review**, each job with the reason it can (or might)
  hire from Lebanon, its fit, salary, dates and apply link.
- **Rejected**, every rejected job listed under the rule that rejected it, with
  the exact word, place or quote: `Title contains "manager"`,
  `Restricted to "Remote - US"`, `Asks for 10+ years of experience`. Jobs
  rejected only for being too old are counted, not listed.
- **Sources**, how many listings each source returned and any errors.

A second run on the same day adds to the same file. A job appears in one daily
file only, and never again after that.

**Date ranges.** `--from 2026-09-20 --to 2026-09-27` fetches every source
**once** and puts each listing posted in that range into the file for the day it
was posted, so you get one file per day. It does not fetch once per day: job
sites only show what is open *now*, so eight fetches would return the same
listings eight times (and use eight times the SerpApi credits). Two consequences:
jobs that already closed cannot be recovered, and sources that only keep their
latest jobs (Remote OK ~100, Remotive ~20) are thin for older days. Himalayas
keeps paging back until it reaches the start of the range, and Hacker News reads
every monthly thread the range touches. Jobs inside the range are kept even if
they are older than the usual 30-day limit.

## How a job is judged

Every decision is made by plain code and comes with a reason you can read in the
report or with `jobhunter show <id>`.

**1. Can they hire someone in Lebanon?** (`src/jobhunter/eligibility.py`)

| verdict | meaning | example |
| --- | --- | --- |
| eligible | the posting says so | "Worldwide", "Lebanon" in the country list |
| likely | a region or time zone that includes Lebanon, or an employer-of-record hint | "EMEA", "UTC-1 to UTC+3", "we hire through Deel" |
| unclear | remote, but nothing decisive, or two signals disagree | "Remote"; "Worldwide" in the location but "must be based in the UK" in the text |
| rejected | onsite/hybrid, or limited to places without Lebanon | "Remote - US", "Europe", "North America Only" |

"Remote" on its own never counts as international. "Europe" counts as a
restriction (it usually means EU residency), but "European time zones" does not.
Preferences ("US preferred") are ignored rather than treated as rules.

**2. Is it a role worth applying to?** (`src/jobhunter/relevance.py`,
`config/filters.json`) Title keywords to include and exclude, a cap on years of
experience, and a fit score from the skills in the posting (used only for
sorting). A posting that mentions Python is a `match`; without Python it is a
`maybe`.

**3. Is it new?** Jobs posted more than 30 days before they were found are
rejected, so the first run is not flooded with months-old listings.

The result is one status: **shortlisted** (eligible or likely), **needs review**
(unclear), or **rejected**.

**4. AI check, only for "needs review".** (`src/jobhunter/ai_check.py`,
`config/ai_check.json`) When the rules can't tell, Claude searches the web:
the company's own posting of the role (which often says "Remote - US" where the
job board said nothing) and its careers page. It must answer with an exact quote
and the page it came from. The code then looks for that quote, word for word, in
the job description or in the page text the API returned. Only a found quote
counts:

| AI answer | quote found | result |
| --- | --- | --- |
| cannot hire | yes | rejected, listed under "AI check: cannot hire from Lebanon" with the quote and link |
| can hire | yes | shortlisted as `likely` |
| anything else | | stays in "needs review", with what the AI found attached |

It runs at the end of `jobhunter run` for that day's new "needs review" jobs
(at most `max_jobs_per_run`), and never on a job the rules already decided. Each
job is checked once; results are stored, so `reclassify` keeps them. It needs
`ANTHROPIC_API_KEY` in `.env` and costs roughly $0.10 to $0.30 per job with the
default model (runs print an estimate). A found quote proves the text exists,
not that the AI read it right, so the link is always shown.

## Only new jobs

The SQLite database (`data/jobs.sqlite`) is the memory; reports are just output
and can be rebuilt from it at any time. Each job belongs to exactly one day's
report.

The same job often appears on several sites. Listings are matched, strongest
key first (details in `src/jobhunter/identity.py`):

1. the same source and listing id again;
2. the same ATS posting (Greenhouse/Lever/Ashby/Workable id found in any of its
   links), e.g. a We Work Remotely listing that links to the company's Greenhouse page;
3. the same normalized company + title within 60 days, unless both carry
   *different* ATS ids (one company posting "Backend Engineer" for EMEA and for
   the US is two jobs).

Every sighting is kept in the `sightings` table, so the report lists all the
sites a job was seen on.

## Sources

Checked on 2026-09-25, SerpApi on 2026-09-27.

| source | how | notes |
| --- | --- | --- |
| Lever, Ashby | public ATS APIs | one entry per company board in `config/sources.json` |
| Himalayas | public API | queried with `country=LB`: returns jobs that list Lebanon or list no countries at all. "No countries" often means Himalayas does not know (it shows "Worldwide" for US-only roles), so those count as no location |
| Remotive | public API | returns its latest ~20 jobs; ignores search terms |
| Remote OK | public API | latest ~100 jobs; `queries` filter them locally |
| We Work Remotely | RSS | back-end and full-stack feeds |
| Hacker News | Algolia API | latest "Who is hiring?" thread, one job per role |
| NoDesk | RSS | engineering feed, ~10 jobs |
| Company careers pages | HTML | reads schema.org JobPosting data when the page has it |
| Google Jobs (SerpApi) | API, key in `.env` | covers LinkedIn postings legally. Free plan: 250 searches/month; 7 queries a day uses ~210. Most results land in "needs review": Google shows remote jobs as "Anywhere" and the reposting sites rarely say who can apply |
| Greenhouse | removed | the configured boards only had US/Canada or single-country remote roles; the adapter is kept for a company that hires internationally |
| HiringCafe | not built | blocks automated requests (HTTP 403) |
| Remote100k | not built | HTML only, no feed |
| LinkedIn, Wellfound, Work at a Startup | not built | bot walls, login, or terms forbid scraping |

Board fixes made while testing: Circle.so is on Ashby (`circle`), Kraken moved to
Ashby (`kraken.com`), and Token Metrics' Lever board no longer exists (disabled).

## Config

- `config/sources.json` — boards and feeds. Any entry can take `"enabled": false`.
- `config/filters.json` — title keywords, experience cap, posting age, fit weights.
  Run `jobhunter reclassify` after changing it.
- `.env` — `SERPAPI_API_KEY`. Not in git; keep it that way.
- `profile/master_profile.md` — the facts about you. **CV tailoring may reorder,
  emphasize, rephrase and remove; it must never add anything that is not in this file.**

## Run it daily

A macOS launchd job (`scripts/local.jobhunter.daily.plist`, installed in
`~/Library/LaunchAgents/`) runs `scripts/run_daily.sh` every day at 09:00 local
time. If the Mac is asleep at 09:00 it runs on wake; if the Mac is off, that day
is skipped. Output goes to `data/run.log`; launchd's own errors go to
`~/Library/Logs/jobhunter.log`.

```sh
launchctl kickstart gui/$(id -u)/local.jobhunter.daily    # run now
launchctl print gui/$(id -u)/local.jobhunter.daily | grep "last exit"
launchctl bootout gui/$(id -u)/local.jobhunter.daily      # stop the schedule
```

To change the time, edit `Hour`/`Minute` in the plist, copy it to
`~/Library/LaunchAgents/` again, then `bootout` and `bootstrap` it.

The project is not inside `~/Desktop` on purpose: macOS blocks background jobs
from reading Desktop, Documents and Downloads ("Operation not permitted") unless
the program is given Full Disk Access.

## Tests

```sh
.venv/bin/pytest
```

Adapters are tested against trimmed real responses in `tests/fixtures/`.

## Not built yet

- **LLM review of "needs review" jobs.** The rules stop at what they can quote;
  the `unclear` jobs are where a model reading the whole posting (and the
  company's hiring pages) adds value.
- **CV tailoring** from `profile/master_profile.md`.
- More sources: the YC jobs page, HN job stories, Remote100k.
