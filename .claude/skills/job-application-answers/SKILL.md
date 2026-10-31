---
name: job-application-answers
description: Write a natural, confident, ready-to-paste answer to an open-ended job application question ("Why this company?", "Why this role?", "Why are you looking for a new role?", "What are you looking for next?", "Why are you a fit?", AI/AGI or other opinion questions) that the profile, memory and apply-job's standard answers don't already answer. apply-job uses it for every such question; also use it when the user pastes an application question and asks for an answer.
---

# Job Application Answers

## Goal

Write natural, confident, ready-to-paste answers that connect the candidate's real experience to
the opportunity. The candidate applies broadly; show a convincing fit without inventing passion or
personal motivations.

## When to use it

- An open-ended question on an application form that `~/job-hunter/profile/master_profile.md`,
  the memory files and the standard answers in apply-job (step 3) don't answer. If one of those
  answers it, use that instead.
- When apply-job hands a question here, this skill's length rule (100-130 words, or the form's
  limit) wins over apply-job's 2-4 sentences.

## Inputs

- Exact question and word/character limit.
- Candidate CV and any stated career goals or preferences: `~/job-hunter/profile/master_profile.md`
  (the only source of facts) and the job's tailored CV (`~/job-hunter/resume/versions/`).
- Job description and company name/site (the job's card in the app, or the posting tab).

Treat the CV and the candidate's latest statements as the source of truth. Research the official
company site when relevant and available.

## Workflow

1. **Identify what is being asked.** Don't reuse one answer for different questions.
2. **Find evidence.** Pick 1-2 relevant CV achievements or responsibilities. Never invent
   achievements, metrics, motivations, or personal opinions.
3. **Find a specific connection.** For company/role questions, identify a real product detail,
   technical challenge, or responsibility that matches the candidate's background.
4. **Choose a credible reason.** Prefer skill match, technical challenge, ownership, new domain, or
   career growth. Never claim the candidate loves the company or its mission without evidence.
5. **Write and check.** Answer directly, keep it human, verify every claim, and respect the length
   limit.

## Answer by question type

- **Why this company?** Specific company detail -> relevant experience -> how the candidate could
  contribute.
- **Why this role / what motivated you to apply?** Specific job responsibility -> matching
  experience -> why the work is a sensible next step.
- **Why are you looking for a new role?** What changed or why now. Use genuine career progression
  and readiness for a new environment if supported; don't replace the explanation with a list of
  future ambitions.
- **What are you looking for next?** Desired work, ownership, impact, and professional growth.
  Focus on the future, not reasons for leaving.
- **Why are you a fit?** Job requirement -> concrete evidence -> potential contribution.
- **AI/AGI or other opinion questions?** Give a grounded personal perspective connected to real
  experience. Acknowledge uncertainty; don't invent strongly held beliefs.

## Candidate positioning

Hands-on backend engineer and team lead with experience building production systems, owning
technical decisions, and connecting engineering to business outcomes. Use the supplied CV for
precise facts. Do not use the '800+ concurrent jobs' metric as verified unless its measurement is
confirmed.

## Style and constraints

- First person. Confident, conversational, direct. No corporate flattery or generic hype.
- Avoid phrases like "dream company," "always been passionate," "cutting-edge," and "perfect fit."
- No invented dissatisfaction, layoffs, incidents, or reasons for leaving.
- Default to 100-130 words unless the question specifies otherwise. Never exceed a hard limit.
- Avoid em dashes, emojis, repetitive openings, and unnecessary buzzwords.
- Distinct answers for multiple questions, with minimal repetition.
- Output only the final answer, ready to paste. Label answers only if there are multiple questions.

## Final test

Does it answer the exact question, say something specific, and contain only claims the candidate
could defend in an interview? If not, revise.
