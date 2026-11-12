---
name: job-application-answer-writer
description: Research, draft, critique, and refine concise, credible answers to software engineering job application questions, using the job description, company facts, and verified candidate evidence. Use for written application questions such as tell us about yourself, why this company, why are you a fit, and how do you use AI coding agents.
---

# Job application answer writer

## Objective
Create job-specific answers that make the candidate's fit easy to assess. Favor credible evidence and clear contribution over polished but generic language. Never invent facts.

## Inputs
- Job posting, role title, location, and application questions.
- Company website or reputable company research, when available.
- Candidate profile and evidence bank: `~/job-hunter/profile/master_profile.md`, from `## Summary of experience` to the end of `## Certifications` (never the Basics or logistics sections: contact details and pay). The Vibe Taxi and job-hunter repo texts in apply-job's standard answers are the only facts outside it.
- Word or character limits, if provided.
- User corrections, which override older candidate-profile information.

If information is missing, draft using verified facts; explicitly flag a truly essential missing fact rather than fabricating it. Do not ask unnecessary questions.

## Workflow
1. **Decode each question.** Identify what the employer is testing: competence, motivation, role fit, judgment, ownership, communication, or evidence of a repeatable process.
2. **Decode the job.** Identify 2-3 highest-priority requirements and the likely problems the new hire will solve. Distinguish mandatory requirements from nice-to-haves. Do not pretend the candidate meets an unmet requirement.
3. **Verify company facts.** If browsing is available, use official company/product/engineering pages and recent reliable sources. Choose 1 specific, relevant reason for interest; don't fabricate claims about the company. If company information is unavailable, state that personalization is limited.
4. **Choose evidence.** Pull 1-2 relevant, confirmed examples from the candidate profile. Distinguish personal work from team outcomes; preserve the original scope of metrics. Never invent tools, metrics, technical practices, or outcomes.
5. **Draft directly.** Answer the question in the first sentence or two. Prefer 60-120 words for unrestricted written questions, adjusting to complexity and explicit limits. Use 1-3 short paragraphs, direct verbs, and natural, confident language. Avoid buzzwords and flattery.
6. **Perform adversarial review.** As a skeptical hiring manager, ask: What specific claim is supported? Why this candidate for this role? Could the company name be swapped? Can the candidate defend each detail in an interview? Is there a generic sentence that adds no evidence? Would a hiring manager understand the contribution after a quick skim?
7. **Revise once.** Remove filler, fix unsupported claims, strengthen relevance and proof, and ensure it fits the character/word limit. Prefer believable language over maximal enthusiasm.

## Answer patterns

### Tell us about yourself
Current professional identity -> strongest relevant result -> distinguishing approach/strength -> optional next-step motivation. Do not recount the entire resume or personal history.

### How do you use AI coding agents, and how do you verify output?
Actual workflow -> candidate's role in scoping/constraints -> independent validation and review -> risk handling before shipping. Explicitly distinguish automated checks, agent QA, and human oversight; do not claim a check is universal if it varies by task. Mention evidence (tests, screenshots, API results, logs) only when true. Explain blast radius and domain-specific edge cases where relevant.

### Why do you want to join this company?
One verifiable company-specific product, technical, or customer problem -> sincere reason it interests the candidate -> relevant experience or desired contribution. Do not praise mission, culture, or scale without evidence. Avoid prestige as the only reason.

### Why are you a great fit?
Choose the top 2-3 job requirements -> support with relevant accomplishment and personal contribution -> connect those skills to the company's needs. Avoid unsupported self-labels such as 'perfect fit.'

### Other behavioral or technical questions
Use a compact context -> action -> outcome -> relevance structure. Be precise about what the candidate personally did, and state outcomes qualitatively if metrics are unavailable.

## Writing guardrails
- Strong, grounded, conversational; not robotic, ingratiating, or overdramatic.
- No em dashes, emojis, inflated superlatives, or generic motivational slogans.
- No vague statements like 'passionate about innovation' without concrete support.
- Avoid repeating the same achievement verbatim across every question in one application.
- Never invent familiarity with company culture, proprietary systems, or hiring managers.
- Never suggest hiding sponsorship/work authorization needs or misrepresenting seniority.
- If material inputs conflict, use the newest verified user-provided information and flag conflicts that affect factual accuracy.
- Obey exact character limits; count the final answer including spaces when a character limit is given.
- Treat examples as demonstrations of principles, not text to copy.

## Output
Return each question followed by its ready-to-paste answer. Unless requested, do not add explanatory essays or scores to the final output. Optionally add one short private-style quality note outside the pasteable answer when an important claim needs verification. If requested, provide alternative tones or a shorter character-limited version.

## Final checklist
- Direct answer to exact question
- Relevant to this role and company
- At least one defensible specific fact where applicable
- No fabricated claims or unverifiable company praise
- Natural, concise, non-repetitive wording
- Character and word limits respected
- A hiring manager can see why interviewing this candidate might be worthwhile
