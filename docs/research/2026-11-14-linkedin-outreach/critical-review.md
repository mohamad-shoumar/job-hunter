# Critical review (2026-11-14)

An independent reviewer (a separate agent that hadn't written any of it) was asked to attack the
playbook: find unsupported conversion claims, generic or misreadable messages, broken rules,
inconsistencies and anything unsafe to publish. It read the six files, the raw research behind
them, the week-one review, the app's database (read-only) and the apply-job skill, re-checked the
German law at the source, and spot-checked 13 cited figures. It found 3 blocking problems,
14 important ones and 23 minor ones.

This page lists what was challenged and what changed. Evidence about specific people or about
your private profile stayed in the reviewer's private notes and isn't repeated here.

## The verdict

**What held up:**

- **German law, checked at the source:** the IT Blue Card's 3 years in 7 with Employment Agency
  approval always needed and no degree check; the 2026 floors (€50,700, €45,934.20 and €45,630);
  the fallback permit needing no qualification for IT jobs; the €411 fast-track fee; the 1-week,
  3-week and 3-week limits; the fast track covering the fallback. Every German message line is
  true on both permit routes, whether or not a first year counts.
- **Sources:** all 13 figures checked are real (Ashby, GitLab, Belkins, Expandi, LinkedIn's help
  page, Bitkom, YouGov, IND, gov.uk). Two were pinned to the wrong report or base; both are fixed.
- **Character counts:** every example matched a code count; no invite note is over 300.
- **Statistics:** the Fisher test (p = 0.19), the 95% ranges and the decision-rule error rates
  were right or close.

**What didn't hold up:** one privacy slip, one claim with no evidence behind it, a plan that could
have messaged people twice, several numbers from sales data read as if they were about job
seekers, two tests that were weaker than they looked, and some rule changes that weren't listed as
rule changes. All of it is fixed below, or listed as not changed with the reason.

**How the fixes were checked:** three files were rewritten after the reviewer finished. The
revisions were checked by script (every character count, every link and heading anchor, every
query re-run on the database, a scan for names and private details), not re-reviewed by the
reviewer. A final pass also found that T1 compares two sequences (each note version comes with
its own follow-up), and the doc now says so.

## Blocking (all fixed)

| problem | why it mattered | what changed |
|---|---|---|
| A public file described the two real conversations: each person's job title plus what they talked about. | The repo is public; a team with one "head of" role makes a person identifiable. | The funnel now says only "2 (both started by the other person)". The earlier draft was never pushed. |
| "The visa-question note got an answer" had nothing behind it. | It was the only piece of your own data offered for note B. | Removed. B now rests on outside data and is labelled a test, not a finding. |
| "Another 8 were waiting" were the same 8 people from week one, and the plan said to send their follow-ups before checking whether they went out on Nov 10-12. | It could have sent 7 people a second follow-up a week after the first, against your "once" rule. | Every file now says: open the thread first; if a follow-up is there, record it and stop. The Nov 10-12 count is 7, plus 1 planned for Nov 17. |

## Claims that were stronger than the evidence (fixed)

- **"The open ending went unanswered 36 times."** 36 is notes *written*; roughly 7 in 10 were
  sent, and the data can't tell a direct reply from a later conversation. Now worded that way,
  everywhere.
- **"A referral beats any message."** The 40% vs 3% interview gap in Ashby's data includes who gets
  referred. The caveat now sits next to the number, not only further down.
- **"25% is a normal rate."** Normal in *sales* data; and the two sales datasets (Belkins and
  Expandi) share data, so they aren't two independent sources. Both said now.
- **"42% of companies say candidates won't move. You will."** That's about candidates unwilling to
  move to the company's town; for a hire from outside the EU the bigger worry is the visa.
  Reframed, with the right base (319 companies with IT openings, report p. 10).
- **"Germany is the best legal fit of your visa-list countries."** Only four of the seven were
  compared. Now "of the four compared", with Finland, Spain and Italy listed as not checked.
- **Smaller ones:** a heading built on 12 people now says "a tiny sample"; a guess from surnames
  about older replies was dropped; Ashby's 18% now cites the report it comes from; a sales-tool
  test is labelled as one; "almost everyone accepts within 2 weeks" is labelled as sales data.

## Messages a stranger could misread (fixed)

| line | problem | now |
|---|---|---|
| "Is it on your team?" | right after a sentence about an AWS system, "it" can read as the system | "Is the role on your team?" |
| "I see you were issued Irish employment permits in [year]." | reads as if the person got a permit | "I see you've hired on Irish employment permits before." |
| the engineer follow-up after a B note | asked "is it your team?" a second time | a different question after a B note: "still open, as far as you know?" |
| "a salary above the Blue Card floor" | an employer who looks it up finds the higher, standard floor | "above the IT Blue Card floor" |
| "flagging my application to the recruiter or hiring manager", sent to a hiring manager | asks them to flag it to themselves | a separate "could you take a look at my application?" version |
| German answer lines with a notice period, "I work in English", "every round by video", "3+ years' experience" | facts outside your four achievements and location, and "3+ years" claims the one thing the Employment Agency decides | lines use only what the employer must do and where you'd move; direct questions get answered from your profile |
| "handling 800+ concurrent jobs" | your profile has said since Nov 11 to add "in a load test" | every template and the paste-ready block follow it; the skill's table is flagged for you to fix |

## Rule changes that weren't listed as rule changes (now listed)

- Adding a German line to every German invite changes the note's shape. It's now README decision
  9, and while test T1 runs it goes only in B notes, so A stays today's note.
- Dropping a note not sent within 7 days is a new rule. Now decision 12.
- A "Monday for Qatar" date sat inside a step called "no rule changes". Now conditional on decision
  2.

## Experiment design (changed)

- **T1 was too slow and measured the wrong thing.** At roughly 22-30 invites a week it takes about
  10-12 weeks, not 6-8. Its main measure was acceptance, which a note barely moves (2 points in the
  sales data). Now the main measure is a meaningful reply within 21 days of the invite, and the
  test compares the two sequences (note plus its follow-up); a simulation of the new rule gives
  about a 5% chance of a false switch and about 7 in 10 of catching a B sequence that adds 10
  points. It also needs skill edits before it can start; those are listed.
- **T2 couldn't lose, and the routine couldn't run it.** It counted per follow-up sent, which
  drops the keenest people from one version only, and next-morning follow-ups need a daily look at
  LinkedIn that the weekly routine didn't have. Now: counted per accept, presented as an optional
  and weak check (it would catch a much worse next-morning version only about half the time), and
  the daily look is in the plan.
- **The Germany funnel could change your visa rule on one or two replies**, its branches overlapped,
  and its fallback channel (contacts named in German posting texts) barely exists (0 of 15 tested
  postings). Now it decides on yes-counts per 30 invites, and the fallback is the Impressum's
  managing director or JOIN's contact field.
- **Germany "ask" cards would have leaked into the other tests and the follow-up list.** The
  queries now leave them out, and the doc says they also show in the app's waiting view.
- **Queries:** the "never sent" list now leaves out notes with an accept or reply recorded; the
  Germany list takes 25 candidates to read, filters clearance titles, and matches company names in
  full instead of on four letters. All queries were re-run on the database.
- **LinkedIn posts** were judged only by a measure they're unlikely to move, and the "time for 20-30
  more invites" didn't exist (invites follow applications). Now: low priority, and if tried, count
  the recruiter messages they bring, the same count as LinkedIn's "Open to work" setting.

## Privacy (fixed)

Several lines in the public files gave personal details that belong only in your git-ignored
profile. They were trimmed; the exact case now lives in the private note in `reports/`. The
reviewer's greps found no names, profile links, emails, phone numbers or salary figures.

## Gaps for acting on this tomorrow (closed)

- A check-then-send order for the 8 waiting people (README, "This week").
- What to do with the 26 notes with no "sent" tick.
- The reference letter for Germany: drafted now, requested only near an offer, since asking now
  tells your employer you're leaving (and the IT Blue Card needs it only "if needed").
- A message for someone who knows you, before applying (Step R).
- What to send after a German "yes".
- A hand-edit rule for the note test (`#edited`).
- The free "Open to work" setting, recruiters only.

## Not changed, and why

- **"Recruiters first" is not proposed as a rule.** 4 of 12 against 3 of 24 is a hint (p = 0.19).
  Record the type on every card first; T3 stays optional.
- **One person per job stays.** Nothing in the evidence was strong enough to double the work per
  job.
- **The 300-character limit stays.** LinkedIn's help page says 200 without a Premium figure, but
  your own invite box allowed 300.
- **No skill, filter or database change.** This was research. The skill wording fixes, the tool's
  German issues (an intermediary on the visa list, "relocation within the EU", a typo past the
  language check, jobs listed in the wrong place, no LinkedIn search for Germany) and the fixed
  follow-up texts are listed for you to approve.

## Still uncertain

- Every outside number about messages comes from sales outreach or recruiters writing to
  candidates. None measures a job seeker writing to a company.
- Week two's outcomes are unknown until someone looks at LinkedIn.
- In Germany: the total time from offer to start, waiting times in Beirut, the right portal
  category, whether an extra security check applies, and whether contractor experience counts.
- Finland, Spain and Italy weren't compared.
