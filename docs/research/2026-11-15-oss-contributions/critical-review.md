# Critical review

The independent reviewer's report, lightly edited: only references to local working files were
removed. The reviewer did none of the earlier work. It got the plans, the trial fixes and the raw
research, but not the ranking, and was told to try to kill each candidate and to re-check
everything live.

**How it was used.** Its verdicts were applied as given: [issues-ranked.md](issues-ranked.md)
follows its order, [effort-and-tests.md](effort-and-tests.md) uses its numbers, and
[contribution-plans.md](contribution-plans.md) includes its corrections (one opik PR instead of
three; the pydantic-ai guard does not fix the reported setup; fastmcp, pydantic-ai and mlflow killed
for now, each with the condition that would revive it). Two facts were re-checked by hand before
publishing: agent-framework's `license/cla` check, and phoenix's REST router having only a GET route.

Reviewed 2026-11-15, 00:11-00:45 UTC. Final live re-check of all 10 issues at 00:35 UTC: all
unchanged since the first pass. Read-only GitHub calls only; nothing was posted, forked,
starred, assigned or labeled. People are named by role only.

## 1. Verdict table

| # | Issue | Verdict | Value 1-5 | Merge odds | Effort h | One-line reason |
|---|---|---|---|---|---|---|
| 1 | opik #8134 (answer_relevance only) | **READY** | 2 | 45% | 3.5 | Free, gate met, repro and spike re-verified; but it is a prompt-template edit plus tests, and the 2 open slices of this issue have had no human review for 14-16 days. |
| 4 | agent-framework #10286 | **NEEDS FIRST STEP**: issue comment (design + AI disclosure), then wait for `ready-for-implementation` | 4 | 25% | 10 | Real, reproduced agent-memory bug; the fix adds API to a base class, which the repo's rules say needs agreement first. |
| 6 | adk-python #6361 | **NEEDS FIRST STEP**: issue comment to the reporter + design check; fallback: wait until 2026-12-12 | 3 | 30% | 9 | Bug still on main today; maintainers named the design; ADK lands outside telemetry fixes; the reporter's claim is the blocker. |
| 5 | strands harness-sdk #3156 | **NEEDS FIRST STEP**: issue comment asking if an outside PR is welcome | 4 | 25% | 12-14 | Best technical fit (asyncio concurrency); some port issues were closed by contributor PRs, but this one sits in a member's design EPIC and the last outside PR died after a month of review. |
| 8 | phoenix #12266 | **NEEDS FIRST STEP**: short "picking this up" issue comment with the one design question, then the PR | 2 | 30% | 4 | Low value (a small REST route), but a first-time outsider's sibling slice (#15561) merged in 4 days this way; the repo's "no feature contributions" text and a staff refactor of delete rules are the risks. |
| 3 | fastmcp #3998 | **KILL** | 3 | 15% | 2.5 (spike done) | For now: `release/3.x` is a maintainers' lane (35 of 37 merges there from members/collaborators, verified live); a collaborator closed an earlier outside attempt on this exact issue. |
| 7 | mlflow #25790 | **KILL** | 3 | 15% | 5 | For now (on the watch list): the bot closes any PR not from the assignee (the reporter), who holds a full fix (#25791) they may reopen; two reassignment asks in this repo are unanswered after 18 and 59 days (verified live). |
| 2 | pydantic-ai #6552 | **KILL** | 3 | 10% | 7 + wait | The planned guard does not fix the report (plain OpenAI provider), its advice also fails on vLLM per the reporter, 4 staff assignees, staff are doing the Groq twin right now. |

Survivors: 1 READY, 4 NEEDS FIRST STEP (one of them, phoenix, low value). Realistic outcome from this list: 1-2
merged PRs in 4-6 weeks.

## 2. Per issue

### 1. comet-ml/opik #8134 (defect 2, `answer_relevance` slice): READY

**Live status (00:12 UTC):** open; 0 assignees; labels Bug, Python-SDK; 8 comments, last 2026-09-18; no closing PRs
(GraphQL `closedByPullRequestsReferences` empty). Open slices: #9317 (Python moderation/factuality/usefulness,
outside author, opened 10-30, only a bot review, policy bot stale warning 11-10) and #9325 (TypeScript copies,
opened 11-01 by the same outside contributor who wrote the merged slices #8195 and #8379, only bot reviews).
No PR or comment names `answer_relevance`, `syc_eval` or `trajectory_accuracy` as taken. The fix files have no
commit on `main` since 11-04 (before the planner's clone at 5ea60d2).

**Attacks and what each found**
- *Already fixed?* No. Re-run at a clean copy of main@5ea60d2 (spike reverted, import path checked):
  `10 failed`.
- *Raced?* No claim today. But two people are positioned to take it: the slicing contributor (still active in
  opik, PRs on 10-28 and 11-01 merged in 2-3 days) mapped these exact judges on 09-17 and asked maintainers how to
  split them; no maintainer ever answered. #9317's author said these three "each read better as its own diff".
- *Will maintainers want it?* Mixed. Opik merges outside SDK fixes fast: of the fork PRs titled `[SDK] fix` closed
  since 10-15, 25 merged: 13 within 5 days, the rest in 1-9 weeks. But the two open #8134 slices have waited 14-16 days with no
  human review, while the same contributor's *other* PRs merged in days. So this specific issue is low priority
  for the maintainers right now. In its favor: slow opik PRs still merge in the end (#8197 after 45 days, #8404
  after 42, #7960 after 63), as long as the author keeps answering, since the policy bot closes a PR 14 days
  after an unanswered review. I lowered the planner's "medium-high" to 45%.
- *Is the plan right?* Yes. The spike re-runs: repro 4 pass / 6 fail (the 6 are the other two judges, as
  expected); the spike's 20 new tests fail on clean main and pass with the fix; 251 nearby tests pass; ruff 0.14.14
  check and format clean. Not run by anyone: mypy (the pre-commit hook runs it).
- *Low value?* Yes, mostly. The source change is about 18 lines of prompt-string edits that copy a pattern
  already merged 4 times. The interview story ("prompt-injection hardening of LLM judges") is real but thin.
  It earns a quick, credible first merge in an eval tool, not a showcase.
- *First step right?* Yes: the gate is "a tracked issue", already met. `CLA.md` has no bot; it says agreement
  comes with submitting, so the user should read it before the PR (part of approving the PR, no separate step).

**Plan corrections**
- Do **one** PR (`answer_relevance`), not a plan of three. Only consider `syc_eval` (the one with real design
  content) after this one gets a human review. A queue of three unreviewed slices from one person helps no one.
- Add the 2 missing named tests the planner listed, and run mypy before opening.
- Merge odds: 45%, not "medium-high". Time box: 4 h of work; give up if no human review 21 days after opening
  (answer every bot finding within 14 days, or the policy bot closes it).

### 2. pydantic/pydantic-ai #6552: KILL

**Live status (00:12 UTC):** open; 4 staff assignees (since 10-13); labels bug, tools, needs-maintainer-discussion,
openai, output, p:3-mid; 4 comments, last 07-23; no closing PRs. #12667 (Groq version of the same guard): open,
approved twice, comments posted "on behalf of" one of #6552's staff assignees, who is deciding its details.
No PR in the newest 100 (all opened since 11-13 00:39 UTC) mentions vLLM or #6552.

**Attacks and what each found**
- *Is the plan right?* No, in two ways the planner half-noted:
  1. The reporter's script uses the plain `OpenAIProvider(base_url=...)`. The guard only fires for `VLLMProvider`,
     so the reported case is **not fixed**. Measured: the planner's repro with only the provider swapped to
     `OpenAIProvider`, run against the spiked clone, still sends tools plus `json_schema`, makes 0 tool calls,
     raises nothing and returns the made-up answer. `Closes #6552` would be wrong.
  2. The error tells users to switch to `ToolOutput(...)`. On 07-23 the reporter showed that on vLLM this also
     fails for them (tool choice "required" blocks thinking). So the guard's advice is misleading on the one
     server it targets. The real fix is the maintainers' bigger design question (#2793: constrain only the final
     message), which explains the discussion label.
- *Gate:* CONTRIBUTING (lines 14, 41, 60): a maintainer must agree and assign before a PR; unassigned PRs are
  closed by `pr-guard.yml`. The issue already has 4 staff assignees.
- *Signals over time:* the discussion label was added by the triage bot on 07-16, before a maintainer's
  "PR welcome" on 07-22. But the newer signal is the 4 staff assignees on 10-13, and staff are shipping the Groq
  twin (#12667) themselves now.
- *Re-run:* matches the planner. Clean main@5552d3a: 1 request with tools and `json_schema`, 0 tool calls, no
  error. Spike: 0 requests, `UserError`. Not run: pyright on my side,
  the complexity check, the public-API check, the 100% coverage gate.

Verdict: KILL. Revive only if a maintainer posts a decided direction on the issue and offers assignment.

### 3. PrefectHQ/fastmcp #3998: KILL (for now)

**Live status (00:12 UTC):** open; 0 assignees; labels bug, client; 2 comments (last: a collaborator's scoping
note, 10-29); all 4 linked PRs closed. No commit on `release/3.x` touching the client or telemetry since 10-15.
#6432 (a collaborator's 3.x backport) still open since 11-10.

**Attacks and what each found**
- *Maintenance branch:* of the 37 PRs ever merged into `release/3.x`, 35 came from members or collaborators and 2
  from other roles (a backport and an integration, both in July); verified live today. No outside PR was closed into it
  since 10-15.
- *Maintainer stance on this very issue:* outside PR #4146 was closed by a collaborator quoting "An open issue is
  not an invitation to submit a PR". Outside PR #6172 got only bot replies in a week; its author closed it.
- *Policy detail to record:* the planner says unassigned linked PRs are closed until assignment; the bot on #6172
  (10-30) said linked PRs "stay open while maintainers triage". The policy may have changed in between. Either
  way the PR cannot merge without a maintainer assigning the user, and I found no case of that on 3.x.
- *Is the plan right?* Yes, and well done. Re-run on a clean copy of release/3.x@9dc7191: `17 failed, 6 passed`;
  with the spike: `23 passed`; nearby telemetry tests `80 passed`; ruff, ruff format and ty clean. The `params=` route (keeps the SDK's tool-schema cache) is the right call.

Verdict: KILL for now, because nothing shows a parked PR gets a maintainer's answer here. The spike is done, so
it is the cheapest item to revive (about 2.5 h) if a maintainer assigns it or asks for a PR.

### 4. microsoft/agent-framework #10286: NEEDS FIRST STEP (issue comment)

**Live status (00:12 UTC):** open; 1 assignee (set by the routing bot); labels python, triage, reproduced, harness;
1 comment (the bot's offline repro, 11-12); no closing PRs. Open fork PRs #10370 (edits `_harness/_loop.py`) and
#10359 (rewrites `FileHistoryProvider.save_messages`): neither is by the reporter, neither fixes this. No commit on
`_loop.py` since 11-10.

**Attacks and what each found**
- *Gate:* CONTRIBUTING (lines 75-90, added 10-08, tightened 11-04): non-trivial changes need the
  `ready-for-implementation` label or an explicit maintainer OK; "assignment, reactions and silence do not
  indicate approval"; and "DON'T make new APIs without filing an issue and discussing with us first". The
  planned option 1 adds two public methods to `HistoryProvider`, so this gate fully applies.
- *Will the gate get answered?* The label is used a lot (at least 25 issues in about two weeks), but since the
  gate began on 10-08 only 2 of 9 reproduced harness issues got it. The closest precedent, #9817 (same middleware, has the label), has fork PR #9818 open
  and unmerged since 10-29. Most merged harness fork PRs I found (#9547, #9294, #9032, #7289, #7242) predate the
  11-04 rule change.
- *Staff doing it themselves?* Possible: the harness owner is assigned. I could not tell staff from outsiders among
  fork authors (private org membership).
- *Plan:* sound. Option 1 (rewind hook) with option 5 (narrow the promise + warn) as fallback is the right pair.
  The repro was not re-run (not one of the four I was asked to re-run); the bot's own repro on the issue
  matches it.
- *Effort:* 8.5 h is optimistic for a newcomer: uv 0.13.7 pin, two write paths, two rebases. Say 10 h.

### 5. strands-agents/harness-sdk #3156: NEEDS FIRST STEP (issue comment)

**Live status (00:12 UTC):** open; 0 assignees; labels enhancement, python, area-multiagent, port; 0 comments;
only closing PR #3448 is closed. EPIC #5673 (member, label `design`): 0 comments, no assignee; lists #3156 in phase 1.

**Attacks and what each found**
- *Will maintainers want an outside PR?* Unclear, but more open than it first looks. In the same EPIC the team
  gave #5670 the `ready for contribution` label and not #3156. But that label is rare on port issues (1 of 49),
  and of the 9 closed port issues with a closing PR, 5 were closed by fork PRs from accounts GitHub shows as
  CONTRIBUTOR (likely outsiders; private org membership can hide staff), mostly without the label. Against:
  the EPIC may fold it into a redesign, two accounts self-assigned and dropped it (Sep-Oct), and the last
  outside PR (#3448) went through about a month of reviews before its author closed it.
- *Code moved?* `graph.py` changed 5 times since 10-15 (latest 10-28, interrupt/resume fixes), all before the
  planner's clone. Draft #5476 (collaborator) also edits `graph.py`: merge-conflict risk.
- *Plan:* sound and well scoped (per-batch semaphore, waiting nodes stay `DISPATCHED`). The resume claim is read
  from code, not run; the planned resume test must prove it.
- *Value:* the best technical story on this list. *Effort:* 11 h is realistic only without a long review;
  budget 12-14 h.

Do not write code until a maintainer says yes or adds `ready for contribution`.

### 6. google/adk-python #6361: NEEDS FIRST STEP (comment to the reporter + design check)

**Live status (00:12 UTC):** open; 2 assignees (triage); labels tracing, needs review; 6 comments, last 07-27;
closing PR #6362 (the reporter's) closed 10-28 over the CLA; not reopened. Main head today is d05e482, the same
commit the planner used. The silent `except (ImportError, AttributeError): pass` is still at `tracing.py` line
1237 on main. No PR mentions `user.id`, the event-only key or the issue.

**Attacks and what each found**
- *Do outside telemetry fixes land?* Yes. They show as "closed", not "merged" (internal import), but two outside
  telemetry PRs closed on 11-13 match two commits on main that day ("trace sub-agents by the model they inherit",
  "mask credential material in the telemetry serializer").
- *Claimed?* The reporter's PR was closed only over the CLA, with an invitation to reopen. The reporter's last
  activity there was 10-16. Their claim is fading, not gone.
- *Will the comment get answered?* Likely: collaborators answered the reporter in this thread and on the PR
  (07-13, 07-27, 09-30, 10-17, 10-28).
- *Plan:* sound; option 1 (env var through `TelemetryConfig`, default = today's behavior, one warning) matches the
  collaborator's own request. Watch the default: a privacy switch invites naming debates; plan 2 review rounds.

### 7. mlflow/mlflow #25790: KILL (for now; watch)

**Live status (00:12 UTC):** open; labels area/tracing, ready; 1 assignee = the reporter (assigned 09-18);
3 comments, last 09-18. Only closing PR: #25791 (the reporter's, bot-closed 09-11 for the then-missing `ready`
label: "feel free to reopen"). The reporter has no other mlflow activity. Open PR #27773 (outside, 11-14,
no review) now edits the same stream loops.

**Attacks and what each found**
- *Re-run (first ever run of the planner's script):* at master@23690c5, 6 of 6 early-stop cases export no trace and
  stay in memory. The bug is real and costly (lost traces + a leak).
- *Does #27773 fix it?* Only partly. With its head (b16b811) dropped into a copy of master, only "cancelled while
  waiting for a chunk" is fixed; 5 of 6 still leak. The `yield` sits in the
  `else:` branch, outside the `try`, so `except BaseException` never sees `GeneratorExit`. But #27773 could grow to
  cover it: a commenter already pushed it once.
- *Gate:* `auto-close-pr.js` (lines 257-265) closes any PR whose linked issue is assigned to someone else. So the
  user needs a reassignment first.
- *Will a reassignment ask be answered?* Two reassignment requests in this repo are still the last comment on
  their issues, unanswered for 18 days (#24140, asked 10-28) and 59 days (#23953, asked 09-17); verified live.
- *Value of taking it over:* the reporter's closed PR (+44/-25 in `fluent.py`, +78 tests) is a full public fix. A
  new PR would look derivative; reviewers may just ask to reopen #25791.

Verdict: KILL as a pick now. Watch it (section 3).

### 8. Arize-ai/phoenix #12266: NEEDS FIRST STEP (short issue comment, then the PR)

**Live status (00:12 UTC):** open; 0 assignees; labels enhancement, c/server, size:S (added 11-07); 0 comments;
no PRs. The router file `routers/v1/custom_model_providers.py` (150 lines, GET only) has no commit since 09-02.
Staff PR #17776 (106 files, base `version-online-evals`, has conflicts) rewrites the custom-provider mutations.

**Attacks and what each found**
- *Repo rules:* CONTRIBUTING line 5: "We are not actively accepting feature contributions right now." Line 43:
  "An open issue is not an invitation to submit a PR. ... please wait for explicit confirmation from a maintainer."
  This text dates from a rewrite on 2026-03-17 (later commits only touched tooling lines).
- *But the precedent cuts the other way:* the sibling slice (#12263, GET `/model_providers`) was taken by a
  first-time outside contributor who posted "Picking this up" with two design questions on 08-20, opened #15561
  on 08-21 (from a fork, CLA signed through the bot) and was merged on 08-24, after the policy text existed.
  Meanwhile an outsider who only *asked* to take sibling #12270 (07-27, 08-08) got no answer (stage 2). So the
  rule is not enforced for roadmap slices the maintainers filed themselves, and "announce + design question +
  quick PR" is the path that worked.
- *Real design question:* on `main` the GraphQL delete is a plain `sa.delete(...)` with no reference check, while
  the issue asks to "confirm no dangling references", and staff PR #17776 adds a decision-reference guard to the
  delete on another branch. The comment should ask which behavior the REST route must follow (and whether a
  missing id is 404, which the GraphQL mutation does not do today).
- *Value:* low (2). A small FastAPI route with admin and lock checks, tests and regenerated OpenAPI/client files
  (the GET slice was +1,377 lines across 14 files, mostly generated). Fine for a backend profile, not a showcase.
- The planner's shell hung, so there is no fix plan or repro; effort (4 h) is my estimate from the GET slice.

## 3. "Taken" confirmed; watch-list picks

**strands-agents/harness-sdk #6160: taken (by a pending fix).** #6160: open, 0 comments, no linked PR. PR #4967 is
still open (review required, last update 11-10). Its diff wraps `stream()` in `AsyncExitStack` and registers
`cleanup.push_async_callback(_close_response_stream, response)` on every call, so the response is closed on
every path. A second PR would duplicate it. Free again only if #4967 closes unmerged.

**deepset-ai/haystack #13753: taken, now twice.** New since stage 3: open PR #13756 (opened 2026-11-14 23:45 UTC,
`closes #13753`, by a third person, not the reporter; CLA not yet signed); the bot then assigned a maintainer.
Plus the reporter's offer in the issue body. Dead for us.

**Watch-list picks** (status re-checked today at about 00:30 UTC):

| Pick | Why it fits | Re-check on | Free when |
|---|---|---|---|
| strands harness-sdk #4896 (MCPClient.load_tools race) | async bug, agent tooling | 2026-11-19 | the 10-05 claim comment still has no PR and no maintainer reply (open, 0 assignees, last update 10-08) |
| inspect_ai #5211 (agent bridge drops Responses logprobs) | evals, `accepted` label already set | 2026-11-23 | PR #5219 still has no commit after 10-09 and the "changes requested" is unanswered |
| mlflow #23953 (AgentServer blocks the event loop) | async server, strong fit | 2026-12-01 | a maintainer unassigns the dormant assignee and the 09-17 requester does not take it |
| logfire #1737 (Anthropic thinking not captured) | LLM observability | 2026-11-30 | the 118-day-old draft is still untouched and a maintainer says what "properly" means |
| mlflow #25790 (this list, #7) | real tracing bug, repro ready | 2026-12-01 | the reporter is unassigned or says they are done; and #27773 has not grown to cover `GeneratorExit` |

## 4. Approved sequence

1. **First (this week): opik #8134 `answer_relevance`.** The only item that needs no one's permission. Steps: read
   `CLA.md`, add the 2 missing named tests, run `make precommit` (incl. mypy), write the PR in the user's words with
   the `AI-WATERMARK` block, open as a draft per CONTRIBUTING. Time box: 4 h. Give up: no human review 21 days after
   opening. Do not open a second slice until this one gets a human review.
2. **In parallel, the same day, three short comments** (each needs the user's OK; answers take days):
   - agent-framework #10286: design proposal (rewind hook, fallback: narrow the promise), with AI disclosure.
   - adk-python #6361: ask the reporter if they will reopen; ask maintainers to confirm the env-var design.
   - strands #3156: ask if an outside PR is welcome now or if the team does it inside the EPIC.
   - Optional, lowest priority: phoenix #12266, a "picking this up" note with the delete-rules question (the path
     #15561 took). If no one objects in 3 days, open the PR (4 h box); drop it if a maintainer points at #17776.
   Write no code for these until a "yes". Give up on each after 14 days of silence (agent-framework says silence is
   not approval). For adk, if the reporter stays silent, re-ask maintainers on 2026-12-12.
3. **When answers come, code in this order:** agent-framework (highest value, repro done; 10 h box), then adk (9 h),
   then strands (14 h box; stop if review passes 3 rounds without convergence). One open PR per repo at a time.
4. **Re-check dates:** 2026-11-19 (strands #4896), 2026-11-23 (inspect_ai #5211), 2026-11-30 (logfire #1737),
   2026-12-01 (mlflow #23953 and #25790), 2026-12-12 (adk claim).

## 5. Strategy suggestions (suggestions, not picks)

- **Announce, don't ask.** In phoenix, an outsider who only asked to take a roadmap slice got silence, while one
  who posted "picking this up" plus design questions and opened the PR the next day was merged in 4 days. One data
  point, but it matches how the busiest outside contributors in opik work. Never do this where a bot enforces
  assignment (pydantic-ai, fastmcp, mlflow).
- **Find your own bugs and send issue + PR together.** In opik, most merged outside SDK fixes are pairs like
  "[issue-NNNN] fix ..." where the same person filed the issue and the PR within a day (about half merged within
  5 days). The race does not apply to a bug only you have found. Use the tools as a user: streaming, early stop, cancellation,
  timeouts, retries. That is exactly the class of bugs on this list (mlflow generators, strands stream close,
  fastmcp context).
- **Choose repos whose gate actually gets answered.** Good: opik (tracked-issue gate), agent-framework (bot repro +
  frequent `ready-for-implementation`), mlflow (`ready` label) when unassigned. Be careful with: phoenix (says it
  is not accepting features, though it merged an outsider's roadmap slice), fastmcp `release/3.x` (maintainers' lane), pydantic-ai issues with staff assignees.
- **Be early, not thorough.** Issues here get a PR within hours to days. Watch new `reproduced` issues in
  agent-framework and new `ready` issues in mlflow daily; post a short design comment the same day.
- **Go deep in 1-2 repos.** The opik slicing contributor got about 10 PRs merged by staying in one repo; known
  names get faster reviews and get invited to take follow-ups.
- **Look for named leftovers.** "This covers half; the other half remains" notes in merged PRs (for example the
  kafka-python consumer half in opentelemetry-python-contrib #4871) are pre-approved work that few people see.
- **Don't polish before the gate.** Keep spikes small until a maintainer says yes; this list shows how often the
  gate, not the code, decides the outcome.

## 6. What would change my mind

- **opik:** a maintainer reviews #9317 or #9325, or answers the slicing question → odds up to about 60%. A PR for
  `answer_relevance` from the slicing contributor or #9317's author → KILL.
- **agent-framework:** `ready-for-implementation` added → go. A PR from the harness owner → KILL.
- **adk:** the reporter says they will continue → KILL. The reporter steps aside and a maintainer confirms the design
  → go.
- **strands:** `ready for contribution` added or a member says yes → go. A member links a PR → KILL.
- **fastmcp:** a maintainer assigns an outsider on 3.x, or asks for a PR on this issue → revive (2.5 h).
- **mlflow:** the reporter is unassigned or releases it → go, crediting #25791. #27773 grows to handle the consumer
  stopping early → dead.
- **pydantic-ai:** a maintainer posts a decided direction (guard vs final-message-only output) and offers
  assignment → revive, but rewrite the error advice and the "Closes" line.
- **phoenix:** a maintainer says to wait for #17776, or a staff PR appears for the custom-provider CRUD routes
  → KILL. A maintainer answers the design question → go (and consider POST #12264 and PATCH #12265 next, which
  carry more substance: encrypted credentials).

## Method and what was not run

- Live status of all 10 issues (issue, timeline, comments, closing PRs) at 00:12 UTC, re-checked at
  00:35 UTC with no changes; the newest PRs per repo; competing PRs; recent commits on the files each
  fix would touch; what happened to recent outside PRs in the same areas (counted only from fork
  PRs, because private org membership hides some staff).
- Re-runs, in a sandbox with no keys and a hard time limit: opik, pydantic-ai, fastmcp and mlflow,
  each against a clean copy of the default branch and against the planner's trial fix where one
  exists.
- Not run: mypy on the opik trial fix; pyright, the complexity, public-API and coverage checks on the
  pydantic-ai trial fix; full test suites; the agent-framework, adk and strands repros (their status
  and code were re-checked instead).
