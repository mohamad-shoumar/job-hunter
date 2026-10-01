// MASTER RESUME (the base CV). Bullets and titles come from ../profile/master_profile.md: edit them there, then run `python3 build.py sync`. Tailored copies live in versions/.
# Mohamad Shoumar
title: Backend Engineer
email: me@example.com
phone: +1 555 010 7788
linkedin: https://www.linkedin.com/in/mohamad-shoumar/
github: https://github.com/mohamad-shoumar
location: Beirut, Lebanon

## Professional Experience

### CoinQuant, Abu Dhabi | Sept 2025 - Present
Algorithmic Trader
// titles: Algorithmic Trader [default] · Team Lead [lead]
- Architected a serverless, event-driven backtesting platform on AWS Lambda and SQS that runs 800+ concurrent Python jobs over historical market datasets with zero production failures.
- Designed its failure handling so no job is silently lost: SQS dead-letter queue with redrive, idempotent PostgreSQL result writes with retry and backoff, and idempotent credit refunds for failed or timed-out jobs.
- Built a comprehensive test suite covering the full testing pyramid, creating quality gates that let the team move toward agentic engineering loops while preserving code quality and maintainability.
- Designed and implemented a slippage model that improves backtest realism and trading cost accuracy.
- Led development of a multi-position scaling feature, enabling advanced position sizing strategies.
// [lead] - Lead a team of 5 engineers through sprint planning, code reviews, and a strict unit and integration testing culture.
// [fullstack, lead] - Built the interactive backtest chart in Next.js and TypeScript on TradingView Lightweight Charts: trade entry/exit markers, indicator panes and win/loss filters, with candle and indicator data lazy-loaded as the user pans.
// [automation] - Built and own an internal LLM automation flow that uses AI agents for extraction, classification, and triage, with validation gates that check every output before it ships - 115+ version-controlled workflows covering code review, release QA, and deploy gates.
// [automation] - Own third-party API integrations end to end, including an event-driven Slack gateway that routes authenticated events, enforces scoped permissions, and reliably handles bot-to-bot messages in production.

### CoinQuant, Abu Dhabi | Aug 2024 - Aug 2025
Backend Developer
- Led the microservices packaging migration from Bazel to Poetry, simplifying dependency management and reproducible builds across internal Python services.
- Established a standardized local development workflow, reducing environment setup and iteration time for the backend team.

### CoinQuant, Abu Dhabi | Jun 2023 - Jul 2024
Full Stack Developer
- Designed and implemented RESTful APIs in Python for the backtesting platform, delivering market and simulation data to the product frontend.
- Built the backtesting platform user interface from scratch, turning a backend-only tool into a product used across the team.
// [fullstack, mobile] - Developed and deployed a cross-platform mobile application using React Native and Firebase.

## Skills
Languages: Python, SQL, TypeScript, JavaScript
Frameworks: Django, FastAPI, Node.js, React, Next.js, React Native
Databases: PostgreSQL, MongoDB, Firebase
Tools & Platforms: AWS (Lambda, SQS), Docker, Git, Datadog, Grafana
Concepts & Methodologies: API design, async programming, serverless architecture, event-driven architecture, message queues, data integration, microservices, LLM/AI automation, unit & integration testing, TDD, Agile/Scrum

## Education

### Software Engineering Factory, Full Stack Software Engineering Bootcamp | Nov 2022 - May 2023
- Completed the boot camp as a Star Developer with a Full stack web app.

### American University of Beirut, Psychology | Sep 2018 - Jun 2021

## Certifications

### Software Engineering Factory, Applied AI Engineering Workshop | Sep 2026
- Built a support agent with tool calling, RAG, structured outputs, evaluations, and human approval gates.

### Zapier Academy, AI Builder Path | Mar 2026
- Built multi-step Zaps with AI steps, webhooks, scheduling, and Zapier Tables to move data between business tools.
