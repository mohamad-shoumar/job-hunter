# Job sources research (2026-10-10)

Why: most shortlisted jobs came from Himalayas, and many were agencies or talent
marketplaces (Jobs for Humanity, EWOR, Xperteez, G2i, micro1, Turing, Proxify,
Alignerr). Almost no GCC jobs came in, because every source is remote-only.
In the DB that day: 76 of 305 shortlisted/needs_review jobs had agency-style
names, and 30 more said "our client" / "talent network" / "vetted".

Endpoints marked "verified" were fetched live on 2026-10-10. Check the request
shape again when you build the source.

## Agency filter (works for every source)

Known agencies to block: Jobs for Humanity, EWOR, Xperteez, G2i, micro1, Turing,
Proxify, Alignerr, Toptal, Remote Quest Jobs, TechBiz Global, Talent Journey,
Arc.dev, Crossover, Andela, Mercor, Outlier, DataAnnotation, BairesDev, Lemon.io,
Gun.io, Braintrust, Revelo, Terminal.io, Hired, Jobgether, ZeinCrew, Vermillion
Analytics, SupportYourApp, Qureos (marketplace listed on the Hub71 board).

Rules that each give a reason you can quote (first match wins):
1. Known list (`blocked_companies`).
2. LinkedIn job detail says `Industries: Staffing and Recruiting` or
   `Human Resources Services`.
3. Company name, as whole words: talent, recruiting/recruitment, staffing,
   headhunt, workforce, outsourcing, placement; "jobs" only as the last word.
4. Description phrases, in the "about" part or 2+ hits: "our client",
   "on behalf of", "talent network", "talent pool", "join our network",
   "vetted developers/engineers", "pre-vetted", "get matched", "top N% of",
   "future opportunities", "train AI models", "paid per task".
5. needs_review only: one company with 8+ open jobs across 4+ unrelated job
   families, or an apply link on a marketplace domain (turing.com, micro1.ai,
   proxify.io, jobgether.com) under a different company name.

## Remote, direct employers

- Getro VC boards (verified). `POST https://api.getro.com/api/v2/collections/<id>/search/jobs`,
  header `Accept: application/json` (406 without it), body like
  `{"hitsPerPage":100,"page":0,"query":"python","filters":{"work_mode":["remote"]}}`.
  One agent used `hits_per_page`, the other `hitsPerPage`: check which works.
  `filters` must be an object. The id is in the board page's `__NEXT_DATA__` at
  `props.pageProps.network.id`. IDs: General Catalyst 222, Accel 8672,
  Point Nine 1680, Hub71 9266, MEVP 1034, BECO Capital 10883.
  Fields: work_mode, locations, seniority, organization.headCount.
- Consider VC boards (verified for Sequoia). GET `https://jobs.sequoiacap.com/jobs`
  (keep cookies, read `csrfToken`), then `POST /api-boards/search-jobs` with header
  `x-csrf-token`, body
  `{"meta":{"size":20},"board":{"id":"sequoia-capital","isParent":true},"query":{"remoteOnly":true},"grouped":false}`.
  Text search seemed ignored, so filter titles in code. a16z id unknown.
- Workable job search (verified).
  `GET https://jobs.workable.com/api/v1/jobs?query=backend%20engineer&workplace=remote&location=Europe`,
  paging via `nextPageToken`. 559 results in the test.
- Jobicy (verified). `https://jobicy.com/api/v2/remote-jobs?count=50&geo=emea&industry=engineering`.
  Asks for credit and a link to the original job.
- YC jobs (verified). `https://www.ycombinator.com/jobs/role/software-engineer/remote`,
  JSON in the `data-page` attribute (`props.jobPostings`). Many are "Remote (US)".
- Bulk ATS slugs (verified). `https://raw.githubusercontent.com/Feashliaa/job-board-aggregator/main/data/<ats>_companies.json`
  (MIT): about 8,300 Greenhouse, 4,400 Lever, 3,200 Ashby slugs. About 16k
  requests for a full pass, so spread it over days.
- Ashby trap: `isRemote` is true for hybrid jobs. Trust only
  `workplaceType == "Remote"` plus the location text.
- Blocked or no use: hiring.cafe (Cloudflare), Wellfound (Turnstile),
  workatastartup (406), 4dayweek (company name hidden), Working Nomads (full of agencies).
- FDE roles that were remote and open in EMEA: n8n "Forward Deployed Engineer - EMEA",
  ElevenLabs FDE UK. Most FDE roles are hybrid in SF/NYC/London; Cohere's
  Riyadh/Dubai ones are hybrid.

## LinkedIn guest API (works; against LinkedIn's terms)

- Search: `GET https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords=...&geoId=...&f_WT=2&f_E=3,4&f_TPR=r604800&start=0`
  (10 HTML cards a page). Detail: `/jobs-guest/jobs/api/jobPosting/<id>` (has Industries).
- geoIds: Lebanon 101834488, EMEA 91000007, Worldwide 92000000, UAE 104305776,
  Dubai 106204383, Saudi Arabia 100459316, Qatar 104170880, Kuwait 103239229,
  Bahrain 100425729, Oman 103619019.
- f_WT: 1 onsite, 2 remote, 3 hybrid. f_E: 2 entry, 3 associate, 4 mid-senior.
- "Remote" in a GCC country usually means remote for people living there.
- Risk: IP block (429/999). Keep it to a few dozen requests a day, no login.

## GCC and Lebanon

Most of it is onsite: of 255 GCC/Lebanon jobs on the Hub71/MEVP/BECO boards,
243 were onsite. Saudi/UAE titles often require nationals ("UAE National").
"Remote (UAE)" is not open to Lebanon unless the text says so.

SerpApi Google Jobs `location` values (from serpapi.com/locations.json):
`Dubai,Dubai,United Arab Emirates`, `Abu Dhabi,Abu Dhabi,United Arab Emirates`,
`Riyadh,Riyadh Province,Saudi Arabia`, `Jeddah,Makkah Province,Saudi Arabia`,
`Doha,Doha Municipality,Qatar`, `Beirut,Beirut Governorate,Lebanon`,
`Manama,Capital Governorate,Bahrain`, `Muscat,Muscat Governorate,Oman`, `Kuwait`.
One credit per page; `chips`/`ltype` are deprecated.

Company boards (verified, job count that day):
- Greenhouse `boards-api.greenhouse.io/v1/boards/<slug>/jobs`: careem 18,
  tamara 35, ai71jobs 11, brkz 23, bybit 160, okx 346.
- Ashby `api.ashbyhq.com/posting-api/job-board/<slug>`: ziina 13, qlub 17,
  LeanTech 3, thndr 10.
- Workable `apply.workable.com/api/v1/widget/accounts/<slug>` (wait 1s between
  calls): salla 41, foodics 27, lucidya 45, mozn-ai 17, syarah 7,
  moyasar-financial-company-1 14.
- Teamtailor RSS `<slug>.teamtailor.com/jobs.rss`: propertyfinder 32, dubizzle 6
  (Saudi), tappayments 20, mumzworld 12, spidersilk 14. Custom domains
  (`/jobs.rss`): careers.calo.app, careers.qashio.com, careers.cleargrid.co,
  careers.getstake.com, careers.sarwa.co, careers.pemo.io, careers.wego.com.
- BambooHR `toters.bamboohr.com/careers/list`: 61 (Lebanon, Iraq), includes
  Senior Backend Engineer and AI Platform Engineer.
- Pinpoint `tabby.pinpointhq.com/postings.json`: 43.
- Recruitee `<slug>.recruitee.com/api/offers/`: unifonic 35, siwaresystems 10.
- SmartRecruiters `api.smartrecruiters.com/v1/companies/<id>/postings`
  (case-sensitive): deliveryhero `?country=ae` 45 (talabat, InstaShop),
  Namshi 6, Seera 9, Almosafer 10, SellAnyCarcom 3, Kamkalima 1 (Beirut).
- Workday, Murex: `POST https://murex.wd3.myworkdayjobs.com/wday/cxs/murex/MurexCareerPage1/jobs`,
  body `{"limit":20,"offset":0,"searchText":"Beirut","appliedFacets":{}}`: 18 Beirut jobs.
- Oracle HCM, Presight:
  `https://iaambv.fa.ocs.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitions?onlyData=true&expand=requisitionList&finder=findReqs;siteNumber=presight-careers,limit=10`.
- Not found or empty: noon, G42, TII, Inception, Sary, Zid, Baraka, Alaan, Hala,
  Huspy, Kitopi, Rewaa, Anghami (Breezy, 0 jobs).
- Regional sites (Bayt, GulfTalent, Dubizzle, NaukriGulf, Daleel Madani, Jadarat):
  blocked or `Disallow: /`, and mostly recruiters. Skip them.

## UAE and Qatar: pay, hiring from abroad, interviews (2026-10-10)

The target: UAE or Qatar only, at least USD 5,000/month (AED ~18,400 / QAR ~18,200), remote interviews only.

- Pay (no income tax). Dubai/Abu Dhabi mid level: Levels.fyi median ~AED 26k/mo (P25 ~19k);
  recruiter guide (Talent Arabia 2026) median AED 18k (12k-28k). Senior AED 25k-38k.
  Doha mid QAR 15k-26k (Qatar Living 2026); Levels.fyi Doha median ~QAR 18.2k (10 entries).
- By employer: government-backed AI (G42 ~AED 30k/mo, TII higher) and top scaleups
  (Careem, talabat, Revolut) clear USD 5k. Banks are borderline to yes (Emirates NBD ~AED 25k).
  IT services/outsourcing do not. Tabby had one low data point (~AED 17.4k).
- Package: basic is often 50-60% of the total, and end-of-service gratuity is on basic only.
  Medical insurance is required by law in the UAE since 2025. Relocation is usually a one-way
  flight plus 2-4 weeks of hotel.
- Rent, 1-bedroom: Dubai JLT ~AED 5-7.7k/mo, Marina/Business Bay AED 7-11k;
  Doha West Bay/Lusail QAR 7-10k.
- Hiring from abroad: visas are sponsored, but 2026 hiring shrank (US-Iran war, Hormuz) and
  employers prefer people already in the country. Offer to start: UAE ~3-6 weeks
  (degree attestation is the usual delay), Qatar ~4-8 weeks.
- Lebanese passport: no official UAE work-visa ban found, but a history of suspensions
  (2020, 2023). Qatar suspended visa-on-arrival for Lebanese in Apr 2026; work visas go through
  the employer.
- Interviews: mostly video (Careem "virtual onsite", Emirates HireVue). No data on paid flights
  for onsite finals.
- Filter phrases. Positive: "visa sponsorship", "relocation package/support/assistance",
  "open to international candidates". Reject: "UAE National", "Emirati only", "Qatari national",
  "UAE residents only", "currently residing in the UAE", "transferable visa", "own visa",
  "no sponsorship", "NOC". Needs review: "immediate joiner", "local candidates preferred",
  "visit visa candidates welcome". "Dubai-based" alone is neutral.
