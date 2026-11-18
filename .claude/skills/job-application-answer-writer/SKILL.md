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
