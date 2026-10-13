# EU/UK visa sponsorship sources (2026-10-13)

Why: you would relocate to the Netherlands, Germany, Finland, the UK, Ireland,
Spain or Italy, and want employers that clearly sponsor a work visa, kept in a
list apart from the remote jobs. Before this, the sources were remote-only: the
whole database held 19 relevant on-site jobs in those countries (17 from Hacker
News), all rejected as `not_remote`.

Everything marked "verified" was fetched live on 2026-10-13.

## Government lists of sponsors (built: `src/jobhunter/sponsors.py`)

| country | list | how to get the latest | format | rows | verified |
| --- | --- | --- | --- | --- | --- |
| UK | Home Office "Register of licensed sponsors: workers" | GOV.UK Content API `https://www.gov.uk/api/content/government/publications/register-of-licensed-sponsors-workers` → `details.attachments[]` with `content_type == "text/csv"` → `url` (asset id and date in the name change every update) | CSV: `Organisation Name, Town/City, County, Type & Rating, Route` | 143,218 (Skilled Worker 123,195; 122,617 after dropping repeats) | yes |
| NL | IND "Public register recognised sponsors: work" | `https://ind.nl/en/public-register-recognised-sponsors/public-register-work` (the old highly-skilled-migrant URL redirects here). No download: an HTML table, the name in `<th scope="row">` | `Organisation`, `KVK number` | 13,024 | yes |
| IE | DETE "Employment permits issued to companies" | `https://enterprise.gov.ie/en/publications/employment-permit-statistics-<year>.html` → the `.xlsx` link with "issued-to-companies" (the file name changed between 2025 and 2026, so it is found, not guessed) | xlsx: employer, a count per month, a total column. 2025 and 2026 are laid out differently | 2026 (Jan-Sep) 7,741; 2025 8,330 | yes |
| FI | Migri certified employers (`migri.fi/en/certified-employers`) | Cloudflare bot check (403 from scripts); 70 rows, mostly staffing firms (Supercell, Bolt, Yousician are on it) | HTML | 70 | browser only, not built |
| DE | none: a Blue Card needs no licensed employer (§18g, §81a AufenthG) | | | | yes |
| ES | the UGE-CE registers companies for 3 years (Ley 14/2013 art. 74); no public list found | | | | unverified (site unreachable) |
| IT | the art. 24-bis protocol is signed by employer associations, not companies | | | | yes |

Quirks the parser handles: UK names and towns with stray spaces, the same
company listed twice ("London" and "London "), `t/a` and `trading as`
("Roofoods Ltd t/a Deliveroo"), towns with commas; NL `""Aa-Dee""` quotes and
empty KvK cells; the two Irish layouts and their Total rows.

**Matching names.** `company_key` on both sides, plus the register name without
trailing words (UK, Europe, Holdings, Payments, Technologies, AI, ...) and with
the spaces removed ("Eleven Labs" = "ElevenLabs"). "B.V." is joined first, or
`company_key` keeps it as two letters (NL matches went from 4 to 23 in the DB).
Measured on the 1,111 company names in the DB: 54 exact UK matches, 12 of them
wrong ("Cursor" → "Cursor Ltd, Lincoln", "Ramp" → "The Ramp, Manchester"),
and every wrong one was a one-word name that is an ordinary word. So a one-word
name counts on the UK list only when the list's town is in the job's location.
A "first words match" rule was measured and is noise (`cloud` alone hits 41
organisations): not used.

**Register × bulk ATS slug lists** (Feashliaa job-board-aggregator: 8,333
Greenhouse, 4,368 Lever, 3,161 Ashby slugs, names not included): 1,996 slugs
match a UK or NL name, 1,243 "strong" ones. A spot check of 41 boards: 19 dead,
the 22 live ones had 170 jobs in the seven countries, only 15 with a target
title. Not built: too many dead boards for what it finds. The watched boards
(`boards.py`) now also follow companies with a job on the visa list instead.

## Job sources

| source | verdict | facts |
| --- | --- | --- |
| Arbeitnow API | **built** (`sources/arbeitnow.py`) | `GET <site>/api/job-board-api?page=N[&visa_sponsorship=true]`, no key, full HTML descriptions, `created_at`. Sites: arbeitnow.com (Germany, and mixes in 50 jobs each from .co.uk, .nl, .fr, .ch per 300), arbeitnow.co.uk, arbeitnow.nl (100 a page). No country field: the job URL's domain says it. UK/NL descriptions are sometimes HTML-escaped twice. The visa flag is per company: of 123 companies, 77 had every job flagged and 43 none; only 120 of 300 flagged jobs mention a visa at all, and some say "We do not provide visa sponsorship" (Terraquantum, Socure, Kraken, Docker). Terms: free, "please do not abuse", link back. 36 hours of NL+UK (flagged) and DE (all) = 11 requests, 281 jobs with a target word in the title |
| Hacker News (already a source) | **rule** | Posts put visa status in the header ("VISA", "NO VISA (EU work authorisation required)", "Visa sponsorship"). 14 posts in the DB mention it; 4 yes posts were in target countries (Attendi, Stream, Flow Traders, Planlab.ai) and were rejected as not remote |
| Relocate.me | not built | Every job lists its package ("Visa services"), robots allow it, but only 23 jobs, 3 with our titles; no API or RSS |
| visasponsor.jobs | not built | IT jobs: UK 207, DE 150, IE 22, NL 20, re-listed from LinkedIn/Careerjet; terms forbid "automated uses"; its visa labels look assigned by country |
| DevITjobs (.de/.uk/.nl) | not built | `/api/jobsLight` has `hasVisaSponsorship`, but "Yes" on 14 of 7,432 jobs and no Python job |
| Landing.jobs | not built | `relocation_paid` field, but 55 jobs, all false, mostly Portugal; robots disallow `/api/` |
| Welcome to the Jungle / Otta | not built | visa filter on the site only; terms forbid scraping |
| ukvisajobs.com | not built | paid members only |
| Duunitori (FI) | not built | open JSON API with full text, but no visa field; "visa sponsorship" finds 1 job |
| Berlin Startup Jobs, IamExpat, EnglishJobs.de, Työmarkkinatori, Work in Finland | not built | too small, robots block the pages, or (Työmarkkinatori) a Finnish business ID is required |

## What postings say (Arbeitnow, 2,511 jobs over 36 hours)

Offers, as written: "Visa sponsorship available (including transfer of Dutch
visa; no relocation support)", "We sponsor visas for the right candidate.",
"Visa and relocation support", "UK visa sponsorship is available.",
"Relocation – you're ready to work onsite in Munich (we support visa)",
"We offer UK work permits and help with relocation.", "Comprehensive
relocation support including flights, shipping and visas."

Refusals: "WE CANNOT PROVIDE VISA SPONSORSHIP", "Permanent right to work in the
UK is required; Socure does not provide visa sponsorship for this role.",
"Relocation and/or Visa are not supported for this role", "No visa sponsor
available", "...as we're unfortunately unable to provide sponsorship at this time."

Traps, so never matched alone: "sponsorship" is mostly events and executives
("executive sponsors", "conference sponsorships", "company-sponsored lunches");
"Visa" is a company ("ex-Netflix, Visa, Microsoft veterans", "Visa/Mastercard");
"immigration and visa restrictions ... the U.S." (IMC, about US training);
"We can't guarantee visa approvals" (not a refusal); "Kairos is happy to
sponsor visas to the US" (a remote job, not ours). One sentence can hold both:
"Visa sponsorship available (...; no relocation support)" is an offer, so each
clause is judged alone.

Languages: 31 of the 161 target-role jobs in the seven countries asked for German or Dutch
("Fluency in Dutch required", "Verhandlungssichere Deutsch- & Englischkenntnisse")
or were written in German or Dutch; "in Dutch or English" and "German is a
plus" are not requirements.

Result on that sample (161 target roles in the seven countries, before the
agency and age rules): 20 offer a visa, 16 offer relocation help only, 30 are on
a sponsor list, 62 say nothing, 2 refuse, 31 need a language; 64 jobs end on
the visa list. On the stored DB, the rules move 5
jobs to the visa list (Wintermute, TradingHub, Aurora Energy Research,
Planlab.ai, Ripple) and change no shortlisted or needs-review job.

## Network note

On this Mac the router's DNS (192.168.1.1) intermittently fails to resolve some
hosts (www.gov.uk, arbeitnow.com, relocate.me) that `dig` resolves. A failed
list keeps its old file and is retried on the next run; a failed source is an
error line in the report.
