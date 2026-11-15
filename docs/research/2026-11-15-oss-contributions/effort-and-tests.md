# Effort and tests

How much work each contribution is, what it costs per merged PR, and how to test it. The numbers in
the table are the independent reviewer's (see [critical-review.md](critical-review.md)); the
planners' own estimates were a little lower.

## The numbers

"Effort per expected merge" = hours of work ÷ merge odds. It is the measure that matters here:
5 hours at 50% costs 10 hours per merged PR, while 10 hours at 20% costs 50. It leaves out the
waiting for maintainers and the time to write comments.

| # | Issue | Verdict | Value (1-5) | Merge odds | Work (h) | Per expected merge (h) | Waiting before any code |
|---|---|---|---|---|---|---|---|
| 1 | opik #8134 (`answer_relevance`) | ready | 2 | 45% | 3.5 | about 8 | none |
| 2 | agent-framework #10286 | first step | 4 | 25% | 10 | about 40 | a maintainer's OK (`ready-for-implementation`) |
| 3 | adk-python #6361 | first step | 3 | 30% | 9 | about 30 | the reporter's answer, or 2026-12-12 |
| 4 | strands #3156 | first step | 4 | 25% | 12-14 | about 52 | a maintainer's "welcome" |
| 5 | phoenix #12266 (optional) | first step | 2 | 30% | 4 | about 13 | about 3 days after a "picking this up" note |
| - | fastmcp #3998 | killed | 3 | 15% | 2.5 (trial fix done) | about 17 | a maintainer assigning you |
| - | mlflow #25790 | killed | 3 | 15% | 5 | about 33 | a reassignment |
| - | pydantic-ai #6552 | killed | 3 | 10% | 7 | about 70 | a decided direction from a maintainer |

What the table says:

- **All five survivors together:** about 40 hours of work for about 1.5 expected merges, so about
  25 hours per merged PR. The reviewer expects 1-2 merged PRs from this list in 4-6 weeks.
- **opik is the cheapest merge but the least impressive** (a prompt-template edit plus tests).
  agent-framework and strands are the strongest engineering stories, at 5 to 7 times the cost per
  merge.
- **The wait, not the code, decides the timeline.** Four of five need a maintainer's answer first,
  and in these repos an answer takes days and sometimes never comes. That is why the first-step
  comments should go out on the same day (see the sequence in [critical-review.md](critical-review.md)).

## Setup on this kind of machine

- No paid API key, cloud account or Docker was needed for any reproduction or trial fix: fake
  models, mock servers and in-memory trace exporters only.
- Several repos need Python 3.12 or 3.13 tooling (the local default was 3.14), and some pin tools:
  agent-framework pins uv 0.13.7, strands uses hatch, fastmcp uses prek.
- Run outside code without your real credentials in reach. Example: strands and langchain-aws can
  call Amazon Bedrock, so a stray test could make billed AWS calls if `~/.aws` is visible. The
  planners ran everything with an empty environment and a fake home folder.

## 1. opik #8134

- **Effort:** setup 0.5, repro 0.25, fix 0.5, tests 1, PR write-up and CI 0.75, review rounds 1 =
  **about 4 h** (the reviewer says 3.5). The next two judges, only after a human review of this one:
  `trajectory_accuracy` 3.25 h, `syc_eval` 5.25 h.
- **Setup:** in `sdks/python`: `uv venv --python 3.12`, then
  `uv pip install -e . -r tests/test_requirements.txt` (about 3 minutes).
- **Run:** `pytest tests/unit/evaluation/metrics/llm_judges -q` (231 tests, about 10 seconds), then
  `make precommit` from the repo root (ruff, ruff-format, mypy).
- **New tests:** `tests/unit/evaluation/metrics/llm_judges/test_answer_relevance_sut_output_isolation.py`,
  modeled on the merged `test_context_metric_sut_output_isolation.py` (not on #9317's file: a review
  bot found two weak checks there). Parametrized over the two builders:
  - each value is inside its own namespaced tag;
  - every value arrives byte for byte (JSON, XML, braces, inner and edge newlines);
  - a forged verdict stays inside the output section (compare the whole section, not `value in text`,
    which can pass on the tag's own closer);
  - `{0}` and `{braces}` are not rewritten;
  - the system prompt names exactly the tags the user message uses;
  - a valid XML answer still parses; the framing and few-shot examples are unchanged.
- **CI the PR must pass:** unit tests on Python 3.10-3.14; pre-commit (ruff 0.14.14, ruff-format,
  mypy 1.19.1, a secret scan); a title check (`[issue-8134] [SDK] fix: ...`); body sections
  `## Details`, `## Change checklist`, `## Issues`, `## Testing`, `## Documentation`; the AI disclosure
  block. Policy bots: at most 3 open PRs, and every review-bot finding needs an answer within 14 days.
  A maintainer may have to approve CI runs for a fork PR (inferred, not confirmed).
- **Not run locally:** the integration tests that call real models; maintainers run them.

## 2. agent-framework #10286

- **Effort:** setup 0.5, repro 0.5, fix 2.5, tests 2, PR write-up and CI 1, review rounds 2 = 8.5 h by
  the planner; **10 h** by the reviewer (the uv pin, two write paths, likely two rebases).
- **Setup:** install uv 0.13.7 (the repo's `required-version`), then `uv run poe setup` (about
  30 minutes the first time). For a quick look, a plain venv with
  `pip install -e packages/core pytest pytest-asyncio` works in under a minute.
- **Run:** `uv run poe test -P core`, or in `python/packages/core`:
  `pytest tests/core/test_harness_loop.py tests/core/test_sessions.py` (299 tests, under a second).
- **New tests:**
  - in `tests/core/test_harness_loop.py`: file history resets between passes (streamed and not; JSON
    Lines and MessagePack), with one turn saved before the loop so "wipe the file" would fail;
  - the file keeps the pre-loop turn and only the final pass;
  - a pass still sees its own tool calls on the per-service-call write path;
  - a warning for history providers without a checkpoint;
  - in `tests/core/test_sessions.py`: checkpoint/restore cuts the tail and keeps the head
    byte-identical, on both formats.
- **CI the PR must pass:** pre-commit hooks; pyright per package; mypy, pyrefly and ty on tests; tests
  on Python 3.11-3.15; 85% coverage on enforced modules; a public-API compatibility check (adding
  methods with defaults should pass; confirm in CI); the Microsoft CLA (`license/cla`). The PR
  template needs `Fixes #10286` and its "AI Assistance" section filled in.

## 3. adk-python #6361

- **Effort:** setup 0.5, repro 0.5, fix 2, tests 2, docs 0.5, PR write-up and CI 1, review rounds 2 =
  8.5 h by the planner; **9 h** by the reviewer. Outside PRs here take a median of 9 days to land.
- **Setup:** the repo's way is `uv sync --all-extras` (heavy). For a quick look:
  `pip install -e . -c constraints-3.12.txt pytest pytest-asyncio pytest-mock pytest-xdist opentelemetry-instrumentation-google-genai mcp`.
- **Run:** `pytest tests/unittests/telemetry` (the two main files: 360 tests, about 2 seconds).
- **New tests:**
  - env-var parsing (unset, each value, lowercase, spaces, invalid);
  - precedence (per-request value, env var, admin lock; fixed at construction);
  - where `user.id` lands for each setting, on ADK's own spans and through the instrumentation
    (in-memory exporters);
  - the warning fires once;
  - the golden files must not change under the default.
- **CI the PR must pass:** pre-commit (ruff, isort, pyink, license header, docs checks and more); mypy
  on Python 3.11-3.13 with no new errors; unit tests on 3.11-3.14; the Google CLA, with the commit
  email matching the CLA account. The PR lands through Copybara, so GitHub shows it as "Closed", not
  "Merged", but the commit on `main` keeps you as its author.

## 4. strands #3156

- **Effort:** setup 0.5, repro 0.5, fix 2, tests 3, PR write-up, docs and CI 1.5, review rounds 3.5 =
  11 h by the planner; **12-14 h** by the reviewer. The earlier attempt took 4+ review rounds over a
  month. Stop if the review passes 3 rounds without converging.
- **Setup:** `hatch` from `strands-py/` (the repo's way). Without hatch: a uv venv with
  `pip install -e '.[otel]' pytest pytest-asyncio pytest-timeout pytest-xdist moto` (about 2 minutes).
- **Run:** `hatch test tests/strands/multiagent/test_graph.py` (101 tests, about 2 seconds).
  Integration tests need AWS: skip them locally; CI runs them after a maintainer allows it.
- **New tests:**
  - cap 2 on a fan-out of 6 peaks at 2; no cap peaks at 6;
  - bad values are rejected (0, -1, 1.5, `True`, "2");
  - a node that waits longer than `node_timeout` for a slot still completes (use the earlier PR's
    deterministic, semaphore-gated version: a time-based one failed on Windows there);
  - slots are freed after a failure or timeout;
  - resume does not re-run nodes.
- **CI the PR must pass:** `hatch test --cover` on Python 3.10-3.14 (Linux, Windows) and macOS; an
  MCP 1.x compatibility job; `hatch fmt --check`; an API-break check (griffe); a Conventional Commits
  title (for example `feat(graph): cap concurrent nodes with max_concurrency`); Codecov. No CLA. The
  PR template's "Human Overview" must be written by you, not by an AI.

## 5. phoenix #12266 (optional)

- **Effort:** about **4 h** (the reviewer's estimate from the merged GET slice, #15561). No plan was
  run for it: the planner's shell hung.
- **Check before starting:** how the server tests run (whether they need Postgres or run on SQLite),
  and how the OpenAPI schema and generated client files are rebuilt. The GET slice's PR shows the
  pattern (+1,377 lines in 14 files, mostly generated).
- **New tests:** delete works for an admin; refused without rights or when the server is locked;
  404 for an unknown id (if the maintainers agree); the reference rule the maintainers choose.
- **CI:** the repo's CLA bot; the rest follows the GET slice.

## Killed items, if they revive

- **fastmcp #3998:** about 2.5 h left (the trial fix is done). Run
  `uv run pytest tests/client/telemetry tests/telemetry -n 0` on `release/3.x`, plus the same with
  `--with mcp==1.24.0` (the oldest allowed SDK); `uv run prek run --files <changed files>`. CI adds
  Windows, a lowest-dependency run, MCP conformance tests (need Node) and a 232K-schema crash test.
- **mlflow #25790:** about 5 h. Tests: each early-stop path (break after the first chunk, `close()`,
  cancel while waiting, an error in the consumer) for sync and async generators ends the span once,
  keeps the partial outputs and closes the inner generator. Every commit needs a DCO sign-off
  (`git commit -s`).
- **pydantic-ai #6552:** about 7 h plus setup. Its full install (every provider SDK and torch) did not
  finish in 8 minutes here; `uv sync --frozen --group lint` is enough to work on it. The coverage gate
  is 100%.
