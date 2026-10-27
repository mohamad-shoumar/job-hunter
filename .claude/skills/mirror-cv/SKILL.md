---
name: mirror-cv
description: Mirror one job posting's own words in that job's tailored CV - put the posting's terms first in the skills rows, bring the bullets that match its duties to the top (un-hiding cut ones), and use its spelling where it means the same thing - without adding any fact the profile doesn't have. Use when the user says "mirror", "mirroring", "match the posting's wording" or "make the CV fit this job better" for a job in the app.
---

# Mirror a job posting in its tailored CV

**What mirroring is:** recruiters skim a CV for a few seconds and ATS filters (the software that
screens CVs) look for the posting's words. Many don't count synonyms. So where you really have
what the posting asks for, say it in the posting's words and in the places a skimmer reads first:
the headline, the start of each skills row, and the first bullets of the newest role.

It is not keyword stuffing. Mirroring changes order, picks which true lines print, and swaps a
word for the posting's spelling of the same thing. It never adds a fact.

## Rules (never break these)

- Facts come only from `profile/master_profile.md` (in `~/job-hunter`, not in git). A posting
  term the profile doesn't have is a **gap**: list it in the report, never add it. That goes for
  things that seem implied too ("FastAPI" doesn't mean you may write "Pydantic"). Only the user
  adds it to the profile.
- The `## Summary` paragraph is the user's own words: never touch it.
- Never shorten a bullet or cut a clause, number or "estimated". Keep the `**bold**`. A swap
  replaces at most two words with the posting's words for the same thing ("Postgres" ->
  "PostgreSQL"), never a new technology, number, title or claim. `check_version` judges a swap
  by the profile's own words, so a spelling the profile doesn't use is blocked ("RESTful APIs"
  -> "REST APIs" fails): keep the profile's word and list the posting's as a gap.
- Certifications always print (the profile says so): never hide one.
- No keyword lists, hidden text or extra lines made of posting words. Each term appears where it
  is true, at most about three times on the CV.
- This file is tracked: never paste profile text, contact details or salary into it.

## Steps

1. **Find the job and its CV.** In `~/job-hunter`:
   `sqlite3 data/jobs.sqlite "select title, company, description from jobs where id=<id>"` and
   `sqlite3 data/jobs.sqlite "select cv_tailored_json from applications where job_id=<id>"`.
   That JSON gives the version file (`source`, under `resume/`), the page count, `notes` (which
   bullets were "Cut to fit one page"), `tags` (why optional bullets matched) and `gaps` (terms
   the tailoring step already found missing). No tailored CV yet? Press **Tailor CV to this job**
   in the app first.
2. **List the posting's terms**, most important first:
   - stack: languages, frameworks, databases, cloud (usually a "tech stack" or "requirements" part)
   - kinds of work: "serverless", "event-driven", "multi-service", "tests and observability"
   - duties, in the posting's words: "design safe, deterministic workflows", "review code",
     "investigate a production issue"
   Leave out perks, company history and soft words the Summary already covers.
3. **Sort each term into one of three groups** by reading the profile:
   - **Have, same word**: move it forward (below).
   - **Have, different word for the same thing** ("Postgres" / "PostgreSQL", "AWS Lambda" /
     "serverless functions"): use the posting's word only if it means exactly the same thing.
     If unsure, keep the profile's word.
   - **Not in the profile**: a gap. Report it.
4. **Edit the version file** (`resume/versions/<name>.md`). First `cp <file> <file>.bak`.
   - **Headline** (`title:`): the app already uses the posting's title. Leave it.
   - **Skills rows**: reorder each row so the posting's terms come first, in the order the
     posting gives them. Push unrelated items to the end of the row.
   - **Bullets**: within each role, sort by how many posting terms and duties a bullet matches.
     The newest role's first two bullets matter most.
   - **Cut bullets** (lines starting with `// `): un-hide one if it matches a main duty of the
     posting. Lines whose tags didn't match this job (`// [fullstack] ...`) stay hidden.
   - **Page count**: the app keeps CVs to one page. A long bullet can take 3 printed lines, so
     un-hiding one can need two or three lines out. Make room by hiding (`// `) the printed
     bullets that match the fewest posting terms (often a trading-only feature, or "Standardized
     the local development workflow"). Never hide the newest role's first bullet, a role's only
     bullet, or a certification. Name every hidden line in the report. The user can undo from
     the `.bak`.
5. **Rebuild** from `~/job-hunter`: `.venv/bin/jobhunter rebuild-cv <id>` (no model, just the
   PDF). It prints the page count ("(1 page)" or "2 pages ... cut a line").
   - To see what spilled onto page 2, save this as `p.swift` in the scratchpad and run
     `swift p.swift <pdf>`:
     `import PDFKit; let d = PDFDocument(url: URL(fileURLWithPath: CommandLine.arguments[1]))!; for i in 0..<d.pageCount { print("=== page \(i+1)"); print(d.page(at: i)!.string ?? "") }`
   - Check the file against the profile. This must print `[]`:
     `.venv/bin/python -c "from pathlib import Path; from jobhunter.cv import check_version; print(check_version(Path('resume/versions/<name>.md').read_text(), Path('profile/master_profile.md')))"`
     Each line it lists says more than the profile. Undo that change.
6. **Already uploaded?** If an application form in Chrome already has this CV, upload the
   rebuilt PDF again (same file name). The form holds the old copy. To check it took, compare
   `input.files[0].size` on the page with `stat -f %z <pdf>`.

## Report

- A table: posting term -> where it is on the CV now (skills row, which bullet), or "gap".
- The gap list, so the user can add any that are true to the profile.
- Bullets you un-hid or hid, page count, and whether you uploaded it again.
