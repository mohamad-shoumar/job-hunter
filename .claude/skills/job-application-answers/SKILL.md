---
name: job-application-answers
description: Write a short, specific, ready-to-paste answer to an open-ended job application question ("What motivated you to apply?", "Tell us about yourself", "Why do you want to join us?", "Why are you a good fit?", "Why are you looking?", "What are you looking for next?", AI/AGI or other opinion questions) that the profile, memory and apply-job's standard answers don't already answer. The answer is written by a Fable agent from the posting and the profile's facts; nothing is invented. apply-job uses it for every such question; also use it when the user pastes an application question and asks for an answer.
---

# Job Application Answers

## Why this skill changed (2026-11-11)

The user read a week of answers and called them "very bad". A Fable review of five of them found
they were not wrong, they were the same answer five times: restate the company's product, paste
the same two CV bullets ("AWS Lambda and SQS ... idempotent PostgreSQL writes", "LLM automation
... validation gates"), pad to 125 words, close with a wish he never stated ("is the step I'm
looking for"). The old rules caused it (100-130 words, "pick 1-2 CV achievements", a fixed
three-step order, "choose a credible reason"). The review is in
`reports/answers_review_2026-11-11.md`. These rules replace the old ones.

## When to use it

- An open-ended question on an application form that `~/job-hunter/profile/master_profile.md`,
  the memory files and the standard answers in apply-job (step 3) don't answer.
- A question the user pastes in chat.

## Who writes the answer

Not you. Spawn one agent per form with the Agent tool, `model: "fable"`, `subagent_type`
`general-purpose`, and paste the answers it returns. (Fable through the Agent tool is Claude
Code usage, not Anthropic API billing: the user's rule is no Anthropic API.)
The agent sees only its prompt, so the brief must carry everything:

1. Every open question on the form, exactly as worded, with its word or character limit. One
   agent for all of a form's questions, so the facts don't overlap.
2. The full posting: `cd ~/job-hunter && sqlite3 data/jobs.sqlite "select company, title, description from jobs where id=<id>;"`.
   For a job not in the database, the posting tab's text.
3. The facts: tell it to read `~/job-hunter/profile/master_profile.md` from `## Summary of
   experience` to just before `## Work authorization and logistics`, plus `## Motivations (my own
   words)` (it exists since 2026-11-11). Never lines before `## Summary of experience` (contact details)
   and never the logistics or self-identification sections.
4. The Vibe Taxi text from apply-job's standard answers, the only fact outside the profile.
5. The role level he is applying at (mid for "Mid & Senior"), and the visa or relocation situation
   for this job in one line (Beirut; relocating on a Skilled Worker visa; remote open to Lebanon).
6. The rules below, copied in, and the final test.
7. What it must return: each answer under its question with a word count; one line per answer
   naming the profile facts it rests on; a last line listing every claim it was tempted to make
   but could not ground. Pass that last line to the user in the report.

Read the answers before pasting. Any claim not in the facts: cut the sentence. Paste the full text
of every answer into the report under the job (not just "written by job-application-answers"), so
the user can read it without opening the form.

## Rules

1. **Length: 2-4 sentences, about 40-90 words.** The form's limit is a ceiling, not a target. Stop
   when the question is answered, even at 50 words. "Tell us about yourself" may run to 5.
2. **One CV fact per answer, as a sentence, never as the bullet.** The CV is attached; the box is
   for what the CV cannot say. Never two bullets back to back. Strip the bullet's metric unless it
   is the one number the answer uses.
3. **At most one number per answer, and no fact used twice on the same form.** Assign the facts to
   the questions before writing. "800+ concurrent jobs" was measured in a scripted stress test
   (confirmed 2026-11-11): in prose say "in a load test", never as production traffic; "~70%"
   and "~1-2%" stay estimates.
4. **What each question wants:**
   - *What motivated you to apply:* one concrete thing in the posting (a requirement, a team, a
     way of working) and the work of his it matches, stated as the match, not as a feeling: "The
     posting asks for a considered view on AI tools; that is what I built at CoinQuant." No
     "made me apply", "I want", "I'm looking for" unless `## Motivations` says so. Not a full
     fit pitch: one match, then stop.
   - *Tell us about yourself:* where he is, how he got here (psychology at AUB, bootcamp, founding
     engineer at CoinQuant), what he builds now, one thing outside work. Plain narrative, no selling.
   - *Why join us:* one thing about this company (a team, a product line, a way of working the
     posting states) and the honest link to his work. Say less when nothing specific is known;
     never invent an attachment to the company or its mission.
   - *Why a fit:* their requirement words mapped to his facts, in a list-like shape, plus the
     tools he would learn. The only question where a CV-style answer is right.
   - *Why are you looking / what next:* only from `## Motivations (my own words)` (written
     2026-11-11). Lines there marked "for me; never in an answer" are context for you, never
     text for a form: no pay, no stress, no private reasons. If the section is missing, say so
     to the user and write from the posting and his work only.
   - *AI or other opinion questions:* the one view he has stated (agents draft, code checks every
     output before it ships; AI to go faster without losing reliability), in his meaning, tied
     to the work it came from. No belief he hasn't stated.
5. **Vary the opening across answers and forms.** A line from the posting he is answering; a plain
   fact about himself; a team or product he would pick; a tool he would learn; a short
   observation. Never open by paraphrasing the company's product description or the role summary
   ("The role spans data ingestion, the ontology layer and...").
6. **Never close with a want he has not stated.** Banned closers: "is the step I'm looking for",
   "is what I want to go deeper on", "is the problem I would be excited to work on", "is a big
   part of what makes the role interesting", "Right now I'm obsessed with". End on a fact, a
   gap, or the visa line.
7. **The profile's motivations are the only motives.** `## Motivations (my own words)` holds the
   user's own lines (why looking now, what next, what he doesn't want, why the Netherlands, London
   or the Gulf, what he's proud of, what he believes about AI agents). Use their meaning, never
   embellish them, and never the lines marked "for me; never in an answer". A motive is used
   only where the question asks for one and the company matches it (a Dutch company may hear
   why the Netherlands; a trading firm never hears "a domain other than trading").
8. **Name gaps honestly**: a tool the posting wants that isn't in the profile's Skills is "new to
   me" in one clause ("What I have not used is Kafka or Scala"). Never explain a gap away.
9. **Concrete over abstract.** Not "technical direction", "failure-prone data flows", "the product
   stack", "friction": the chart, the queue, the test suite, the gate.
10. **The visa line once per form**, where natural: "I'm in Beirut and would relocate to London,
    so I would need Skilled Worker sponsorship."
11. **Banned words:** passionate, excited, exciting, dream, cutting-edge, perfect fit, aligns,
    resonates, leverage, obsessed, journey, thrilled. No em dashes, no emojis.
12. **Side projects count only when written down:** Job Hunter is in the profile; the Vibe Taxi
    bot is in apply-job's standard answers. Nothing else.
13. **Small drifts are drifts.** "AI agents handle code review" is not the profile's bullet (the
    agents do extraction, classification and triage, inside workflows that cover code review).
    Keep each fact's own words' meaning.

## Bad -> good, from real answers

- Closer. Bad: "Manufacturing would be a new domain for me, and working directly with founders
  and customers on it is the step I'm looking for." Good: "Manufacturing is new to me. Making a
  data flow survive failures is not."
- Opening. Bad: "TabPFN only matters to most people once there is a product around it, and the
  part I would want to own is exactly that: data upload, exploration, inference and results for
  data scientists who notice every bit of friction." Good: "This job is the interface between a
  model and the people using it. I have built that once: a backtesting UI that turned a
  backend-only tool into something people could actually use."
- Path. Bad: "I came into software through a bootcamp after a psychology degree at AUB, and I've
  been building ever since." Good: "I studied psychology at AUB, did a bootcamp, and joined
  CoinQuant as its founding engineer."
- Invented view. Bad: "Deciding when an agent may act, without adding friction for the people
  using it, is the part of AI engineering I most want to go deeper on." Good: "At work, agents
  draft and code checks every output before it ships. That is the view on AI tools I would
  bring."

## Final test

- Could another candidate paste this answer with only the company name changed? Rewrite.
- Does the first sentence contain something only he could write? If not, rewrite.
- Is every claim in the profile (or the Vibe Taxi text)? Cut what isn't.
- Does a "motivation" or "why join" answer actually give a reason, not a fit summary?
