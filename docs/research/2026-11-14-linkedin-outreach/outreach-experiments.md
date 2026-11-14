# Outreach experiments (2026-11-14)

What your LinkedIn outreach has produced so far, what the data can't see, and a small set of
tests that can tell acceptance, replies, conversations, referrals and interviews apart at the
volume you actually send.

Sources: the app's database (read-only), the tracker file used until Nov 5, the week-one review
of 2026-11-07 and the follow-ups drafted that day (both in the git-ignored `reports/` folder).
People are counted, never named or described. Nothing was sent or ticked.

## The short version

- **Known so far:** at least 65 invites sent, 12 accepted, 3 replied, 2 real conversations,
  0 referrals, and 0 interviews that can be tied to outreach. (The Nov 7 review counted 10 accepts
  and 2 replies; the app holds 2 accepts and 1 reply that the review's table missed.)
- **Week two is a blank.** 26 notes on jobs applied to since Nov 9 have no "sent" tick, and the
  app has no box for "follow-up sent", so it can't say whether the 8 people who accepted in week
  one have heard from you since. The first job is a look at LinkedIn (below).
- **Fix the leaks before testing anything.** An unsent note or follow-up has a 0% reply rate, so
  there's nothing to learn by testing it.
- **The volume decides what can be tested.** At roughly 22-30 invites a week, one comparison of
  two versions takes about 10-12 weeks and still only catches big differences. So: at most one
  real test (the note), referrals and interviews **counted, never compared**, and the rest decided
  by judgment, labelled as such.
- **LinkedIn posts: low priority.** If you try them, one a week for 4 weeks, and count the
  recruiter messages that come to you; none → stop.

## 1. What happened so far

### The funnel, counted from the people targeted

| step | count | can the data see it? |
|---|---|---|
| people picked | 188 (129 by Nov 7, 59 since) | yes |
| invite sent | at least 65 | only up to Nov 7; nothing ticked since |
| accepted | at least 12 | only up to Nov 7 |
| follow-up sent after accepting | unknown | no: there is no box for it |
| replied | at least 3 | only up to Nov 7 |
| real conversation | 2 (both started by the other person) | no field |
| referral | 0 (never asked: the skill forbids it) | no field |
| interview tied to outreach | 0 known | no field |

Per invite sent: 3 replies from at least 65, about **5%**. Per person picked by Nov 7: 3 from 129,
about **2%**.

### Week one by who was targeted

| who | sent | accepted | rate | likely range (95%) |
|---|---|---|---|---|
| hiring manager or engineering lead | 24 | 3 | 12% | 4%-31% |
| in-house recruiter or HR | 12 | 4 | 33% | 14%-61% |
| founder, CEO or CTO | 12 | 2 | 17% | 5%-45% |
| other | 7 | 1 | 14% | too few |
| agency recruiter | 5 | 0 | 0% | too few |
| engineer (peer) | 4 | 0 | 0% | too few |
| notes opening "fellow AUB alum" | 8 | 1 | 12% | too few |
| everything sent by Nov 1 (had time to land) | 40 | 10 | 25% | 14%-40% |

Recruiters at 4 of 12 against hiring managers at 3 of 24 **looks** like a big gap, but a gap
that size turns up about 1 time in 5 by pure luck (Fisher's test, p = 0.19). It's a hint worth
watching, not a finding. Anything under 10 people is an anecdote.

### What the data can't separate

- **The note and the person.** Each type of person gets its own template (recruiters get the
  "quick chat" ask, managers the "what your team is building" ask). So "recruiters accepted more"
  and "the quick-chat note did better" are the same 4 accepts. A note test has to change the note
  **for every type of person at once**.
- **Which notes were answered directly.** The open ending ("I'd love to hear what your team is
  building next...") ended 36 of the notes written, and roughly 7 in 10 regular notes were sent.
  The data can't tell a reply to the note from a conversation the other person started later, so
  nobody knows how that ending did.
- **The region.** The 12 accepts were 5 Gulf, 7 visa-list countries (5 UK, 2 Netherlands) and
  0 remote roles. Which week-one people were sent was never saved by region, so there is no rate
  per region. Remote-role contacts: no accept from at most about 11 sent. Something to watch, not
  a result.
- **Timing.** Sent dates were only filled in afterwards, often equal to the accept date, so "days
  from applying to inviting" can't be computed.

### The mix has changed since Nov 8

Of the 57 notes written since Nov 8, about 4 in 10 went to AUB alumni or engineers (the ladder's
steps A and B, added Nov 4), the two groups with the weakest week-one acceptance (1 of 8 and 0 of
4). Visa-list jobs are now most of the notes (32), then Gulf (16), then remote (9). It's the biggest
change in who gets contacted, and nothing records it.

### The "half never sent" leak, explained

- Week one: 129 picked, 64 sent, 64 never sent, 1 already a connection.
- 47 of the picked were the backlog of jobs applied Oct 24-29, whose notes were written "in case
  you want to send them later". Only 5 went out.
- Of the regular notes, about 59 of 82 went out: **about 72%**.
- Today: 30 jobs at Reached out have a note and no "sent" tick: 26 applied since Nov 9, 4 on
  Nov 5-6. Either they were sent and not ticked, or not sent.

### Interviews

No job is at Interviewing or Offer today, and the stage history isn't reliable for this (stages
were set by hand for other reasons before). 49 jobs were closed by rejection emails. Nothing links
an interview to outreach yet, which is why the definitions below record **how** an interview came
about.

### Closing the gap: a look at LinkedIn first

Done by you, or by Claude read-only with your OK, the way the Nov 7 review did it (about 20
minutes):

1. Messaging: for each of the 8 people who accepted in week one, did a follow-up go out? Your
   Nov 7 plan had 7 of them for Nov 10-12 and 1 for Nov 17. Did they answer?
2. My Network → Manage → **Sent**: who is still pending (match on the `/in/<name>` part of the
   profile link).
3. Connections, sorted by **Recently added**, back to Oct 24: who accepted.
4. Tick the boxes on the cards. Claude may fill in dates with `jobhunter linkedin <id> --sent-at
   ...` only with dates you confirm.

This gives the first real numbers for the follow-up step, the main change of Nov 7.

## 2. How much data a test needs

A test compares two versions ("arms"). The question is how many people each arm needs before a
difference is real and not luck. With the usual settings (a 5% chance of a false alarm, an 80%
chance of catching a real difference):

| question | from → to | people per arm |
|---|---|---|
| acceptance | 25% → 40% | 152 invites |
| reply after accepting | 20% → 50% | 38 accepts (about 152 invites) |
| meaningful reply per invite | 3% → 10% | 194 invites |
| meaningful reply per invite, doubled | 3% → 6% | 748 invites |

**The volume:** jobs moved to Reached out were 38 and 35 in the weeks of Nov 2 and Nov 9, with
notes on about 30 of them, and about 72% of regular notes went out in the past. That's roughly
**22-30 invites a week**. 200 invites (100 per version) take 7-9 weeks, plus 21 days of waiting:
**about 10-12 weeks for one answer.**

**A faster way to decide: write the rule now.** Instead of waiting for proof, decide in advance
what result makes you switch, and accept a known chance of being wrong. Simulated for the T1 rule
below (100 invites per version, a 5% base rate of meaningful replies):

| if note B really... | chance the rule switches to B |
|---|---|
| does no better | about 5% (a false switch) |
| adds 4 points (5% → 9%) | about 1 in 3 |
| adds 7 points (5% → 12%) | a bit over half |
| adds 10 points (5% → 15%) | about 7 in 10 |

So one note test is the most the volume supports, and it only catches a big improvement. Small
improvements will look like ties; at this volume they don't matter much anyway. **Referrals and
interviews can only be counted, never compared.**

## 3. Fix these first (they are not tests)

**F1. Send each note in the same sitting as the application, and tick "Invite sent" as you
press Connect.**
- The note says "I just applied", so it's only true for a few days.
- Proposed (needs your OK, it's a new rule): a note not sent within 7 days of applying is dropped,
  not sent late with a false opener.
- Measure: **send rate** = invites ticked / notes on applied jobs, each week. Target: 9 in 10.

**F2. Send every follow-up, and record it.**
- 8 people who accepted in week one show no follow-up on record (see section 1).
- Measure: **follow-up rate** = follow-ups sent / accepts older than the wait in
  [followup-plan.md](followup-plan.md). Target: all of them.
- There is no box for "follow-up sent", so record it as a tag (`#fu-sent 11-17`) until there is.

**F3. Record what happened after "Replied"**, as tags in the card's Tracking notes box (section
5): the app only has boxes for sent, accepted and replied.

**F4. Record who was targeted.** apply-job adds one line to the Tracking notes: `type:recruiter`
(or `manager`, `founder`, `engineer`, `aub`, `agency`). The review can then split by type without
guessing from the note.

## 4. The tests

### How a job gets its version: from its id, never by choice

From the job's id in the app, so nobody chooses and nothing extra needs recording:

- **Note version:** even id → `NOTE-A`, odd id → `NOTE-B` (SQL: `job_id % 2`).
- **Follow-up version** (only if T2 runs): `(job_id / 2) % 2` = 0 → `FU-A`, 1 → `FU-B`.
- **Who** (only if T3 runs): `(job_id / 4) % 2`.

Ids are handed out in the order jobs are found, so these digits have nothing to do with how good a
job is. If T1 and T2 both run, they form a 2×2: every combination gets about a quarter of the
jobs. After 3-4 weeks, check that the versions got similar mixes of contact types and regions
(query Q2b). If not, compare within each type.

### T1. The invite note: `NOTE-A` (today) vs `NOTE-B`

- **Question:** does the B sequence (a note ending with a five-second question, and the follow-up
  that goes with it) lead to more meaningful replies than today's?
- **Versions:** `NOTE-A` = today's note ("I just applied for the [Role] role." + two
  achievements + the ask for that type of person). `NOTE-B` changes the ending: one five-second
  question, plus the list line or the German line where the question needs it
  ([message-templates.md](message-templates.md), section 1). The location or visa question for
  recruiters and founders; "Is the role on your team?" for managers, engineers and alumni. Every
  type of person gets both versions. While T1 runs, list lines and the German line go only in B
  notes, so A stays today's note.
- **Read it two ways:** for recruiters and founders, B also raises Beirut or the visa in the first
  message, so a win there can't say whether the question or the topic did it. For you that's fine:
  raising it early is the point. Count the two groups apart as well as together.
- **Main measure:** a meaningful reply within 21 days of the invite, whatever started it (a direct
  answer to the note, or a reply to the follow-up). Each version comes with its own follow-up:
  after a B note, the follow-up states the location instead of asking it again, and the engineer
  one asks "still open, as far as you know?" ([message-templates.md](message-templates.md),
  section 2). So T1 compares two sequences, note plus follow-up, not the note alone.
- **Second measures:** accepted within 21 days, and a direct reply to the note itself
  (`#direct-reply MM-DD`: a reply that came before your follow-up). With next-morning follow-ups
  the window for a direct reply is short, so read it as extra information only.
- **Size:** 100 invites per version, then wait 21 days after the last one: **about 10-12 weeks**
  at today's volume.
- **Decision rule, written now:** switch to the B sequence (B note and its follow-up) if it gets at
  least 5 more meaningful replies per 100 invites and its acceptance is no more than 5 points
  lower. Otherwise keep today's.
- **Early stop:** after 50 per version, stop `NOTE-B` if its acceptance is 15 or more points
  lower.
- **Hand edits:** if you change the last sentence before sending, add `#edited`; those notes are
  left out of the count.
- **What it needs before it can start:** apply-job must write B notes for odd job ids and A notes
  for even ones, write the `type:` line, and use the corrected wording ("in a load test", "highly
  skilled migrant"). Until the skill says so, it keeps writing today's notes. Start date: the
  Monday after you OK it and the skill is updated.
- **Needs your OK:** yes. You kept the note's shape as it is on 2026-11-07.

### T2 (optional): a check that next-morning follow-ups don't do worse

[followup-plan.md](followup-plan.md#how-long-after-the-accept) recommends simply switching to the
next working morning (needs your OK). This is only a check that it doesn't do worse, and a weak
one.

- **Versions:** `FU-A` = today's rule: 4-6 working days after the accept, on their Tuesday to
  Thursday. `FU-B` = their next working morning after the accept, any working day except the first
  morning of their week. Q4 shows each job's version.
- **Main measure, per accept** (so neither version loses the people who write first): a
  meaningful reply within 15 working days of the accept, whatever started it. Every accept counts
  in its version.
- **Size:** 25 accepts per version, about 100 invites each.
- **Decision rule:** keep `FU-A` only if it does at least 15 points better; otherwise use `FU-B`.
- **How weak:** simulated, if `FU-B` were really 15 points worse (20% against 35%), this rule would
  catch it only about half the time. It is built to switch.
- **Needs your OK:** yes, it changes your timing rule for half the jobs. It also needs the daily
  2-minute look at LinkedIn in [followup-plan.md](followup-plan.md#the-weekly-rhythm).
- The wording isn't tested: the fixes in [message-templates.md](message-templates.md) apply to
  every follow-up.

### T3 (optional). In-house recruiter vs hiring manager

- **Question:** at companies over 50 people, does the recruiter or the hiring manager answer more?
  Week one hints at recruiters (4 of 12 vs 3 of 24), unproven.
- **Where it applies:** only when the ladder reaches step C at a company over 50 people. Steps A
  and B stay first (your call, Nov 4).
- **Versions:** `(job_id / 4) % 2` = 0 → recruiter, 1 → hiring manager. If that person can't be
  found within the search budget, take the other, write `who:fallback`, and count the job in its
  assigned version anyway.
- **Main measure:** accepted within 21 days. Meaningful replies counted alongside.
- **Size:** 60 per version. Only some jobs qualify (maybe 10-15 a week), so 8-12 weeks.
- **Decision rule:** if one side's acceptance is at least 10 points higher and it has at least as
  many meaningful replies, it goes first at companies over 50. Otherwise keep today's order.
- **Needs your OK:** yes, it changes the ladder's order for some jobs.
- **Cheaper alternative (recommended first):** don't run T3. Record `type:` on every card (F4) and
  look at the split after 6 weeks. The catch: the ladder picks the type, so types also differ in
  company size and region. A 2× gap with 30+ people per type would still be worth acting on.

### Counted, not compared: the "flag my application" ask after a meaningful reply

- **When:** someone has replied meaningfully and the role is still open. Not the recruiter (they
  already have your application); for a hiring manager, the "could you take a look" version.
- **What:** not "refer me" but the "flag my application" ask in
  [message-templates.md](message-templates.md) (section 4): a stranger usually can't refer
  someone who already applied, but can point the recruiter at the application.
- **Count:** asks made, yes, confirmed referrals or flags, interviews after one. The numbers will
  be single digits, so there's no comparison.
- **Needs your OK:** yes. The skill says "Never ask for a referral" today.

### A separate funnel: Germany, ask before applying

- **Why:** German postings that say nothing about visas are rejected as `no_visa_evidence`, but a
  German Blue Card needs no sponsor licence from the employer
  ([germany-strategy.md](germany-strategy.md)), so silence often just means nobody wrote it down.
  Last month there were 13-27 such postings a week with a target title.
- **Which jobs:** German location, rejected `no_visa_evidence`, relevance `match`, posted in the
  last 7 days, not a company that refused a visa on another posting, not asking for German (read
  the whole posting: a misspelled "required" slipped past the tool once) or a security clearance,
  not an intermediary posting for an unnamed client. Each Monday, take 10 from query Q6, one per
  company, newest first.
- **Who:** the CTO or a founder at small companies (the Impressum's managing directors, or JOIN's
  contact field), the recruiter at bigger ones.
- **What:** the "before I apply" note in [message-templates.md](message-templates.md). It must not
  say "I just applied".
- **Count it separately:** postings picked → person found → invite sent → accepted → answered the
  question → yes, no or unclear → applied → interview. And days to an answer.
- **Record:** `jobhunter linkedin <id> --url ... --note ...` works on a rejected job too (it creates
  the job's card); add `#de-ask` to its Tracking notes, and `#de-yes`, `#de-no` or `#de-unclear`
  when they answer. These cards also show in the "LinkedIn: accepted, waiting on you" view; the
  queries below leave them out of T1, T2 and the follow-up list.
- **Decision rule, counted per invite, after 30 invites (about 3 weeks):**
  - 3 or more yes: keep asking, and Claude brings you a proposal to change the German rule (an
    English-language target job with no visa words goes to the visa list marked "ask first").
    Changing the rule is your call.
  - 0 yes: stop; the rule stays.
  - 1 or 2 yes: 30 more invites, then decide the same way.
- **Needs your OK:** yes. It acts on rejected jobs and sends a note before applying, which no rule
  covers today.

### Optional: late invites on the 41 unsent backlog notes

41 jobs applied Oct 24-29 are still open and their contact never got an invite. Sending them now,
with an honest opener ("I applied for the [Role] role last month"), is the only way to learn
something about **timing**: are invites sent 3-4 weeks after applying still accepted? Not a clean
test (different jobs, different weeks), so read it as a rough check, and tag them `#late` so they
stay out of T1. **Needs your OK:** those notes were written as optional, and the opener must
change.

### LinkedIn posts: low priority

- **What they could do:** recruiters who look at your profile see recent activity, and posts can
  bring recruiters to you. The second is the real reason to post, and it can be counted: recruiter
  messages that come to you, per week.
- **What can't be measured here:** whether posts make invites more likely to be accepted. That
  would need about 330 invites per version for a 10-point lift, and comparing weeks with posts
  against weeks without mixes in everything else that changes.
- **If you try them:** one a week for 4 weeks, about real work (for example the AWS event-driven
  system), and count the recruiter messages that come to you. None after 4 weeks → stop. The same
  count works for LinkedIn's free "Open to work" setting (see
  [contact-discovery.md](contact-discovery.md#linkedin-limits-that-change-the-plan)).

## 5. What each measure means

Every rate is **per targeted contact** unless it says otherwise.

| measure | counts when | recorded today as |
|---|---|---|
| targeted contact | a person is on the card of a job you applied to | the LinkedIn box + the stage |
| invite sent | you pressed Connect | "Invite sent" box |
| accepted | they accepted **within 21 days** of the invite | "Accepted" box |
| follow-up sent | you sent the follow-up | tag `#fu-sent MM-DD` (no box yet) |
| direct reply | they replied to the note itself, before your follow-up | tag `#direct-reply MM-DD` |
| replied | any message from them (auto-replies don't count) | "Replied" box |
| meaningful reply | it answers the question (yes, no, still open, a visa answer), **or** says something new about the role (team, timeline, who decides), **or** offers a next step (send the CV, apply here, a call). Not meaningful: "thanks for connecting", an emoji, a like, "apply on our site" with nothing about you | tag `#meaningful MM-DD` |
| conversation | 2 or more messages from them in the thread | tag `#conversation` |
| referral | they (or the recruiter) say in writing that they referred you, or forwarded your CV to a named recruiter or the hiring manager. "I'll pass it on" alone doesn't count | tag `#referral MM-DD` |
| interview | a screen or interview with a date, for this job | tag `#interview MM-DD via-outreach` or `via-application` (via-outreach when the contact set it up or the company's first message mentions them) |
| Germany ask | as above, plus whether they answered the visa question, and how | tags `#de-ask`, then `#de-yes`, `#de-no` or `#de-unclear` |
| hand-edited note | you changed the note's last sentence before sending | tag `#edited` |

**The three weekly numbers** (the goal of this work), each with its denominator:

- meaningful replies per targeted contact;
- confirmed referrals per targeted contact;
- interviews per targeted contact (via outreach and via application, separately).

Write them as counts ("3 meaningful replies from 120 targeted contacts"), for the people invited
at least 21 days ago, so fresh invites don't drag the rate down.

## 6. The weekly review (15 minutes)

1. **You, 5 minutes, on LinkedIn:** Sent invitations and Connections (recently added) → tick
   "Accepted"; Messaging → tick "Replied" and add the tags. Or, with your OK, Claude does this
   read-only and lists the ticks for you to confirm.
2. **Claude, 2 minutes:** runs Q3 (notes with no sent tick) and Q4 (follow-ups due). That's the
   week's to-do list.
3. **Claude, 3 minutes:** runs Q1, Q2, Q5 and Q6, and writes 5 lines: the three numbers, the send
   and follow-up rates, and whether a test has reached its decision point.
4. **You, 5 minutes:** send the follow-ups that are due, at the times in
   [followup-plan.md](followup-plan.md), and tag them `#fu-sent`.

**What only you can do:** tick Invite sent when you press Connect; tick Accepted and Replied; add
the outcome tags. Claude writes the `type:` line. The version comes from the job id, so it's never
typed.

### The queries (read-only: `sqlite3 -readonly ~/job-hunter/data/jobs.sqlite`)

All were run on the real database on 2026-11-14.

```sql
-- Q1. Funnel by the week the invite was sent (Monday of that week); Germany asks and late invites left out
SELECT date(a.linkedin_sent_at, '-6 days', 'weekday 1') AS week_of,
  COUNT(*) AS sent,
  SUM(a.linkedin_accepted_at IS NOT NULL
      AND julianday(a.linkedin_accepted_at) - julianday(a.linkedin_sent_at) <= 21) AS accepted_21d,
  SUM(a.notes LIKE '%#fu-sent%') AS fu_sent,
  SUM(a.linkedin_replied_at IS NOT NULL) AS replied,
  SUM(a.notes LIKE '%#meaningful%') AS meaningful,
  SUM(a.notes LIKE '%#conversation%') AS conversation,
  SUM(a.notes LIKE '%#referral%') AS referral,
  SUM(a.notes LIKE '%#interview%') AS interview
FROM applications a
WHERE a.linkedin_sent_at IS NOT NULL
  AND a.notes NOT LIKE '%#de-ask%' AND a.notes NOT LIKE '%#late%'
GROUP BY week_of ORDER BY week_of;

-- Q2. The tests, by version: invites sent since the start date and at least 21 days ago
SELECT CASE a.job_id % 2 WHEN 0 THEN 'NOTE-A' ELSE 'NOTE-B' END AS note_arm,
       CASE (a.job_id / 2) % 2 WHEN 0 THEN 'FU-A' ELSE 'FU-B' END AS fu_arm,
  COUNT(*) AS sent,
  SUM(a.linkedin_accepted_at IS NOT NULL
      AND julianday(a.linkedin_accepted_at) - julianday(a.linkedin_sent_at) <= 21) AS accepted_21d,
  SUM(a.notes LIKE '%#direct-reply%') AS direct_reply,
  SUM(a.notes LIKE '%#fu-sent%') AS fu_sent,
  SUM(a.linkedin_replied_at IS NOT NULL) AS replied,
  SUM(a.notes LIKE '%#meaningful%') AS meaningful
FROM applications a
WHERE a.linkedin_sent_at >= :start                      -- e.g. '2026-11-23'
  AND julianday('now') - julianday(a.linkedin_sent_at) >= 21
  AND a.notes NOT LIKE '%#de-ask%' AND a.notes NOT LIKE '%#late%' AND a.notes NOT LIKE '%#edited%'
GROUP BY note_arm, fu_arm;

-- Q2b. Balance check: contact types per note version
SELECT CASE a.job_id % 2 WHEN 0 THEN 'NOTE-A' ELSE 'NOTE-B' END AS note_arm,
  SUM(a.notes LIKE '%type:recruiter%') AS recruiter, SUM(a.notes LIKE '%type:manager%') AS manager,
  SUM(a.notes LIKE '%type:founder%') AS founder, SUM(a.notes LIKE '%type:engineer%') AS engineer,
  SUM(a.notes LIKE '%type:aub%') AS aub, COUNT(*) AS sent
FROM applications a
WHERE a.linkedin_sent_at >= :start
  AND a.notes NOT LIKE '%#de-ask%' AND a.notes NOT LIKE '%#late%'
GROUP BY note_arm;

-- Q3. Notes with no "sent" tick (applied more than 2 days ago, and no accept or reply recorded)
SELECT a.job_id, j.company, j.title,
  date(COALESCE(a.applied_at, (SELECT MIN(at) FROM events e WHERE e.job_id = a.job_id
       AND e.kind = 'stage' AND e.detail LIKE '%→ Reached out%'))) AS applied
FROM applications a JOIN jobs j ON j.id = a.job_id
WHERE a.stage = 'reached_out'
  AND COALESCE(a.linkedin_note, '') <> '' AND a.linkedin_sent_at IS NULL
  AND a.linkedin_accepted_at IS NULL AND a.linkedin_replied_at IS NULL
  AND julianday('now') - julianday(COALESCE(a.applied_at, (SELECT MIN(at) FROM events e
       WHERE e.job_id = a.job_id AND e.kind = 'stage' AND e.detail LIKE '%→ Reached out%'))) > 2
ORDER BY applied DESC;

-- Q4. Follow-ups: accepted, no reply, no follow-up recorded. FU-B is due at once,
--     FU-A once 6 calendar days (about 4 working days) have passed. Without T2, everything is FU-A
--     under today's rule, or due at once if you OK next-morning follow-ups.
SELECT a.job_id, j.company, date(a.linkedin_accepted_at) AS accepted,
  CAST(julianday('now') - julianday(a.linkedin_accepted_at) AS INT) AS days_waiting,
  CASE (a.job_id / 2) % 2 WHEN 0 THEN 'FU-A' ELSE 'FU-B' END AS fu_arm,
  CASE WHEN (a.job_id / 2) % 2 = 1
         OR julianday('now') - julianday(a.linkedin_accepted_at) >= 6 THEN 'due' ELSE 'wait' END AS status
FROM applications a JOIN jobs j ON j.id = a.job_id
WHERE a.linkedin_accepted_at IS NOT NULL AND a.linkedin_replied_at IS NULL
  AND a.notes NOT LIKE '%#fu-sent%' AND a.notes NOT LIKE '%#de-ask%' AND a.stage <> 'closed'
  AND julianday('now') - julianday(a.linkedin_accepted_at) >= 1
ORDER BY status, a.linkedin_accepted_at;

-- Q5. The headline: per targeted contact (a person on the card of a job you applied to)
SELECT COUNT(*) AS targeted,
  SUM(a.linkedin_sent_at IS NOT NULL) AS sent,
  SUM(a.linkedin_accepted_at IS NOT NULL) AS accepted,
  SUM(a.linkedin_replied_at IS NOT NULL) AS replied,
  SUM(a.notes LIKE '%#meaningful%') AS meaningful,
  SUM(a.notes LIKE '%#referral%') AS referrals,
  SUM(a.notes LIKE '%#interview%') AS interviews,
  SUM(a.notes LIKE '%#interview%via-outreach%') AS interviews_via_outreach
FROM applications a
WHERE COALESCE(a.linkedin_url, '') <> ''
  AND (a.stage = 'reached_out' OR a.closed_reason = 'rejected' OR a.applied_at IS NOT NULL)
  AND a.notes NOT LIKE '%#de-ask%';

-- Q6. Germany: candidates for this week's asks (pick 10, one per company, after reading each),
--     and the asks so far
SELECT j.id, j.company, j.title, j.location_raw, date(j.posted_at) AS posted
FROM jobs j
WHERE j.reject_code = 'no_visa_evidence' AND j.relevance = 'match'
  AND (j.location_raw LIKE '%Germany%' OR j.location_raw LIKE '%Berlin%' OR j.location_raw LIKE '%Munich%'
       OR j.location_raw LIKE '%München%' OR j.location_raw LIKE '%Hamburg%' OR j.location_raw LIKE '%Frankfurt%'
       OR j.location_raw LIKE '%Cologne%' OR j.location_raw LIKE '%Köln%' OR j.location_raw LIKE '%Stuttgart%'
       OR j.location_raw LIKE '%Düsseldorf%' OR j.location_raw LIKE '%Leipzig%' OR j.location_raw LIKE '%Karlsruhe%')
  AND julianday('now') - julianday(j.posted_at) <= 7
  AND j.title NOT LIKE '%TS/SCI%' AND j.title NOT LIKE '%clearance%'
  -- skip companies that refused a visa on another posting, or that you skipped for "no visa"
  AND NOT EXISTS (SELECT 1 FROM jobs k
                  WHERE lower(trim(replace(k.company, ' - English', ''))) = lower(trim(replace(j.company, ' - English', '')))
                  AND k.reject_code = 'no_sponsor')
  AND NOT EXISTS (SELECT 1 FROM events e JOIN jobs k ON k.id = e.job_id
                  WHERE lower(trim(replace(k.company, ' - English', ''))) = lower(trim(replace(j.company, ' - English', '')))
                  AND e.kind = 'stage' AND e.detail LIKE '%Closed (skipped)%' AND e.detail LIKE '%visa%')
ORDER BY j.posted_at DESC LIMIT 25;

SELECT COUNT(*) AS asked,
  SUM(a.linkedin_sent_at IS NOT NULL) AS sent, SUM(a.linkedin_accepted_at IS NOT NULL) AS accepted,
  SUM(a.notes LIKE '%#de-yes%' OR a.notes LIKE '%#de-no%' OR a.notes LIKE '%#de-unclear%') AS answered,
  SUM(a.notes LIKE '%#de-yes%') AS yes, SUM(a.notes LIKE '%#de-no%') AS no
FROM applications a WHERE a.notes LIKE '%#de-ask%';
```

Results on 2026-11-14: Q1 shows 25 ticked invites (3 in the week of Oct 26, 22 in the week of
Nov 2, none since); Q3 lists 23 notes with no sent tick (it skips the last 2 days and anything with
an accept or reply recorded); Q4 lists the 8 people who accepted in week one; Q5 shows 61 targeted
contacts in the app (the Oct 24 - Nov 5 people live only in the old tracker file); Q6 lists 25
candidates to read and pick 10 from (the first is a venture fund's board posting for an unnamed
company: an intermediary, so skip it).

## 7. The smallest code change that would help (needs your OK; not built)

Tags work today, but they're slow to type and easy to misspell. The smallest change that makes
the review one command:

- one migration (5) adding to `applications`: `linkedin_type` (recruiter, manager, founder,
  engineer, aub, agency) and four dates: `linkedin_followup_sent_at`, `linkedin_meaningful_at`,
  `linkedin_referral_at`, `linkedin_interview_at`;
- the four dates added to `LINKEDIN_STEPS`, so the card gets four more tick boxes next to Invite
  sent, Accepted and Replied, each writing an `events` row like the others; `jobhunter linkedin`
  gets `--type` and the matching `--...-at` options for filling in past dates;
- a `jobhunter linkedin-review` command that prints Q1, Q2, Q4 and Q5.

Why: a tick is one click where a tag is typing, a column can't be misspelled, and "follow-up sent"
gets a real date. Suggestion: wait 2 weeks; if the tags are being added reliably, the change can
wait longer.

## 8. What needs your OK

| proposal | the rule it touches |
|---|---|
| T1: `NOTE-B` for half the jobs, and the skill edits it needs | the note's shape, kept as it is on 2026-11-07 |
| the follow-up the next working morning after the accept (for everyone, or half in T2) | your timing rule (4-6 working days) |
| T3: recruiter vs hiring manager, by job id | the ladder's order (step C: hiring manager before HR) |
| the "flag my application" ask after a meaningful reply | "Never ask for a referral" (apply-job step 4, `pitch.py`) |
| Germany: ask before applying | notes always follow an application today; this acts on rejected jobs |
| F1: drop a note not sent within 7 days of applying | a new rule |
| late invites on the 41 backlog notes | those notes were optional; the opener must change |
| apply-job writes `type:` and picks the versions by job id | an apply-job skill change |
| migration 5 and `linkedin-review` | a code change |

F2-F4 and the weekly review need no rule change. Nothing here sends anything: every message is
still sent by hand, by you.
