# Issues ranked

Open-source issues worth a PR for an applied AI / backend profile, ranked. Status as of 2026-11-15
(every link re-checked just before publishing; see the end). Nothing was posted anywhere: every
public step below needs your OK.

## The main point

- **1 issue is ready to start today, 4 need a public first step, 3 were killed for now, 2 turned
  out to be taken**, and there is a dated watch list.
- **"5 achievable PRs" does not exist today as "5 ready to start".** In all 19 repos searched, a
  real, confirmed bug usually got a PR within hours to 3 days, often from its own reporter. The
  honest list is 1 ready plus 4 that depend on a maintainer's answer. Expect 1-2 merged PRs from it
  in 4-6 weeks.
- **The best long-term route is a suggestion, not a pick:** find your own bugs while using these
  tools (streaming, stopping early, cancellation, timeouts, retries) and send the issue and the PR
  together. Nobody races you to a bug only you have found. More in
  [critical-review.md](critical-review.md), section 5.

## The ranked list

| # | Issue | What the PR does | First step (needs your OK) | Value 1-5 | Odds | Work |
|---|---|---|---|---|---|---|
| 1 | [opik #8134](https://github.com/comet-ml/opik/issues/8134) | Protect the `answer_relevance` LLM judge from prompt injection by the output it grades | None: the PR itself | 2 | 45% | 3.5 h |
| 2 | [agent-framework #10286](https://github.com/microsoft/agent-framework/issues/10286) | Make an agent loop's "fresh context" really reset file-backed chat history | Comment proposing the design | 4 | 25% | 10 h |
| 3 | [adk-python #6361](https://github.com/google/adk-python/issues/6361) | Stop silently dropping `user.id` from GenAI telemetry; add a privacy switch | Comment asking the reporter, or wait until 2026-12-12 | 3 | 30% | 9 h |
| 4 | [strands #3156](https://github.com/strands-agents/harness-sdk/issues/3156) | Cap how many multi-agent Graph nodes run at once (asyncio semaphore) | Comment asking if an outside PR is welcome | 4 | 25% | 12-14 h |
| 5 | [phoenix #12266](https://github.com/Arize-ai/phoenix/issues/12266) | REST route to delete a custom model provider (optional) | "Picking this up" comment with one design question | 2 | 30% | 4 h |

Value, odds and hours are the independent reviewer's. "Odds" means the chance the PR is merged
if you do the work. Plans are in [contribution-plans.md](contribution-plans.md); costs and tests
are in [effort-and-tests.md](effort-and-tests.md).

### 1. opik #8134: ready now

- **Why first:** the only item that needs nobody's permission. The gate is "a tracked issue", already
  met. The bug was reproduced, and a trial fix passed 20 new tests plus the 231 existing ones around
  it.
- **Why only 45%:** the two other open slices of this same issue have waited 14-16 days with no human
  review. Slow opik PRs do still merge (after 42-63 days) if the author keeps answering.
- **Why value 2:** it is a prompt-template edit plus tests, copying a pattern already merged four
  times. It earns a quick, credible first merge in an eval tool, not a showcase.
- **Changes the verdict:** a maintainer reviewing the other slices (odds up to about 60%), or someone
  else opening a PR for `answer_relevance` (dead).

### 2. agent-framework #10286: needs a design comment

- **Why second:** a real agent-memory bug (stale tool results leak between "fresh" passes),
  reproduced with the repo's own fake model, in a repo that merged 410 outside PRs in 60 days.
- **Why only 25%:** the fix adds two public methods to a base class, and the repo's rules say new
  APIs need agreement first. Since that rule started, only 2 of 9 reproduced harness issues got the
  `ready-for-implementation` label. The package owner is assigned and could do it.
- **Changes the verdict:** the label is added (go), or the package owner opens a PR (dead).

### 3. adk-python #6361: needs a word with the reporter

- **Why third:** the maintainers named the design themselves (an opt-in env var), the bug is still on
  `main`, and outside telemetry fixes land here.
- **What blocks it:** the reporter's PR was closed only over an unsigned CLA, with an invitation to
  come back, so their claim lapses only around 2026-12-12.
- **Changes the verdict:** the reporter says they'll continue (dead), or steps aside and a maintainer
  confirms the design (go).

### 4. strands #3156: needs a "welcome"

- **Why fourth:** the best technical story (asyncio concurrency control in a multi-agent
  orchestrator), but the most uncertain.
- **What blocks it:** it sits in a team member's `design` epic; two accounts picked it up and dropped
  it; the last outside PR went through a month of reviews before its author closed it.
- **Changes the verdict:** a member says yes or adds `ready for contribution` (go), or a member links a
  PR (dead).

### 5. phoenix #12266: optional, last

- **Why it's on the list:** a sibling slice from a first-time outside contributor merged in 4 days by
  posting "picking this up" with design questions and opening the PR the next day.
- **Why last:** low value (a small REST route); the repo says "We are not actively accepting feature
  contributions right now"; a large staff PR is reworking custom providers.
- **Changes the verdict:** a maintainer says to wait for the staff PR (dead), or answers the design
  question (go).

## Killed for now

| Issue | Why killed | Revives if |
|---|---|---|
| [fastmcp #3998](https://github.com/PrefectHQ/fastmcp/issues/3998) | `release/3.x` is the maintainers' lane: 35 of 37 merges there are theirs, and a collaborator closed an earlier outside PR on this exact issue | a maintainer assigns it or asks for a PR; then it's the cheapest item (about 2.5 h, trial fix done) |
| [pydantic-ai #6552](https://github.com/pydantic/pydantic-ai/issues/6552) | the planned guard doesn't fix the reporter's setup (checked by running it); 4 staff assignees; staff are shipping the same guard for Groq | a maintainer posts a decided direction and offers assignment |
| [mlflow #25790](https://github.com/mlflow/mlflow/issues/25790) | assigned to its reporter, and mlflow's bot closes PRs from anyone else; the reporter's closed PR is already a full fix | the reporter is unassigned or says they're done (re-check 2026-12-01) |

## Taken

- [strands #6160](https://github.com/strands-agents/harness-sdk/issues/6160): open PR #4967 already
  fixes it, and a team member is reviewing it.
- [haystack #13753](https://github.com/deepset-ai/haystack/issues/13753): the reporter offered a fix,
  and a third person has since opened PR #13756.

## Watch list

| Re-check on | Issue | Why it fits | Free when |
|---|---|---|---|
| 2026-11-19 | [strands #4896](https://github.com/strands-agents/harness-sdk/issues/4896) | async race in MCP tool loading | the October claim still has no PR and no maintainer reply |
| 2026-11-23 | [inspect_ai #5211](https://github.com/UKGovernmentBEIS/inspect_ai/issues/5211) | evals; already `accepted` | its PR still has no commit after 2026-10-09 and the requested changes are unanswered |
| 2026-11-30 | [logfire #1737](https://github.com/pydantic/logfire/issues/1737) | LLM observability (Anthropic extended thinking) | the 118-day-old draft PR is still untouched and a maintainer says what "properly" means |
| 2026-12-01 | [mlflow #23953](https://github.com/mlflow/mlflow/issues/23953) | an agent server that blocks its event loop (async, health checks) | a maintainer unassigns the dormant assignee and the September requester doesn't take it |
| 2026-12-01 | [mlflow #25790](https://github.com/mlflow/mlflow/issues/25790) | traces lost when a stream is stopped early (reproduced) | as in "Killed for now" |
| 2026-12-12 | [mlflow #27012](https://github.com/mlflow/mlflow/issues/27012) | a stale cached prompt served when the registry is down (fallback logic) | the reporter, assigned on 2026-10-28, still has no PR |
| 2026-12-12 | [adk-python #6361](https://github.com/google/adk-python/issues/6361) | item 3 | the reporter's claim lapses |

## Considered and rejected

How wide the search was: 55 repos measured, 19 searched for issues, over 1,000 issues read with their
comments, 14 candidates written up, 10 taken into planning, 8 planned and reviewed. The closest misses:

- [logfire #2549](https://github.com/pydantic/logfire/issues/2549): Anthropic streaming calls record
  no output or cost. Can't start until another open PR (#2548) merges; no maintainer reply.
- [temporal #438](https://github.com/temporalio/sdk-python/issues/438): untouched for 3 years, needs a
  design decision, and building the repo needs a Rust toolchain even for a Python change.
- [litellm #33434](https://github.com/BerriAI/litellm/issues/33434): an SSO role bug; litellm wants
  live proof, which needs a Microsoft Entra tenant.
- [qdrant-client #948](https://github.com/qdrant/qdrant-client/issues/948): client timeouts; no
  maintainer agreed it is a bug.
- [phoenix #12049](https://github.com/Arize-ai/phoenix/issues/12049): set aside for students in a
  course.

Everything else was claimed, already fixed, already had a PR, needed a paid key or cloud account,
was docs-only, or needed a design discussion first. Repo-level reasons are in [repos.md](repos.md).

## How this list was built

1. **Repos** ([repos.md](repos.md)): 55 AI/LLM repos measured from GitHub's own data. Which ones
   merge outside PRs, how fast, and what their contribution rules say (gates, CLAs, AI policies).
2. **Issues:** four analysts searched the best 19 repos for open, unclaimed, real bugs whose fix is
   code plus a test and can be reproduced with no paid key and no Docker.
3. **Plans** ([contribution-plans.md](contribution-plans.md)): each candidate was re-checked, and 7 of
   the 8 were reproduced at a named commit. The phoenix one is a missing feature, and its planner's
   shell hung before a plan was run. Three got a short trial fix to test the plan.
4. **Review** ([critical-review.md](critical-review.md)): a separate reviewer, who did none of the
   earlier work, tried to kill each candidate and re-ran four reproductions. Its verdicts set this
   order.

All GitHub access was read-only. Repository code ran in a sandbox with no API keys and no access to
real credentials.

## Last check

All 20 issue links in these files were re-checked on 2026-11-15 at 00:50 UTC (state, assignees,
linked and cross-referenced PRs, latest comment). All were open, and none had a new PR, assignee or
claim since the review.
