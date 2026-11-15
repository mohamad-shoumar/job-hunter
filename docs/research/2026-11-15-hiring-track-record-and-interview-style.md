# Hiring track record and interview style per company (2026-11-15)

Two questions, asked per company, answered by a script with a quote it can find again
on a page it fetched itself:

- **Q1.** Has this company hired people from outside the EU before, above all in Germany?
- **Q2.** Does its interview have live coding / LeetCode-style tests, and how many rounds?

Everything marked "checked" was fetched on 2026-11-15. "Not read" means the page blocked
the script, so its terms were never seen (and that alone makes the site unusable).

## Verdict in short

- **Q1: nothing public proves real non-EU hires per German company.** Germany has no
  sponsor register (a Blue Card needs no licensed employer). The best proof a script can
  get is **the company's own postings offering a visa, seen again and again over time**.
  The tool already stores those postings, so the best source is our own database.
- **Q2: there is no clean public source.** The best one is **the posting's own text**
  (about 20 of ~700 kept companies describe their steps there), then **hiring-without-whiteboards**, which is alive
  and easy to parse but covers only ~2% of the companies we keep.
- Glassdoor, Kununu, levels.fyi, Blind and Reddit are **not usable**: they block scripts,
  forbid it, or both.

## Q1 sources, ranked

| # | source | script can use it? | what it proves | notes |
|---|---|---|---|---|
| 1 | **Our own stored postings** (`data/jobs.sqlite`, read with `visa.read_posting`) | yes, already ours | the company **offered** a visa in a posting, with the sentence | checked: 190 companies have a visa offer (no refusal) in some posting; 13 on a German-located posting; 6 of those in 2+ different posting months (Wayve, n8n, The Exploration Company, Clera, Solve Intelligence, and a "stealth startup" that reads like a recruiter: drop agencies first). Grows every run |
| 2 | **EuropeVisaJobs** `feed.json` (CC BY 4.0, already used for board discovery) | yes; robots.txt invites bots, asks ~1 request/s and a named User-Agent | a third party **says** a posting offers a visa; each job has `evidence_quote` + `apply_url` | checked: 1,473 jobs, 146 in Germany (`country_code` DE) from 20 companies. For Germany its only badge is "Explicit Visa Policy" (a posting sentence): no register exists. Use only as a pointer: fetch `apply_url` ourselves and find `evidence_quote` there (`find_quote`); never trust its word alone (project rule) |
| 3 | EuropeVisaJobs `data/verified-sponsors-2026.json` | yes, same terms | per company: hubs, register matches, a summary | checked: 203 employers, only 20 hiring in Germany. Live roles only, so a company drops out when it stops posting. Same rule: a pointer, not proof |
| 4 | **relocate.me** "companies hiring" lists (`/companies-hiring/germany?page=N`) | robots.txt allows it; its terms page (employer terms) has no scraping clause that we found; no API | the company is on a **hand-picked** list of firms that hire from abroad | checked: 74 German companies over 4 pages. The profile page itself (e.g. adjoe) has no visa sentence, so there is no quote to re-check. Jobs list "Visa services", but only ~23 jobs site-wide (2026-10-13 research). Weak, but cheap |
| 5 | Company careers / "life at" pages (home, /careers, /jobs, /about) | yes, the company's own site | "visa & relocation support", "25+ nationalities" | checked on 11 companies with German offices (8 from our kept jobs, 3 others; a 12th returned nothing): only 2 had a usable sentence on a guessed URL (adjoe: "extensive visa & relocation support"; Prior Labs: "Seamless relocation including relocation bonus"). The rest had no such text at those URLs (some may build the page in JavaScript; not checked). "N nationalities" counts EU people too, so it is not proof of non-EU hiring |
| 6 | Bundesagentur Jobsuche API (`rest.arbeitsagentur.de/.../pc/v6/jobs`, public key `jobboerse-jobsuche`) | yes: v6 answers 200 with a plain User-Agent (v4 now 403) | nothing about visas | checked: no "international" or Make-it-in-Germany field in the results. Not useful for Q1 |
| 7 | Make it in Germany job listings | **no**: listing pages sit behind a Radware bot check; robots.txt disallows search URLs (`tx_solr[q]`) | an employer agreed to show the job to foreign applicants (per the site's FAQ, seen through a search summary only) | jobs come from the Bundesagentur board, mostly in German. Not automatable |
| 8 | Kununu | **no**: robots.txt blocks `/api/` and search; a company page answered 202 with an empty bot-check body, the terms page a CAPTCHA (terms not read) | reviews, not hiring facts | skip |
| 9 | Glassdoor | **no**: 403 to scripts (terms not read; older versions forbid scraping) | reviews | skip |

Measured on the stored postings: **0 of 35,800 mention "Blue Card"**. German employers
almost never name the permit; they say "visa support" or "relocation". So match the
general visa wording (as `visa.py` does), not the permit name.

**What a "track record" score could be (idea, not built):** for each company, count the
distinct months in which one of its stored postings had a visa offer quoted by
`read_posting`, plus a re-found EuropeVisaJobs quote. Every point is a sentence on a page
we fetched. Two or more months = "has done it before"; one = "says so now"; zero = unknown,
never "no".

## Q2 sources, ranked

| # | source | script can use it? | what it proves | notes |
|---|---|---|---|---|
| 1 | **The posting's own text** (already stored) | yes | the steps, when the company writes them ("4 stages - HR ➡️ Technical discussion ➡️ Live Technical interview ➡️ Home Assignment") | checked on 35,800 postings / kept jobs: "live coding" 184 / 9, "pair programming" 221 / 20, "take-home" 222 / 12, HackerRank 12 / 0, LeetCode 20 / 0, Codility 3 / 1. Read by hand on kept jobs: take-home 12 of 12 companies are about the interview (two say there is none: "no live coding or take-home"); live coding 6 of 7 (Databricks means a skill); pair programming only 2 of ~13 (the rest describe daily work). "Interview process" alone is mostly boilerplate (fraud warnings, disability help). So: about 20 kept companies say something, and a negation check is needed |
| 2 | **hiring-without-whiteboards** (`raw.githubusercontent.com/poteto/hiring-without-whiteboards/main/README.md`) | yes: MIT licence, raw GitHub file | a note on the process, sent in by a contributor (who is not recorded) | checked: alive, not archived, 53k stars, last commit 2026-11-14 (most recent ones fix dead links). One line per company: `- [Name](url) \| Location \| Process note`. A simple regex reads 762 of 766 lines; 756 have a note. 85 are in Germany. Only 15 of our 718 kept companies are on it (SumUp, GitLab, Doctolib, Sourcegraph, Algolia, ...); 85 of 5,356 stored |
| 3 | Company "how we hire" / engineering-blog pages | yes, own site | the process in their words | same 12-company sample: only adjoe had one ("Interview Process ... Step 1 Online Application, Step 2 A Recruiter Call, Step 3 Take..."). Needs the right URL per company; a guess rarely hits. Some publish a GitHub repo (AutoScout24/hiring) |
| 4 | levels.fyi | **unclear, so no**: robots.txt and `llms.txt` invite agents to salary pages, but a salary `.md` page gave 403 to our script and the terms page a CAPTCHA (terms not read) | salaries; its `llms.txt` never mentions interviews | skip for Q2 |
| 5 | Glassdoor interview pages | **no**: 403 (terms not read) | | skip, though it is the richest source |
| 6 | Blind | **no**: robots.txt blocks ClaudeBot, GPTBot, anthropic-ai and `/search/` | | skip |
| 7 | Reddit | **no** for scraping: robots.txt is `Disallow: /`; a search `.json` URL gave 403 (the official API was not checked) | | skip |

**Careful with hiring-without-whiteboards:** being on the list does not mean "no live
coding". Contentful's note says "live coding challenge (you can use the internet)";
Adeva's "online coding assignment". The signal is the **note text**, read with the same
phrases as the posting (live coding, pair programming, take-home), not the listing itself.
Notes are undated and sent in by anyone; the list started in 2017, so some may be old. The README has a "Duds"
section asking readers to remove companies that changed, but no dates.

**Rounds:** neither source gives a number reliably. Count only when a sentence lists the
steps ("4 stages", "Step 1 ... Step 4"); otherwise leave it unknown.

## Netherlands and UK (bonus)

Already covered better than Germany: the UK Home Office register and the Dutch IND
register are in `sponsors.py`, and the Irish permit list counts permits actually
issued per company, the closest thing to a real "track record" number we found. EuropeVisaJobs
re-uses the same registers, so it adds nothing for NL/UK beyond pointers.

## Cost

Every usable source above is free with no key: our database, EuropeVisaJobs (free, CC BY 4.0,
asks for a link back), relocate.me pages, company sites, the GitHub raw file, the Bundesagentur
API (public shared key). The blocked ones sell data or ask for paid partner access.

## What we did not check

- Kununu, Glassdoor, levels.fyi and Blind terms text (pages blocked scripts); Reddit's official API.
- Make it in Germany's employer-consent rule on its own FAQ page (seen only in a search summary).
- relocate.me per-job "Visa services" pages this time (counted on 2026-10-13).
- Whether hiring-without-whiteboards notes match what companies do today.
