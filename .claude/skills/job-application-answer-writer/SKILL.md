---
name: job-application-answer-writer
description: Answer one written job application question ("Why this company?", "Tell us about yourself", "How do you use AI coding agents?") from the job description and the tailored CV.
---

# Job application answer writer

Give Claude these three things and let it answer:

1. **The job description** (the posting's full text).
2. **The CV**: this job's tailored CV (`~/job-hunter/resume/versions/<name>.md`), else `~/job-hunter/resume/resume.md`.
3. **The question**, with its word or character limit if the form shows one.

Then: "Answer this question for this job, from this CV."

Then, before using the answer, run it through the `humanizer:humanizer` skill in embedded mode
(it returns only the final text), so it doesn't read like AI wrote it (the user's call,
2026-11-20). Humanizer may reorder, cut and reword, but the profile rule still wins: it must not
add a fact, skill, number or detail that isn't in the CV, even where it asks for "a specific
detail". Keep the form's word or character limit. If the humanizer plugin isn't installed, skip
this step and note it.
