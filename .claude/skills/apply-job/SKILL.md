---
name: apply-job
description: Work through the "To apply" column of the jobhunter app in Chrome - get a checked tailored CV, fill the job's application form on the company site or in LinkedIn Easy Apply, find one LinkedIn contact per job (CEO at a small company, else the hiring manager, else HR, else a team lead) and write a note of at most 300 characters with two achievements - and stop before the final Apply/Submit, never pressing Connect or Message. Use when the user says "apply to my jobs", "go through To apply", or names a job to apply to.
---

# Apply to jobs from the "To apply" column

Runs in the user's real Chrome through Claude in Chrome (`mcp__claude-in-chrome__*`; read the
`claude-in-chrome` skill first). The goal is to be **autonomous**: never stop the whole run on one
question, one field or one stuck page. Make a sensible choice, note it, keep going.

## Two hard stops (the only things you never do)

1. **Never press the final Apply / Submit / Send application button.** Fill everything, scroll to it,
   leave the tab open for the user to press it.
2. **Never contact anyone.** On LinkedIn never press Connect, Message, Follow or InMail, and never
   open the Connect dialog or type into it. Step 4 only finds the person and writes the note; the
   user sends it. Never press Send on an email in the app either (.claude/CLAUDE.md: emails go out
   only from the user's own click on Send).

Everything else (uploading the CV, answering questions, clicking Next between form pages, Tailor CV,
searching LinkedIn and opening profiles) you do without asking.

The user has said yes, for every run, to ticking an application form's privacy notice / data
processing / candidate privacy policy checkbox (the one a form needs before it can be submitted).
Tick it and note it in the report. This covers only those boxes on application forms, not
creating an account, newsletters or marketing opt-ins (leave those unticked).

## Facts you may use

- Only `profile/master_profile.md` (in `~/job-hunter`, not in git) and the job's tailored CV. Read
  the profile once at the start of the run.
- Name, email, phone, LinkedIn and the like: `MY_*` in `~/job-hunter/.env`. Use them only to fill forms.
  Never write them into a tracked file.
- Never invent a skill, employer, title, date, project or number. For open questions you can choose
  the story and polish the wording, but the facts come from the CV.

## Setup

1. Make sure the app is running: `curl -s http://127.0.0.1:8765/api/status`. If it isn't, start
   `cd ~/job-hunter && .venv/bin/jobhunter serve` in the background and wait for it.
2. Open http://127.0.0.1:8765/#pipeline in a new tab. The **To apply** column lists shortlisted
   jobs the user hasn't applied to yet, plus visa-list jobs (the **visa** chip) posted today or
   yesterday. Do them one at a time, top to bottom (or only the job the user named).

## For each job

### 1. CV
- Open the job's card. In the **CV** section:
  - If it shows a tailored CV ("Tailored ... by ..."), use it.
  - If not, press **Tailor CV to this job** and wait until the tailored info appears (it can take a
    minute).
- **Quick check before using it** (open it with "View ↗", or read
  `~/job-hunter/resume/versions/` / `resume/output/`):
  - The name and contact line are right, and it is 1-2 pages.
  - The employers, titles and dates match `resume/resume.md`.
  - The headline makes sense for this role.
  - There is no Summary section, and no `TODO` or leftover tag such as `[core]`.
  - The "Code changed these" warnings don't point to a broken line.
  If something critical is wrong, fall back to the general CV (`<Last>_Resume_General.pdf` in
  `resume/output/`), note it for the report and keep going. Don't fix a broken CV by hand.
- **Mirror it only for grade 4 or 5** (the user's call, 2026-10-31: mirroring is real work, so
  it goes to the best-fitting jobs). The card shows the grade chip ("grade 4/5"); or
  `sqlite3 data/jobs.sqlite "select json_extract(fit_grade_json,'$.grade') from jobs where id=<id>"`.
  - **Grade 4 or 5:** after the quick check, follow the whole `mirror-cv` skill on this job's
    CV, then upload the rebuilt PDF. Do it thoroughly, not as a quick pass. Don't ask anything
    during it: the `.bak` lets the user undo. If mirroring can't end at one page with
    `check_version` printing `[]`, restore the `.bak`, rebuild, upload that and note it.
  - **Grade 1-3 or no grade:** use the tailored CV as it is. No hand edits, unless the user
    asked to mirror this job.
  - A CV the user edited by hand (`edited_at` in `cv_tailored_json`) is mirrored too, but
    their own lines are kept as they wrote them: only reorder around them.
- The PDF is already on disk in `~/job-hunter/resume/output/`, so upload it from there. Press
  **Download ↓** too if the user wants a copy in Downloads.

### 2. Find the real application page
- Press **Open posting ↗**.
- If the posting is behind a sign-in or paywall (We Work Remotely always is), don't sign in and
  don't pay. Search for the same role on the company's own careers page or its job board (Greenhouse,
  Lever, Ashby, Workable, BambooHR, LinkedIn) and apply there. Match the title, and the location if
  one is given.
- If the role can't be found anywhere or is closed, skip it (below) and move to the next job.
- If the company can't hire from Lebanon (residence required in another country, US-only), skip it
  and say so in the report. If the user wants that company never shortlisted again, add it to
  `blocked_companies` in `config/filters.json` with a short `why`, then run
  `.venv/bin/jobhunter reclassify`.
- **Skipping a job:** press the red **Skip** button at the top of the job's card in the app. It
  moves the job to Closed with the reason "skipped", so it leaves To apply. Don't drag the card to
  the Closed column: that opens a "Why closed?" pop-up that blocks the browser tools. Skip every
  job you can't apply to: closed or not found, location rules, a site that refuses applicants from
  Lebanon, only on job aggregators, or a sign-up you can't do (except Proxify, below). A job whose
  form you filled but the user must finish (a CAPTCHA, a field only they can answer) stays in To
  apply. In the Skip pop-up pick the reason that fits and write a short note that quotes the
  posting ("UAE-Based Candidates only"): the fit grade learns from both, and the final answer
  reuses the note.

### 3. Fill the form
- Upload the tailored CV PDF wherever a resume is asked for. If `find`/`read_page` can't see the
  file box (SmartRecruiters and other sites hide it inside a web component, "shadow DOM"), use a
  stand-in box (below). Don't fetch the PDF from the app's `/api/cv/` from the page: Chrome holds
  that request for a local-network permission and the tab freezes. If a cover letter is asked for and one
  exists (`resume/output/<Last>_CoverLetter_<Company>_*.md`), paste or upload it. If none exists,
  press **Write cover letter** in the app first. If it's optional and that fails, skip it.
- **Hidden file box, stand-in method** (tested on SmartRecruiters, Oct 2026):
  1. `javascript_tool`: add a plain box the tools can see:
     `let p=document.createElement('input'); p.type='file'; p.id='jh-proxy'; p.setAttribute('aria-label','jh proxy file input'); p.style.cssText='position:fixed;top:0;left:0;z-index:99999'; document.body.appendChild(p)`
  2. `find` "jh proxy file input", then `file_upload` the PDF into it.
  3. `javascript_tool`: find the real box and copy the file over:
     ```js
     function deep(r,o=[]){r.querySelectorAll('*').forEach(e=>{if(e.tagName==='INPUT'&&e.type==='file')o.push(e);if(e.shadowRoot)deep(e.shadowRoot,o)});return o}
     const t=deep(document).find(i=>i.id==='<id>');  // list ids + page position first to pick the Resume one
     const dt=new DataTransfer(); dt.items.add(document.getElementById('jh-proxy').files[0]); t.files=dt.files;
     t.dispatchEvent(new Event('input',{bubbles:true,composed:true})); t.dispatchEvent(new Event('change',{bubbles:true,composed:true}));
     document.getElementById('jh-proxy').remove()
     ```
     On SmartRecruiters the Resume box is `spl-dropzone-file-input-1` (the lower one on the page);
     `-2` is the "Easy Apply" autofill box at the top. Check the screenshot shows the file name
     under Resume.
     After the change event the site empties the box again, so reading `t.files` afterwards shows 0:
     trust the screenshot, not that number.
- **SmartRecruiters notes:** the "Message to the Hiring Team" box rejects semicolons (`;`). The
  City field needs the suggestion clicked ("Beirut, Beyrouth, Lebanon"). Jobs for Humanity adds a
  "Preliminary questions" page after Next: industries Financial services + Computers and
  information technology, function Engineering, 3 - 5 years, the floor bracket for monthly salary
  (3,000 - 3,500), languages from the profile's "Spoken languages" line, visa No,
  gender, community and disability from the profile's self-identification section (below),
  privacy box ticked.
- **LinkedIn Easy Apply** (the user is already signed in to LinkedIn in Chrome):
  - Use it only when the LinkedIn job page shows an **Easy Apply** button. A plain **Apply** button
    goes to the company site: follow it and fill that form instead.
  - Never sign in, type a password, or edit the user's LinkedIn profile. If LinkedIn asks to sign
    in or shows a security check, stop on that job, note it and move on.
  - Go slowly, like a person: one job at a time, no browsing or scraping lists of jobs, and at most
    10 Easy Apply forms per run. LinkedIn forbids automation and can restrict the account, so if
    it shows any "unusual activity" warning, stop all LinkedIn work for the run and say so in the report.
  - **Contact info:** check the email and phone against `MY_*` in `.env`; fix them if they differ.
  - **Resume:** upload the tailored PDF and make sure it is the one selected, not an older resume.
    LinkedIn has no file box on the page: it makes one only when **Upload resume** is pressed and
    opens the system file picker, which the tools can't use. So catch that box instead (tested Oct
    2026, on the Resume step of the Easy Apply window):
    ```js
    const orig=HTMLInputElement.prototype.click;
    HTMLInputElement.prototype.click=function(){ if(this.type==='file'){ this.setAttribute('aria-label','jh caught file'); if(!this.isConnected){this.style.cssText='position:fixed;top:0;left:0;z-index:999999'; document.body.appendChild(this);} return;} return orig.call(this)};
    [...document.querySelectorAll('button')].find(b=>/Upload resume/i.test(b.innerText||b.getAttribute('aria-label')||''))?.click()
    ```
    Then `find` "jh caught file input" and `file_upload` the PDF into it. LinkedIn shows "Resume
    uploaded successfully" and selects the new file at the top of the list.
  - **Screening questions:** "How many years of experience with X?" gets the years from the
    profile. If X isn't in the profile, answer 0 and note it, never a guess. Yes/No skill questions
    are Yes only when the skill is in the profile. Other questions use the standard answers below.
  - Press **Next** / **Review** between steps. On the Review page untick **Follow <company>**.
  - Stop at **Submit application**. Don't press it. Leave the Easy Apply window open in that tab
    (closing it asks to save or discard: don't close it).
- Profile photo / avatar field: upload `~/Downloads/image.png` (the user's headshot).
- Fill every field from the profile and CV (autofill first, then fix what autofill got wrong).
- Standard answers:
  - **Authorized to work?** Yes, in Lebanon (lives in Beirut). If the question is about the US, EU
    or another specific country, answer truthfully from the profile (contractor / EOR, no visa
    needed for remote work). Sponsorship needed? No, when the role is remote.
  - **Jobs the user would move for** (on-site/hybrid in the UAE or Qatar, and visa-list jobs in the
    Netherlands, Germany, Finland, the UK, Ireland, Spain or Italy): authorized to work there? No.
    Needs visa sponsorship? Yes. Willing to relocate / work on-site there? Yes (for the EU and UK only
    with sponsorship, as the user said on 2026-10-13). Current location: Beirut, Lebanon. In the UAE
    or Qatar the pay floor is the profile's relocation line (5000 usd/month), not the remote floor.
    A visa-list job whose posting or form says it can't sponsor (needs an existing right to work):
    Skip it with that reason.
  - **Location / time zone / notice:** from the profile's "Work authorization and logistics" section.
    If the form's notice options don't include 2 weeks / 14 days, pick the next shorter one
    (10 days, not 20).
  - **"Are you an AI model applying on behalf of your user?"** (or any question asking whether an
    AI, bot or agent is filling in the form): **don't answer it, neither Yes nor No.** Leave it
    empty for the user to click themselves, and list it in the report as "AI question left for
    you". The job stays in To apply.
  - **Disability, medical needs, accommodations or adjustments:** No / none needed.
  - **Gender, sexual orientation, race and other voluntary (EEO) questions:** answer from the
    profile's "Voluntary self-identification (forms only)" section, word for word in meaning, and
    never "Prefer not to say" for a question it covers unless its line says so (the user's call,
    2026-10-21). Those answers
    live only in the profile (not in git): never copy them into a tracked file. A voluntary
    question the section doesn't cover: leave it empty for the user (pick "Prefer not to say" only
    if the field is required) and list it in the report.
  - **How did you hear about us:** pick **Other** ("Other (please specify)" or the like) and write
    "An AI job hunter tool I built in-house" in its text box. A free-text question gets the same
    words. If the list has no Other option, pick the closest choice ("Job board") and note it.
  - **Expected salary:** do a quick web search for what this company pays for this role and level
    (Levels.fyi, Glassdoor, the posting's own range). Ask for a bit below the usual figure, but
    never below the "Salary floor" line in the profile. Use the form's currency and period (monthly
    or yearly). If nothing turns up, use the floor plus about 10%.
  - **Something you're proud of building / a project you're proud of:** use this, as the user
    wrote it (if the box has a length limit, drop the "I built it in TypeScript ..." sentence
    first, never the last one):
    "I built Vibe Taxi, a booking system for my dad's one-driver taxi business in Lebanon, so he
    no longer has to answer every booking message by hand while driving. It's a WhatsApp bot that
    chats naturally with customers, plus a booking website with a map and live prices, and a phone
    dashboard he uses to accept rides and take over chats. I built it in TypeScript (Node, Hono,
    SQLite, deployed on Fly.io). The AI is never trusted with money: it can only call tools I
    wrote, so every price and booking comes from my own code, and the bot switches to a simple
    button flow if OpenAI goes down. It taught me how to use AI safely in a real product, and it
    solves a real problem for someone I care about."
    Vibe Taxi has no public link: if the question requires a link or repo, use the job-hunter one
    below and note it in the report.
  - **Code sample / repo / portfolio link:** https://github.com/mohamad-shoumar/job-hunter
    If the form also asks about that code (or "tell us about it"), use this, as the user wrote it:
    "A job-search tool I built that uses Claude to tailor my CV. The rule is that the model may
    reword my experience, but code decides what's true. check_bullet compares each AI rewrite to
    the original bullet and rejects any new number, technology, seniority word or name, with a
    readable reason for each. I'm proud of it because it makes an AI feature trustworthy without
    trusting the AI."
  - **Current salary / current benefits:** the profile's "Current salary" and "Current benefits"
    lines, in the form's currency.
  - **Open questions:** be objective. Answer the question itself, on its merits, the way an
    engineer would explain it: 2-4 short sentences, plain words, no pitch. Don't bend the answer
    toward the user's experience. The user found answers that fit a CV achievement into every
    reply "too AI".
    - Use a CV bullet or achievement only where it makes sense: the question asks about the
      user's experience ("What experience do you have ...", "Tell us about a challenge"), or a
      real example actually makes the point clearer. Otherwise leave the CV out. Never invent.
    - **An open question the profile, memory and the standard answers above can't answer**
      ("Why this company?", "Why this role?", "Why are you looking?", "What are you looking for
      next?", "Why are you a fit?", "What excites you ...", AI/AGI or other opinion questions):
      follow the `job-application-answers` skill and fill it in (the user's call, 2026-10-31).
      Its length rule (100-130 words, or the form's limit) wins here. List each one in the report
      as "written by job-application-answers" so the user reads it before pressing Apply.
    - Avoid pitch phrases such as "My rule of thumb is", "What excites me is", "That is how I work
      today", and avoid stacking numbers (115+, 370+, 800+) into one answer.
- **Unsure about a field?** Pick the most reasonable answer, note it for the report, keep going.
- **Stuck?** If a page freezes, an upload fails or a button doesn't respond, reload and try again
  (up to 2 retries per step). If it still fails, leave the tab as it is, note it and go to the next
  job. Never stop the whole run because of one job.
- **CAPTCHA or account sign-up:** don't solve or create it (Claude may not create accounts or type
  passwords, even with permission). Fill what you can, leave the tab open and note it for the user.
  Proxify ("Get paid, not played" postings, often re-posted on job boards) always needs a talent
  account, so the user does those.
- Finish at the final **Apply/Submit** button. Don't press it. Leave the tab open.

### 4. One LinkedIn contact (find and write, never send)
Outreach goes through LinkedIn now, not email (the user's call, 2026-10-29). Don't use the app's
Find contact, Write with AI or Gmail drafts in this step. Search only on LinkedIn, where the user is
already signed in.
- **One person per job** (the user's call, 2026-10-29). Go down this list and stop at the first
  group where you find someone:
  1. **The CEO / founder, only at a small company:** at most 50 employees on the company's LinkedIn
     page ("11-50 employees"), the same line the app uses (`small_company_max_employees` in
     `config/outreach.json`). A size you can't find counts as small, as in the app. A bigger
     company starts at 2.
  2. **The hiring manager:** the engineering manager or head of the team the role sits in.
  3. **HR / recruiter / talent acquisition** at the company (one who hires engineers, or in the
     job's region, if you can tell).
  4. **An engineer, team lead or tech lead** on that team.
  Leave out people who have left the company. Leave out agency recruiters too, unless an agency
  posted the job and hides the client: then the agency's recruiter for it is the one person.
- **Inside a group, pick the one with a link to the user:** a 1st or 2nd-degree connection, or
  shared connections ("X mutual connections"); a fellow alum of the American University of Beirut
  (AUB) or Software Engineering Factory; an Arab background the profile shows (studied, worked or
  lives in Lebanon or another Arab country, or lists Arabic). Go by what the profile shows, not a
  guess from the name alone. A link never moves someone above an earlier group.
- **How to search:** the company's LinkedIn page, People tab, with a keyword (CEO, founder,
  engineering manager, recruiter, talent, HR, tech lead, team lead); its "Where they studied" filter
  finds AUB alumni. Or people search:
  `https://www.linkedin.com/search/results/people/?keywords=<company> recruiter`.
  Read only the first page of results. Opening a profile is fine (they will see the user viewed it).
- **Pace:** the Easy Apply rules apply here too: slowly, at most 4 searches and 5 profiles per
  company, and any "unusual activity" warning stops all LinkedIn work for the run.
- **Email:** only when it is public, on the person's LinkedIn Contact info or the company's own site.
  Never guess one.
- **The note** (the user's rules, 2026-10-29):
  - **At most 300 characters** (LinkedIn's limit), counting spaces and punctuation; aim for
    220-290. Count with code (`len()` in Python or `.length` in JS), never by eye, and put the
    count in the report. Over 300: shorten the opening or the ask first, never the role or an
    achievement's facts.
  - **TWO achievements**, the two that best fit the posting and the person, joined in one sentence
    so it reads like a person talking, not a list. Keep each one's facts and numbers word for word
    (15K, 800+, 3 engineers, "AI-native"); only the joining words and the tense may change ("I lead
    a backend team of 3 engineers and built an AWS event-driven system handling 800+ concurrent
    jobs."). Never two that say the same thing.

    | Achievement | Best fit |
    | --- | --- |
    | **Scale:** Helped scale a platform to 15K users. | Product, startups, scalability |
    | **AI delivery:** Built AI-native workflows to ship features and fixes daily. | AI-first, fast-paced teams |
    | **AWS:** Built an AWS event-driven system handling 800+ concurrent jobs. | Backend, cloud, distributed systems |
    | **Leadership:** Lead a backend team of 3 engineers. | Lead and senior roles |

  - **The template for the person's group** ([Achievements] is the one sentence above). These
    are a starting shape, not a script: reword so it reads naturally for this person and job, but
    keep the parts (who you are writing to, the role, the two achievements, one easy ask).
    - CEO / hiring manager: "Hi [Name], I just applied for the [Role] role at [Company].
      [Achievements] I'd love to hear what your team is building next and how I could help."
    - HR / recruiter: "Hi [Name], I just applied for the [Role] role at [Company]. [Achievements]
      Would you be open to a quick chat about it?"
    - Engineer / team lead: "Hey [Name], I just applied for the [Role] role at [Company].
      [Achievements] I'd love to hear what it's like on your team from someone on the inside." If
      it fits, name their team or work instead of the general line.
    - Agency recruiter (only for an agency-posted job, see above): "Hi [Name], I'm a backend
      developer and team lead looking at [role/location] roles. [Achievements] Happy to connect if
      you're hiring for something similar."
    - Example (286 characters, long names on purpose): "Hi Alexandra, I just applied for the
      Senior Backend Engineer role at Wayve Technologies. I've built AI-native workflows to ship
      features and fixes daily, and an AWS event-driven system handling 800+ concurrent jobs. I'd
      love to hear what your team is building next and how I could help."
  - A real shared link may go in when it fits ("Fellow AUB alum."). Details about the person only
    from their profile; never invent an achievement or a detail about them. Never ask for a
    referral. Tone: confident, human, direct; no stiff lines like "I'd love to discuss how I could
    contribute to your team".
- Nobody found in any group: note "no LinkedIn contact" and the searches you tried.

## At the end

Report one line per job: company, role, grade, where you applied (the URL of the tab left open), CV
used (mirrored or not; if mirrored, the posting's must-haves the profile doesn't have, so the user
can add any that are true), salary entered and anything you guessed. Under it, its one LinkedIn contact: name, title, profile
URL, group and why (the company size for a CEO, the link to the user if any), email if public, and
the note ready to paste with its character count.

Then, in the chat answer itself (not only in a file), **why you skipped each job**: every job you
pressed Skip on in this run, whether you looked at its form or not, one short line each with the
company, the role and the reason in plain words, quoting the posting's own words when there are
any. Group them like this (the user's request, 2026-10-31):

- **Can't hire you from Lebanon:** location or visa rules. "**Corgi**, Full Stack: London on-site,
  and the posting says "Visa Sponsorship: Not available"."
- **Closed or gone:** "**IP STUDIOS**, Senior web developer: closed on LinkedIn a day after
  posting, no other copy anywhere."
- **Not your kind of role (my call, move back any you disagree with):** the posting's main work
  is outside the target roles, or it is far too senior. "**Canonical**: despite the title, it's
  a Jira administrator job."

The user then goes through the open tabs and presses Apply, and sends the LinkedIn notes themselves.
