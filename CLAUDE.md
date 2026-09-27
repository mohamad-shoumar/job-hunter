# Notes for agents working on this project

- `profile/master_profile.md` is the only source of facts about the user. Generated CVs, cover letters and application answers may reorder, emphasize, rephrase and remove, and must NEVER add a skill, technology, employer, title, date, responsibility, achievement or metric that is not in that file. `TODO` entries are unknown: leave them out.
- Deterministic code decides filtering, dedup and eligibility, and every verdict carries a quotable reason. LLM judgment belongs only on jobs with status `needs_review` (eligibility `unclear`). Do not replace a rule that quotes evidence with a guess.
- The LLM step is `ai_check.py` (Claude + web search). It changes a status only when its quote is found word for word in the description or a page the API fetched (`find_quote`); `classify.apply_ai_check` combines it with the rules, and results live in `jobs.ai_check_json` so `reclassify` keeps them.
- A source's "no location given" is unknown, never "Worldwide" (Himalayas shows "Worldwide" for US-only roles).
- The SQLite DB (`data/jobs.sqlite`) is the memory; Markdown reports are output only. Rejected jobs stay stored on purpose, so they never reappear as new.
- Reports are `reports/<YYYY-MM-DD>.md`, one per day, rendered from `jobs.report_date` (see `store.py`); there is no `latest.md` or run-numbered file. A date-range run (`--from/--to`) fetches once and files jobs by posting day.
- After changing `config/filters.json` or the rules, run `.venv/bin/jobhunter reclassify`.
- Tests: `.venv/bin/pytest`. A new source = a module in `src/jobhunter/sources/` with `from_config()`, an entry in `BUILDERS`, and a test against a trimmed real response in `tests/fixtures/`.
- Error lines go through `sources.base.describe_error`, which drops query strings, so the SerpApi key never reaches logs or reports. The `httpx` logger stays at WARNING for the same reason.
