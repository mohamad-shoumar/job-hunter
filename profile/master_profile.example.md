<!-- An example for a made-up person. Copy it to profile/master_profile.md (not in git) and replace
     everything with your own facts. Your name, email, phone, LinkedIn, GitHub and location go in
     .env (MY_NAME, MY_EMAIL, ...), not here. -->
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

## Basics

Name, email, phone, LinkedIn, GitHub and location: MY_* in .env.

- Headline: Backend Engineer
- Open to: remote work as an international contractor, through an employer of record (EOR), or as a direct international employee
- Open to relocation: TODO
- Portfolio: TODO
- Spoken languages and levels: TODO

## Summary of experience

- About 4 years of software engineering (March 2022 – present, as of October 2026)
- Backend-heavy, with full-stack work earlier on
- Currently Tech Lead, leading a team of 3 engineers

## Target roles

Backend Engineer · Software Engineer · Python Engineer · Full Stack Engineer

## Experience

Each bullet starts with its tags (see "Tailoring rules" below). `Printed title:`
lines are the titles a CV may print for that role; the `###` heading keeps the
real title.

### Tech Lead - Backend Engineer — Example Logistics (Remote)        Jan 2025 – Present

Printed title: Backend Engineer [default] · Tech Lead [lead]

- [core] Built a Python and FastAPI order-tracking API on PostgreSQL that serves 2M+ requests a day.
- [core] Moved the nightly batch jobs to AWS Lambda and SQS, cutting the run from 3 hours to 20 minutes. (Confirmed by me 2026-10-01.)
- [lead] Lead a team of 3 engineers through sprint planning and code reviews.
- [fullstack] Built the shipment dashboard in React and TypeScript.
- [automation] Built an LLM triage step that sorts incoming support tickets into 12 queues.

### Software Engineer — Example Shop (Remote)        Mar 2022 – Dec 2024

- [core] Wrote the REST APIs in Django for the checkout and refunds flows.
- [core] Added unit and integration tests that brought coverage from 40% to 85%.
- [fullstack, mobile] Built a React Native app for store staff.

## Skills (confirmed)

Only skills listed here may appear on a CV.

- Languages: Python, SQL, TypeScript
- Frameworks: FastAPI, Django, React, React Native
- Databases: PostgreSQL
- Tools & Platforms: AWS (Lambda, SQS), Docker, Git
- Concepts & Methodologies: API design, event-driven architecture, unit & integration testing, LLM/AI automation

## Projects

TODO — name, one line on what it is, your part, technologies, link if public.

## Education

- Example University — BSc Computer Science, Sep 2018 – Jun 2021

## Certifications

Newest first. Always on the CV.

## Tailoring rules

Which bullets and title a CV prints. Code (`cv.py`) and `build.py new` follow these.

- `[core]` bullets are always printed. A bullet with no tag counts as core.
- An optional bullet is printed only when the job matches one of its tags:
  - `lead`: the job asks for leading, managing or mentoring engineers (Team Lead, Tech Lead, Engineering Manager).
  - `fullstack`: a full-stack or frontend job, or one that asks for React / Next.js.
  - `automation`: the job is about automation, AI or LLMs, or lists AI agents, LLM workflows, Slack or third-party integration work as a requirement.
  - `mobile`: the job asks for mobile or React Native.
- Printed title: the `[default]` one, unless the job matches another one's tag (`Tech Lead` for `lead` jobs).
- Certifications are always printed.

## Work authorization and logistics

- Lives in Beirut, Lebanon
- Needs: remote role open to Lebanon residents (contractor, EOR, or direct international employment)
- Time zone: Lebanon, UTC+2 (winter) / UTC+3 (summer)
- Notice period / availability: TODO
- Compensation expectations: TODO
