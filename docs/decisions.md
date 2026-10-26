# Decisions

The main choices I made building jobhunter, and why, in my own words. Dates come from the commits.
[`.claude/CLAUDE.md`](../.claude/CLAUDE.md) holds the same rules written as instructions for coding agents; this file is the human version.

Sentences marked "(draft: check)" give a reason I have not written down anywhere else yet.

1. [Plain rules decide; a model only looks at unclear jobs, and only a quote code can find counts](#1-plain-rules-decide-a-model-only-looks-at-unclear-jobs-and-only-a-quote-code-can-find-counts)
2. [SQLite is the memory; reports are only output](#2-sqlite-is-the-memory-reports-are-only-output)
3. [The same job on several sites: three keys, strongest first](#3-the-same-job-on-several-sites-three-keys-strongest-first)
4. [The fit grade only sorts, and learns from what I apply to and skip](#4-the-fit-grade-only-sorts-and-learns-from-what-i-apply-to-and-skip)
5. [One job per company on screen, for display only](#5-one-job-per-company-on-screen-for-display-only)
6. [A posting that offers a 401(k) is rejected](#6-a-posting-that-offers-a-401k-is-rejected)
7. [When a posting narrows its own location, the narrower rule wins](#7-when-a-posting-narrows-its-own-location-the-narrower-rule-wins)
8. [AI and forward-deployed roles only at junior level](#8-ai-and-forward-deployed-roles-only-at-junior-level)
9. [Jobs abroad that sponsor a visa are a separate list](#9-jobs-abroad-that-sponsor-a-visa-are-a-separate-list)
10. [DeepSeek and the Claude Code CLI instead of the paid Anthropic API](#10-deepseek-and-the-claude-code-cli-instead-of-the-paid-anthropic-api)
11. [Tailored CVs: the model picks order and wording, code owns the facts](#11-tailored-cvs-the-model-picks-order-and-wording-code-owns-the-facts)
12. [Cover letters: two paragraphs, only when I ask](#12-cover-letters-two-paragraphs-only-when-i-ask)
13. [Emails go out only when I click Send, and a second click cannot send twice](#13-emails-go-out-only-when-i-click-send-and-a-second-click-cannot-send-twice)
14. [A Gmail app password, not Google OAuth](#14-a-gmail-app-password-not-google-oauth)
15. [The web app only answers my own browser](#15-the-web-app-only-answers-my-own-browser)
16. [Personal details stay out of git](#16-personal-details-stay-out-of-git)
17. [LinkedIn through its logged-out search, slowly](#17-linkedin-through-its-logged-out-search-slowly)

---

## 1. Plain rules decide; a model only looks at unclear jobs, and only a quote code can find counts

**Date:** 2026-09-28 (DeepSeek reading pages that code fetched: 2026-10-09)

**Context:** Most postings say who they can hire ("Remote - US", "Worldwide"). Some only say "Remote", and then nobody can tell whether they would hire someone living in Lebanon.

**Decision:** Plain code makes every call it can, and each verdict quotes the words it rests on (`Restricted to "Remote - US"`). Only jobs the rules mark `unclear` (status `needs_review`) go to a model. The model must answer with an exact quote and the page it came from. Code then looks for that quote, word for word, in the posting or in a page code fetched itself (`find_quote` in `llm.py`). If the quote is not there, the answer changes nothing.

**Why:** A model can write a quote that sounds right but is not on the page. A quote that code finds in text it fetched itself cannot be made up. Rules that quote their reason also let me see exactly why a job was dropped, and fix the rule when it is wrong (draft: check).

**Trade-off:** Rules miss things a person would catch, so some jobs wait in "needs review". A found quote proves the words exist, not that the model read them right, so the report always shows the link.

## 2. SQLite is the memory; reports are only output

**Date:** 2026-09-28

**Context:** The tool runs every day and should only show me jobs I have not seen.

**Decision:** Every job goes into one SQLite file (`data/jobs.sqlite`), rejected ones too. Each job has a `report_date`, and each day's Markdown report (`reports/<date>.md`) is built from the rows with that date. There are no other report files.

**Why:** Keeping rejected jobs means a job I already passed on never comes back as "new". Because reports are built from the database, any day can be rebuilt after a rule change (`jobhunter reclassify`), and two runs on the same day add to the same file. SQLite is one file with no server to run, which suits a tool with one user (draft: check).

**Trade-off:** The database keeps growing with jobs I will never look at again. A rule change only reaches stored jobs through `reclassify`, and one long write once locked the web app out ("database is locked"), so `reclassify` now saves 100 jobs at a time.

## 3. The same job on several sites: three keys, strongest first

**Date:** 2026-09-28

**Context:** One job often shows up on the company's own board, a remote job site and Google Jobs.

**Decision:** Two listings are the same job when, checked in this order:
1. they have the same source and listing id;
2. they share an ATS posting id (ATS: the hiring software behind a company's careers page, like Greenhouse, Lever, Ashby or Workable), found in any of their links;
3. they have the same company and title, after cleanup, within 60 days (`dedupe_window_days`). This key is skipped when the two listings carry different ATS ids.

Every sighting is kept, so the report lists every site a job was seen on.

**Why:** Job sites often link straight to the company's ATS page, so key 2 joins them reliably. Key 3 catches copies that link nowhere useful. But a company can post "Backend Engineer" twice, once for EMEA and once for the US. Merging those could hide the one that is open to Lebanon, so two different ATS ids always mean two jobs.

**Trade-off:** Key 3 can still merge two different jobs with the same title at the same company when neither has an ATS id. 60 days is my guess at how long one posting stays up (draft: check).

## 4. The fit grade only sorts, and learns from what I apply to and skip

**Date:** 2026-10-19

**Context:** Many jobs pass the rules every day, and I needed the best ones at the top.

**Decision:** DeepSeek grades each shown job 1 to 5, with one sentence why. It learns only from examples: my profile's facts, a short `preferences` text in my words, the jobs I marked Applied, and the jobs I skipped with a one-tap reason (Too senior, Wrong stack, ...). The grade only orders the report, the To apply column and which jobs get a CV first. It never changes a job's status, never hides a job and never rejects one. A posting that asks for 5+ years is ranked down by the grade, not rejected.

**Why:** There are no preference rules to keep up to date: each Applied or Skip changes the examples, so the grades follow what I actually do. Keeping the grade out of the status means every rejection still has a quoted reason (decision 1). Stages I set by hand (Reached out, Interviewing) are not used as examples, because I set them for other reasons than liking the job.

**Trade-off:** The order can be wrong, but a wrong grade only moves a job down the list; I still see it. It costs about $0.0015 a job.

## 5. One job per company on screen, for display only

**Date:** 2026-10-22

**Context:** On 2026-10-21 one board fetch brought in 17 Palantir roles in London, and they filled the lists.

**Decision:** The report, the To apply column and the Today view show each company's best job (by grade, then fit) and fold the rest ("Also at Palantir (16 more)"). This is display only: it never changes a status, a reject reason or which jobs get a CV.

**Why:** One line per company lets me see more companies at a glance (draft: check). Keeping it out of the status means no job is lost; the others are still stored and one click away.

**Trade-off:** If a folded role fits better than the top-graded one, I only see it when I open the fold.

## 6. A posting that offers a 401(k) is rejected

**Date:** 2026-10-19

**Context:** Alloy came in as "Anywhere in the World" on We Work Remotely, but the posting offered a 401(k).

**Decision:** Any posting that mentions a 401(k) is rejected (code `us_benefits`), with the line quoted, whatever its location says and whatever the AI check found. The one exception is the visa list (decision 9).

**Why:** A 401(k) is a US-only retirement plan, so a remote job that offers one is remote within the US. Visa-list jobs are kept because those employers pay for the move, and big companies list every country's benefits in one posting.

**Trade-off:** I lose global-remote companies like Metabase that offer a 401(k) to their US staff. I accept that. The check runs after the location rules, so a job they already reject keeps its own reason.

## 7. When a posting narrows its own location, the narrower rule wins

**Date:** 2026-10-22

**Context:** Some postings say "Worldwide" in the location field but "must be based in the UK" in the text, or "EMEA" with the location "Remote, United Kingdom". They used to wait in "needs review".

**Decision:** A location that fits, narrowed somewhere else in the posting, is rejected (code `location_conflict`), quoting both. When the posting itself doubts the limit ("US only" next to "we hire globally", or "Remote - Europe (UTC-1 to UTC+3)"), the job stays `unclear`. A salary sentence ("applies to US-based candidates only") is not a location rule.

**Why:** The narrower rule is the one that applies when they actually hire. It also keeps "needs review" short, so the AI check spends its runs on real unknowns.

**Trade-off:** A company with a careless location field that really does hire widely gets rejected (draft: check).

## 8. AI and forward-deployed roles only at junior level

**Date:** 2026-10-20

**Context:** My main experience is backend work; my AI engineering experience is newer.

**Decision:** AI engineer, AI automation and forward-deployed engineer titles are rejected (code `junior_only`, quoted) when the title says "senior" or "lead", or the posting asks for 3+ years in any field ("3+ years of software, 1+ with LLMs" counts as 3). A posting with no years stated is kept. A title that also says backend or full stack keeps the usual rules, and backend, software and solutions roles are rejected only at 6+ years.

**Why:** My AI experience is junior level, so senior AI roles are a poor match, while my backend experience can stretch to a 5-year ask (draft: check).

**Trade-off:** I lose senior AI roles that might still hire a strong backend engineer.

## 9. Jobs abroad that sponsor a visa are a separate list

**Date:** 2026-10-14 (verified sponsorship in any country: 2026-10-22)

**Context:** Besides remote jobs I can do from Lebanon, I would move to the Netherlands, Germany, Finland, the UK, Ireland, Spain or Italy, but only with clear visa sponsorship.

**Decision:** A target role in those countries gets its own status, `visa_list`, never `shortlisted`. It has its own report section and web view, and gets no automatic CV, cover letter or contact lookup. It gets there only with quoted evidence: the posting offers a visa, the posting offers help moving (weaker), or the company is on its country's government sponsor list (UK, Dutch, Irish). The To apply column shows only the ones posted today or yesterday. Separately, since 2026-10-22, a job the AI check finds sponsors a work visa in any country is shortlisted as `likely`, when code finds the quote and also reads it as an offer.

**Why:** These jobs mean moving, a bigger step than a remote job, so they stay apart from the remote shortlist. "Sponsorship" alone usually means something else ("executive sponsors", "company-sponsored lunches"), so only the visa words together count. A run can find old postings, so To apply shows only fresh ones. A company that will sponsor the move is worth applying to wherever it is.

**Trade-off:** Germany, Finland, Spain and Italy keep no sponsor list, so there the posting itself must say it. A posting that says nothing about visas is rejected (`no_visa_evidence`), even if the company would sponsor.

## 10. DeepSeek and the Claude Code CLI instead of the paid Anthropic API

**Date:** 2026-10-09 (cover letters: 2026-10-20)

**Context:** Several steps need a model: the AI check, the fit grade, CV rewording and cover letters. Through the Anthropic API with its web search, the AI check alone cost about $0.10-0.30 a job.

**Decision:** DeepSeek does the reading: the AI check (about $0.003-0.01 a job), the fit grade (about $0.0015) and CV rewording (about $0.01). DeepSeek cannot search the web, so code fetches the pages it reads, including ATS postings through their public APIs. Jobs DeepSeek cannot settle go to the Claude Code CLI (`claude -p`) with web search, on my Claude login, so there is no API bill. Claude Code also writes cover letter paragraph 1. The code still accepts `claude-*` models through the API.

**Why:** Cost. This runs every day for one person, and the API was too expensive for that.

**Trade-off:** Claude Code is slow (30-60 seconds a job), and what it read never reaches my code, so code fetches the page it names and checks the quote there. The contact-search backup still uses a small Claude model through the API (about $0.03-0.05 a company), and it is off in the daily run unless I turn it on.

## 11. Tailored CVs: the model picks order and wording, code owns the facts

**Date:** 2026-10-01 (Summary rule: 2026-10-20; bullet length: 2026-10-23)

**Context:** A CV tailored to each job helps, but a model rewriting my CV can add a skill, a number or a title I do not have.

**Decision:** `profile/master_profile.md` is the only source of facts about me. The model only orders and rewords profile bullets and picks skills. Code:
- copies my name, employers, dates and education from `resume.md`;
- decides which bullets print, from tags on each bullet (`[core]` always; `[lead]`, `[fullstack]` and others only when the job matches, with the matched words quoted);
- checks every rewritten bullet against the profile bullets it cites: no new number, tool, name or seniority word, and at most 1 of the original words dropped. A bullet that fails is sent back once, then printed in the profile's own words.

The model never writes a Summary: the Summary paragraph is mine and is copied word for word. I can still edit a CV by hand; the app then lists lines that say more than the profile, without changing them.

**Why:** Anything on my CV can come up in an interview, so it must be true and in my own words (draft: check). On 2026-10-23 the model had cut clauses and an "estimated" from bullets, which changed what they claimed, so a rewrite may no longer shorten a bullet.

**Trade-off:** The CVs are less tailored than a free rewrite would make them.

## 12. Cover letters: two paragraphs, only when I ask

**Date:** 2026-10-20

**Context:** Earlier versions wrote a full letter (header, opening, body, closing) for every new shortlisted job in the daily run.

**Decision:** A letter is two paragraphs, with no header, date, greeting or sign-off, and is written only when I click Write cover letter (or run `jobhunter cover <id>`). Paragraph 1 is why this company: Claude Code writes it from the posting and up to 3 pages code fetches from the company's site. Code checks every name and number in it against those pages and my profile, and drops a sentence that pitches my own past work. Paragraph 2 is my own text, printed as is.

**Why:** The application form already has my name and the job, so a header and greeting add nothing. In a side-by-side test DeepSeek's paragraph read as AI, so Claude Code writes it. Paragraph 2 is about me, so I wrote it myself. Only on request, because most applications do not ask for a letter and each one needs a read before I use it (draft: check).

**Trade-off:** Paragraph 1 still needs that read: plain claims like "they ship weekly" pass the checks. A letter takes about 25 seconds when I click.

## 13. Emails go out only when I click Send, and a second click cannot send twice

**Date:** 2026-10-01

**Context:** The web app writes cold emails and follow-ups to real people, from my own Gmail.

**Decision:** An email is sent only by the Send button (`POST /api/jobs/{id}/send`). Nothing is sent automatically, follow-ups included: the app only shows them as due. Before the network call, the email is saved as a row with the state `sending`. A unique index on (job, step) means a second `sending` row for the same email cannot be saved, so a second click fails instead of sending again. If Gmail refuses, the row is marked failed and the app says "Not sent". If the call ends without a clear answer, the row stays `sending`, the app says Gmail did not confirm and not to send again yet, and the next inbox check looks up the email's Message-ID in Gmail: found means it went out, missing means it did not.

**Why:** These go out under my name, so I read and time each one myself. Sending the same email twice, or not knowing whether one went out, looks careless to the person reading it (draft: check). A daily cap (15, and 3 for guessed addresses) protects my Gmail's reputation, since bounces hurt it.

**Trade-off:** More clicks for me and no scheduling. After an unclear send I wait for the next inbox check to know.

## 14. A Gmail app password, not Google OAuth

**Date:** 2026-10-01

**Context:** The app sends through my Gmail and reads replies and bounces from the inbox.

**Decision:** It uses a Gmail app password (which needs 2-Step Verification), with SMTP to send and IMAP to read. The inbox is opened read-only, and nothing is marked as read.

**Why:** Google's OAuth for reading a personal inbox logs you out every 7 days unless Google reviews the app.

**Trade-off:** An app password opens the whole mailbox, so it lives only in `.env`, which is not in git, and the code never turns on the mail libraries' debug output, which would print the login line.

## 15. The web app only answers my own browser

**Date:** 2026-10-01 (CV exception: 2026-10-07)

**Context:** `jobhunter serve` can send email from my Gmail, so any web page that could reach it could press Send.

**Decision:**
- It listens on 127.0.0.1 only.
- A request whose Host header is not 127.0.0.1 or localhost on its port is refused.
- Every request that changes something needs a random token put into the page at startup (`X-JH-Token`), a JSON body, and no foreign Origin.
- There is no CORS (the browser rule that lets one site read another site's answers), except GET `/api/cv/...`, which any page may read.

**Why:** 127.0.0.1 keeps it off the network. The Host check stops DNS rebinding (a trick where a website gets your browser to treat it as localhost). The token and the JSON-only rule stop another site open in my browser from sending a request that changes something. The CV exception lets my Chrome extension attach a CV on a job site; it only reads PDFs in `cv_dir` and changes nothing.

**Trade-off:** There is no login and no access from my phone or another computer. Any site I allow can read my CV PDFs (Chrome asks once per site before a site reaches this computer).

## 16. Personal details stay out of git

**Date:** 2026-10-02

**Context:** The CVs, emails and letters need my name, contact details and work history, and the code is public.

**Decision:** My name and contact details are `MY_*` lines in `.env`. My profile (`profile/master_profile.md`) and base CV (`resume/resume.md`) are ignored by git; git has made-up `*.example.md` copies to start from. Tests use a frozen profile in `tests/fixtures/`, so editing the real one never breaks a test. Numbers like the lowest pay I would move for (`RELOCATION_MIN_MONTHLY_USD`) are also in `.env`, never in a tracked file.

**Why:** The code can be shared while my data stays private. It also stops profile edits from showing up as code changes.

**Trade-off:** A fresh checkout does not run as me until I copy the example files and fill in `.env`.

## 17. LinkedIn through its logged-out search, slowly

**Date:** 2026-10-21

**Context:** LinkedIn has many jobs in the Gulf, and jobs that offer visa sponsorship, that no other source brought in. A one-day trial found 75 jobs not in the database: 13 shortlisted and 10 for the visa list.

**Decision:** I read LinkedIn's logged-out job search, knowing its terms forbid automated access. It stays small: 2.5 seconds between requests (about one a second gets HTTP 429, "too many requests"), searches by place only (the UAE, Qatar, Lebanon, and the UK and the Netherlands with "visa sponsorship"), only target titles get their page read, and it is never fetched twice in a run.

**Why:** It finds jobs worth applying to that I had no other way to see, and at this low volume the load on LinkedIn stays tiny.

**Trade-off:** It goes against LinkedIn's terms and can stop working at any time. It is the slowest source (a few minutes a run), and logged out, the remote and level filters do nothing, so searches cannot be narrowed further.
