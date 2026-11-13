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
18. [No review list: a job is shortlisted or rejected](#18-no-review-list-a-job-is-shortlisted-or-rejected)
19. [The old review list is cleared, and the Pipeline has fewer columns](#19-the-old-review-list-is-cleared-and-the-pipeline-has-fewer-columns)
20. [The LinkedIn note lives on the job](#20-the-linkedin-note-lives-on-the-job)

---

## 1. Plain rules decide; a model only looks at unclear jobs, and only a quote code can find counts

**Date:** 2026-09-28 (DeepSeek reading pages that code fetched: 2026-10-09)

**Context:** Most postings say who they can hire ("Remote - US", "Worldwide"). Some only say "Remote", and then nobody can tell whether they would hire someone living in Lebanon.

**Decision:** Plain code makes every call it can, and each verdict quotes the words it rests on (`Restricted to "Remote - US"`). Only jobs the rules mark `unclear` go to a model. The model must answer with an exact quote and the page it came from. Code then looks for that quote, word for word, in the posting or in a page code fetched itself (`find_quote` in `llm.py`). If the quote is not there, the answer changes nothing.

**Why:** A model can write a quote that sounds right but is not on the page. A quote that code finds in text it fetched itself cannot be made up. Rules that quote their reason also let me see exactly why a job was dropped, and fix the rule when it is wrong (draft: check).

**Trade-off:** Rules miss things a person would catch, so some jobs stay `unclear` (shortlisted since 2026-10-27, see [18](#18-no-review-list-a-job-is-shortlisted-or-rejected)). A found quote proves the words exist, not that the model read them right, so the report always shows the link.

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

## 18. No review list: a job is shortlisted or rejected

**Date:** 2026-10-27

**Context:** Jobs the rules could not settle waited in "needs review": a posting that says only "Remote", or one with no posting date. By 2026-10-27 that list held 183 jobs, next to 208 shortlisted.

**Decision:** Every job the rules keep is shortlisted, an unclear or undated one too. A job is now rejected, shortlisted, or (abroad) on the visa list. The daily run's AI check and date lookup still run on those jobs and reject the ones they find quoted evidence against; what they cannot settle stays shortlisted, marked `unclear` or "No posting date". The jobs already in "needs review" stay there for me to go through by hand: `reclassify`, the AI check and the date lookup leave them alone.

**Why:** (draft: check) One list to act on. The fit grade sorts the shortlist, so an unclear job worth a look still gets seen, instead of sitting in a second list.

**Trade-off:** The shortlist gets jobs that may turn out to be US-only or months old, and the daily run makes CVs and looks up contacts for them too. The report and the web app mark them `unclear`, so I check those before applying.

## 19. The old review list is cleared, and the Pipeline has fewer columns

**Date:** 2026-10-29

**Context:** Since decision 18, 183 jobs still waited in "needs review", all weeks old. Judged again by today's rules, every one would come out shortlisted, which would fill To apply with old postings. The Pipeline also had a Saved column nobody used (no job was in it), a Rejected column next to Closed, and an Email someone column for applied jobs nobody at the company had been emailed about.

**Decision:** The 183 jobs are rejected with the code `review_cleared` (migration 2), and `reclassify` never judges them again. The "needs review" status is gone from the code. The Pipeline drops the Saved, Rejected and Email someone columns: a saved job shows in To apply, a rejected one in Closed (the reason is on the card), and every Reached out job is in one column, newest first.

**Why:** The jobs in review are old now, and new unclear jobs go to the shortlist anyway. Outreach goes through LinkedIn now: I send a LinkedIn note for every job I apply to (the apply-job skill finds the person and writes it), so a column of "jobs nobody was emailed about" no longer says what to do next. (draft: check) Fewer columns, and one place for each job.

**Trade-off:** A cleared job that was worth applying to is gone from my lists. They are still stored, under "Rejected (in a report)" in the Jobs tab and "Cleared from the old review list" in their day's report, and a database copy from before the change is in `data/backups/`.

## 20. The LinkedIn note lives on the job

**Date:** 2026-11-05

**Context:** Since 2026-10-29 I reach out on LinkedIn, not by email: one person per job, one note of at most 300 characters. The apply-job skill wrote those into a Markdown file (`reports/linkedin_notes_2026-10-31.md`), one row per job, while the job's own card still showed a "Who to contact" box and an email composer (subject, body, Fill template, Save edits, Copy, Send) I no longer use.

**Decision:** The person's LinkedIn link and the note live on the job itself (`applications.linkedin_url` and `linkedin_note`, migration 3). The card's "Who to contact" and "Email" boxes are gone; in their place one **LinkedIn** box: the link to the person, the note, and a character count. Both boxes save when I click away, so there are no buttons, and nothing is sent from the app: I press Connect on LinkedIn myself. The apply-job skill fills them with `jobhunter linkedin <id> --url ... --note ...` instead of adding a row to the file. Jobs I already applied to and reached out on keep whatever they had; nothing was copied over.

**Why:** The note lives next to the job it is about, so I open one card and see the CV, the posting, the person and the note. The Markdown file meant two places to look, and the email boxes on the card were dead weight I kept scrolling past. The lookup, drafts and sending code stays: the inbox check still reads replies, bounces and rejections for the emails I sent before.

**Trade-off:** The file's "Why this person" column (fellow AUB grad, an Arab or Muslim name, CEO at a small company) is not on the card: the skill still says it in its report. The jobs from Oct 24 to Nov 5 stay only in the file, so the week-one review on about 2026-11-07 reads both.

## 21. Forward-deployed stays a target role, but only as an engineering title

**Date:** 2026-11-06

**Context:** I wondered whether to drop forward-deployed (FDE) roles, or keep them only for the UAE and Qatar: in Europe the role is client-facing, so it often wants the local language at native level, and I am junior, which makes visa sponsorship harder. The stored jobs said otherwise. Of the 28 FDE jobs that reached the visa list, about 24 are London or Dublin, where the language is English; only 3 are Amsterdam. The 12 FDE jobs that did ask for German or Dutch were already rejected with the sentence quoted (`language_required`). And FDE is one of my most active searches: 15 of 18 shortlisted FDE jobs are in the UAE or Qatar with 7 reached out, and in the UK I reached out on Women Building Bio and OJ Digital and applied to Palantir FDSE UK Government. What did keep showing up wrongly were FDE titles that are not engineering at all: "Forward-Deployed Banker" and "Forward Deployed AI Scientist", both of which I skipped by hand as not my role.

**Decision:** FDE stays a target role everywhere, with no country restriction. "forward deployed" moves into a new list, `title_include_needs_role` in `config/filters.json`: a keyword there counts only when the title also names an engineering role (engineer, engineering, developer, programmer, swe; not "development", which would let "Forward Deployed Business Development Representative" through). "Forward Deployed Engineer" and "Forward Deployed ML Engineering Expert" still pass; "Forward-Deployed Banker", "Forward Deployed Data Scientist" and "Deployment Strategist - Forward Deployed" are `title_not_target`. Checked against the stored jobs: the title rule changes its answer on 28 of 27,065, all of them banker, investor, consultant, scientist, analyst, lawyer or strategist titles, and only 4 rows were still live.

**Why:** The worry was real but the rules already covered it: a posting that wants German says so, and the language rule quotes it. Cutting FDE to the Gulf, or dropping it, would have hidden the London roles I actually applied to. The junior-plus-sponsorship doubt is about the visa list as a whole, not this one title, so it is not settled here.

**Trade-off:** An FDE posting that is engineering work under a non-engineering title ("Forward Deployed Builder") is now rejected without being read.

## 22. The Pipeline has a Rejected column again

**Date:** 2026-11-11

**Context:** Decision 19 folded Rejected into Closed, so one column held three different things: companies that said no, jobs I chose to skip, and jobs that went quiet. By today there are 579 closed applications: 54 rejections and 525 jobs I skipped. When I asked for "the jobs I got rejected from in the past week" there was no column to move them to: the two the inbox check closed (Aurora Energy Research, Airwallex) landed in Closed next to the 21 jobs I had skipped the day before.

**Decision:** Rejected is a column again, between Offer and Closed. It holds the applications closed with reason `rejected`; Closed keeps `skipped` and `ghosted`, with the reason still on the card. This is display only: both are the stage `closed`, told apart by `closed_reason`, so there is no new stage, no migration, and nothing changes in `tracking.py`, the reports or the Jobs tab. Moving a card into Rejected closes it with reason "rejected" and stops asking me why, which is what the generic Closed column prompts for.

**Why:** (draft: check) A rejection is the one closing I did not choose, and it is the number I want to see without reading chips: how many said no this week, against how many I skipped myself. Mixing them made the Closed count meaningless.

**Trade-off:** Two columns to scroll past instead of one, and the board now shows every rejection ever (54 today), not just this week's. The column asks for its own list (`closed_rejected`), because the job list stops at 500 rows and 525 skipped jobs would otherwise push the oldest rejections out of sight. Decision 19's reason for dropping the column still stands for Saved and Email someone, which stay gone.

## 23. A rejected job follows a listing of itself somewhere else

**Date:** 2026-11-11

**Context:** I sent four LinkedIn screenshots and asked whether we had caught those jobs. We had: 8 of the 9 jobs in the alert emails, and the 6 we had missed from the "Jobs similar to..." panel were all 26 to 68 days old and posted before the LinkedIn source existed (`reports/linkedin_alert_check_2026-11-11.md`). What the check turned up instead was a dedup hole. `find_match` matches a listing to a stored job by company and title alone (`identity.fingerprint`, no location), and a match goes to `touch`, which records the sighting and returns: the job is never judged again, and `location_raw` is not even among the fields `touch` fills in. So the first country a job is seen in decides its verdict for good. Virtusa's "Lead Software Engineer" was stored from LinkedIn on Oct 22 as London and rejected `no_visa_evidence`; five **Doha** listings were folded into it on Oct 30 and a **Dubai** one on Nov 7, none of them judged. I fetched one of the Doha postings and ran its real text through `classify` as a Qatar job: it shortlists. Kraken (a UAE listing on a US row) and Brain Co. (an Abu Dhabi listing on a San Francisco row) have the same shape, but `touch` threw away their dates, so they cannot be judged after the fact. Callsign is the near miss: "Software Engineer (Full Stack)" is on the visa list from London (6998) and also exists in Abu Dhabi; it escaped only because the Abu Dhabi posting was 40 days old.

**Decision:** When a listing matches a stored job but names a different place, and the stored job is **rejected for where it is**, classify the incoming listing on its own words and, if it is not rejected, the row follows that listing (`pipeline._rejudge`, `store.adopt_listing`). Three guards keep it narrow, because two listings of ONE posting also differ in their location text ("Dubai - United Arab Emirates" against "Dubai, Dubai, United Arab Emirates"): only the reject codes that are about the place (`_PLACE_CODES`: not_remote, local_only, location_restricted, location_conflict, residency_required, timezone_restricted, no_sponsor, no_visa_evidence, below_relocation_pay), so a thin second listing can never undo `too_old`, `too_senior` or a title rule, whose evidence is in the text; only a listing that brings its own description, since Getro has none and LinkedIn job pages do fail; and only upwards, never pushing a shortlisted job down. Over the 33k stored jobs this trigger fits 234 of them (111 `no_visa_evidence`, 51 `not_remote`, 49 `location_restricted`, 23 `no_sponsor`) - a couple per run - where the un-narrowed version fitted 1,542, including 616 `too_old` and 45 `too_senior`. When a job does follow a listing, everything the classifier reads is overwritten with that listing's values, along with `source`, `source_url` and `application_url`, so `reclassify` reproduces the verdict and the link opens the posting that was judged; `ai_check_json` and `date_check_json` belonged to the old listing and are dropped. `company`, `title`, `fingerprint` and `ats_key` stay, so the old listing still matches this row instead of coming back as a new job. Jobs cleared out of the old review list (`review_cleared`) stay rejected, as in `reclassify`. The daily report lists what came back under **Listed somewhere else**; `assign_daily` gives the job today's report date, which is what the date lookup, the AI check and the fit grade read, and it is passed to the outreach step as if it were new, so it gets a CV.

**Why:** (draft: check) A job I could actually take was sitting behind a verdict about another country, with no way for me to see it. The alternative, putting the country into `fingerprint` so each place is its own job, needs a migration that recomputes every stored row (or hundreds of rejected jobs come back as new) and would split rows whose source gives no location at all.

**Trade-off:** One row still holds one verdict, so a job like Callsign cannot be both "London, visa list" and "Abu Dhabi, relocation" at once: whichever listing is seen while the row is rejected wins, and a job's reason can change under me between runs. A rejection about the posting's own words is never revisited, so a job rejected `too_old` or `language_required` whose Gulf listing is fresh stays rejected. And the fix only acts on listings seen from now on: Virtusa 17758 and the other rows that already swallowed a Gulf listing stay rejected unless they are repaired by hand.

## 24. One copy of a role, and one box per company

**Date:** 2026-11-14

**Context:** Two complaints in one message: the shortlist showed the same role more than once, and a company with several open roles took over the list. Both come from how a listing is matched to a stored job. `identity.fingerprint` is company + title with no location, and `find_match` refuses to merge two listings that carry **different ATS ids**, on purpose: one company can post "Backend Engineer" for EMEA and for the US, and merging those could hide the one open to Lebanon. But a company also re-posts the same opening under a new id. On 2026-11-13 the stored jobs held 19 roles with more than one live copy, 45 rows: Axle Energy's London "Software Engineer" four times, hyperexponential's "Senior Product Engineer" five, Databricks' London "Forward Deployed Engineer" twice. In 16 of the 24 foldable rows one copy was a role I had already applied to, reached out on or skipped, so roles I had decided about kept coming back as new. Separately, 127 of the 247 jobs waiting in the Jobs tab were at the 37 companies with more than one: one board fetch brought 15 Deliveroo roles and 10 at Google.

**Decision:** Two parts, both on my call.

*Duplicates are rejected, not hidden* (`duplicates.py`, code `duplicate_role`). After the rules judge a job, every copy of its role is gathered - same fingerprint, same place - and all but one are rejected, the reason naming the job that was kept ("Same role, already kept as job #6251: ... posted 2026-10-14 (you applied to it)"). The copy that stays is the one carrying my work (applied, reached out, LinkedIn note, or skipped), else the newest posting, which is the one still open; between two copies that are equal on both, the dated one wins, because an undated job sorts by the day it was found and the date lookup later in the same run may still reject it as `too_old`. Only copies still `shortlisted` or `visa_list` are candidates, so a twin rejected as `too_old` or for its country can never swallow a posting the rules kept, and a copy I acted on myself is never the one rejected, whichever one is kept: it is not in a waiting list, so it clutters nothing, and rejecting it would file a job I applied to under Rejected and put a red chip on its card in Tracked. That is the difference between 24 foldable rows and the 16 the live run folded. A tailored CV does not count as my work: the daily run writes those on its own. Place is part of being the same role: two location texts match when one's words are the other's or a subset of them ("London" = "London, UK" = "London (hybrid), United Kingdom"), and two bare-remote texts match each other, so Resonance's "Applied AI Engineer" stays twice, once for London and once for Berlin. The rule runs in `pipeline.ingest` for the role a new job belongs to and in `jobhunter reclassify` for every role, through the same `duplicates.fold`, so the two can never disagree and running it twice changes nothing the second time.

*One company, one box* (`byCompany` / `companyBox` in `app.js`). The Jobs tab's two waiting views (Shortlisted, Visa list) and the Pipeline's To apply column draw a company's jobs in one box: its best job (grade, then fit), then a button counting the rest, which opens them in place. The old flat "+N more at Palantir" button stays in Today's triage lists, and Tracked, Closed, Rejected and the LinkedIn follow-ups stay flat: those are jobs I am already working, where a second one at the same company must never sit behind a button. Display only: every job keeps its status, and the box sits where the company's best job sat, so the day headings still read top to bottom.

**Why:** (draft: check) The duplicate copies were not a display problem. They were separate rows with separate statuses, so each one got its own CV from the daily run, its own place in the report and its own card in To apply, and a role I had already applied to came back looking new. Rejecting the copy is what the rest of the project does with a verdict: it stays stored so it never returns as new, it carries a reason I can read, and `reclassify` works the whole rule out again from scratch, so changing the rule undoes it. The company box is the opposite kind of problem - every one of Deliveroo's 15 roles is a real job - so it stays display only and lets me choose from inside the box.

**Trade-off:** A keeper can still be rejected later in the same daily run - the date lookup and the AI check run after `ingest`, and nothing re-folds until the next run or a `reclassify` - so a role can briefly show no copy at all; ranking dated copies above undated ones makes the likeliest case rare. A fresh re-posting of a role I applied to is now hidden behind a rejection, so if a company re-posts because the first opening closed, I will not see the new one in the shortlist; it is in Rejected with the reason naming the job it was folded into. The place rule is a word-subset test, not a gazetteer: "Netherlands / Belgium" and "Netherlands" read as one place, and a company that writes its location two unrelated ways ("Worldwide" against "Remote - India") reads as two. Grouping by company in the Jobs tab pulls a company's older jobs up under its newest day's heading; each row still shows its own date.
