# job-hunter

Finds newly posted remote software and AI jobs that can hire someone **living in
Lebanon**. It runs once a day, stores every job it sees in SQLite (rejected ones
too, so they never come back as "new"), and writes one Markdown report per day,
`reports/<YYYY-MM-DD>.md`, with the jobs you have not seen yet.

`jobhunter serve` opens a local web app on top of the same database. It shows
who to email about each job (with proof), writes a short cold email, sends it
from your Gmail when you click Send, and tracks every application: replies,
bounces, follow-ups and ghosting. See "Outreach and tracking".

## Quick start

The project lives in `~/job-hunter` (`~/Desktop/job-hunter` is a shortcut to it;
see "Run it daily" for why it is not on the Desktop itself).

```sh
cd ~/job-hunter
python3 -m venv .venv && .venv/bin/pip install -e ".[dev,web]"
cp .env.example .env          # optional keys: see "Outreach and tracking" and "Config"
.venv/bin/jobhunter run       # about a minute
open reports/$(date +%F).md
.venv/bin/jobhunter serve     # the web app, http://127.0.0.1:8765
```

| command | what it does |
| --- | --- |
| `jobhunter run` | fetch every source, store, classify new jobs, write today's `reports/<date>.md` |
| `jobhunter run --from 2026-09-20 --to 2026-09-27` | one report per day for that range (see below) |
| `jobhunter run --days 7` | the same for the last 7 days, today included |
| `jobhunter run --sources himalayas,lever` | only some sources |
| `jobhunter run --no-ai` | no Claude calls this time (AI check, email drafts) |
| `jobhunter run --no-outreach` | skip contact lookups, drafts and the inbox check |
| `jobhunter serve` | the web app: jobs, who to email, drafts, sending, tracking (`--port`, `--no-open`) |
| `jobhunter contacts` | find who to email for shortlisted jobs without a contact, best fit first (`--limit N`, `--no-claude`, or job ids) |
| `jobhunter tailor <id>` | a CV tailored to that job, in `resume/output/` (the daily run does new shortlisted jobs) |
| `jobhunter rebuild-cv <id>` | after you edit a job's CV text in `resume/versions/`, rebuild its PDF (no AI) and list lines that say more than your profile |
| `jobhunter cover <id>` | a cover letter for that job, next to its CV (the daily run does these too) |
| `jobhunter inbox` | check Gmail for replies and bounces (the daily run does this too) |
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

## Outreach and tracking

`jobhunter serve` opens `http://127.0.0.1:8765`. Tabs: **Today** (replies to
answer, follow-ups due, new jobs to triage), **Jobs** (the list; click one for
everything about it), **Pipeline** (every tracked job by stage) and **Stats**.

**Who to email** (`src/jobhunter/contacts.py`, per company, looked up once):

| company size | who first | then |
| --- | --- | --- |
| 50 people or fewer | CEO / founder | CTO |
| more than 50 | head of engineering (head, VP, director) | engineering manager, recruiter, HR |
| unknown | CEO / founder, labelled "size unknown" | CTO |

Why: at a small company the founder decides and replies most. Above ~50
people the hiring manager beats HR. Job boards and staffing agencies (skip list
in `config/outreach.json`, or "Not a real employer" in the app) get no pitch.

How it finds them, cheapest first:

1. The company's domain from the job's own links and description, else Hunter's
   free Domain Finder (only when it returns the same company name).
2. Hunter: company size (`"11-50"`), then the people in the target roles with
   their emails. Each email shows the pages Hunter saw it on (the proof) and a
   badge: `verified`, `found`, `accept-all` (the server accepts anything, so it
   can't be checked), `guessed`, `bounced`, `added by you`. About 1.2 of the free
   plan's 50 monthly credits per company.
3. Nobody found: "Search the web with Claude" (Haiku, 2 searches, about
   $0.03–0.05). A name counts as confirmed only when the API's own search
   results show it (e.g. a LinkedIn title "Jane Doe - CTO - Acme"). The email
   is then Hunter's Email Finder, or a guess from the domain's pattern, shown
   as `guessed`. In the daily run this backup is off unless
   `claude_fallback_in_daily_run` is true.
4. You can always add a person by hand.

The daily run looks up only that run's new shortlisted jobs, best fit first,
and spreads the Hunter credits left over the days until they reset. It never
looks up in a date-range run (that would spend the month).

**The email** (`src/jobhunter/pitch.py`) is your own text from
`config/outreach.json` (`subject_template`, `pitch_text`, `ask_text`), with no
AI and no cost:

```
Subject: Full Stack Engineer - Mohamad Shoumar

Hi Rima,

Saw you are looking for a Full Stack Engineer. In three years at a trading firm
I went from full-stack developer to leading a team of 5, building the platforms
the firm runs on: 800+ concurrent jobs and 115+ AI workflows in production.

What's the best next step — a screening call or a technical task? I can turn
either around this week.

Mohamad Shoumar
Beirut · +15550107788 · LinkedIn
```

- The title has noise like "- Remote" or "(m/f/d)" removed.
- Emails go out as plain text ("LinkedIn: https://…") plus an HTML copy, where
  "LinkedIn" is a link.
- The CV is attached to the first email: a PDF from `cv_dir`
  (`resume/output`). The job's tailored CV (below) wins, then a
  file named after the company (`Shoumar_FullStack_LigaData_Sep2026.pdf`),
  else `default_cv`; you can pick another, or "No CV", per job. Follow-ups
  carry no attachment.

**Tailored CVs** (`src/jobhunter/cv.py`). The CV box in each job has **Tailor
CV** and a **View** link that opens the PDF, so it is ready both for the email
and for uploading when you apply through the posting. `cv_model` (DeepSeek,
about $0.01 and 10 seconds a CV) orders and rewords your profile's bullets and
picks skills for the posting. Plain code builds the file and checks it:

- which bullets print is decided by code from the profile's tags: `[core]`
  bullets always; `[lead]`, `[fullstack]`, `[automation]` or `[mobile]` ones only
  when the job's title or posting has one of that tag's phrases (`TAG_RULES` in
  `cv.py`, overridable as `cv_tags` in `config/outreach.json`). The box says
  which tags matched and why. The same tags pick the role's printed title from
  its `Printed title:` line (Team Lead for lead jobs, else Algorithmic Trader);
- name, contact lines, employers, dates and education are copied from
  `resume.md` in `resume_dir`; the model never writes them;
- each bullet rewords profile bullets of the same role and must keep their
  numbers (next to the same word), add no tool, name or seniority word, and add
  at most 4 other words. A rewrite that fails is sent back once, then replaced
  by the profile's own words;
- skills rows only hold skills from the profile row with the same label;
- the headline is one of your target roles, optionally "- focus" in profile
  words; there is never a Summary section.

It writes `versions/<Role>_<Company>_<MonYYYY>.md` (optional bullets not for
this job kept as `// [tag] - ...` comments to swap in by hand), runs `build.py` (again with `compact: yes`
if it spills onto page 2), adds a row to `applications.csv`, and never
overwrites a CV you made by hand (`_2` is added instead). The box also lists
what the posting asks for that is not in your profile. `jobhunter tailor <id>`
does the same from the terminal. The daily run tailors its new shortlisted
jobs (`auto_tailor`, `max_cvs_per_run`), and catches up on shortlisted jobs
from the last `catch_up_days` (7) that still have none, so one that failed on a
network error at wake-up is tried again the next day. It only catches up on
jobs still at New or Saved, and never on one that already has a CV you made for
that company (the PDF the email would attach).

**Fixing a CV by hand.** A model can still get a line wrong, and a CV made by
hand or with a chat assistant has no check at all. **Edit CV text** in the CV
box opens the text behind the job's CV (`versions/<name>.md`, tailored or made
by hand; not the general `resume.md`). Delete a line, or put `//` in front of it
to hide it, then **Save & rebuild PDF**: `build.py` rebuilds the PDF with no AI,
so what you save is what prints. The text before your edit is kept as
`<name>.md.bak`. Above the text, the box lists lines that say more than your
profile, so you know where to look first: a bullet whose number, tool, name or
"lead"/"senior"-type word is not in the profile bullet closest to it, and a
skills item with a word your profile does not have (`PostgreSQL (relational)`).
It only points; it never changes a line. Once you edit a tailored CV, **Tailor
again** asks before replacing your edits, and the daily run leaves it alone.
From the terminal: edit the file in any editor, then `jobhunter rebuild-cv <id>`.
A wrong line that comes from `profile/master_profile.md` itself is better fixed
there (then `python3 build.py sync` in `resume/`), so no future CV or cover
letter repeats it.

**Cover letters** (`src/jobhunter/cover.py`). The Cover letter box under the CV
has **Write cover letter** and **Copy**; `jobhunter cover <id>` does the same.
`cover_model` (empty: the same model as `cv_model`; about $0.005 and 5 seconds
a letter on DeepSeek) writes the opening, two paragraphs and the closing. Code
writes the rest (your contact lines from the profile, the date, "Dear <Company>
Hiring Team,", the sign-off) and checks every sentence:

- the letter may only use the facts the job's CV prints: the summary, the
  Experience bullets for the job's tags, skills, education, certifications and
  where you live (never the salary line);
- each paragraph names the facts it uses, and its numbers, tools and seniority
  words must be in those facts ("800+ concurrent jobs" next to the same word);
- the opening and closing may repeat what the posting says about the company
  ("Novakid has 80,000 students"), but a sentence about you still names only
  your tools; years are never above the profile's;
- what the posting asks for that you lack is never claimed: the model picks up
  to 3 (each word for word in the posting and sharing no word with your
  facts), and code writes one sentence, `cover_gap_text`: "I have not worked
  with Kafka or Kubernetes yet, and I would make learning them an early
  priority."

A letter that breaks a rule is sent back once with the reasons; a sentence
that still breaks one is left out, and the box lists what was left out and
why, plus names from the posting to check by eye. The letter is
`resume/output/Shoumar_CoverLetter_<Company>_<MonYYYY>.md`, plain text to paste
into a form or upload; a file you made by hand is never overwritten (`_2`).
The box shows the file as it is now, so your edits stay. The daily run writes
one for each new shortlisted job (`auto_cover`, `max_covers_per_run`, same
catch-up), and each job in the daily report links its tailored CV and cover
letter.

**The resume folder** is `resume/` in this project: `build.py` and `resume.md`
(both in git), and what they produce, `versions/`, `output/` and
`applications.csv` (not in git, like `reports/`). It is inside the project, not
in `~/Documents`, because macOS keeps background jobs (the daily run) out of
Documents. `resume_dir` and `cv_dir` in `config/outreach.json` may be relative
to the project.
- `"pitch_mode": "ai"` switches the sentence after the opening to one written by
  `pitch_model` (DeepSeek or Claude). Plain code then checks it against
  `profile/master_profile.md`: a line with a number comes from one fact, with
  the number next to the same word; years never above the profile's; no skill
  or title you don't have.

The daily run drafts an email as soon as a contact is known, and never
overwrites one you edited.

**Sending** (`src/jobhunter/mailer.py`): only when you click Send. Nothing is
sent automatically, follow-ups included. "Send test to me" sends it to yourself
first. Guards: a daily cap (15, and 3 for guessed addresses, because bounces hurt
your Gmail's reputation), a second confirm for guessed addresses and for a
second person at the same company, and no double sends (the step is saved
before the send, and the page says which step it showed).

**Tracking** (`src/jobhunter/tracking.py`): stages New → Saved → Reached out →
Replied → Interviewing → Offer, or Closed (rejected, ghosted, skipped). The
inbox check (daily run, the "Check inbox" button, `jobhunter inbox`) reads
Gmail's All Mail without marking anything read:

- a reply in the thread (or from anyone at the company's domain, "probable")
  moves the job to Replied and cancels its follow-ups;
- out-of-office replies are noted, not counted;
- a permanent bounce (5.x.x) marks the address and suggests the next person.

Follow-up 1 is due 4 business days after the first email, follow-up 2 seven
more (research: follow-ups bring about 40% of replies; two is enough). They
show in Today, pre-written, one click each. No reply after the whole schedule
plus 7 business days: the job closes as ghosted (a late reply reopens it). Stats
show your own reply rate by who you emailed and by company size.

**Setup, once** (all optional; the app says what is missing):

- `DEEPSEEK_API_KEY` for drafts (the default `pitch_model`), or `ANTHROPIC_API_KEY` with a Claude
  `pitch_model`. The web-search backup for contacts and the AI eligibility check need
  `ANTHROPIC_API_KEY` either way (DeepSeek has no web search).
- `HUNTER_API_KEY`: a free account at hunter.io.
- Gmail: turn on 2-Step Verification, create an app password at
  myaccount.google.com/apppasswords, set `GMAIL_ADDRESS` and
  `GMAIL_APP_PASSWORD`. An app password instead of Google's OAuth, because
  OAuth for reading a personal inbox logs you out every 7 days unless Google
  reviews the app.

The app listens on 127.0.0.1 only and every change needs a token that is put
into the page when it starts, so another website open in your browser cannot
press Send.

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
- `config/outreach.json` — who to target by size, the job-board skip list,
  lookup and send limits, follow-up days, the models, the resume folder, and the
  CV and cover letter settings.
- `.env` — `SERPAPI_API_KEY`, `ANTHROPIC_API_KEY`, `DEEPSEEK_API_KEY`, `HUNTER_API_KEY`,
  `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`. Not in git; keep it that way.
- `profile/master_profile.md` — the facts about you. **CV tailoring and cover letters may
  reorder, emphasize, rephrase and remove; they must never add anything that is not in this file.**

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

- In the web app: drag-and-drop in Pipeline, and send-time hints.
- More sources: the YC jobs page, HN job stories, Remote100k.
