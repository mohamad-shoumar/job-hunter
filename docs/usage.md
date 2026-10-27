# Using jobhunter

The full manual: setup, every command, how a job is judged, the web app, the sources and the config.
For what the project is and how it is built, start with the [README](../README.md). For why it works
this way, see [decisions.md](decisions.md).

- [Setup](#setup)
- [Commands](#commands)
- [Reports](#reports)
- [How a job is judged](#how-a-job-is-judged)
- [Only new jobs](#only-new-jobs)
- [Outreach and tracking](#outreach-and-tracking)
- [Sources](#sources)
- [Config](#config)
- [Run it daily](#run-it-daily)
- [Tests](#tests)
- [Not built yet](#not-built-yet)

## Setup

You need Python 3.11 or newer. Every key is optional: a step without its key is skipped with a note, and
the rest still runs.

```sh
python3 -m venv .venv && .venv/bin/pip install -e ".[web]"   # ".[dev]" adds pytest and ruff
cp .env.example .env                                          # your name and contact (MY_*), optional keys
cp profile/master_profile.example.md profile/master_profile.md   # your facts (not in git)
cp resume/resume.example.md resume/resume.md                     # your base CV (not in git)
.venv/bin/jobhunter run        # a few minutes with every source on
open reports/$(date +%F).md
.venv/bin/jobhunter serve      # the web app, http://127.0.0.1:8765
```

Without a profile, the run still finds and judges jobs; it just makes no CVs, cover letters or emails.

**Which key does what.** With the settings in `config/`:

| key or tool | used for | without it |
| --- | --- | --- |
| `DEEPSEEK_API_KEY` | AI check step 1, fit grade, tailored CVs, and the email's one AI line when `pitch_mode` is `"ai"` | those steps are skipped |
| the `claude` CLI (Claude Code), signed in | AI check step 2 (web search), posting-date lookups, cover letters | the AI check uses DeepSeek only; dates come from job pages only; no cover letters |
| `ANTHROPIC_API_KEY` | only a `claude-*` model in a config file, and the contact lookup's "search the web" backup | the "Search the web with Claude" button is off |
| `HUNTER_API_KEY` | finding who to email | you add contacts by hand (or use the backup above) |
| `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD` | sending, and reading replies and bounces | no sending |
| `SERPAPI_API_KEY` | the Google Jobs source | that source is skipped |

Claude Code runs on your Claude login, not on an API key. `CLAUDE_CODE_BIN` in `.env` says where `claude`
is, when it is not on PATH or in `~/.local/bin`.

## Commands

Every command takes `--home <folder>` (the project folder; default `$JOBHUNTER_HOME`, else the folder
that holds `config/`) and `-v` (debug logging).

| command | what it does |
| --- | --- |
| `jobhunter run` | fetch every source, store, classify new jobs, run the optional steps, write today's `reports/<date>.md` |
| `jobhunter run --from 2026-09-20 --to 2026-09-27` | one report per day for that range (see [Date ranges](#date-ranges)) |
| `jobhunter run --days 7` | the same for the last 7 days, today included |
| `jobhunter run --sources himalayas,lever` | only these sources (`--skip serpapi` leaves some out) |
| `jobhunter run --no-ai` | no model calls: no posting-date lookups, AI check, fit grade, CVs, cover letters or AI-written email lines |
| `jobhunter run --no-outreach` | no contact lookups, drafts, CVs, cover letters or inbox check |
| `jobhunter run --no-report` | store and classify only |
| `jobhunter serve` | the web app: jobs, who to email, drafts, sending, tracking (`--port`, `--no-open`) |
| `jobhunter contacts` | find who to email for shortlisted jobs without a contact, best fit first (`--limit N`, `--no-claude`, or job ids) |
| `jobhunter tailor <id>` | a CV tailored to that job, in `resume/output/` (`--replace-edits` to redo one you edited) |
| `jobhunter rebuild-cv <id>` | after you edit a job's CV text in `resume/versions/`, rebuild its PDF (no AI) and list lines that say more than your profile |
| `jobhunter cover <id>` | a two-paragraph cover letter for that job, next to its CV |
| `jobhunter inbox` | check Gmail for replies and bounces (the daily run does this too) |
| `jobhunter check` | AI-check shortlisted jobs the rules left `unclear`, newest first (`--limit N`, `--recheck`, or job ids) |
| `jobhunter dates` | find when undated shortlisted jobs were posted (`--limit N`, `--recheck`, or job ids) |
| `jobhunter grade` | AI fit grade 1-5 for open jobs, learned from your Applied and skipped jobs (`--regrade`, `--days N`, `--limit N`, or job ids) |
| `jobhunter show <id>` | everything stored about one job and why it got its status (`-d` adds the description) |
| `jobhunter reclassify` | judge every stored job again after you edit `config/filters.json`, and rebuild the day files that changed |
| `jobhunter report --date 2026-09-25` | rebuild one day's file from the database |
| `jobhunter boards` | company boards watched because a job there was shortlisted (`--remove ashby:acme` stops one for good, `--all` shows removed ones) |
| `jobhunter sponsors` | the government lists of visa sponsors (`--update` downloads them; `--company Monzo --place London` looks one up) |
| `jobhunter stats` / `jobhunter sources` | counts by status and source / which sources are on |

## Reports

One Markdown file per day, `reports/2026-09-27.md`. Each job in it has the reason for its status. It has five
parts:

- **Shortlisted**: each job with the reason it can (or might) hire from Lebanon (`unclear` when nothing
  says), its fit, salary, dates and apply link. Days before 2026-10-27 also have **Needs review**, for the
  jobs judged while that list existed.
- **Visa list**: jobs abroad (the EU and UK) at employers that sponsor a work visa, each with the quoted
  evidence. Kept apart from the remote jobs: see [the visa list](#moving-abroad-on-a-work-visa).
- **Rejected**: every rejected job, listed under the rule that rejected it, with the exact word, place or
  quote: `Title contains "manager"`, `Restricted to "Remote - US"`, `Asks for 10+ years of experience`.
  Jobs rejected only for being too old are counted, not listed.
- **Sources**: how many listings each source returned, and any errors.

Each company shows its best job (by grade, then fit), and its other jobs are named under it ("Also at
Palantir (16 more)"). This is display only: no job is hidden from the database or the app.

A second run on the same day adds to the same file. A job appears in one daily file only, and never again
after that.

### Date ranges

`--from 2026-09-20 --to 2026-09-27` fetches every source **once**. Each listing posted in that range goes
into the file for the day it was posted, so you get one file per day.

It does not fetch once per day: job sites only show what is open *now*, so eight fetches would return the
same listings eight times (and use eight times the SerpApi credits). So jobs that already closed cannot be
found, and sources that only keep their latest jobs (Remote OK: about 100) are thin for older days.
Himalayas keeps paging back until it reaches the start of the range, and Hacker News reads every monthly
thread the range touches. Jobs inside the range are kept even when they are older than the usual 14-day
limit. A date-range run looks up no contacts and makes no CVs: that would spend a month of credits.

## How a job is judged

Plain code makes every decision here and gives a reason you can read in the report or with
`jobhunter show <id>`. Models come in only at steps 4 to 6, and only where code can check them.

The rules run in this order; the first one that rejects a job gives its reason:

1. **Blocked companies** (`blocked_companies` in `config/filters.json`): companies you never want again,
   with your reason.
2. **Agencies** (`agencies`): staffing agencies and talent marketplaces, quoting the name, the word in the
   name ("Staffing") or the sentence ("on behalf of our client").
3. **Too old**: posted more than `max_posting_age_days` (14) before it was found.
4. **Not a target role**: the title or the years asked (below).
5. **Cannot hire from Lebanon**: the location rules (below).
6. **401(k)**: a posting that offers one is remote within the US, whatever its location says
   ([decision 6](decisions.md#6-a-posting-that-offers-a-401k-is-rejected)).

### 1. Can they hire someone in Lebanon?

`src/jobhunter/eligibility.py`

| verdict | meaning | example |
| --- | --- | --- |
| eligible | the posting says so | "Worldwide", "Lebanon" in the country list |
| likely | a region or time zone that includes Lebanon, or an employer-of-record hint | "EMEA", "UTC-1 to UTC+3", "we hire through Deel" |
| unclear | remote, but nothing decisive, or a limit the posting itself doubts | "Remote"; "US only" next to "we hire globally" |
| rejected | on-site or hybrid, limited to places without Lebanon, or a fitting location narrowed elsewhere in the posting | "Remote - US", "Europe"; "Worldwide" in the location but "must be based in the UK" in the text |

"Remote" on its own never counts as international. "Europe" counts as a limit (it usually means EU
residency), but "European time zones" does not. Preferences ("US preferred") are ignored, not treated as
rules. A source that gives no location means "unknown", never "Worldwide".

Jobs in the UAE or Qatar, and jobs in the EU and UK that sponsor a visa, have their own rules: see
[Sources](#sources).

### 2. Is it a role worth applying to?

`src/jobhunter/relevance.py`, `config/filters.json`

- **Title words** to include and exclude, plus any "AI ... engineer/developer" title ("AI Harness
  Engineer").
- **Years of experience**, read from the posting's own sentence, which the reason quotes:
  `Asks for 5+ years (a stretch): "5+ years building production backend systems"`. It reads "Minimum 5
  years", "(typically 8+ years)", "4-7 years in ...". A "nice to have" cancels only the years in its own
  sentence. 6+ is rejected; 5 is a "stretch" note that the fit grade ranks down.
- **AI and forward-deployed roles** (`junior_only`) are wanted only at junior level: rejected when the title
  says "senior" or "lead", or the posting asks for 3+ years in any field. A title that also says backend or
  full stack keeps the usual rules ([decision 8](decisions.md#8-ai-and-forward-deployed-roles-only-at-junior-level)).
- **Fit score** from the skills in the posting (`fit_weights`). A posting that mentions Python is a `match`;
  without Python it is a `maybe`.

### 3. The status

Each job gets one status:

- **shortlisted**: a target role the rules did not reject. Eligible and likely ones, and also `unclear` ones
  (nothing says whether Lebanon is allowed) and ones with no posting date, marked so: check those before
  applying. The two steps below can still reject them;
- **visa list**: a job abroad that sponsors a visa ([below](#moving-abroad-on-a-work-visa));
- **rejected**.

There is no "needs review" any more (since 2026-10-27). The jobs that had it keep it, for you to go through:
`reclassify` and the steps below leave them alone.

### 4. Posting dates, only for undated shortlisted jobs

`src/jobhunter/posted_date.py`, `find_dates` in `config/ai_check.json`

Before the AI check, the run looks up when undated shortlisted jobs were posted (Google Jobs often gives
no date), up to `max_dates_per_run` (25). Code first reads the schema.org `datePosted` on the job's own
pages. When no page has one, Claude Code (`web_model`) searches the web and quotes the words that state the
date. Code finds that quote on the page and reads the date from the quote, never from the model's answer.
Then the usual age rule judges the job. `jobhunter dates` does the same by hand.

### 5. AI check, only for `unclear` jobs

`src/jobhunter/ai_check.py`, `config/ai_check.json`

When the rules can't tell, a model looks for the company's own posting of the role (which often says
"Remote - US" where the job board said nothing) and its careers page, in two steps:

1. **DeepSeek** (`model`: `deepseek-v4-pro`, about $0.01 a job). It can't search the web, so code fetches
   the job's own links and the links in its description, and reads a Greenhouse, Lever or Ashby posting
   through the board's public API. Code never fetches Himalayas, LinkedIn, Indeed, Glassdoor or Hacker
   News pages here. DeepSeek reads those pages and the description.
2. **Claude Code** (`web_model`: `claude-code`), only for jobs step 1 could not settle: the Claude Code CLI
   with web search and fetch, on your Claude login, so no API bill (about a minute a job). What it read
   never reaches the code, so code fetches the page it names itself.

Either way, the model must answer with an exact quote and the page it came from. Code looks for that quote,
word for word, in the job description or in a page code fetched itself (its readable text, or the data
embedded in it). A `claude-*` model instead uses the Anthropic API with its own web search
(`ANTHROPIC_API_KEY`, about $0.10-0.30 a job). Only a found quote counts:

| AI answer | quote found | result |
| --- | --- | --- |
| cannot hire | yes | rejected, under "AI check: cannot hire from Lebanon", with the quote and link |
| can hire | yes | shortlisted as `likely` |
| sponsors a work visa (any country) | yes, and the visa rules read it as an offer | shortlisted as `likely` |
| anything else | | stays shortlisted as `unclear`, with what the AI found attached |

It runs at the end of `jobhunter run` on unchecked `unclear` shortlisted jobs from the last `lookback_days` (14),
newest first, at most `max_jobs_per_run` (50), and never on a job the rules already decided. Each job is
checked once, and the result is stored, so `reclassify` keeps it. For older waiting jobs:
`jobhunter check --limit 250`. A found quote proves the words exist, not that the AI read them right, so the
link is always shown.

### 6. Fit grade, for sorting only

`src/jobhunter/fitgrade.py`, `config/fit_grade.json`

The steps above decide a job's status. The grade never changes it, never hides a job and never rejects one.
It only decides the order: the report, the To apply column and which jobs get a CV first show the best
grade first.

DeepSeek (`deepseek-v4-flash`, about $0.0015 a job) grades each shown job 1-5 with one sentence why, after
reading:

- your profile's facts (no contact details);
- `preferences` in `config/fit_grade.json`, in your words;
- your latest choices: jobs you marked **Applied**, and jobs you **skipped**, with the reason you picked
  (Too senior, Wrong stack, Not open to me, Agency, repost or gig, Not my kind of role, Pay too low, Other)
  and your note.

There are no preference rules to keep up to date: each Applied or Skip changes the examples the next grades
read, so the grades follow what you actually do. Stages you set by hand (Reached out, Interviewing) are not
used. A job keeps its grade; `jobhunter grade --regrade` grades the open ones again with today's examples.
The daily run grades open jobs from the last `lookback_days` (7), up to `max_jobs_per_run` (60).

## Only new jobs

The SQLite database (`data/jobs.sqlite`) is the memory. Reports are only output and can be rebuilt from it
at any time. Rejected jobs stay stored on purpose, so they never come back as new.

The same job often appears on several sites. Two listings are the same job when, strongest key first
(`src/jobhunter/identity.py`):

1. they have the same source and listing id;
2. they share an ATS posting id (Greenhouse, Lever, Ashby or Workable) found in any of their links, e.g. a
   We Work Remotely listing that links to the company's Greenhouse page;
3. they have the same company and title, after cleanup, within 60 days (`dedupe_window_days`), unless both
   carry *different* ATS ids (one company posting "Backend Engineer" for EMEA and for the US is two jobs).

Every sighting is kept in the `sightings` table, so the report lists every site a job was seen on.

A job is judged once, when it is first seen. After you change a rule or `config/filters.json`, run
`jobhunter reclassify` to judge the stored jobs again. It keeps the stored AI checks, posting dates and
grades.

## Outreach and tracking

`jobhunter serve` opens `http://127.0.0.1:8765`. It has four tabs:

- **Today**: replies to answer, follow-ups due, new shortlisted and visa-list jobs to triage (Save or Skip),
  sends to double-check, and jobs ghosted this week.
- **Jobs**: the list, by view (Shortlisted, Needs review (jobs from before 2026-10-27), Visa list, ...). Click
  one for everything about it.
- **Pipeline**: every tracked job by stage. **To apply** holds shortlisted jobs you haven't acted on, plus
  visa-list jobs posted today or yesterday (with a "visa" chip), newest posting first, one per company.
  **Email someone** holds jobs you applied to where nobody at the company has been emailed yet, for
  `reach_out_days` (7) after you reached out. Then Saved, Reached out, Replied, Interviewing, Offer,
  Rejected and Closed.
- **Stats**: your own reply rate, by who you emailed and by company size.

### Who to email

`src/jobhunter/contacts.py`. Looked up once per company.

| company size | who first | then |
| --- | --- | --- |
| 50 people or fewer | CEO / founder | CTO |
| more than 50 | head of engineering (head, VP, director) | engineering manager, recruiter, HR |
| unknown | CEO / founder, labelled "size unknown" | CTO |

Why: at a small company the founder decides and replies most. Above about 50 people, the hiring manager beats
HR. Job boards and staffing agencies (the skip list in `config/outreach.json`, or "Not a real employer" in the
app) get no pitch.

How it finds them, cheapest first:

1. The company's domain from the job's own links and description, else Hunter's free Domain Finder (only
   when it returns the same company name).
2. Hunter: company size (`"11-50"`), then the people in the target roles, with their emails. Each email shows
   the pages Hunter saw it on (the proof) and a badge: `verified`, `found`, `accept-all` (the server accepts
   anything, so it can't be checked), `guessed`, `bounced`, `added by you`. About 1.2 of the free plan's 50
   monthly credits per company.
3. Nobody found: "Search the web with Claude" (`fallback_model`, Haiku through the API, 2 searches, about
   $0.03-0.05). A name counts as confirmed only when the API's own search results show it (e.g. a LinkedIn
   title "Jane Doe - CTO - Acme"). The email is then Hunter's Email Finder, or a guess from the domain's
   pattern, shown as `guessed`. In the daily run this backup is off unless `claude_fallback_in_daily_run` is
   true.
4. You can always add a person by hand.

The daily run looks up only that run's new shortlisted jobs, best fit first, and spreads the Hunter credits
left over the days until they reset.

### The email

`src/jobhunter/pitch.py`. By default (`pitch_mode: "fixed"`) it is your own text from `config/outreach.json`
(`subject_template`, `pitch_text`, `ask_text`, `hr_ask_text`), with no AI and no cost. With made-up values:

```
Subject: Full Stack Engineer - Jane Doe

Hi Sam,

I just applied for the Full Stack Engineer role. I built the payment APIs behind 2M monthly checkouts.

Once this role is filled, what's the first thing you'd want that person to get right?

Jane Doe
<city> · <phone> · LinkedIn
```

The name, city, phone and LinkedIn come from `MY_NAME`, `MY_LOCATION`, `MY_PHONE` and `MY_LINKEDIN` in
`.env`.

- HR and recruiters get `hr_ask_text` as the question instead ("From your side, what quality stands out the
  most for this role at {company}?"). The question never asks for a call, an interview or a referral.
- The title loses noise like "- Remote" or "(m/f/d)".
- Emails go out as plain text ("LinkedIn: https://...") plus an HTML copy, where "LinkedIn" is a link.
- The first email carries a CV: a PDF from `cv_dir` (`resume/output`). The job's tailored CV (below) wins,
  then a file named after the company (`Doe_FullStack_Acme_Sep2026.pdf`), else `default_cv` (empty means
  `<Last name>_Resume_General.pdf`, the master CV). You can pick another, or "No CV", per job. Follow-ups
  carry no attachment.

**`pitch_mode: "ai"`.** The model in `pitch_model` writes the one sentence after "I just applied for the
... role." instead of `pitch_text`. It can be any model `llm.json_model` knows: `deepseek-*`
(`DEEPSEEK_API_KEY`), `claude-*` (`ANTHROPIC_API_KEY`) or `claude-code`. The model sees your profile's facts
as a numbered list and says which ones it used. Then code (`check_draft`, built on `grounding.py`) checks the
line:

- every number is in a fact it cites, next to the same word ("800+ concurrent jobs" passes; "5 years" does
  not, unless a fact says it);
- years of experience are never above the profile's;
- every skill it names is in the profile;
- seniority words ("senior", "staff", ...) are in the profile.

A line that fails is sent back once with the reasons. If it still fails, the draft is saved with the problems
shown, and Send is blocked until you edit it.

The daily run drafts an email as soon as a contact is known, and never overwrites one you edited.

### Tailored CVs

`src/jobhunter/cv.py`. The CV box in each job has **Tailor CV to this job** and a **View** link that opens the
PDF, so the CV is ready both for the email and for uploading when you apply. `cv_model` (`deepseek-v4-pro`,
about $0.01 and 10 seconds a CV) orders and rewords your profile's bullets and picks skills for the posting.
Plain code builds the file and checks it:

- **Which bullets print** is decided by code, from the tags on each profile bullet: `[core]` bullets always;
  `[lead]`, `[fullstack]`, `[automation]` or `[mobile]` ones only when the job's title or posting has one of
  that tag's phrases (`TAG_RULES` in `cv.py`, or `cv_tags` in `config/outreach.json`). The box says which
  tags matched and why. The same tags pick each role's printed title from its `Printed title:` line (for
  example a lead title for lead jobs).
- **Name, contact lines, employers, dates and education** are copied from `resume.md`; the model never
  writes them.
- **Each bullet** rewords profile bullets of the same role. It must keep their numbers (next to the same
  word), add no tool, name or seniority word, add at most 4 other words, and drop at most 1 of their words,
  so a rewrite never shortens what a bullet claims. Code puts back the profile's bold (`**800+**`). A rewrite
  that fails is sent back once, then replaced by the profile's own words.
- **Skills rows** only hold skills from the profile row with the same label.
- **The headline** is the posting's own title, cleaned by code ("Senior Software Engineer, Payments
  Platform" becomes "Senior Software Engineer"; "Senior Backend & Platform Engineer" becomes "Senior Backend
  Engineer"; levels like "II" and words like "Remote" are dropped). When the title does not read as one
  engineering role, the model picks one of your target roles, and the box says so.
- **There is no AI-written summary.** The Summary paragraph in `resume.md` is yours and is copied word for
  word.

It writes `versions/<Role>_<Company>_<MonYYYY>.md` (optional bullets not used for this job stay in it as
`//` comments, to swap in by hand) and runs `build.py`. When the CV spills onto a second page, it builds again
with `compact: yes`, then drops optional bullets (oldest role first, never `[core]` ones) until it fits. It
adds a row to `applications.csv` when that file exists, and never overwrites a CV you made by hand (`_2` is
added instead). The box also lists what the posting asks for that is not in your profile.

`jobhunter tailor <id>` does the same from the terminal. The daily run tailors its new shortlisted jobs
(`auto_tailor`, up to `max_cvs_per_run`: 5), best grade first. It also catches up on shortlisted jobs from
the last `catch_up_days` (7) that still have none (one that failed on a network error at wake-up is tried
again the next day), but only jobs still at New or Saved, and never one that already has a CV you made for
that company.

**Fixing a CV by hand.** A model can still get a line wrong, and a CV made by hand or with a chat assistant
has no check at all. The CV box has **View**, **Download** (saves the PDF, ready to upload) and **Edit CV**,
which opens the text behind the job's CV (`versions/<name>.md`, tailored or made by hand; not the general
`resume.md`). Delete a line, or put `//` in front of it to hide it, then **Save & rebuild PDF**: `build.py`
rebuilds the PDF with no AI, so what you save is what prints. The text before your edit is kept as
`<name>.md.bak`.

Above the text, the box lists lines that say more than your profile, so you know where to look first: a
bullet whose number, tool, name or "lead"/"senior"-type word is not in the profile bullet closest to it, and a
skills item with a word your profile does not have. It only points; it never changes a line. Once you edit a
tailored CV, **Tailor again** asks before replacing your edits, and the daily run leaves it alone. From the
terminal: edit the file in any editor, then `jobhunter rebuild-cv <id>`. A wrong line that comes from
`profile/master_profile.md` itself is better fixed there (then `python3 build.py sync` in `resume/`), so no
future CV or cover letter repeats it.

### Cover letters

`src/jobhunter/cover.py`. Only when you ask: the Cover letter box under the CV has **Write cover letter**,
**Copy** and **Download** (a .txt file to upload), and `jobhunter cover <id>` does the same. The daily run
writes none (`auto_cover` is false). A letter is two paragraphs, with no header, date, greeting or sign-off
(the form already has your name and the job):

1. **Why this company.** `cover_model` (`claude-code`: the Claude Code CLI on your Claude login, about 25
   seconds) writes it from the posting and up to 3 pages code fetches from the company's site: its home page,
   /about and /blog. The domain is the one the contact lookup found, else one in the job's links, else a
   guess (`acme.com`, kept only when the page names the company). Job boards and agencies get the posting
   only. Code checks every sentence (`check_sentence`, built on `grounding.py`): each name, number and word
   for what kind of company it is ("consultancy", "startup") must be in the posting, those pages or your
   profile. A sentence about you names only your profile's tools and years, and never describes your past work
   ("I built", "my experience", your employer): paragraph 2 does that. The model also quotes the words its
   reason rests on, and code looks for them.
2. **Yours.** `cover_paragraph` in `config/outreach.json`, word for word, never checked.

How paragraph 1 reads is in `config/cover_letter_guidelines.md` (`cover_guidelines`): 2 or 3 sentences, at
most 65 words, one specific reason, like a developer talking to a hiring manager, plus lists of phrases that
read as AI ("passionate about", "cutting-edge"). Its `writer:start`/`writer:end` part is the model's
instructions, so edit that file to change how it reads. A sentence that breaks a fact rule is sent back once,
then left out, and the box lists what was left out and why. Length, a dash, or a quote code cannot find is
sent back once, then only noted. Plain-word claims ("they ship weekly") pass the checks, so read paragraph 1
before you use it.

The letter is `resume/output/<Last name>_CoverLetter_<Company>_<MonYYYY>.md`, plain text to paste into a
form or upload. A file you made by hand is never overwritten (`_2`). The box shows the file as it is now, so
your edits stay, and each job in the daily report links its tailored CV and cover letter.

### The resume folder

`resume/` in this project holds `build.py` (in git), `resume.md`, your base CV (not in git: start from
`resume.example.md`), and what they produce: `versions/`, `output/` and `applications.csv` (not in git, like
`reports/`). The name and contact lines on every CV come from `MY_*` in `.env`, so `resume.md` needs none.
It lives inside the project, not in `~/Documents`, because macOS keeps background jobs (the daily run) out of
Documents. `resume_dir` and `cv_dir` in `config/outreach.json` may be relative to the project.

### Sending

`src/jobhunter/mailer.py`. Only when you click Send. Nothing is sent automatically, follow-ups included.
"Send test to me" sends it to yourself first. Guards:

- a daily cap: 15 emails, and 3 to guessed addresses, because bounces hurt your Gmail's reputation;
- a second confirm for a guessed address, for a second person at the same company, and for an early
  follow-up;
- no double sends: the email is saved as `sending` before the network call, and a unique index on (job,
  step) refuses a second one. If Gmail refuses, the app says **Not sent**. If the call ends without a clear
  answer, the app says Gmail did not confirm and not to send again yet; the next inbox check looks the email
  up by its Message-ID and settles it ([decision 13](decisions.md#13-emails-go-out-only-when-i-click-send-and-a-second-click-cannot-send-twice)).

### Tracking

`src/jobhunter/tracking.py`. Stages: New, Saved, Reached out, Replied, Interviewing, Offer, or Closed
(rejected, ghosted, skipped). The inbox check (daily run, the "Check inbox" button, `jobhunter inbox`) reads
Gmail's All Mail read-only, without marking anything read:

- a reply in the thread (or from anyone at the company's domain: "probable") moves the job to Replied and
  cancels its follow-ups;
- out-of-office replies are noted, not counted;
- a permanent bounce (5.x.x) marks the address and suggests the next person.

Follow-up 1 is due 4 business days after the first email, follow-up 2 seven more (`follow_up_business_days`).
They show in Today, pre-written, one click each. No reply after the whole schedule plus 7 business days
(`ghost_after_business_days`): the job closes as ghosted, and a late reply reopens it.

### Setup for outreach

All optional; the app says what is missing.

- `HUNTER_API_KEY`: a free account at hunter.io.
- Gmail: turn on 2-Step Verification, create an app password at myaccount.google.com/apppasswords, and set
  `GMAIL_ADDRESS` and `GMAIL_APP_PASSWORD`. An app password instead of Google's OAuth, because OAuth for
  reading a personal inbox logs you out every 7 days unless Google reviews the app.
- `ANTHROPIC_API_KEY`: only for the "Search the web with Claude" backup, or a `claude-*` model.
- Email drafts need no key with `pitch_mode: "fixed"`. With `"ai"`, they need `pitch_model`'s key.

The app listens on 127.0.0.1 only, refuses a request whose Host is not 127.0.0.1 or localhost, and every
change needs a token that is put into the page when it starts, so another website open in your browser cannot
press Send ([decision 15](decisions.md#15-the-web-app-only-answers-my-own-browser)).

## Sources

Checked on 2026-09-25; SerpApi on 2026-09-27; the investor and Gulf boards on 2026-10-10; LinkedIn, Jobicy and
EU Remote Jobs on 2026-10-21. Research notes: [job sources](research/2026-10-10-job-sources.md),
[market size](research/2026-10-21-market-size.md).

Every run first waits (up to 5 minutes) until the network answers, since the scheduled runs start right after
the Mac wakes. A source whose requests could not connect is fetched once more a minute later (never SerpApi,
which pays per query, or LinkedIn).

| source | how | notes |
| --- | --- | --- |
| Lever, Ashby | public ATS APIs | one entry per company board in `config/sources.json` |
| Himalayas | public API | queried with `country=LB`: returns jobs that list Lebanon or list no countries at all. "No countries" often means Himalayas does not know (it shows "Worldwide" for US-only roles), so those count as no location |
| Jobicy | public API | remote jobs with the region each company hires in ("Anywhere", "EMEA", "USA"); `queries` filter titles locally |
| EU Remote Jobs | the site's own job list (JSON) | about 100 remote jobs a day of all kinds; target titles get their page read (schema.org JobPosting: full text, allowed countries, the company's apply link) |
| LinkedIn | logged-out job search | searches by place (the UAE, Qatar, Lebanon, and the UK and the Netherlands with "visa sponsorship"); logged out, only keywords, location and posted-within work. 2.5 seconds between requests (faster gets HTTP 429), so a run spends a few minutes on it; only target titles get their page read. A one-day trial found 75 jobs not in the database: 13 shortlisted, 10 for the visa list |
| Remote OK | public API | latest ~100 jobs; `queries` filter them locally |
| We Work Remotely | RSS | back-end and full-stack feeds |
| Hacker News | Algolia API | the latest "Who is hiring?" thread, one job per role |
| NoDesk | RSS | engineering feed, ~10 jobs |
| Company careers pages | HTML | reads schema.org JobPosting data when the page has it |
| Google Jobs (SerpApi) | API, key in `.env` | the evening run only. Each day: two remote searches, one search in each of Dubai, Abu Dhabi and Doha (the search words take turns) and two in Beirut: 7 credits a day, about 217 a month (the free plan has 250). Most remote results land in "needs review": Google shows remote jobs as "Anywhere", and the reposting sites rarely say who can apply |
| Investor job boards (Getro) | public search API | General Catalyst, Accel, Point Nine (remote jobs) and Hub71, MEVP, BECO Capital (UAE, Qatar, Lebanon): only the funds' own portfolio companies, so no agencies. No descriptions in the API |
| Greenhouse, Teamtailor, BambooHR, SmartRecruiters, Pinpoint | public ATS APIs / RSS | companies in the UAE, Qatar and Lebanon (Careem, talabat, Property Finder, Calo, Qashio, Toters, Tabby, ...). Mostly on-site: the `relocation` rules decide. Pinpoint gives no dates, so Tabby's jobs go to "needs review" |
| Arbeitnow | public API | jobs in Germany, the Netherlands and the UK, for the visa list. Its visa flag is per company (flagged postings say "we do not provide visa sponsorship" too), so it only trims the NL and UK feeds; the posting's words decide. Only titles with one of `queries` are kept |
| Workable | public job search API | every company on Workable, searched by country and `day_range`, for the visa list. Full text |
| Investor job boards (Getro), European funds | public search API | Index Ventures, Atomico, Creandum, Seedcamp, Speedinvest, and Accel/General Catalyst/Point Nine's jobs in the UK, the Netherlands and Ireland, for the visa list. No posting text, so only the countries with a sponsor register |
| HiringCafe | not built | blocks automated requests (HTTP 403) |
| Remote100k | not built | HTML only, no feed |
| Remotive | removed 2026-10-21 | its free API returns only 10 jobs in total |
| Remote Rocketship | not built | its terms forbid scraping; the paid API ($29/month) does not document location fields (checked 2026-10-21) |
| Wellfound, Work at a Startup | not built | bot walls or login |
| Bayt, GulfTalent, NaukriGulf | not built | block scripts or forbid them in robots.txt, and mostly recruiters |
| Relocate.me, visasponsor.jobs, Welcome to the Jungle/Otta, DevITjobs, Landing.jobs, Duunitori, EURES, Bundesagentur für Arbeit, Consider (Balderton) | not built | checked 2026-10-13 for the visa list: too few jobs, no visa field, or terms forbid scripts ([research](research/2026-10-13-eu-visa-sponsorship.md)) |

Every source keeps the same 14-day age limit, company careers pages included.

### Agencies

Staffing agencies and talent marketplaces (Jobs for Humanity, Toptal, Proxify, micro1, ...) are rejected,
quoting what matched: a name, a word in the company name ("Staffing"), or a sentence only an agency writes
("on behalf of our client"). See `agencies` in `config/filters.json`.

### Moving to the UAE or Qatar

`relocation` in `config/filters.json`. A job there may be on-site. It is rejected only when it wants nationals
or a visa you already hold ("UAE Nationals only", "transferable visa"), or pays under
`RELOCATION_MIN_MONTHLY_USD` (in `.env`; empty means pay is not checked). An offer of a visa or relocation is
quoted; "immediate joiner" is noted. Pay in AED, QAR or SAR with no period is read as monthly.

### Moving abroad on a work visa

`src/jobhunter/visa.py`, `src/jobhunter/sponsors.py`, `visa_list` in `config/filters.json`. A target role in
the Netherlands, Germany, Finland, the UK, Ireland, Spain or Italy (on-site, hybrid, or remote only for people
living there) goes to a separate **visa list**, never the shortlist. It is its own section in the report and
its own view in the web app (Jobs, then "Visa list"). The daily run makes no CV, cover letter or contact
lookup for it. The Pipeline's To apply column shows the ones posted today or yesterday, with a "visa" chip,
next to the shortlisted jobs; the buttons in the app work as for any job.

It gets there only with quoted evidence:

| code | evidence | example |
| --- | --- | --- |
| visa_offered | the posting offers a visa, or a Hacker News header says VISA | "Relocation support, including visa sponsorship and allowance" |
| relocation_offered | it offers help moving but names no visa (weaker: ask) | "For internationals: all-in relocation package" |
| visa_register | the company is on its country's government sponsor list (on-site or hybrid only) | "Monzo Bank Ltd, London, Worker (A rating), Skilled Worker" |

Rejected, quoted: the posting refuses ("We are unable to provide visa sponsorship") or wants a right to work
you don't have (`no_sponsor`); it asks for a language your profile does not list, or is written in one
(`language_required`: "Fluent German (C1)"); or nothing says it sponsors (`no_visa_evidence`). "Sponsorship"
alone never counts. A remote job open to Lebanon stays a remote job.

The government lists: the UK register of licensed sponsors (Skilled Worker rows, updated every working day),
the Dutch IND register of recognised sponsors (needed to sponsor a highly skilled migrant), and Ireland's list
of companies issued employment permits this year and last. Germany, Finland, Spain and Italy keep none (a Blue
Card needs no licensed employer), so there the posting must say it. `jobhunter sponsors --update` downloads
them to `data/sponsors/`; the daily run refreshes them every `refresh_days` (7);
`jobhunter sponsors --company Monzo --place London` looks one up. A one-word name ("Cursor") counts on the UK
list only when the list's town is in the job's location ("Cursor Ltd, Lincoln" is not Cursor in London).

### Watched boards

`src/jobhunter/boards.py`. A shortlisted job means its company can hire from Lebanon, so after each run the
code looks for that company's own Greenhouse, Lever or Ashby board and fetches it from the next run on, next
to the boards in `config/sources.json`. Its new jobs then arrive straight from the source, often before a job
site reposts them, and with the board's exact location line.

The board comes from the job's own link (`jobs.ashbyhq.com/<slug>/...`), or else from trying slugs made from
the company name (and its domain). A guessed board is kept only when it lists the shortlisted job's title, or
(Greenhouse) names the same company, so a slug that belongs to someone else is not watched. Each board keeps
that evidence, shown in the run's output, the day's report and `jobhunter boards`.

Job sites, agencies (`skip_companies`, "Not a real employer" in the app) and blocked companies are never
watched. A company with no board found is tried again after `retry_after_days` (30), and at most
`max_probes_per_run` (10) companies are tried per run. The list lives in the database (`watched_boards`), not
in `config/sources.json`, whose `watch_boards` section only holds these settings (`"enabled": false` turns it
off). A board you remove with `jobhunter boards --remove kind:slug` is never added again.

## Config

- `config/sources.json`: boards and feeds. Any entry can take `"enabled": false`.
- `config/filters.json`: blocked companies, agencies, title words, the years caps, posting age, fit weights,
  and the relocation and visa-list rules. Run `jobhunter reclassify` after changing it.
- `config/ai_check.json`: the posting-date lookup and the AI check (steps 4 and 5).
- `config/fit_grade.json`: the fit grade (step 6), including your `preferences`.
- `config/outreach.json`: who to target by size, the job-board skip list, lookup and send limits, follow-up
  days, the email text, the models, the resume folder, and the CV and cover letter settings.
- `config/cover_letter_guidelines.md`: how cover letters read.
- `.env`: about you (`MY_NAME`, `MY_EMAIL`, `MY_PHONE`, `MY_LINKEDIN`, `MY_GITHUB`, `MY_PORTFOLIO`,
  `MY_LOCATION`, printed on CVs, cover letters and emails; each wins over the same Basics line in the
  profile), `RELOCATION_MIN_MONTHLY_USD`, and the keys in [Setup](#setup). Not in git; keep it that way.
- `profile/master_profile.md`: the facts about you, not in git (start from
  `profile/master_profile.example.md`, a made-up person). **CVs and cover letters may reorder, emphasize,
  rephrase and remove; they must never add anything that is not in this file.**

Keys starting with `_` in the JSON files are comments.

## Run it daily

A macOS launchd job (`scripts/local.jobhunter.daily.plist`; the top of the file says how to install it with
your paths filled in) runs `scripts/run_daily.sh` every day at 09:00 local time. If the Mac is asleep at 09:00
it runs on wake; if the Mac is off, that day is skipped. Output goes to `data/run.log`; launchd's own errors
go to `~/Library/Logs/jobhunter.log`.

A second one (`scripts/local.jobhunter.evening.plist`, installed the same way) runs at 21:00. Most jobs are
posted 14:00-17:00 Lebanon time (the US morning), so with the 09:00 run alone they wait until the next
morning; the evening run puts them in the same day's report. SerpApi runs only in the evening run (the morning
one has `--skip serpapi`), so its credits last the month and it sees the day's US postings.

```sh
launchctl kickstart gui/$(id -u)/local.jobhunter.daily    # run now
launchctl print gui/$(id -u)/local.jobhunter.daily | grep "last exit"
launchctl bootout gui/$(id -u)/local.jobhunter.daily      # stop the schedule
```

To change the time, edit `Hour`/`Minute` in the plist, install it in `~/Library/LaunchAgents/` again, then
`bootout` and `bootstrap` it.

Keep the project out of `~/Desktop`, `~/Documents` and `~/Downloads`: macOS blocks background jobs from
reading those folders ("Operation not permitted") unless the program is given Full Disk Access.

## Tests

```sh
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
.venv/bin/ruff check .
```

Source adapters are tested against trimmed real responses in `tests/fixtures/`. Tests never reach Hunter,
Claude, DeepSeek or Gmail, and never run the Claude Code CLI. See [CONTRIBUTING.md](../CONTRIBUTING.md).

## Not built yet

- In the web app: drag-and-drop in Pipeline.
- More sources: the YC jobs page, HN job stories, Remote100k.
