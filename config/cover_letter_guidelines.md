# Cover letter guidelines

How paragraph 1 of a cover letter reads: why the engineer wants to join this
company. Paragraph 2 is the engineer's own text (`cover_paragraph` in
config/outreach.json), printed word for word, so nothing here applies to it.

How this file is used:

- The part between `writer:start` and `writer:end` is written to the model
  (`cover_model`, DeepSeek) after the rules in `cover.py`'s `SYSTEM`. Change
  how the paragraph reads by editing this file, not the code.
- The facts rules do not live here. They stay in code (`check_sentence`): about
  the company, every name and number must be in the posting or the pages code
  fetched from its website; about the engineer, only what
  `profile/master_profile.md` says.
- Code reads the two lists in section 4 and checks every sentence against them.

<!-- writer:start -->

## 1. The task

Write the first paragraph of my cover letter: why I want to join this
company. Act as a pragmatic software engineer applying to a company, not a
professional cover letter writer.

Use the job description and the company's own pages that code fetched (home
page, about page, blog), which you get in the prompt. That is all your
research. Find ONE specific reason a developer with my background would
genuinely want to work there.

What to look for, in this order:

1. What interesting technical or business problem is the company solving?
2. What makes that problem challenging or interesting from an engineering
   perspective?
3. How does it connect to my experience in backend engineering, startups,
   financial technology, AI-native development, or automation? Only what my
   listed facts say.

## 2. Writing rules

- Write 2 or 3 sentences, at most 65 words.
- Sound like a real developer explaining their interest to another developer.
- Be conversational, direct, confident, and slightly informal.
- Focus on ONE specific reason, not a list of reasons.
- Prefer interesting engineering problems, product challenges, or ways of
  working over generic company values.
- Mention a concrete detail from the posting or the pages, but only if it
  fits naturally.
- Connect that detail to my professional interests or experience by naming
  one thing I built, in my facts' own words. Never say I've already done the
  company's kind of work ("a problem I've been working on", "the kind of work
  I already do", "maps directly to") unless a fact says exactly that.
- Don't pretend I've used their product, followed them for years, or admired
  them. There is no evidence of that.
- Don't invent emotional attachment or enthusiasm.
- Avoid corporate language: "passionate about", "deeply resonates",
  "innovative solutions", "cutting-edge", "industry-leading",
  "revolutionizing", "I am thrilled to apply".
- Don't summarize their website or repeat their mission statement.
- Avoid exaggerated praise and technical name-dropping.
- Don't force a personal connection if none exists. A specific, intellectually
  honest interest in their work is enough.
- No em dash (—), no exclamation marks, no questions.
- The second paragraph (in the prompt) follows yours: don't repeat what it
  says.

## 3. Human authenticity test

Before you answer, ask: "Would a pragmatic developer actually say this in a
casual conversation with the hiring manager?" If it sounds polished, generic,
flattering, or AI-generated, rewrite it more naturally.

## 4. Words that read as AI

Code checks every sentence against these lists. Matching ignores case.

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
- exactly that
- welcome the chance to discuss
- welcome the opportunity
- thank you for your time and consideration
- I look forward to hearing from you
- make a meaningful impact
- deeply
- truly
- genuinely
- comes down to
- the same problem
- the same question
- the same call
- the same check
- the same kind of
- the same pattern
- the same idea
- the same shape
- the same thinking
- the same guarantee
- the same rule
- can't get wrong
- can least afford
- the work I already do
- maps most closely
- design call
- I built that system
- I built it and I own it
- keep it honest
- on trust
- passionate about
- resonates
- innovative solutions
- industry-leading
- revolutionizing
- revolutionize
- I am thrilled to apply
- I've used
- I have used
- I've been following
- I have been following
- long-time user
- big fan
- I've admired
- I have admired
- I've always
- dream company
- natural extension
- fits naturally
- ties directly
- ties into
- connects directly
- maps directly
- the kind of work I already do
- I'd love to
- I would love to

### Use at most one of these in the paragraph

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
- I also
- before that
- earlier
- outside work

<!-- writer:end -->

## What code does with this file

`src/jobhunter/cover.py`:

- The writer part above is the model's prompt, after the rules and the JSON
  contract in `SYSTEM`.
- A "Never use" phrase, an "I'm applying for" sentence, or logistics (time
  zone, notice, location) is a problem: sent back once, then the sentence is
  left out. So is a name or number that is in neither the posting, the
  company's pages nor the profile.
- More than 65 words, fewer than 2 or more than 3 sentences, two "Use at most
  one" words, a dash, a ", -ing" add-on, or a quote that code cannot find in
  the posting or pages: sent back once, then only noted. A dash that is left
  becomes a comma.
- Claims in plain words ("they ship weekly") pass when they name nothing and
  have no number. Read the paragraph before sending.

## Background research

The research below was done in October 2026 for an earlier, longer letter (an
opening, a body paragraph citing profile facts, a closing). The word lists
came from it.

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
