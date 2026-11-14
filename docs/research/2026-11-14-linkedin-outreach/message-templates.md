# Message templates (2026-11-14)

What to write at each step: the invite note, the message after someone accepts, the last
nudge, the ask after someone replies, and short answers to the usual replies. Each template
says which week-one problem or which piece of evidence it answers. When to send each one is in
[followup-plan.md](followup-plan.md); how to test them is in
[outreach-experiments.md](outreach-experiments.md).

Every example is filled in with a made-up name ("Sara") and the role "Senior Backend Engineer",
and every count was made with code, spaces and punctuation included.

## The short version

- **Keep the invite.** 25% of invites were accepted. In sales data from one platform
  (Belkins/Expandi, 11-13 million requests) that's normal: 25-28%. The problem was what came
  after: 8 of the 10 people who accepted in week one never heard from you again.
- **Try ending each note with one question someone can answer in five seconds.** The open ending
  ("I'd love to hear what your team is building next and how I could help") ended 36 of the notes
  written; roughly 7 in 10 notes were sent, and the data can't tell whether any note was answered
  directly. In email data, messages with a question get more replies than messages without one.
  That's a reason to test it (note B against today's note A), not proof.
- **Follow the 800+ wording from your profile:** "handling 800+ concurrent jobs in a load test".
  Your profile has said so since Nov 11, but the skill's table and every draft still leave it out.
- **Fix the follow-ups already on cards:** six of the eight waiting drafts use a fact outside your
  four ("Python"), make a second offer ("happy to send my CV"), give an unconfirmed date, or use
  "knowledge migrant" where the IND's own term is "highly skilled migrant".
- **New:** a German line, a note that asks German companies before you apply, a last nudge, an
  ask for after someone replies ("could you flag my application?", since a stranger usually can't
  refer you), a message to someone who knows you, and the reply after a German "yes". Several need
  your OK; each says so.

## Rules that stay (yours)

- The invite note is at most 300 characters. It opens "Hi [Name], I just applied for the
  [Role] role." and never names the company: the person works there.
- It has two of your four achievements, joined in one sentence, facts and numbers word for word.
- Facts about you come only from your profile. In notes and follow-ups that means the four
  achievements plus where you live and would move. When someone asks you a direct question (your
  notice period, video interviews, your working language), answer it from your profile.
- Nothing about the other person that isn't on their profile.
- One person per job, and you send everything yourself.
- The message after they accept: one closed question, no second pitch, the "will someone in
  Beirut really move?" worry answered, an easy way out, 2-3 sentences.

**One thing to check once:** LinkedIn's help page now says notes can be "up to 200 characters" and
doesn't give a Premium figure. Your own invite box allowed 300 on 2026-10-29, which is what counts.
If it ever shows 200, the shortest B notes (210-227 characters) still need trimming.

## The parts

**Your four achievements, as four ready pairs** (facts word for word, "in a load test" as your
profile says; only the joining words change):

| pair | text | best for |
|---|---|---|
| lead + AWS | I lead a backend team of 3 engineers and built an AWS event-driven system handling 800+ concurrent jobs in a load test. | backend and lead roles |
| AWS + AI | I built an AWS event-driven system handling 800+ concurrent jobs in a load test, and AI-native workflows to ship features and fixes daily. | backend at AI-first teams |
| scale + AI | I helped scale a platform to 15K users and built AI-native workflows to ship features and fixes daily. | startups and product roles |
| AWS + scale | I built an AWS event-driven system handling 800+ concurrent jobs in a load test, and helped scale a platform to 15K users. | engineers: the technical pair |

The skill's achievement table (apply-job step 4) still says "handling 800+ concurrent jobs" with
no "in a load test". Updating it is a wording fix to follow your own rule (listed in the README).

**The five-second question, by where the job is:**

| where | question |
|---|---|
| remote, open to Lebanon; or remote at a Kuwait or Bahrain company | Can you hire someone based in Lebanon for it? (never "relocate" for Kuwait or Bahrain: you wouldn't move there) |
| on-site or hybrid in the UAE or Qatar | Is it open to someone relocating from Beirut? |
| Germany | Is it open to someone relocating from Beirut? Germany needs no sponsor licence for it. |
| UK, Netherlands or Ireland, company on the government list | the list line below, then "Is it open to someone relocating from Beirut?" |
| Finland, Spain, Italy, or a company on no list | Does it come with visa sponsorship? |

**The list lines** (check `grep -i "<company>" ~/job-hunter/data/sponsors/{uk,nl,ie}.json`
first; in the invite say "you", in the follow-up name the company):

| country | invite | follow-up |
|---|---|---|
| Netherlands | I see you're an IND recognised sponsor. | I see [Company] is an IND recognised sponsor. Would this role be open to someone relocating from Beirut as a highly skilled migrant? |
| UK | I see you're a licensed Skilled Worker sponsor. | I see [Company] is on the UK register of licensed sponsors for Skilled Worker visas. Would this role be open to someone relocating from Beirut? |
| Ireland | I see you've hired on Irish employment permits before. | I see [Company] has hired on Irish employment permits before. Would this role be open to someone relocating from Beirut on a permit? |

- Netherlands: "highly skilled migrant" is the IND's own English name for the permit. "Knowledge
  migrant" is a word-for-word translation of "kennismigrant", so it's understood; the IND's term is
  just more exact. The skill's own example (apply-job step 4) still says "knowledge migrant", which
  is why the drafts keep using it.
- Ireland: the government list only shows companies that were given permits that year. It isn't a
  licence, so never write "licensed sponsor" for Ireland.

**The answer to "will he really move?", by where the job is** (a statement, used in follow-ups):

| where | line |
|---|---|
| UAE | I'm in Beirut and would relocate to the UAE for it. |
| Qatar | I'm in Beirut and would relocate to Doha for it. |
| Germany | I'm in Beirut and would relocate; Germany needs no sponsor licence for it, just a Federal Employment Agency form. |
| other visa-list countries | the list line or the visa question above |
| remote | the question "Can you hire someone based in Lebanon for it?", or, if already asked, "I'm based in Beirut." |

**Why the German lines talk about the employer, not the Blue Card:** whether your experience
counts for the IT Blue Card is the Employment Agency's call (see
[germany-strategy.md](germany-strategy.md)). If it doesn't, a second permit for experienced IT
workers takes over. What the employer has to do is the same on both: no sponsor licence, one
Federal Employment Agency form, a salary above a floor. So that's the claim; the Blue Card is only
your plan.

**A new line for remote jobs (needs your OK):** "I already work remotely from Beirut for a
company in Abu Dhabi." (63 characters). It's true (your profile confirms it), and it answers the
real worry behind a remote job: can this person work across borders? It isn't one of the four
achievements, so it needs your OK.

## 1. The invite note

Two versions per type of person: **A** is today's note. **B** changes the ending into one
five-second question, plus the list line or the German line where the question needs it. Which one
a job gets comes from its id (even → A, odd → B), so nobody picks. While the test runs, the German
and list lines go only in B notes, so A stays today's note; if you don't run the test, they can go
in every note (README, decision 9).

**When a longer name or role pushes a note over 300:** the examples below use "Sara" and a
23-character role, which leaves this much spare room: Ireland B 18, UK B 25, alum A 26, manager A
29, Germany B 32. Over 300, drop the list line or the German sentence first and keep the question;
never cut an achievement's facts or the role.

Hand edits: if you change the last sentence of a note before sending, add `#edited` to the card,
since that turns an A note into something else.

### In-house recruiter (4 of 12 accepted in week one: a tiny sample)

**A, today:** `Hi [Name], I just applied for the [Role] role. [lead + AWS] Would you be open to a quick
chat about it?`

Example (225 characters):
> Hi Sara, I just applied for the Senior Backend Engineer role. I lead a backend team of 3 engineers and built an AWS event-driven system handling 800+ concurrent jobs in a load test. Would you be open to a quick chat about it?

**B:** `Hi [Name], I just applied for the [Role] role. [lead + AWS] [the five-second question for
that place]`

- Why: a recruiter knows the location and visa rules, and a quick "no" saves both of you the
  follow-up. "A quick chat" is already a question, but it asks for a call.

Example, UAE or Qatar (227 characters):
> Hi Sara, I just applied for the Senior Backend Engineer role. I lead a backend team of 3 engineers and built an AWS event-driven system handling 800+ concurrent jobs in a load test. Is it open to someone relocating from Beirut?

Example, remote (227 characters):
> Hi Sara, I just applied for the Senior Backend Engineer role. I lead a backend team of 3 engineers and built an AWS event-driven system handling 800+ concurrent jobs in a load test. Can you hire someone based in Lebanon for it?

Example, Germany (268 characters):
> Hi Sara, I just applied for the Senior Backend Engineer role. I lead a backend team of 3 engineers and built an AWS event-driven system handling 800+ concurrent jobs in a load test. Is it open to someone relocating from Beirut? Germany needs no sponsor licence for it.

Example, UK, company on the register (275 characters):
> Hi Sara, I just applied for the Senior Backend Engineer role. I lead a backend team of 3 engineers and built an AWS event-driven system handling 800+ concurrent jobs in a load test. I see you're a licensed Skilled Worker sponsor. Is it open to someone relocating from Beirut?

Example, Ireland, company on the list (282 characters):
> Hi Sara, I just applied for the Senior Backend Engineer role. I lead a backend team of 3 engineers and built an AWS event-driven system handling 800+ concurrent jobs in a load test. I see you've hired on Irish employment permits before. Is it open to someone relocating from Beirut?

### Hiring manager (3 of 24 accepted)

**A, today:** `Hi [Name], I just applied for the [Role] role. [AWS + AI] I'd love to hear what your team
is building next and how I could help.`

Example (271 characters):
> Hi Sara, I just applied for the Senior Backend Engineer role. I built an AWS event-driven system handling 800+ concurrent jobs in a load test, and AI-native workflows to ship features and fixes daily. I'd love to hear what your team is building next and how I could help.

**B:** `Hi [Name], I just applied for the [Role] role. [AWS + AI] Is the role on your team?`

- Why: anyone can answer it in five seconds, and the answer tells you whether you reached the
  person who decides. The location question waits for the follow-up.

Example (226 characters):
> Hi Sara, I just applied for the Senior Backend Engineer role. I built an AWS event-driven system handling 800+ concurrent jobs in a load test, and AI-native workflows to ship features and fixes daily. Is the role on your team?

### Founder or CEO of a small company (2 of 12 accepted)

**A, today:** `Hi [Name], I just applied for the [Role] role. [scale + AI] I'd love to hear what your
team is building next and how I could help.`

Example (235 characters):
> Hi Sara, I just applied for the Senior Backend Engineer role. I helped scale a platform to 15K users and built AI-native workflows to ship features and fixes daily. I'd love to hear what your team is building next and how I could help.

**B:** `Hi [Name], I just applied for the [Role] role. [scale + AI] [the five-second question for
that place]`

- Why: at startups under 25 people a recruiter is involved in only 38% of jobs (Ashby, 1,200+
  startups, Feb 2026), so the founder often screens first. Ask the one thing that decides it.

Example, remote (210 characters):
> Hi Sara, I just applied for the Senior Backend Engineer role. I helped scale a platform to 15K users and built AI-native workflows to ship features and fixes daily. Can you hire someone based in Lebanon for it?

### Engineer (0 of 4 accepted)

**A, today:** `Hey [Name], I just applied for the [Role] role. [AWS + scale] I'd love to hear what it's
like on your team from someone on the inside.`

Example (258 characters):
> Hey Sara, I just applied for the Senior Backend Engineer role. I built an AWS event-driven system handling 800+ concurrent jobs in a load test, and helped scale a platform to 15K users. I'd love to hear what it's like on your team from someone on the inside.

**B:** `Hey [Name], I just applied for the [Role] role. [AWS + scale] Is the role on your team?`

- Why: an engineer usually can't refer a stranger (section 4), so "is it your team?" is the
  question they can actually answer.

Example (211 characters):
> Hey Sara, I just applied for the Senior Backend Engineer role. I built an AWS event-driven system handling 800+ concurrent jobs in a load test, and helped scale a platform to 15K users. Is the role on your team?

### Fellow AUB alum (1 of 8 accepted)

The alum gets the note for their own job (recruiter, manager, founder or engineer) with
"fellow AUB alum." added after the name. Examples for an alum who is an engineer:

**A, today** (274 characters):
> Hi Sara, fellow AUB alum. I just applied for the Senior Backend Engineer role. I built an AWS event-driven system handling 800+ concurrent jobs in a load test, and helped scale a platform to 15K users. I'd love to hear what it's like on your team from someone on the inside.

**B** (227 characters):
> Hi Sara, fellow AUB alum. I just applied for the Senior Backend Engineer role. I built an AWS event-driven system handling 800+ concurrent jobs in a load test, and helped scale a platform to 15K users. Is the role on your team?

### Agency recruiter (0 of 5 accepted)

Only for a job an agency posted (today's rule), with today's agency note. No B version: too few
to test.

### Germany: asking before you apply (needs your OK)

For German postings that say nothing about visas (see
[germany-strategy.md](germany-strategy.md)). It can't say "I just applied", so it's a different
note. It states what the employer would have to do, which is true whichever permit you end up on.
It uses one achievement instead of your usual two, on purpose: the visa line needs the room.

`Hi [Name], before I apply for the [Role] role: do you hire from outside the EU for it? I lead a
backend team of 3 engineers and would relocate from Beirut. Germany needs no sponsor licence for
this, just a Federal Employment Agency form from you.`

Example (261 characters):
> Hi Sara, before I apply for the Senior Backend Engineer role: do you hire from outside the EU for it? I lead a backend team of 3 engineers and would relocate from Beirut. Germany needs no sponsor licence for this, just a Federal Employment Agency form from you.

## 2. The message after they accept

Same rules as today. One change in what the question does: if the invite was a B note and
already asked the location or visa question, the follow-up asks whether the role is still open
and *states* the location line instead, so nothing is asked twice.

### Recruiter

`Hi [Name], thanks for connecting. Is the [Role] role still open, or has it moved to interviews?
[location line] If it's filled, no problem, I'll leave it there.`

Example, UAE (211 characters):
> Hi Sara, thanks for connecting. Is the Senior Backend Engineer role still open, or has it moved to interviews? I'm in Beirut and would relocate to the UAE for it. If it's filled, no problem, I'll leave it there.

Example, remote, when the invite didn't ask yet (165 characters):
> Hi Sara, thanks for connecting. Quick one on the Senior Backend Engineer role: can you hire someone based in Lebanon for it? If not, no problem, I'll leave it there.

Example, remote, after a B note that already asked (180 characters):
> Hi Sara, thanks for connecting. Is the Senior Backend Engineer role still open, or has it moved to interviews? I'm based in Beirut. If it's filled, no problem, I'll leave it there.

Example, Netherlands, company on the IND list (246 characters; "Example B.V." stands in for the
company):
> Hi Sara, thanks for connecting. One question on the Senior Backend Engineer role: I see Example B.V. is an IND recognised sponsor. Would this role be open to someone relocating from Beirut as a highly skilled migrant? If not, I'll leave it there.

Example, Ireland, company on the list (245 characters):
> Hi Sara, thanks for connecting. One question on the Senior Backend Engineer role: I see Example Ltd has hired on Irish employment permits before. Would this role be open to someone relocating from Beirut on a permit? If not, I'll leave it there.

Example, Germany (279 characters; a message, so no 300 limit):
> Hi Sara, thanks for connecting. One question on the Senior Backend Engineer role: would you hire someone relocating from Beirut? Germany needs no sponsor licence for it, just a Federal Employment Agency form and a salary above the IT Blue Card floor. If not, I'll leave it there.

- "The IT Blue Card floor", not "the Blue Card floor": an employer who looks up the second finds
  the higher standard floor and thinks you cost more than you do.

Example, Finland, Spain or Italy (181 characters):
> Hi Sara, thanks for connecting. One question on the Senior Backend Engineer role: does it come with visa sponsorship for someone relocating from Beirut? If not, I'll leave it there.

### Hiring manager

`Hi [Name], thanks for connecting. Is the [Role] role still open on your side, or has it moved to
interviews? [location line] If you're not the right person, no problem, I'll leave it there.`

- Why: managers accepted least. "If you're not the right person" turns silence into a cheap
  redirect.

Example, Qatar (237 characters):
> Hi Sara, thanks for connecting. Is the Senior Backend Engineer role still open on your side, or has it moved to interviews? I'm in Beirut and would relocate to Doha for it. If you're not the right person, no problem, I'll leave it there.

### Founder

`Hi [Name], thanks for connecting. Are you still hiring for the [Role] role? [location line] If
not, no problem, I'll leave it there.`

Example, UAE (183 characters):
> Hi Sara, thanks for connecting. Are you still hiring for the Senior Backend Engineer role? I'm in Beirut and would relocate to the UAE for it. If not, no problem, I'll leave it there.

Example, remote, when the invite didn't ask yet (142 characters):
> Hi Sara, thanks for connecting. Is the Senior Backend Engineer role open to someone based in Lebanon? If not, no problem, I'll leave it there.

### Engineer (and an alum who is an engineer)

After an A note, ask whose team it is:

`Hi [Name], thanks for connecting. Is the [Role] role on your team, or should I ask someone else
about it? [location line] No problem either way, I'll leave it there.`

Example, UAE (216 characters):
> Hi Sara, thanks for connecting. Is the Senior Backend Engineer role on your team, or should I ask someone else about it? I'm in Beirut and would relocate to the UAE for it. No problem either way, I'll leave it there.

After a B note (which already asked whose team it is), ask what they can know:

Example, UAE (195 characters):
> Hi Sara, thanks for connecting. Is the Senior Backend Engineer role still open, as far as you know? I'm in Beirut and would relocate to the UAE for it. No problem either way, I'll leave it there.

### Fixes to the follow-ups drafted on Nov 7

Six of the eight drafts waiting on cards have at least one of these. Check every follow-up on a
card before sending it:

| draft said | change to | why |
|---|---|---|
| "I lead a backend team of 3 in Python and AWS" | "I lead a backend team of 3 engineers" | "Python" isn't in your four achievements |
| "Happy to send my CV straight to you" / "happy to just be on your radar for the next one" | (drop it) | a second ask, and they already have your CV |
| "I applied last week" | "I applied for the [Role] role" | a date is a fact: only use one the app shows |
| "knowledge migrant permit" | "as a highly skilled migrant" | the IND's own term |

## 3. The last nudge (needs your OK: your rule says "once")

Send 5-7 working days after the follow-up, if there's no answer, then stop for good.

- Why: in a sales dataset of 2,966 campaigns, the second message had the best reply rate per
  send (8.8%), and three-message sequences beat longer ones (Expandi, 2026; sales, not job
  seekers).

`Hi [Name], one last note on the [Role] role: is it still open? If I don't hear back, I'll take it
as filled and leave it there.`

Example (142 characters):
> Hi Sara, one last note on the Senior Backend Engineer role: is it still open? If I don't hear back, I'll take it as filled and leave it there.

## 4. After someone replies: the "flag my application" ask (needs your OK)

Your rule today: never ask for a referral. The evidence says that rule is right for strangers, and
suggests a smaller ask instead.

- **A referral is worth a lot, partly because of who gets referred.** In Ashby's data (38M
  applications, 2021-2024), referred candidates reached interview 40% of the time against 3% for
  people who applied cold. Two published studies found referred people about 6-12 times as likely
  to be hired (Burks et al. 2015; Brown, Setren and Topa 2016). Employees refer people they already
  think will fit, so not all of that gap is the referral itself.
- **But a stranger usually can't refer you.** GitLab's public policy defines a referral as
  "someone you have worked with in the past, or have developed a close personal relationship
  with", tells staff to turn down people they don't know who ask on LinkedIn, and counts an
  applicant whose application "has been reviewed and progressed" as an "endorsement" (a note to the
  recruiter, no bonus). Its process expects endorsements after the candidate "applied directly",
  which is exactly your situation. Carnegie Mellon's system shows an error if you try to refer
  someone who already applied.
- **So the ask is the small one:** "could you flag my application?", made easy, with a way out.

Use it only after the person has written back and the role is still open. Never in the invite,
never with a bonus mentioned.

**To an engineer, alum or anyone who is neither the recruiter nor the hiring manager:**

`Thanks, [Name], that helps. Since I've already applied, would you be comfortable flagging my
application to the recruiter or hiring manager? Everything they'd need is below. If that's not
something you do, no problem at all.`

Example (222 characters):
> Thanks, Sara, that helps. Since I've already applied, would you be comfortable flagging my application to the recruiter or hiring manager? Everything they'd need is below. If that's not something you do, no problem at all.

**To the hiring manager** (asking them to flag it to themselves makes no sense):

Example (153 characters):
> Thanks, Sara, that helps. Since I've already applied, could you take a look at my application? Everything you'd need is below. If not, no problem at all.

Then, in the same message, a block they can paste, and the same CV PDF you applied with:

```
Name on the application: [full name]
Role: [Role], applied [date from the app]: [job link]
- I lead a backend team of 3 engineers.
- I built an AWS event-driven system handling 800+ concurrent jobs in a load test.
- I'm in Beirut and would relocate to the UAE for it.
CV attached: the version I applied with.
```

Pick the two achievements that fit the job, and the location line for that job.

## 5. Someone who knows you, before you apply (Step R; needs your OK)

Only for someone who actually knows you (a former colleague, a classmate you know, a connection
you've talked to) at a company with a grade 4-5 job. Why and when:
[contact-discovery.md](contact-discovery.md#referrers). It's a message, not an invite: you're
already connected.

`Hi [Name], hope you're well. Your team has a [Role] opening I'm about to apply for: [link]. Would
you be comfortable referring me, or would you rather I just apply directly? Either is completely
fine.`

Example (215 characters):
> Hi Sara, hope you're well. Your team has a Senior Backend Engineer opening I'm about to apply for: [link]. Would you be comfortable referring me, or would you rather I just apply directly? Either is completely fine.

Apply within 48 hours either way; through their referral link if they send one.

## 6. Short answers to the usual replies

| they say | you answer | count |
|---|---|---|
| "Send me your CV" | "Thanks, [Name]. Here it is, the same CV I applied with for the [Role] role." + the PDF the application used (add the location line if it hasn't been said) | 90 for the example |
| "We don't sponsor" / "local candidates only" | "Thanks for telling me straight, [Name]. I'll leave it there, and good luck with the hire." Then close the card with the quote. | 87 |
| "The role is filled" | "Thanks, [Name], good to know. I'll leave it there." | 48 |
| "Please apply on our site" | "Thanks, [Name]. I applied through the site on [date], so it should be in the system under my name." | 96 |
| A German "yes, we'd consider it" (after the before-you-apply note) | Apply, then: "Thanks, [Name], good to hear. I've just applied for the [Role] role." If they're not the recruiter and you've OK'd section 4, add the flag ask | 83 |

A clear no is a good outcome: it frees the slot, and it counts as a meaningful reply (the measure
in [outreach-experiments.md](outreach-experiments.md)).

## 7. What not to write

| don't | why |
|---|---|
| "I'd love to hear what your team is building next and how I could help." | not a question, and it asks for effort; it ended 36 notes written and no direct answer to it is on record |
| "I'd love to discuss how I could contribute", "I'm passionate about ..." | says nothing; your rule already bans stiff lines |
| any fact outside your profile, and in notes anything beyond the four achievements and your location ("Python", "5 years", a title) | your rule; and it can contradict the CV |
| "800+ concurrent jobs" without "in a load test" | your profile's own wording rule (Nov 11) |
| "at [Company]" in the invite | your rule: they work there |
| a link in the invite | a small sales-tool test (Waalaxy, 2,000 invites) saw 26% accepted with a link against 32% without |
| "I qualify for the Blue Card" | the Employment Agency decides; state what the employer must do instead |
| "licensed sponsor" for Ireland | Ireland has no licence: say "has hired on Irish employment permits before" |
| a referral bonus, or "refer me" to a stranger | policies forbid it; it burns the contact |
| a second offer in the same message ("happy to send my CV", "happy to jump on a call") | one message, one ask |

## The evidence behind these choices

| claim | number | who measured, on whom | grade |
|---|---|---|---|
| a note barely changes acceptance but raises replies | 25.3% accepted with a note vs 27.6% without; 8.2% vs 5.3% replied | Belkins, 11.5M connection requests sent in 2025 (sales) | B |
| a normal acceptance rate | 28.5% | Expandi, 13.2M requests, May 2025-Apr 2026 (sales; it shares data with Belkins, so not a second, independent source) | B |
| a question beats no question | 1-3 questions: 50% more replies than none | Boomerang, 40M+ emails, 2016 (mixed email) | B |
| shorter messages do better | InMails under 400 characters: 22% more replies than average | LinkedIn, tens of millions of recruiter InMails, 2021-22 (recruiters writing to candidates: the opposite direction) | A for that direction |
| accepts and replies come early | median accept 1 day; 60% of replies in the first week | Belkins, 152,636 contacts, Mar 2025-Feb 2026 (sales) | B |
| the 2nd message is the best one | 8.8% replies per send; 3 messages beat 5+ | Expandi, 2,966 campaigns, 2026 (sales) | B |
| referred candidates get interviews | 40% vs 3% | Ashby, 38M applications, 2021-2024 | A, with a selection effect |
| strangers can't be referred | policy text | GitLab handbook (Oct 2025); Carnegie Mellon HR | one employer each |
| your own week one | 25% of the 40 invites old enough to judge were accepted; 2 replies from 64 sent, both started by the other person | the Nov 7 review | your data, tiny |

None of these measured job seekers writing to companies. They are reasons to test, not
promises.

### Sources

- Belkins, LinkedIn outreach study (2025 data; updated 2026-06-29): https://belkins.io/blog/linkedin-outreach-study ;
  response times: https://belkins.io/blog/linkedin-response-time-study
- Expandi, benchmarks 2026: https://expandi.io/blog/linkedin-outreach-benchmarks-2026/ ; follow-ups:
  https://expandi.io/blog/linkedin-follow-up-message/
- Boomerang (2016): https://blog.boomerangapp.com/2016/02/7-tips-for-getting-more-responses-to-your-emails-with-data/
- LinkedIn Talent Blog, InMail data (2022): https://www.linkedin.com/business/talent/blog/talent-strategy/these-inmails-get-best-response-rates
- LinkedIn Help, personalized invitations: https://www.linkedin.com/help/linkedin/answer/a563153
- Waalaxy, connection requests: https://www.waalaxy.com/blog/linkedin-outreach/connection-request-on-linkedin
- Ashby Talent Trends, referrals (2025): https://www.ashbyhq.com/talent-trends-report/reports/referrals ;
  startup hiring (Feb 2026): https://www.ashbyhq.com/talent-trends-report/reports/startup-hiring
- Brown, Setren and Topa, Journal of Labor Economics 34(1), 2016: https://www.newyorkfed.org/medialibrary/media/research/staff_reports/sr568.html
- Burks, Cowgill, Hoffman and Housman, Quarterly Journal of Economics 130(2), 2015: https://repec.iza.org/dp7382.pdf
- GitLab referral process: https://handbook.gitlab.com/handbook/hiring/referral-process/
- Carnegie Mellon referral program: https://www.cmu.edu/hr/career/managers/recruiting-staffing/referral-program.html
- IND, highly skilled migrant: https://ind.nl/en/residence-permits/work/highly-skilled-migrant
