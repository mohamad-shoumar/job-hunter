# How many jobs are out there, and how many we see (2026-10-21)

Question: how many relevant jobs are posted a day, and how many does the pipeline miss?
"Relevant" means a target title, mid level (about 2-5 years asked), and one the user can
actually take: remote and open to Lebanon, on-site/hybrid in the UAE or Qatar, or in one of
the 7 visa-list countries with a visa offered.

Method: four research passes on 2026-10-21 (Gulf, Western Europe, US/Canada/Australia, and
direct counts from remote-job APIs), plus the database (`data/jobs.sqlite`, runs 25-38).
Site counts were never added across sites, because aggregators repost each other.
Everything is one day or one week of data, so treat the ranges as rough.

## Summary

The pipeline already sees most of the jobs that fit. The gap is about **2-4 jobs a day**, not
dozens. Most "remote" jobs in the US, Canada and Australia are for people living there, so the
big numbers on LinkedIn are not jobs the user can take.

| Region | Relevant jobs a day, anyone can apply | Open to the user | Pipeline surfaces now (DB, Oct 17-20) | Where the gap is |
|---|---|---|---|---|
| UAE + Qatar, on-site/hybrid | ~20 (target title, any level) | 2-4 | 2.3 shortlisted + 2.5 review | LinkedIn: ~10-15 more a week, mostly not in our DB |
| Gulf companies, remote | - | ~0-1 a week | - | none (gig platforms and global companies) |
| Western Europe, remote (open to Lebanon) | 150-350 (estimate) | 1-3 | remote, all regions: 1.8 shortlisted + 5.3 review | small: EU Remote Jobs, Jobicy |
| Western Europe, visa offered | - | 1-3 direct employers (2-6 with recruiters) | 5.5 visa list (incl. sponsor registers) | UK/NL "visa sponsorship" on LinkedIn |
| US, remote | 30-150 | 1-3 | (in the remote row above) | Remote Rocketship (~2-3 before dedupe) |
| Canada, remote | 5-25 | 0-1 | (in the remote row above) | - |
| Australia, remote | 1-5 | ~0 | - | - |

## What the pipeline does now (DB, 2026-10-17 to 2026-10-20)

- Each run reads about 10,000 listings (`runs.stats_json`, `fetched`). Most are whole careers
  pages of watched boards: Greenhouse alone gave 1,648 too-old jobs in those 4 days.
- About 115 a day are recent with a target title. Of those, per day: 5 shortlisted, 8.5 need
  review, 5.5 visa list. The rest are rejected for good reasons (spot-checked): no visa
  evidence 17.5, agency 15, other stack 11, not remote 11, junior-only rule 10.5, too senior
  6.5, language 6.5, location-restricted 6.
- Sources barely overlap: of 358 shortlisted/review/visa jobs since Oct 1, 257 (72%) were found
  by one source only. SerpApi (Google Jobs, mostly Gulf and Beirut) found 104 and shared 1 with
  any other source. Little overlap means the sources each see a different slice.
- Applied jobs (`applied_at` set) by source: Himalayas 17, SerpApi 8, Arbeitnow 4, HN 3,
  WWR 2, Ashby 2, one each from Teamtailor, RemoteOK, NoDesk, Getro. Greenhouse, the biggest
  source by volume, gave none.

## Findings

### 1. Runs lose sources to the network (cheapest fix)

In 4 of the last 5 runs (35-38) the first requests of several sources failed with
`ConnectError`: all Gulf Greenhouse boards (Careem, Tamara, AI71, Bybit, OKX), Teamtailor,
BambooHR (Toters), SmartRecruiters (talabat, Namshi), Pinpoint (Tabby), Lever, MailerLite, and
the first Getro queries. The later requests of the same sources worked. Retrying every failed
endpoint a few hours later returned 200 for all of them. So the machine's network is not up
yet when the run starts (likely right after waking), and the boards listed first are the ones
lost. Careem's board failed in runs 35, 37 and 38 (last read in run 36, 2026-10-20 morning).

### 2. US, Canada, Australia: the jobs are mostly not open to Lebanon

- 29 recent LinkedIn US remote backend jobs read: 17 US/North America only, 1 international
  without Lebanon (Nango), 3 open (Constructor "UTC+1 to UTC+7", 2 Canonical EMEA), 1 country
  list, 7 silent. Only 1 was a US company the user could clearly apply to.
- WFH.team's 2026-08-27 snapshot of 7,475 remote jobs: 65.2% US-only, 19.6% one other
  country, 3.4% worldwide.
- Himalayas, all engineering, 24h: 224 jobs, 77 US-only, 11 US+Canada, 4 with no country
  limit.

### 3. Western Europe

- "Remote Europe/EMEA" usually excludes Lebanon: of 26 such jobs, 15% yes, 58% no, 27%
  unclear. Of 12 that named no countries in the text, 9 had a country list on the company's
  own job page without Lebanon (Ashby `secondaryLocations`, Workable `locations`, Breezy
  `applicantLocationRequirements`). A silent posting is usually a no.
- Visa offered, from LinkedIn "visa sponsorship" searches with descriptions read (24h): NL 6 of
  50, UK 8 of the first 60 (of 177), DE 1 of 60 (17 demand a work permit), ES 0/60, IE 0/25,
  FI 0/11. 639 of 957 German titles have "(m/w/d)", and many are German-language.
- Logged out, LinkedIn's public search ignores `f_WT` (remote) and `f_E` (level); only
  `f_TPR`, keywords and location work. `2026-10-10-job-sources.md` lists `f_WT`/`f_E` as
  filters; logged out they no longer apply.

### 4. Gulf

- LinkedIn 7 days: UAE 1,015 / Qatar 111 distinct jobs for 7 keywords; target titles UAE 128,
  Qatar 12. Without senior/lead titles and agencies about 9 a day; 68 descriptions read, about
  3 a day fit ~3 years of Python backend, about 2 a day under the junior-only AI/FDE rule.
- Fitting employers absent from our DB: Open Innovation AI, Generative Futures, Artefact, ADG,
  UAE University, AMOUAGE, eMinds, Boundless, Al-Futtaim, Core42/G42. TII and Deeplight appear
  only as `needs_review`.
- Brain Co. has a public Ashby board, `brainco`, with 5 Abu Dhabi jobs.
- Gulf "remote" listings are gig platforms (Ethos, Jobgether, Mindrift, Alignerr) or global
  companies naming a UAE location; real Gulf remote roles were few and senior.
- Bayt, GulfTalent and Naukrigulf answer 403 to scripts and add little over LinkedIn. Indeed
  (all countries) shows a Cloudflare check.

### 5. Remote boards we do not use add little

Measured today (target title, open to Lebanon/worldwide/EMEA, new to us after matching on
company and title): Jobicy ~0.4 a day, Jobspresso ~0.3, python.org ~0.1, EU Remote Jobs ~4
non-senior worldwide/EMEA a day before dedupe (12 of 53 in 6 days were ElevenLabs). Working
Nomads, Landing.jobs, 4dayweek, Arc, Wellfound: ~0. Remote Rocketship (location filter
Lebanon, `seniority=mid-level`, data in `__NEXT_DATA__`) showed 12 software, 3 backend, 1 full
stack, 3 AI in 7 days, ~2-3 a day before dedupe, several of them G2i reposts.

Remotive is broken: its API returns 10 jobs in total whatever the parameters (oldest
2026-09-21); 1 job in our DB in the last 14 days.

Himalayas jobs with an empty country list (Himalayas' "worldwide", ~7 a day) are already
handled: since Oct 14 they went to needs_review 21, agency 44, other stack 19, shortlisted 1.

## Options, by expected extra fitting jobs a day

1. **Wait for the network, retry failed requests once** (code, free): gets back the Gulf company
   boards and Lever/SmartRecruiters on most runs. Their jobs are not lost for good (a later
   run within 14 days picks them up), but they arrive late or not at all.
2. **LinkedIn's public guest search** (`/jobs-guest/jobs/api/seeMoreJobPostings/search`, then
   `/jobs-guest/jobs/api/jobPosting/<id>`): ~1-2 a day for the Gulf, plus UK/NL "visa
   sponsorship" jobs. Works without login, but about 1 request a second before 429, about
   1,000 results at most, and LinkedIn's terms forbid scraping. A compliant alternative is more
   Google Jobs (SerpApi) queries, which include LinkedIn postings, but the free plan is nearly
   used (7 credits a day, ~217 of 250 a month).
3. **Remote Rocketship** (~1-2 a day after dedupe, likely): check its terms first.
4. **Small adds**: Brain Co. (`ashby_boards`, `brainco`), EU Remote Jobs, Jobicy, Workable
   `workplace=remote&location=Lebanon`. Drop Remotive.

Not worth it: Bayt/GulfTalent/Naukrigulf (blocked, little new), Indeed (blocked), Welcome to
the Jungle (terms forbid scraping), Working Nomads, 4dayweek, Wellfound.
