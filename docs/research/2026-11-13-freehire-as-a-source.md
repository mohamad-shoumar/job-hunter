# ai-job-search-dev/ai-job-search, and freehire.me as a source (2026-11-13)

Asked: is that repo worth cloning to **discover more jobs**? (Ignoring its CV/STAR features.)

## Verdict

**Don't clone it.** Listing `.agents/skills/` gives the whole source list:
`jobindex-search`, `jobnet-search`, `jobbank-search`, `jobdanmark-search` (four
Danish portals), `linkedin-search` (LinkedIn's logged-out `jobs-guest` endpoints —
the same endpoints `sources/linkedin.py` reads), and `freehire-search`. The Danish
portals are useless for UAE/Qatar/Lebanon/remote/EU-visa, and the repo is Bun CLIs
plus Markdown skills with CSV/JSON state — it would not plug into this pipeline.

**The one thing worth taking is freehire.me**, as a new `sources/` module.

## What freehire.me is

An open-source aggregator (`strelov1/freehire`, Go + Postgres + Meilisearch,
self-hostable). ~4.89M open jobs from ~446 sources / ~179 ATS platforms, including
Bayt, Naukri, Adzuna, Workday, Oracle, SuccessFactors, iCIMS, Taleo, Personio,
Recruitee, JazzHR, Comeet, Breezy, Manatal, Zoho Recruit, Keka, Avature,
Cornerstone, Wellfound, Instahyre, Telegram — families we do **not** read today.

Public JSON API, **no key, no account**. `robots.txt` allows `/api/` for all but
Googlebot, and the project ships its own API skill, so this is sanctioned use.
It is a personal project on best-effort hosting, **no SLA**.

- `GET /api/v1/agent/jobs/search` — **full descriptions**. Use this one.
- `GET /api/v1/jobs/search` — same query, description cut to ~1000 chars: useless for our rules.
- `GET /api/v1/jobs/{slug}`, `GET /api/v1/jobs/facets`.

Params: `q` (supports `title:"..."` and uppercase `OR`, max 5 alternatives),
`countries`, `regions`, `cities`, `work_mode`, `posted_within_days`, `seniority`,
`category`, `skills`, `limit`/`offset` (`offset+limit <= 10000`). Each job carries
`url` (the real employer/ATS link), `company`, `location`, `countries`, `work_mode`,
`skills`, `posted_at`, **`created_at`**, `public_slug`, `enrichment`.

Facet notes: prefer `q` with `title:` over `category` — on UAE/7 days, `category` in
(backend, fullstack, ml_ai) returned 87 jobs where the title keyword search returned
143. `is_tech` is an output field, **not** a search facet (filtering on it returns 0).
The `visa_sponsorship` facet exists (16,275 jobs) but is sparse in our target
countries (GB 1,110; GB + tech category, 7 days: 10; NL: 2) — and `visa.py` reads the
posting text anyway, which is the rule.

## Problem 1: `posted_at` is re-dated; `created_at` is the usable date

freehire re-dates postings, like Himalayas (decision 2026-11-02) but with no
`expiryDate` to catch it. Measured over the **42 jobs matched to ours by `ats_key`**
(so the same posting for certain), against our own `posted_at`:

| freehire field | median difference | within 7 days of ours |
|---|---|---|
| `posted_at` | **+18 days** | 38% |
| `created_at` | **+0 days** | **76%** |

Concrete: a Binance "Full Stack Engineer (Web, Frontend)" we stored as posted
2026-10-19 came back with `posted_at` 2026-11-13 — but `created_at` 2026-10-23.

**So: ignore `posted_at`, use `min(created_at, posted_at)`** as the posting date and
let the usual age rule judge it.

Even then, **137 of 941 jobs (14%)** returned by a `posted_within_days=2` query had
a `created_at` older than 2 days — about one in seven is re-dated backlog.

## Measured yield

978 jobs pulled through the agent endpoint (Nov 11-13), then: drop anything whose
`created_at` is older than 2 days, dedupe against the live DB by `ats_key` /
`fingerprint` / application URL / loose company-prefix + title, dedupe within the
pull, run the **real** `classify.classify` + `config/filters.json`, then remove junk
a new source would have to filter (Problem 2).

```
fetched                            923
created_at older than 2 days       151   <- freehire re-dating
remaining                          772
not already in our DB              720   (dedup: fingerprint 31, cross-bucket 55, loose 11, ats 9, url 1)
rejected by the rules              672
junk needing new filters            19
"keepers"                           29
```

Hand-checking the 13 Gulf keepers against our stored rows for the same company
(Problem 3) found **~5 were duplicates our matching missed**. Correcting for that
across the pull:

> **roughly 10 genuinely new shortlist/visa-list jobs a day**, against a baseline of
> ~16 shortlisted + ~14 visa_list = **~30/day**. Call it **+1/3**.

Soft in both directions: it is **rules only** (10 of the 29 are `unclear` and would
still face the AI check and the date lookup, which reject some — the ~30/day baseline
is *after* those), while the remote, GB and NL/DE/IE pulls were **capped at 300** of
951/633/330 matches, so those buckets are undercounted.

**Where the gain is real.** Gulf jobs with nothing of that company in our DB for 60
days: Studdy Lab (x2), Showcify, TAYSIR BRIDGE, BroadNet (x2), Platinus (via naukri),
McKinsey QuantumBlack Doha. On remote and the visa list: Hydden, Storyteller, Mercor,
Outpatient, ERP Suites, Macquarie, Motorola Glasgow, a DWP role, Alen Space. The Gulf
is our thinnest coverage today (only SerpApi and LinkedIn scraping), so that half
matters most.

## Problem 2: junk that needs new filters

19 of the rules' survivors were things we would have to filter:

- **Russian / Spanish-language postings** from `hh`, `habr_career`, `getmatch`,
  `huntflow`, `getonbrd`, `whatjobs-es|co|mx` (Москва, "Весь мир", "Inglés
  Avanzado"). New failure mode: `language_required` fires on an explicit language
  *ask*, not on a posting *written* in another language. Needs a source block list
  or a script check.
- **Agencies `agency.py` misses**: IT People Gulf, JobLeader, Penta Consulting,
  AimGulf, Fis QA, Airswift, Brooksource, "Institutions Using VISIO".
- `MeVitae "Software Engineer Demo Job"` — a literal test posting.
- `eures` rows with an **empty company** field.

## Problem 3: dedup, and a filter bypass

The one that worries me most. 12 of the 29 keepers came via `whatjobs-*`, itself an
aggregator, and **whatjobs rewrites the company name and the title**. That defeats
`fingerprint` (company + title) and, worse, our content filters:

| freehire says | we already had | our verdict |
|---|---|---|
| `Edenred (United Arab Emirates)` / Backend Developer (L2) | `Edenred UAE` / Backend Developer (L2) | **rejected**, serpapi, 2026-10-20 |
| `Telemetry Today LLC` / SWE II - Python | `Telemetry Today LLC` / SDE II: Python Backend & Kubernetes | shortlisted, serpapi, 2026-11-12 |
| `Qrusible` / Finance Automation Full-Stack Engineer | `Qrusible Talent Network` / Application Engineer (Full-Stack) | **rejected as `agency`**, linkedin, 2026-11-03 |
| `Lean` / Senior Backend Engineer - FinTech Infra | `Lean Technologies` — our watched Ashby board | (not on the board; may be real) |

The Qrusible row is the dangerous one: whatjobs dropped the "Talent Network" suffix,
so `agency.py` had nothing to quote and the job came through as a shortlist. The
Edenred row would resurrect a posting we deliberately rejected. A freehire adapter
**must** normalise company names and re-dedupe, or it will quietly undo earlier
decisions.

Also: whatjobs `url`s return HTTP 200 but only ~5 KB — a whatjobs landing wall, not
the employer's form. `apply-job` would have to click through to find the real
application, which is friction the skill does not have today.

`ats_key_from_url` does work where freehire carries a real ATS link (9 matches here),
and a loose company-prefix match caught 11 more that `fingerprint` missed. An adapter
needs both, plus a whatjobs-specific company cleanup.

## If we build it

`sources/freehire.py` with `from_config()`, an entry in `BUILDERS`, and a test
against a trimmed real response, per the project's source convention.

- agent endpoint, `description_format=text`, `limit=50`, paged.
- searches by market, like `linkedin`/`serpapi`: `countries=ae|qa|lb`,
  `work_mode=remote`, and `countries=gb,nl,de,ie,es,it,fi` for the visa list.
- `q` from the existing target-role words with `title:` + `OR` (max 5 per request).
- **`posted_at = min(created_at, posted_at)`** (Problem 1), with a source note.
- `application_url` = freehire's `url`, so `ats_key_from_url` dedups properly.
- a source block list for the foreign-language boards, plus new agency names in
  `config/filters.json` (check each against the stored jobs first, per the agency rule).
- **company-name normalisation before dedup** (Problem 3). For a first version,
  consider dropping `whatjobs-*` entirely: it is 12 of the 29 keepers but carries all
  of the dedup and filter-bypass risk, and its links are landing walls. Without it the
  gain is smaller but clean.

Cost: free, no key, ~20-40 requests a run.

## Built and run (2026-11-13, same day)

`sources/freehire.py`, with `whatjobs-*` and the Russian/Spanish boards skipped, dated by
`created_at`, and the posting's own location only (freehire's country codes were wrong on
some jobs: "Toronto, Canada" and "Bucharest" tagged as the UK, so they are never used).
Two more gaps found on the way and fixed: freehire wrote EWOR as `eworgmbh`, which hid it
from `agency.py` (the adapter now puts the space back), and Emirates NBD's
"Software Engineer" said "(UAE National)" only in its text (added to `local_only`, checked
against the stored jobs: the bare words would have hit "UAE National Allowance" and
"Qatar National Bank").

One full run on a copy of the database, with the AI check and the fit grade, as the daily
run does it (2-day window, ~80 requests, ~3.5 minutes, $0.07 of AI check):

```
717 listings, 626 not already stored
593 rejected (rules, then 14 by the AI check)
 16 shortlisted   grades: one 4, the rest 1-2
 17 visa_list     grades: six 4, two 3, the rest 1-2
```

Against the last 14 days of the other sources (grade 3+ per day: ~6 shortlisted, ~6 visa
list):

- **Visa list: useful.** ~4 more grade-3+ jobs a day, from big employers whose own ATS we
  do not read: Google London, MongoDB Ireland, ServiceNow Dublin, Workday Dublin,
  Booking.com Amsterdam, Tradeweb London, Motorola Glasgow, Kneat Limerick, Machine
  Medicine London, apoha London.
- **Remote and Gulf: little.** One grade-4 shortlisted job (TECDATA) and one Dubai job
  (Cognita, grade 2). The Gulf gain measured earlier was almost all whatjobs, which is
  skipped for the reasons above.
- Known leftover: company names written differently still slip past dedup now and then
  ("Visa Europe Limited" vs a stored "Visa" job). Cost: an occasional repeat in the list.

Kept enabled as is: it is free and fast, and the visa-list gain alone is worth it.
