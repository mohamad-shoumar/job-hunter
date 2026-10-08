---
name: apply-job
description: Work through the "To apply" column of the jobhunter app in Chrome - get a checked tailored CV, fill the job's application form on the company site or in LinkedIn Easy Apply, draft the outreach email - and stop before the final Apply/Submit and Send. Use when the user says "apply to my jobs", "go through To apply", or names a job to apply to.
---

# Apply to jobs from the "To apply" column

Runs in the user's real Chrome through Claude in Chrome (`mcp__claude-in-chrome__*`; read the
`claude-in-chrome` skill first). The goal is to be **autonomous**: never stop the whole run on one
question, one field or one stuck page. Make a sensible choice, note it, keep going.

## Two hard stops (the only things you never do)

1. **Never press the final Apply / Submit / Send application button.** Fill everything, scroll to it,
   leave the tab open for the user to press it.
2. **Never press Send on an email** in the app. Draft it and leave it. (CLAUDE.md: emails go out
   only from the user's own click on Send.)

Everything else (uploading the CV, answering questions, clicking Next between form pages, Tailor CV,
Find contact, Write with AI) you do without asking.

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
   jobs the user hasn't applied to yet. Do them one at a time, top to bottom (or only the job the
   user named).

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
  `resume/output/`), note it for the report and keep going. Don't hand-edit the CV.
- The PDF is already on disk in `~/job-hunter/resume/output/`, so upload it from there. Press
  **Download ↓** too if the user wants a copy in Downloads.

### 2. Find the real application page
- Press **Open posting ↗**.
- If the posting is behind a sign-in or paywall (We Work Remotely always is), don't sign in and
  don't pay. Search for the same role on the company's own careers page or its job board (Greenhouse,
  Lever, Ashby, Workable, BambooHR, LinkedIn) and apply there. Match the title, and the location if
  one is given.
- If the role can't be found anywhere or is closed, note that for the report and move to the next job.
  Don't change the job's stage.
- If the company can't hire from Lebanon (residence required in another country, US-only), skip it
  and say so in the report. If the user wants that company never shortlisted again, add it to
  `blocked_companies` in `config/filters.json` with a short `why`, then run
  `.venv/bin/jobhunter reclassify`.

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
  (3,000 - 3,500), languages English only (the profile's languages line is TODO), visa No,
  gender and community "Prefer not to say/answer", disability left empty, privacy box ticked.
- **LinkedIn Easy Apply** (the user is already signed in to LinkedIn in Chrome):
  - Use it only when the LinkedIn job page shows an **Easy Apply** button. A plain **Apply** button
    goes to the company site: follow it and fill that form instead.
  - Never sign in, type a password, or edit the user's LinkedIn profile. If LinkedIn asks to sign
    in or shows a security check, stop on that job, note it and move on.
  - Go slowly, like a person: one job at a time, no browsing or scraping lists of jobs, and at most
    10 Easy Apply forms per run. LinkedIn forbids automation and can restrict the account, so if
    it shows any "unusual activity" warning, stop all LinkedIn work for the run and say so in the report.
  - **Contact info:** check the email and phone against `MY_*` in `.env`; fix them if they differ.
  - **Resume:** press **Upload resume** and upload the tailored PDF (use the stand-in method above if
    the file box is hidden). Make sure the tailored file is the one selected, not an older resume.
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
  - **Location / time zone / notice:** from the profile's "Work authorization and logistics" section.
  - **Disability, medical needs, accommodations or adjustments:** No / none needed.
  - **Gender, race, veteran and other voluntary questions:** "Prefer not to say" / "Decline to
    self-identify" when that option exists.
  - **How did you hear about us:** the site the job came from (the job's source in the app), or
    "Job board".
  - **Expected salary:** do a quick web search for what this company pays for this role and level
    (Levels.fyi, Glassdoor, the posting's own range). Ask for a bit below the usual figure, but
    never below the "Salary floor" line in the profile. Use the form's currency and period (monthly
    or yearly). If nothing turns up, use the floor plus about 10%.
  - **Code sample / project you're proud of / portfolio link:** https://github.com/mohamad-shoumar/job-hunter
    If the form also asks why (or "tell us about it"), use this, as the user wrote it:
    "A job-search tool I built that uses Claude to tailor my CV. The rule is that the model may
    reword my experience, but code decides what's true. check_bullet compares each AI rewrite to
    the original bullet and rejects any new number, technology, seniority word or name, with a
    readable reason for each. I'm proud of it because it makes an AI feature trustworthy without
    trusting the AI."
  - **Open questions** ("Why this role?", "A feature you're proud of", "Tell us about a challenge"):
    write 3-6 confident sentences built on the best-matching CV bullet for this posting. Tie it to
    what the company does, and don't make up anything that isn't in the CV.
- **Unsure about a field?** Pick the most reasonable answer, note it for the report, keep going.
- **Stuck?** If a page freezes, an upload fails or a button doesn't respond, reload and try again
  (up to 2 retries per step). If it still fails, leave the tab as it is, note it and go to the next
  job. Never stop the whole run because of one job.
- **CAPTCHA or account sign-up:** don't solve or create it (Claude may not create accounts or type
  passwords, even with permission). Fill what you can, leave the tab open and note it for the user.
  Proxify ("Get paid, not played" postings, often re-posted on job boards) always needs a talent
  account, so the user does those.
- Finish at the final **Apply/Submit** button. Don't press it. Leave the tab open.

### 4. Email draft
- Back in the app, on the job's card: if there's no contact, press **Find contact**. Then press
  **Write with AI** (or **Fill template**) to draft the email. The app's own rules and checks
  (`pitch.py`, `check_draft`) write and check it.
- If the draft shows "needs edit" warnings, leave them for the user. **Don't press Send.**
- If no contact can be found, still draft the email so it's ready, and note "no contact".

## At the end

Report one line per job: company, role, where you applied (the URL of the tab left open), CV used,
salary entered, anything you guessed or skipped, and the email status (drafted / no contact /
needs edit). The user then goes through the open tabs and presses Apply, and presses Send in the app.
