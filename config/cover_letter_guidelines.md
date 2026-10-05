# Cover letter guidelines

How the letters should read: length, shape, voice, and the words that make a
letter sound machine-written. Built from research in October 2026 (sources at
the end).

How this file is used:

- The part between `writer:start` and `writer:end` is written to the model
  that drafts the letter. `cover.py` loads it as the writer's instructions
  (`cover_guidelines` in config/outreach.json), so you can change how letters
  read by editing this file, not the code.
- The facts rules do not live here. They stay in code (`check_sentence`,
  `valid_gap`) and in CLAUDE.md: a letter may only say what
  `profile/master_profile.md` says. This file only decides how those facts are
  told.
- The lists in section 10 are one item per line so code can read them and
  check every letter, the same way it checks numbers today.

<!-- writer:start -->

## 1. What the letter has to do

You write the middle of a cover letter for a software engineer applying to one
job. Code adds the header, the date, the greeting and the sign-off, and checks
every sentence you write against the engineer's numbered facts.

Keep three things in mind:

- **The reader is fast.** Many hiring managers spend under 30 seconds on a
  letter. The first two sentences decide whether they read the rest, and
  the last one is what they remember. Spend your best material on the
  opening and the closing.
- **Polish is free now.** Since AI writing tools spread, a smooth, tailored
  letter no longer tells an employer much, because everyone can make one.
  What still works is something specific and checkable: a real system the
  engineer built, a real number, a clear reason for this job.
- **It is a writing sample.** Remote companies read the letter to see how
  the person writes. It should read like a short email from a capable
  engineer to someone they respect but have not met.

## 2. Length

- **150 to 250 words** for everything you write. Never more than 300.
- Shorter is fine when there is little to say. A tight 160-word letter beats
  a padded 320-word one.
- Do not add sentences to reach a length. If a sentence could be cut without
  losing a fact or a reason, cut it.

## 3. Shape

- 3 or 4 short paragraphs in all: an opening of 1 or 2 sentences, 1 or 2
  body paragraphs, and a closing of 1 or 2 sentences.
- The parts of your answer (opening, paragraphs, closing) are containers, not
  a formula. Paragraphs do not need to be the same length, and letters for
  different jobs should not all have the same rhythm.
- **Pick one main story.** Choose the one fact that best answers what this
  posting most needs, and tell it properly. Add at most one supporting point.
  Do not try to cover every requirement in the posting; that turns the letter
  into a weaker copy of the CV.
- **Do not mirror the posting.** Never open a paragraph by restating what
  the job asks for ("The role calls for...", "The posting emphasizes...",
  "You need...", "Dremio values..."). Mention the posting's main need at most
  once, in the opening. Body paragraphs start with what the engineer did.

## 4. Opening

The opening is the most important part of the letter. Its job is to make
the reader think "this person has done our hard part before".

- **Never announce the application.** No "I'm applying for the X role", "I
  am writing to apply", "please accept my application". The reader is on
  the application page for that job, and the letter's header already names
  it. That sentence spends the best line of the letter on something they
  know. Code removes it.
- **Lead with the match.** Put the posting's hardest or most central
  problem next to the thing the engineer built that solves the same kind
  of problem. Name the real system, and if it fits, one number from the
  fact. Two sentences at most.
- Good shapes (write your own, never copy these):
  - The connection: "Making sure no payment event gets lost is the same
    problem I solved for our backtesting platform: 800+ concurrent Python
    jobs on AWS Lambda without a production failure."
  - The thing built, then why it matters here: "I built the job system
    behind CoinQuant's backtesting platform, and your ingestion pipeline
    has the same shape: long, multi-step jobs that must never fail
    silently."
- Starting with "I" is fine. Naming the company is fine. Naming the job
  title is not needed; do it only when the title itself carries the match.
- **Do not read the company's own description back to them.** "Slite is
  expanding its vision with Super, a second product that..." tells them what
  they wrote. They learn nothing about the engineer.
- No "I am writing to", no "I am thrilled", no "my name is", no claim to be
  the perfect or ideal candidate.

## 5. The body: same facts, told plainly

The engineer's facts are CV bullets. CV bullets are dense and stiff. Pasting
them into a letter makes it read like a CV read aloud, and if every letter
uses the same sentence it reads like a template.

**Use no new facts. Tell the same facts in a new way.** That means:

- Say what the system does in plain words first, then the technology.
  Not "Architected a serverless, event-driven backtesting platform", but
  "Each backtest on our platform is a Python job on AWS Lambda, fed by an
  SQS queue. I built that system."
- Pick the detail of the fact that matters for this job. For a reliability
  job that is the failure handling; for a product job it is who used it.
- Use one or two numbers, inside the story, exactly as the fact gives them.
- Plain verbs: built, wrote, moved, set up, led, fixed. Prefer them to the
  CV verbs (architected, spearheaded, established), even when the fact uses
  the CV verb.

What you must not add, even though it sounds natural:

- Feelings, motives or history that no fact states: "the work I'm proudest
  of", "I've always loved", "most of my last year went into".
- What other people thought or did: "the team loved it", "the team now
  relies on it".
- Claims about a domain or a setting: "algorithmic trading is a high-trust,
  compliance-conscious domain". If it is not in a fact, leave it out.
- Results, scale or time spans that no fact gives.

If a sentence needs something only the engineer knows (why they want this
job, what they enjoyed), do not invent it. Leave it out and say so in your
notes (section 12), so the engineer can add it in their own words.

## 6. Why this company

- One specific reason, at most one or two sentences, tied to something the
  posting actually says: a product, a problem, a piece of the stack, a way of
  working.
- Talk about it the way an engineer would talk to a colleague, not the way
  marketing would. No praise words (innovative, impressive, exciting,
  world-class, cutting-edge).
- If the posting gives nothing specific, skip the "why us" and let the main
  story carry the letter.

## 7. Gaps

Code writes the gap sentence, not you. You only choose which gap, if any.

- Default: **name no gap, or one.** Never more than one.
- Name a gap only when the posting clearly requires it and it is central to
  the role (it is in the title, or the posting asks for it more than once).
  A "nice to have" is never a gap worth naming.
- Never name a gap that sits next to something the engineer did. A
  Developer Experience posting asks for CI/CD; the engineer built test-suite
  quality gates. Naming "CI/CD" as a gap undersells real, related work.
- Never mention a gap yourself in your own sentences, and never apologize
  for one.

## 8. Closing

The closing is the second most important part: it is the last thing read.

- One or two sentences. Tie back to the main story and offer something
  concrete to talk about, aimed at the posting's problem. "I'd be glad to
  walk you through how the platform handles failed jobs, since that's the
  part your pipeline can't get wrong." A short thank-you after it is fine.
- **No logistics.** Never mention time zone, working hours, location,
  notice period, start date or availability, in the closing or anywhere
  else. The header shows where the engineer is, and the application form
  asks for the rest. A logistics line as the last sentence turns the
  letter's final impression into admin. Code removes it.
- Nothing new about the engineer, no summary of the letter, no restated
  enthusiasm.
- Not "I would welcome the chance to discuss how I can contribute", not
  "thank you for your time and consideration", not "I look forward to
  hearing from you", not a bare "Happy to talk whenever suits you" with
  nothing specific in it.

## 9. Voice

- Write like a person talking: contractions are fine (I'm, I've, I'd, we're).
- Mix sentence lengths. Put at least one short sentence in each paragraph.
- Use plain "is" and "has". Not "serves as", "stands as", "boasts".
- Be direct and confident without adjectives. Let the fact do the selling.
- One idea per sentence. Few commas.
- No buzzwords, no exclamation marks, no questions, no bold or bullet points
  in the letter text.
- Never use the em dash (—) or a spaced en dash ( – ) as punctuation. Use a
  comma, a colon, a full stop or brackets. Claude in particular overuses the
  em dash, and readers treat it as a sign of AI writing.

## 10. Words and patterns that read as AI

Code checks every letter against these lists. Matching ignores case. A word
or phrase that appears in the fact a sentence cites is allowed in that
sentence (for example "comprehensive test suite").

### Never use

- —
- I am writing to
- express my interest
- express my strong interest
- thrilled
- excited to apply
- I'm excited to
- I am excited to
- excited about the opportunity
- aligns perfectly
- perfectly aligns
- aligns with
- align with
- proven track record
- track record
- passionate
- passion for
- results-oriented
- results-driven
- team player
- detail-oriented
- dynamic
- synergy
- synergistic
- leverage
- leveraging
- cutting-edge
- world-class
- innovative
- unwavering
- transformative
- testament to
- pivotal
- plays a key role
- plays a crucial role
- serves as
- stands as
- boasts
- not only
- it's not just
- isn't just
- not just about
- in conclusion
- in summary
- ultimately
- I hope this finds you well
- uniquely qualified
- perfect candidate
- ideal candidate
- perfect fit
- non-negotiable
- mindset
- fast-paced
- hit the ground running
- wear many hats
- exactly the kind of
- welcome the chance to discuss
- welcome the opportunity
- thank you for your time and consideration
- I look forward to hearing from you
- make a meaningful impact
- deeply
- truly
- genuinely

### Use at most one of these in a whole letter

- delve
- tapestry
- intricate
- meticulous
- realm
- showcase
- showcasing
- robust
- seamless
- seamlessly
- enhance
- foster
- fostering
- elevate
- empower
- harness
- landscape
- navigate
- journey
- vibrant
- crucial
- invaluable
- streamline
- spearheaded
- additionally
- furthermore
- moreover
- I believe

### Patterns to avoid

- An opening that announces the application: "I'm applying for", "I am
  writing to apply", "please accept my application".
- Logistics anywhere in the opening or closing: time zone, UTC, notice,
  start date, "based in", "I work remotely from".
- A paragraph that opens by restating the posting: "The role calls for",
  "The role asks for", "The posting emphasizes", "You need", "<Company>
  values".
- An opening that summarizes what the company does in its own words.
- Lists of three adjectives or three abstract nouns ("scalable, reliable and
  maintainable"). A list of concrete things is fine; prefer two over three.
- A sentence that ends in a ", -ing" add-on: ", ensuring...",
  ", highlighting...", ", enabling...".
- "Not X, but Y" and "It's not X, it's Y" contrasts.
- A last sentence in a paragraph that sums up the paragraph or states its
  moral ("exactly the kind of reliability a green branch demands").
- Every paragraph the same length; every sentence the same length.
- The same telling of a fact as in other letters. Tell the main story fresh
  for each job.

## 11. Format

Code handles all of this; it is here so you know what surrounds your text.

- Header: name, contact line, location, date. Then "<Company> Hiring Team",
  the job title, and "Dear <Company> Hiring Team,".
- Sign-off: "Best regards," and the name.
- Plain text: it is pasted into form boxes as often as it is uploaded. No
  markdown, no bullet points, no bold.

## 12. Notes to the engineer

Hiring data shows that letters the applicant edited do better than letters
sent as the tool wrote them. Your notes are how the engineer knows what to
edit. Write 1 to 3 short lines:

- Which fact you led with, and why it fits this posting.
- The one sentence they should make their own before sending, usually the
  reason they want this job, which only they can write.
- Any gap you chose not to name, if it might come up in an interview.

## 13. Before and after

These "before" sentences come from real letters this app wrote. The "after"
versions use only the engineer's facts. They show the idea, not words to
copy: write each opening and closing fresh for the job, so two letters never
start or end with the same sentence.

**The opening reads the company's copy back to them.**

- Before: "Slite is expanding its vision with Super, a second product that
  makes AI ready-to-use at work by syncing company data and providing teams
  with powerful recipes and tools."
- After: "Super needs features built end to end, from the API to the
  screen. At CoinQuant I built both halves of our backtesting platform: the
  Python API and the interface on top of it."

**A CV bullet pasted in whole (this fact, in nearly these words, was in all six letters).**

- Before: "I architected a serverless, event-driven backtesting platform on
  AWS Lambda and SQS that runs 800+ concurrent Python jobs over historical
  market datasets with zero production failures."
- After: "Each backtest on our platform is a Python job on AWS Lambda, fed by
  an SQS queue. I built that system, and it runs 800+ concurrent jobs without
  a production failure. When a job fails, it lands in a dead-letter queue we
  can redrive, and the user gets their credits back."

**A paragraph that opens by restating the posting.**

- Before: "The posting emphasizes a track record of automated tests and
  testable codebases, plus hands-on experience with relational databases and
  message queues."
- After: "I built our test suite across the whole testing pyramid. Its
  quality gates are what let the team start working with AI coding agents
  without losing code quality."

**A claim that is not in the facts.**

- Before: "Working in algorithmic trading means every system I built ran in
  a high-trust, compliance-conscious domain where correctness and reliability
  were non-negotiable."
- After: leave it out. Nothing in the facts says this. The code that checks
  sentences does not catch it either, because it has no number, tool or
  title in it, so it is on you not to write it.

**A gap list that works against the engineer.**

- Before: "I have not worked with CI/CD, Jenkins or Kubernetes yet, and I
  would make learning them an early priority."
- After: no gap sentence. CI/CD is close to the test-suite quality gates the
  engineer built, and three gaps in a row read as three reasons to say no.
  If the posting lists Kubernetes as a must-have, name that one alone.

**An opening that announces the application.**

- Before: "I'm applying for the Full Stack Engineer role. You want someone
  who owns features end to end with real depth on the backend."
- After: "At CoinQuant I own the backtesting platform end to end: the job
  system on AWS Lambda and SQS behind it, and the Next.js chart users see."
  The header already says Full Stack Engineer.

**A closing that ends on logistics.**

- Before: "I'm in Beirut on UTC+2 in winter and UTC+3 in summer, the same
  as EET. Happy to walk you through the failure handling whenever suits
  you."
- After: "I'd be glad to walk you through how failed jobs are retried and
  refunded, since a lost job is the failure your platform can least
  afford."

**A closing made of filler.**

- Before: "I'd bring a scrappy, automation-first mindset to Dremio's
  infrastructure, plus leadership reps that keep teams unblocked. I'd welcome
  a conversation about how I can help your engineers ship faster."
- After: "I'd be happy to walk you through the Bazel to Poetry move in more
  detail. Thanks for reading."

## 14. A full example

For a made-up posting: Backend Engineer at Northwind, a payments API. The
posting says the hardest part of the job is making sure no payment event is
lost, and asks for Python, PostgreSQL and message queues.

> Making sure no payment event gets lost is the same problem I solved for
> the backtesting platform at CoinQuant. There, a job that fails is never
> silently dropped.
>
> Each backtest is a Python job on AWS Lambda, fed by an SQS queue. I built
> that system, and it runs 800+ concurrent jobs without a production failure.
> A job that fails goes to a dead-letter queue we can redrive, and the user
> gets their credits back. Result writes to PostgreSQL are idempotent, so a
> retry never saves a result twice.
>
> Before that I led our move from Bazel to Poetry for the Python services,
> which made builds reproducible and dependencies simpler to manage.
>
> I'd be glad to walk you through the retry and refund path, since that's
> the part a payments API can't get wrong. Thanks for reading.

About 145 words. The opening puts their hardest problem next to the
engineer's system, without naming the job title. One main story, one
supporting point. The closing comes back to the same story. No logistics.

## 15. Check before you answer

- [ ] 150 to 250 words, never over 300.
- [ ] The opening does not announce the application; it puts the
      posting's main problem next to something the engineer built.
- [ ] One main story, told in plain words, not pasted from a bullet.
- [ ] No paragraph opens by restating the posting.
- [ ] Every fact about the engineer is in the numbered facts; no feelings,
      motives or results added.
- [ ] No word or phrase from "Never use", at most one from "Use at most one".
- [ ] No em dash.
- [ ] At most one gap chosen, and only a central, required one.
- [ ] The closing is one or two plain sentences that come back to the main
      story. No time zone, location, notice or availability.
- [ ] Notes say which sentence the engineer should make their own.

<!-- writer:end -->

## What code does with this file, and what is still open

Done (`src/jobhunter/cover.py`):

- The `writer:start`/`writer:end` part is the writer's prompt, after the fact
  rules and the JSON contract, which stay in code.
- `check_style` reads the two lists in section 10. A "Never use" phrase is
  treated like a fact problem: sent back once, then the sentence is left out.
  Dashes, ", -ing" add-ons, questions, two "Use at most one" words and a
  letter over 300 words are sent back once, then only noted; a dash that is
  left becomes a comma. In a body paragraph, a sentence that opens by
  restating the posting ("The role calls for...") is a problem. So is a
  sentence that announces the application ("I'm applying for...") and, in
  the opening or closing, logistics (time zone, notice, location). When the
  whole opening is removed, the first body paragraph opens the letter; no
  stock line is added.
- The letter's facts no longer include the profile's logistics lines (where
  you live, time zone, notice period). The header still shows your location.
- Gaps: at most 1, and only when the posting names it in the title or twice
  and the facts have nothing close to it (`gap_matters`; the CI/CD case).
- Writer model: `cover_model` is `claude-code` (`claude -p`, your Claude
  login, no tools, none of your Claude settings).

Still open:

- Greeting: when the `contacts` table has the hiring manager's name,
  "Dear <First name>," reads better than "Dear <Company> Hiring Team,".
  `render_letter` always writes the second today.
- Claims written in plain words ("a high-trust, compliance-conscious domain",
  "the chart shows every trade") pass every check, because the checks look
  for numbers, tools, titles, names and the phrase lists. Read each letter
  before sending.

## Evidence

Strength: **[strong]** field data, an experiment or a peer-reviewed or working
paper; **[survey]** a survey that states its method (answers are self-reported);
**[vendor docs]** a product's own help pages; **[opinion]** advice from hiring
managers or career offices.

What changed with AI:

- [strong] Galdin & Silbert, "Making Talk Cheap" (2025). About 2.7M
  applications to coding jobs on Freelancer.com. Before ChatGPT, a clearly more
  tailored proposal was worth about $25.67 to employers; after, $14.85.
  Employers leaned more on reputation scores instead.
  https://arxiv.org/abs/2511.08785
- [strong] Cui, Dias & Ye (2025). 5M cover letters on Freelancer.com. After the
  platform's AI letter tool arrived, the link between a tailored letter and a
  callback fell 51%. Applicants who spent more time editing the AI draft got
  more offers (a correlation, not proof of cause).
  https://arxiv.org/abs/2509.25054
- [strong] Cowgill, Hernandez-Lagos & Wright, Management Science (2024/25).
  ChatGPT made pitches better but more alike, and evaluators picked out the
  real experts less accurately.
  https://pubsonline.informs.org/doi/10.1287/mnsc.2024.07027
- [strong] Jakesch, Hancock & Naaman, PNAS (2023). Across 4,600 people, nobody
  could reliably tell AI-written self-descriptions from human ones. People
  relied on wrong cues, such as "I" and contractions.
  https://www.pnas.org/doi/10.1073/pnas.2208839120
- [strong] OpenAI withdrew its AI-text detector in 2023 (it caught 26% of AI
  text and flagged 9% of human text). Detectors flag non-native English
  writers far more often (Liang et al., Patterns, 2023). Recruiters judge by
  feel, so surface tells are what matter.
  https://www.cell.com/patterns/fulltext/S2666-3899(23)00130-7

Whether letters are read:

- [survey] Resume Genius, 625 US hiring managers (2023): 83% always or often
  read cover letters; 36% spend under 30 seconds on one.
  https://resumegenius.com/blog/cover-letter-help/cover-letter-statistics
- [survey] CV Genius, 625 UK/Ireland hiring managers (2024): 80% view obvious
  AI writing negatively; 45% of tech hiring managers would discard an
  application that looks AI-written.
  https://cvgenius.com/blog/career-advice/cv-and-cover-letter-trends-survey
- [survey] ResumeGo field test, 7,287 applications (2019-20, before
  ChatGPT): tailored letters got 53% more callbacks than no letter; generic
  letters helped much less. https://www.resumego.net/research/cover-letters/
- [vendor docs] Greenhouse and Ashby AI screening tools match the resume, not the
  cover letter, against the job (vendor docs, 2025). Keyword-stuffing a
  letter does not help with the software; the letter is for people.

Length, shape, tone:

- [opinion] Engineering managers on Hacker News: "less than a page, ideally
  just a couple of paragraphs" (2025); a short note "works well for startup
  jobs" (2017). https://news.ycombinator.com/item?id=44522262
- [opinion] Harvard career services (2025): in computing fields the letter
  "can be even shorter... just a few short paragraphs."
- [opinion] Ask a Manager: do not try to cover every requirement in the
  posting, it makes a "crowded, less effective" letter that repeats the
  resume (2013); starting with "I" is fine (2018).
  https://www.askamanager.org/2013/12/something-your-cover-letter-does-not-need-to-do.html
- [opinion] Jason Fried, 37signals (2025): write about "why you want this
  particular job and not just any job"; "If AI wrote your cover letter and you
  change 5% of it, it's not yours."
  https://37signals.com/podcast/the-case-for-cover-letters/
- [opinion] Automattic, an all-remote company: "clear, thoughtful writing is
  highly valued here." https://automattic.com/how-we-hire/
- [opinion] Gaps, where sources split: Ask a Manager says acknowledge a
  missing requirement and show how you'll make up for it; The Muse says
  apologizing for missing experience tells them you're not a great hire.
  Section 7's "one central gap at most, never apologize" sits between them.

Openings and closings (added October 2026):

- [opinion] Ask a Manager says a plain opening ("I'm interested in your X
  position because...") is fine, and a freeCodeCamp hiring manager agrees
  ("I'm interested in X"). This file goes further on purpose: the header
  already names the job, so the first line goes to the fit.
  https://www.askamanager.org/2018/01/these-are-bad-ways-to-start-your-cover-letter.html
  https://www.freecodecamp.org/news/how-to-improve-your-cover-letter/
- [opinion] Software hiring advice that does agree: open with one
  hand-picked achievement that matches the job, not a self-introduction
  (Springboard, Lilach Bullock); "you must add something specific about the
  role/company", which "will get you miles ahead of others" (a hiring
  manager on Hacker News, 2024).
  https://www.springboard.com/blog/software-engineering/software-engineer-cover-letter/
  https://news.ycombinator.com/item?id=42532176
- [opinion] Closings: career sites agree the last paragraph is what the
  reader remembers and should point at one standout match plus a next step.
  Their formula (restate enthusiasm, 70 to 120 words) is left out: it is the
  filler sections 8 and 10 ban. Logistics in the closing was the app's own
  habit, not advice from any source.
  https://huntr.co/blog/how-to-end-a-cover-letter

AI tells:

- [strong] Wikipedia, "Signs of AI writing" (WikiProject AI Cleanup): the
  phrase and pattern lists in section 10 come mostly from here, including the
  report that Claude uses more em dashes than professional writers.
  https://en.wikipedia.org/wiki/Wikipedia:Signs_of_AI_writing
- [strong] Kobak et al., Science Advances (2025), and Liang et al. (2024):
  words like delve, showcasing, underscores, intricate and meticulous appear
  many times more often since LLMs. https://www.science.org/doi/10.1126/sciadv.adt3813
- [strong] Reinhart et al., PNAS (2025): models use ", -ing" add-on clauses
  2 to 5 times more than people. https://www.pnas.org/doi/10.1073/pnas.2422455122
- [opinion] MIT career office: em dashes and writing that is "too perfect"
  read as AI. https://capd.mit.edu/resources/using-ai-for-cover-letters/

Left out on purpose because no real source could be found: "HBR: 89% of AI
letters...", "Forbes: 80% discard AI applications", "ResumeGo: ~300 words
gets 23% more replies", "Ladders: 76% prefer half a page".
