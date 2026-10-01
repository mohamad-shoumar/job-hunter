<!-- A frozen copy of profile/master_profile.md (2026-09-30) for the tests, which cite its bullets by
     position. Edit the real profile freely; change this file only together with the tests. -->
# Master profile

> **This file is the only source of facts about me.** Every CV, cover letter and
> application answer is built from it.
>
> Tailoring MAY: reorder sections and bullets, emphasize what is relevant,
> rephrase bullets, and remove what is not relevant.
>
> Tailoring MUST NEVER add a skill, technology, employer, job title, date,
> responsibility, achievement, metric or certification that is not written here.
> If a job asks for something that is not in this file, the answer is a gap, not
> a new bullet.
>
> Anything marked `TODO` is unknown. Leave it out of generated material until it
> is filled in with real facts.
>
> Sources: `~/Documents/resume/output/Shoumar_Resume_General.pdf` (September
> 2026) and what I stated when setting up this project.

## Basics

- Name: Mohamad Shoumar
- Headline: Backend Engineer
- Email: me@example.com
- Phone: +1 555 010 7788
- LinkedIn: linkedin.com/in/mohamad-shoumar
- Location: Beirut, Lebanon
- Open to: remote work as an international contractor, through an employer of record (EOR), or as a direct international employee
- Open to relocation: TODO
- GitHub: github.com/mohamad-shoumar
- Portfolio: TODO
- Spoken languages and levels: TODO

## Summary of experience

- About 3.3 years of software engineering (June 2023 – present, as of September 2026), all at CoinQuant
- Backend-heavy, with full-stack and mobile work earlier on
- Currently Team Lead, leading a team of 5 engineers

## Target roles

Backend Engineer · Software Engineer · Python Engineer · AI Engineer ·
Applied AI Engineer · Forward Deployed Engineer · Solutions Engineer ·
AI Automation Engineer · Full Stack Engineer 

## Experience

Each bullet starts with its tags (see "Tailoring rules" below). `Printed title:`
lines are the titles a CV may print for that role; the `###` heading keeps the
real title.

### Team Lead - Algorithmic Trader — CoinQuant (Abu Dhabi)        Sept 2025 – Present

Printed title: Algorithmic Trader [default] · Team Lead [lead]

- [core] Architected a serverless, event-driven backtesting platform on AWS Lambda and SQS that runs 800+ concurrent Python jobs over historical market datasets with zero production failures. (Confirmed by me 2026-09-30: each backtest's data manifest goes through an SQS request queue with a dead-letter queue.)
- [core] Designed its failure handling so no job is silently lost: SQS dead-letter queue with redrive, idempotent PostgreSQL result writes with retry and backoff, and idempotent credit refunds for failed or timed-out jobs. (Confirmed by me 2026-09-30: I built the Lambda system and its SQS + DLQ; details from an internal repo.)
- [core] Built a comprehensive test suite covering the full testing pyramid, creating quality gates that let the team move toward agentic engineering loops while preserving code quality and maintainability. (Confirmed by me 2026-09-30.)
- [core] Designed and implemented a slippage model that improves backtest realism and trading cost accuracy.
- [core] Led development of a multi-position scaling feature, enabling advanced position sizing strategies.
- [lead] Lead a team of 5 engineers through sprint planning, code reviews, and a strict unit and integration testing culture.
- [fullstack, lead] Built the interactive backtest chart in Next.js and TypeScript on TradingView Lightweight Charts: trade entry/exit markers, indicator panes and win/loss filters, with candle and indicator data lazy-loaded as the user pans. (Confirmed by me 2026-09-30: my commits in an internal repo, Apr-Aug 2026. The divergence pivots and the "Why this trade?" panel are a teammate's work, never claim them.)
- [automation] Built and own an internal LLM automation flow that uses AI agents for extraction, classification, and triage, with validation gates that check every output before it ships - 115+ version-controlled workflows covering code review, release QA, and deploy gates.
- [automation] Own third-party API integrations end to end, including an event-driven Slack gateway that routes authenticated events, enforces scoped permissions, and reliably handles bot-to-bot messages in production. (Confirmed by me 2026-09-27; from the spare bullets in `~/Documents/resume/resume.md`.)
- TODO: did I do the switch from the SQS response queue (job status) to direct PostgreSQL writes? The current code calls the response queue legacy.

### Backend Developer — CoinQuant (Abu Dhabi)        Aug 2024 – Aug 2025

- [core] Led the microservices packaging migration from Bazel to Poetry, simplifying dependency management and reproducible builds across internal Python services.
- [core] Established a standardized local development workflow, reducing environment setup and iteration time for the backend team.

### Full Stack Developer — CoinQuant (Abu Dhabi)        Jun 2023 – Jul 2024

- [core] Designed and implemented RESTful APIs in Python for the backtesting platform, delivering market and simulation data to the product frontend.
- [core] Built the backtesting platform user interface from scratch, turning a backend-only tool into a product used across the team.
- [fullstack, mobile] Developed and deployed a cross-platform mobile application using React Native and Firebase.

All three CoinQuant roles: full time, working remotely from Beirut, Lebanon for
the Abu Dhabi company. (Confirmed by me 2026-09-27.)

## Skills (confirmed)

Only skills listed here may appear on a CV.

- Languages: Python, SQL, TypeScript, JavaScript
- Frameworks: Django, FastAPI, Node.js, React, Next.js, React Native
- Databases: PostgreSQL, MongoDB, Firebase
- Tools & Platforms: AWS (Lambda, SQS), TradingView Lightweight Charts, Docker, Git, Datadog, Grafana, AI coding agents (Claude Code)
- Concepts & Methodologies: API design, async programming, serverless architecture, event-driven architecture, message queues, data integration, microservices, LLM/AI automation, unit & integration testing, TDD, Agile/Scrum
- Also stated by me: distributed/backend systems
- Domain: algorithmic trading, backtesting (position sizing, slippage modelling), historical market data
- Leadership: team lead of 5 engineers; sprint planning, code reviews, testing culture

## Projects

TODO — name, one line on what it is, your part, technologies, link if public.

## Education

- Software Engineering Factory — Full Stack Software Engineering Bootcamp, Nov 2022 – May 2023. Completed the boot camp as a Star Developer with a Full stack web app.
- American University of Beirut — Psychology, Sep 2018 – Jun 2021. Degree type: TODO

## Certifications

Newest first. Always on the CV. (Confirmed by me 2026-09-30.)

- Software Engineering Factory — Applied AI Engineering Workshop, Sep 2026. Built a support agent with tool calling, RAG, structured outputs, evaluations, and human approval gates.
- Zapier Academy — AI Builder Path, Mar 2026. Built multi-step Zaps with AI steps, webhooks, scheduling, and Zapier Tables to move data between business tools.

## Tailoring rules

Which bullets and title a CV prints. Code (`cv.py`) and `build.py new` follow these.

- `[core]` bullets are always printed. A bullet with no tag counts as core.
- An optional bullet is printed only when the job matches one of its tags:
  - `lead`: the job asks for leading, managing or mentoring engineers (Team Lead, Tech Lead, Engineering Manager).
  - `fullstack`: a full-stack or frontend job, or one that asks for React / Next.js.
  - `automation`: the job is about automation, AI or LLMs, or lists AI agents, LLM workflows, Slack or third-party integration work as a requirement.
  - `mobile`: the job asks for mobile or React Native.
- Printed title: the `[default]` one, unless the job matches another one's tag (`Team Lead` for `lead` jobs).
- Certifications are always printed.

## Work authorization and logistics

- Lives in Beirut, Lebanon
- Needs: remote role open to Lebanon residents (contractor, EOR, or direct international employment)
- Time zone: Lebanon, UTC+2 (winter) / UTC+3 (summer)
- Notice period / availability: 2 weeks 
- Compensation expectations: 4200-6800 usd
