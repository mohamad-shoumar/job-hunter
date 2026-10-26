# Contributing

## Setup

```sh
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
cp .env.example .env
cp profile/master_profile.example.md profile/master_profile.md
cp resume/resume.example.md resume/resume.md
```

The `dev` extra holds the web app's packages, pytest and ruff. The copied files hold made-up details. Your
real profile, CV and `.env` are ignored by git; keep names, contact details, pay and the like out of every
tracked file.

## Tests and lint

```sh
.venv/bin/pytest
.venv/bin/ruff check .
```

CI (`.github/workflows/ci.yml`) runs both on Python 3.11 and 3.12 for every push and pull request.

Tests never call Hunter, Claude, DeepSeek or Gmail, and need no key. A new source needs a test against a
trimmed real response in `tests/fixtures/`. After changing `config/filters.json` or a rule, run
`.venv/bin/jobhunter reclassify` so stored jobs are judged again.

## Commits

- One change per commit.
- Subject: imperative, 72 characters at most ("Reject postings that offer a 401(k)").
- Body: why the change was made, and anything a reviewer could not tell from the diff.

## Decisions

Choices about how jobs are judged, what the models may do, and how email is sent are recorded in
[docs/decisions.md](docs/decisions.md). Add a record there when you make one, and keep
[`.claude/CLAUDE.md`](.claude/CLAUDE.md) (the same rules, written for coding agents) in step.
