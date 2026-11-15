# Repos: where outside PRs actually get merged

Measured on 2026-11-14 with read-only GitHub calls; nothing was posted anywhere. This file decides
where contribution time should go. The issues picked in these repos are in
[issues-ranked.md](issues-ranked.md).

## The main point

- **Stars don't tell you who merges outside work.** Of 55 AI/LLM repos measured, 14 merge outside
  PRs well: 30+ in the last 60 days, about half or more of the outside PRs they close get merged,
  and the median wait is 10 days or less. Several famous repos barely merge any.
- **LangChain and LangGraph are poor bets right now.** In those 60 days `langchain` merged 11
  outside PRs (2% of the outside PRs it closed) and `langgraph` 2 (0%). Their bots close PRs from
  anyone not assigned to the issue first. The LangChain repo that does merge outside work is
  `langchain-aws`: 43 merged, 69%, median 1.4 days.
- **Some repos are closed to outsiders.** `openai-agents-python`: "We do not accept pull requests
  from non-collaborators". `letta` says its code is archived.
- **Check the gate before writing any code.** Several good repos close a PR unread unless the
  issue was approved first: `inspect_ai` needs the `accepted` label, `agent-framework` needs the
  `ready-for-implementation` label or a maintainer's explicit OK for anything non-trivial,
  `fastmcp` and `pydantic-ai` need you assigned, and `openinference` needs a maintainer's OK.
  Getting past the gate takes a public step (a comment, or in `fastmcp` a PR that its bot parks
  until a maintainer assigns you), so it waits for your OK.
- **AI help is allowed in every repo whose rules were read, but often must be disclosed.**
  `agent-framework`, `inspect_ai` and `opik` ask for it, and `haystack` does when a PR is fully
  AI-generated. `agent-framework` and `temporal` may close PRs that are undisclosed or "entirely
  AI-driven". `litellm` and `promptfoo` forbid Claude credit lines in commits, while `fastmcp`
  wants agents to say who they are. So: understand and own every line, disclose AI help where a
  repo asks, and follow each repo's own attribution rule.
- **A healthy repo is not enough: the issues are raced.** In all 19 repos searched for issues
  (the 15 below, then 4 reserves), a real, confirmed bug usually got a PR within hours to 3 days,
  often from its own reporter, sometimes within a minute of the issue. Maintainers close a second
  PR on a taken issue. What was still free on 2026-11-15 is in [issues-ranked.md](issues-ranked.md).

## How to read the numbers

- "Outside" means not a maintainer. GitHub hides private team membership, so anyone who merged or
  closed someone else's PR is also counted as a maintainer. Without that, `pydantic-ai` would show
  1,996 "outside" merges instead of 105. The number in brackets is GitHub's own label.
- "Merge rate" = outside PRs merged / outside PRs closed (merged or not), in the window.
- "Stale" = an open outside PR, older than 30 days, with no review from a maintainer.
- Window: PRs merged from 2026-09-15 to 2026-11-14. Details are in "Method" at the end.

## Searched for issues: the 15 shortlisted repos, then 4 reserves

The 15 below were searched first. They gave too little, so 4 reserves were searched in a second
round: opentelemetry-python-contrib, mlflow, promptfoo and phoenix (dbos was not, because its
tests need a Postgres server). In that round, contrib turned out to have moved its GenAI
instrumentation to a new repo, opentelemetry-python-genai ("Do not add instrumentations here, and do not fix bugs or add
features to the ones that remain"), and promptfoo had an open PR on 42 of 45 issues checked.

Numbers: outside PRs merged in 60 days, share of closed outside PRs that were merged, median days to merge, and how many different outside authors (how many of them had exactly one merge: a long tail of one-PR people means a newcomer can get in). TypeScript count: 1 (strands; its main language is TypeScript, but the target would be its Python SDK in `strands-py/`).

### A. Agents / MCP (5)
1. **microsoft/agent-framework** (Python): 410 merged, 71%, 3.0 days, 119 authors (58 with one merge). Non-trivial changes need the `ready-for-implementation` label or a maintainer's explicit OK first (the first read of its rules said "issue first, no assignment"; corrected during the issue search). AI allowed if disclosed. Microsoft CLA (a `license/cla` check). Unit tests need no keys.
2. **google/adk-python** (Python): 395 landed through Copybara, 69%, 9.2 days, 186 authors (121 with one merge). Issue or a clear PR description, CLA. The PR shows "Closed", not "Merged", but the landed commit keeps the contributor as author (checked on #7398).
3. **PrefectHQ/fastmcp** (Python, MCP): 294 merged, 64%, 7.1 days, 111 authors (84 with one merge). Strict gate: you must be assigned to a linked issue, unless the issue has the `prs welcome` label. That label has 0 open issues today, and the guide says not to comment just to ask for assignment. So the realistic path is to report a real bug with a reproduction first: "The issue reporter has first claim on implementing the fix". One outside contributor has 87 merges, so outsiders do get through.
4. **pydantic/pydantic-ai** (Python): 105 merged, 24%, 3.0 days, 71 authors (59 with one merge). The low rate comes from the bot closing PRs that skipped the gate: 263 closes, and of 40 read, 26 were "not assigned" and 11 had no issue link. PRs that pass the gate land in a median of 3 days. Highly relevant (typed agents, providers). Trivial fixes need no issue. The path to assignment is a comment on the issue (later, not in this research). 10 open issues carry `community-backed`.
5. **strands-agents/harness-sdk**, Python SDK only (`strands-py/`): 133 merged, 49%, 3.3 days, 76 authors (55 with one merge). Of those 133, 24 come from one account named like the project's own agent. Counts include PRs to the TypeScript SDK and the docs site. Issue first only for "anything significant". Fits the AWS/Bedrock profile.

### B. RAG / integrations / structured output (5)
6. **docling-project/docling** (Python, document parsing for RAG): 347 merged, 77%, 2.1 days, 151 authors (80 with one merge). No gate, CLA or AI rule found. 3 `good first issue` and 2 `help wanted` issues open. Weak spot: 0 of 20 sampled issues got a maintainer reply within 7 days, so pick issues where the fix is clear without help.
7. **deepset-ai/haystack** (Python): 189 merged, 50%, 5.1 days, 130 authors (99 with one merge, the best long tail). Only 1 open PR at a time for newcomers. CLA. No PRs on issues "handled internally".
8. **qdrant/qdrant-client** (Python, vector DB client): 63 merged, 46%, 3.2 days, 45 authors (36 with one merge). Almost no written rules. Target the `dev` branch. Test setup is unknown; check whether tests need a running Qdrant server (Docker is off here).
9. **langchain-ai/langchain-aws** (Python, Bedrock): 43 merged, 69%, 1.4 days, 23 authors (16 with one merge). No gate or CLA found. Its numbers verdict is "ok" only because 22 of 41 open outside PRs are stale. Strong fit with AWS work. Integration tests call AWS, but mocks are allowed.
10. **BerriAI/litellm** (Python, LLM gateway): 482 merged, 236 authors (196 with one merge, by far the most), 2.3 days. But only 23% of closed outside PRs merge, and 1,660 open outside PRs are stale. CLA. Each PR needs proof from a live proxy, sometimes with real (paid) provider calls. Keep it only for bugs a maintainer has confirmed.

### C. Evals / observability / reliability (5)
11. **UKGovernmentBEIS/inspect_ai** (Python, evals): 157 merged, 60%, 4.8 days, 93 authors (66 with one merge). Hard gate: the issue must carry the `accepted` label, or the PR is auto-closed. 55 open issues carry `accepted` and 8 carry `good first issue`, but on 2026-11-15, 49 of the 55 already had an open PR, and the other 6 were claimed, fixed, deferred or assigned. Agent use must be disclosed.
12. **pydantic/logfire** (Python, observability): 93 merged, 84% (the best rate), 0.9 days (the fastest), 52 authors (38 with one merge). No gate, CLA or AI rule found. 4 `good first issue` issues open.
13. **Arize-ai/openinference** (Python, OpenTelemetry tracing for LLM libraries): 99 merged, 74%, 9.1 days, 49 authors (34 with one merge). You must wait for a maintainer's OK on the issue before starting. CLA by comment. Open now: 3 `good first issue`, 1 `help wanted`, 2 `good student issue`. Many small integration packages mean many separate, contained PRs.
14. **temporalio/sdk-python** (Python, durable workflows, retries): 53 merged, 59%, 2.2 days, 30 authors (20 with one merge). 0 stale outside PRs, and half of sampled issues got a reply within 7 days (median 5 hours). No gate. CLA. AI is fine, but "entirely AI-driven" PRs may be closed. The best fit for queues, retries and idempotency.
15. **comet-ml/opik** (Python SDK, evals and tracing): 127 merged, 64%, 5.0 days, 80% of issues answered within 7 days, 3 stale. Issue first, at most 3 open PRs, CLA, and an AI disclosure block. Caveat: top 5 authors made 60% of the merges.

Reserve (not dropped, left out for balance). **promptfoo/promptfoo** is the first swap-in if fastmcp or pydantic-ai yield no usable issue: TypeScript, 137 merged, 69%, 4.8 days, no gate found. The others: **Arize-ai/phoenix** (89 merged, 54%, 1.6 days; "a good chance we close it or never get to it"; its bot may move your commits to its own PR), **mlflow/mlflow** (197 merged, 53%, but 452 of 678 open outside PRs stale, `ready` label gate, DCO), **dbos-inc/dbos-transact-py** (Postgres-backed workflows, strong fit, but only 18 merged; tests need Postgres on localhost:5432), **open-telemetry/opentelemetry-python-contrib** (73 merged, 72%, but 15.7-day median; 50 `good first issue` open; EasyCLA).

## All 55 repos measured

Window: PRs merged 2026-09-15 to 2026-11-14 (60 days). Bots left out. "Outside" = not a maintainer (see Method, section 5). The first number in "outside merged" also moves people who merged or closed other people's PRs to the maintainer side, because GitHub hides private org membership; the number in brackets uses GitHub's author_association label only (the literal definition).

Verdict (numbers only): good = 30+ outside PRs merged, 45%+ of closed outside PRs merged, median 10 days or less, and not more than half of 20+ open outside PRs stale; poor = under 10 merged or under 20% merged; ok = the rest. Rules (section 2) can change the final pick.

| # | repo | lang | stars | outside merged 60d (by association only) | outsider share | outsider merge rate | median days to merge (outside) | stale outside PRs / open outside PRs | insider reply within 7d (median hours) | verdict (numbers only) |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | microsoft/agent-framework | Python | 14,676 | 410 (416) | 50% | 71% | 3.0 | 65 / 193 | 30% (82h) | good |
| 2 | google/adk-python | Python | 22,217 | 395 (395) | n/a (staff commit internally) | 69% | 9.2 | 63 / 232 | 50% (32h) | good |
| 3 | docling-project/docling | Python | 70,580 | 347 (347) | 74% | 77% | 2.1 | 62 / 242 | 0% (none) | good |
| 4 | PrefectHQ/fastmcp | Python | 28,435 | 294 (294) | 48% | 64% | 7.1 | 9 / 48 | 5% (128h) | good |
| 5 | deepset-ai/haystack | Python | 27,006 | 189 (459) | 37% | 50% | 5.1 | 9 / 57 | 15% (79h) | good |
| 6 | UKGovernmentBEIS/inspect_ai | Python | 3,248 | 157 (159) | 27% | 60% | 4.8 | 8 / 92 | 15% (68h) | good |
| 7 | promptfoo/promptfoo | TypeScript | 27,180 | 137 (663) | 18% | 69% | 4.8 | 93 / 429 | 20% (19h) | good |
| 8 | strands-agents/harness-sdk | TypeScript | 9,209 | 133 (294) | 23% | 49% | 3.3 | 138 / 348 | 10% (56h) | good |
| 9 | comet-ml/opik | Python | 23,416 | 127 (446) | 16% | 64% | 5.0 | 3 / 51 | 80% (63h) | good |
| 10 | Arize-ai/openinference | Python | 1,321 | 99 (256) | 39% | 74% | 9.1 | 25 / 72 | 15% (19h) | good |
| 11 | pydantic/logfire | Python | 4,553 | 93 (206) | 38% | 84% | 0.9 | 16 / 67 | 25% (8h) | good |
| 12 | Arize-ai/phoenix | Python | 12,289 | 89 (435) | 12% | 54% | 1.6 | 44 / 111 | 14% (86h) | good |
| 13 | qdrant/qdrant-client | Python | 1,378 | 63 (63) | 54% | 46% | 3.2 | 30 / 70 | 40% (135h) | good |
| 14 | temporalio/sdk-python | Python | 1,249 | 53 (128) | 38% | 59% | 2.2 | 0 / 7 | 50% (5h) | good |
| 15 | BerriAI/litellm | Python | 63,254 | 482 (2660) | 18% | 23% | 2.3 | 1660 / 2771 | 20% (65h) | ok |
| 16 | mlflow/mlflow | Python | 28,812 | 197 (197) | 34% | 53% | 3.0 | 452 / 678 | 40% (13h) | ok |
| 17 | vercel/ai | TypeScript | 27,947 | 123 (246) | 11% | 24% | 5.8 | 496 / 788 | 10% (5h) | ok |
| 18 | agno-agi/agno | Python | 43,192 | 111 (326) | 27% | 32% | 2.1 | 719 / 789 | 5% (132h) | ok |
| 19 | pydantic/pydantic-ai | Python | 21,209 | 105 (1996) | 5% | 24% | 3.0 | 85 / 213 | 11% (119h) | ok |
| 20 | open-telemetry/opentelemetry-python-contrib | Python | 1,129 | 73 (95) | 66% | 72% | 15.7 | 40 / 143 | 0% (355h) | ok |
| 21 | langfuse/langfuse | TypeScript | 37,429 | 52 (1212) | 3% | 25% | 4.6 | 406 / 555 | 35% (30h) | ok |
| 22 | langchain-ai/langchain-aws | Python | 354 | 43 (52) | 39% | 69% | 1.4 | 22 / 41 | 25% (4h) | ok |
| 23 | stanfordnlp/dspy | Python | 39,053 | 33 (33) | 20% | 24% | 6.6 | 224 / 317 | 10% (1h) | ok |
| 24 | confident-ai/deepeval | Python | 19,479 | 32 (46) | 54% | 53% | 3.8 | 358 / 483 | 0% (none) | ok |
| 25 | langchain-ai/langchainjs | TypeScript | 18,344 | 32 (80) | 25% | 50% | 7.0 | 313 / 446 | 0% (none) | ok |
| 26 | traceloop/openllmetry | Python | 7,536 | 19 (19) | 95% | 46% | 3.6 | 243 / 341 | 0% (none) | ok |
| 27 | dbos-inc/dbos-transact-py | Python | 1,684 | 18 (27) | 32% | 51% | 0.9 | 0 / 2 | 50% (23h) | ok |
| 28 | langfuse/langfuse-python | Python | 514 | 17 (30) | 22% | 36% | 0.7 | 63 / 116 | 25% (129h) | ok |
| 29 | weaviate/weaviate-python-client | Python | 230 | 14 (18) | 36% | 32% | 4.7 | 12 / 19 | 0% (1416h) | ok |
| 30 | crewAIInc/crewAI | Python | 60,896 | 94 (99) | 28% | 11% | 0.8 | 228 / 742 | 0% (none) | poor |
| 31 | mastra-ai/mastra | TypeScript | 29,521 | 67 (1118) | 3% | 18% | 0.6 | 0 / 1 | 15% (25h) | poor |
| 32 | topoteretes/cognee | Python | 33,314 | 39 (255) | 7% | 17% | 0.8 | 150 / 279 | 10% (40h) | poor |
| 33 | openai/openai-agents-python | Python | 30,682 | 35 (568) | 5% | 40% | 8.4 | 0 / 0 | 20% (143h) | poor (rule: no PRs from non-collaborators) |
| 34 | run-llama/llama_index | Python | 52,901 | 27 (32) | 69% | 7% | 4.7 | 516 / 951 | 0% (none) | poor |
| 35 | modelcontextprotocol/typescript-sdk | TypeScript | 13,769 | 21 (29) | 66% | 19% | 21.3 | 193 / 334 | 5% (15h) | poor |
| 36 | mem0ai/mem0 | Python | 68,962 | 18 (47) | 36% | 6% | 36.0 | 346 / 440 | 0% (none) | poor |
| 37 | langchain-ai/langchain | Python | 149,502 | 11 (47) | 6% | 2% | 1.0 | 54 / 75 | 0% (none) | poor |
| 38 | 567-labs/instructor | Python | 14,113 | 9 (9) | 10% | 3% | 20.9 | 0 / 1 | 0% (587h) | poor |
| 39 | NVIDIA-NeMo/Guardrails | Python | 7,495 | 8 (9) | 8% | 73% | 6.7 | 44 / 63 | 20% (84h) | poor |
| 40 | langchain-ai/openevals | Python | 1,253 | 7 (26) | 27% | 78% | 7.2 | 5 / 14 | 5% (838h) | poor |
| 41 | vibrantlabsai/ragas | Python | 16,320 | 6 (6) | 50% | 26% | 84.7 | 236 / 267 | 0% (none) | poor |
| 42 | jd/tenacity | Python | 8,831 | 4 (4) | 36% | 33% | 0.2 | 37 / 64 | 20% (86h) | poor |
| 43 | langchain-ai/langgraphjs | TypeScript | 3,415 | 4 (192) | 2% | 8% | 3.5 | 41 / 129 | 0% (none) | poor |
| 44 | chroma-core/chroma | Rust | 29,684 | 3 (71) | 4% | 6% | 18.0 | 436 / 528 | 0% (none) | poor |
| 45 | langchain-ai/langgraph | Python | 44,961 | 2 (148) | 1% | 0% | 27.6 | 82 / 93 | 0% (none) | poor |
| 46 | openai/openai-agents-js | TypeScript | 4,017 | 1 (505) | 0% | 6% | 10.3 | 0 / 0 | 5% (154h) | poor |
| 47 | pgvector/pgvector-python | Python | 1,545 | 1 (1) | 100% | 14% | 0.0 | 5 / 8 | 85% (8h) | poor |
| 48 | dottxt-ai/outlines | Python | 16,010 | 0 (0) | n/a | 0% | n/a | 80 / 103 | 5% (110h) | poor |
| 49 | guardrails-ai/guardrails | Python | 7,608 | 0 (0) | n/a | 0% | n/a | 25 / 37 | 5% (136h) | poor |
| 50 | huggingface/smolagents | Python | 30,369 | 0 (1) | 0% | 0% | n/a | 496 / 639 | 0% (none) | poor |
| 51 | langchain-ai/agentevals | Python | 759 | 0 (0) | n/a | n/a | n/a | 10 / 11 | 10% (183h) | poor |
| 52 | langchain-ai/langchain-postgres | Python | 281 | 0 (0) | 0% | n/a | n/a | 42 / 53 | 10% (62h) | poor |
| 53 | letta-ai/letta | n/a | 25,438 | 0 (0) | 0% | n/a | n/a | 0 / 0 | 0% (177h) | poor |
| 54 | microsoft/graphrag | Python | 36,646 | 0 (5) | 0% | 0% | n/a | 29 / 29 | 0% (none) | poor |
| 55 | modelcontextprotocol/python-sdk | Python | 24,861 | 0 (23) | 0% | 0% | n/a | 43 / 58 | 0% (none) | poor |

## Contribution rules (26 repos read)

How to read this: "Gate" = what must happen before a PR is reviewed. "Bot closes" = what the repo's bot wrote when it closed outside PRs in the window (read from the PR comments with GraphQL). "None found" means none in the saved files (CONTRIBUTING, PR template, AGENTS/CLAUDE, AI policy), not proof there is none. Quotes are copied as written. Docker is not running on the test machine; Python 3.12-3.14 are there.

**microsoft/agent-framework** (Python)
- Gate: an agreed issue first. "Except for trivial changes, create or reuse an issue before starting implementation." ([CONTRIBUTING.md#L66](https://github.com/microsoft/agent-framework/blob/main/CONTRIBUTING.md#L66)), and for non-trivial changes: "Wait for a maintainer to add the `ready-for-implementation` label or explicitly comment that the proposed direction is ready for implementation." and "Automated triage, issue assignment, reactions, and silence do not indicate approval." ([#L75-L85](https://github.com/microsoft/agent-framework/blob/main/CONTRIBUTING.md#L75-L85)). CLA: yes. The files read don't mention it, but a `license/cla` check runs on outside PRs (seen on #10359).
- AI: allowed, must be disclosed: "AI tools may be used to prepare contributions to Microsoft Agent Framework. Their use does not lower the project's quality bar, transfer responsibility to the tool, or create an entitlement to review or acceptance." and "Disclose material AI assistance in the issue or pull request description." ([AI_CONTRIBUTIONS.md#L3](https://github.com/microsoft/agent-framework/blob/main/AI_CONTRIBUTIONS.md#L3), [#L27](https://github.com/microsoft/agent-framework/blob/main/AI_CONTRIBUTIONS.md#L27)). Breaking it costs the PR: "Contributions may be closed without detailed review when they do not follow this policy or the Contribution Guidelines. This includes undisclosed material AI assistance, unverified generated content, speculative changes without an agreed issue, and repeated low-quality or high-volume submissions." ([#L114](https://github.com/microsoft/agent-framework/blob/main/AI_CONTRIBUTIONS.md#L114)).
- Tests: "Unit tests: `uv run poe test -A -m "not integration"`"; "Integration tests: ... (requires API keys/endpoints)" ([CONTRIBUTING.md#L269](https://github.com/microsoft/agent-framework/blob/main/CONTRIBUTING.md#L269)). Unit tests need no keys.

**google/adk-python** (Python)
- Gate: "All PRs, other than small documentation or typo fixes, should have an Issue associated. If a relevant issue doesn't exist, please create one first or you may instead describe the bug or feature directly within the PR" ([CONTRIBUTING.md#L72](https://github.com/google/adk-python/blob/main/CONTRIBUTING.md#L72)). No assignment rule.
- CLA: yes, "Contributions to this project must be accompanied by a Contributor License Agreement (CLA)." ([#L24](https://github.com/google/adk-python/blob/main/CONTRIBUTING.md#L24)).
- How PRs land: "GitHub shows that as a *closed* pull request rather than a merged one, and your change appears on `main` as a separate commit." ([#L53](https://github.com/google/adk-python/blob/main/CONTRIBUTING.md#L53)). Checked: PR #7398 was closed by the project bot ("successfully imported and merged via Copybara in commit f67cc35"), and that commit's author is the PR author. So the PR page says "Closed", but the commit is the contributor's.
- AI: only "This repo includes built-in skills for AI coding agents" ([#L267](https://github.com/google/adk-python/blob/main/CONTRIBUTING.md#L267)); no ban or disclosure rule found. Tests: `pytest`, "`tox` with `tox-uv`" ([#L162](https://github.com/google/adk-python/blob/main/CONTRIBUTING.md#L162)); API keys for tests: unknown.

**docling-project/docling** (Python)
- Gate, CLA/DCO, AI rule: none found (AGENTS.md and CLAUDE.md only guide coding agents).
- Tests: "make test           # run pytest" ([AGENTS.md#L50](https://github.com/docling-project/docling/blob/main/AGENTS.md#L50)); output changes need "`DOCLING_GEN_TEST_DATA=1 uv run pytest`" ([CONTRIBUTING.md#L79](https://github.com/docling-project/docling/blob/main/CONTRIBUTING.md#L79)). No keys or Docker mentioned.

**PrefectHQ/fastmcp** (Python)
- Gate: assignment first: "External PRs must link an issue with an auto-close keyword such as `Fixes #123`. The author must also be assigned to that issue, unless it carries the `prs welcome` label. A PR that doesn't meet both conditions is closed automatically." ([docs/development/contributing.mdx#L23](https://github.com/PrefectHQ/fastmcp/blob/main/docs/development/contributing.mdx#L23)). Also "Do not post comments just to claim an issue or ask to be assigned." (#L27). Bot closes: 38 of 40 sampled were this gate, e.g. [#5202](https://github.com/PrefectHQ/fastmcp/pull/5202).
- Not accepted: "Third-party integrations generally belong in a separate package." and "Enhancements need a maintainer-approved design in an issue before implementation." (#L17). CLA: none found.
- AI: "AI assistance is welcome under the same standards as other contributions." (#L43); "Agents NOT acting on behalf of a PrefectHQ maintainer MUST identify themselves" ([AGENTS.md#L140](https://github.com/PrefectHQ/fastmcp/blob/main/AGENTS.md#L140)).
- Tests: `uv sync`, `uv run pytest ...`, `uv run prek run --files ...`; the hooks need the `gitleaks` binary ([AGENTS.md#L41](https://github.com/PrefectHQ/fastmcp/blob/main/AGENTS.md#L41)).

**deepset-ai/haystack** (Python)
- Gate: no issue rule found (whole CONTRIBUTING checked), but "Until your first PR is approved, keep it your only open PR in this repository: additional PRs are closed automatically" ([CONTRIBUTING.md#L28](https://github.com/deepset-ai/haystack/blob/main/CONTRIBUTING.md#L28)) and "Community contributors can have only one open pull request at a time in this repository." ([AGENTS.md#L65](https://github.com/deepset-ai/haystack/blob/main/AGENTS.md#L65)); bot: "First-time contributors can have at most 1 open pull request in this repository until it has been approved" ([#12880](https://github.com/deepset-ai/haystack/pull/12880)).
- Not accepted: "Please do not open pull requests for issues that are marked or commented as handled internally." ([CONTRIBUTING.md#L172](https://github.com/deepset-ai/haystack/blob/main/CONTRIBUTING.md#L172)). CLA: yes ([#L27](https://github.com/deepset-ai/haystack/blob/main/CONTRIBUTING.md#L27)).
- AI: allowed; "If your PR was fully AI-generated, add a short disclaimer in the PR description" ([#L184](https://github.com/deepset-ai/haystack/blob/main/CONTRIBUTING.md#L184)).
- Tests: `hatch run test:unit`; integration: `hatch run test:integration` ([AGENTS.md#L37](https://github.com/deepset-ai/haystack/blob/main/AGENTS.md#L37)).

**UKGovernmentBEIS/inspect_ai** (Python)
- Gate: approved issue first: "Everyone else: start from an issue a maintainer has labeled `accepted` before writing code ... PRs that aren't linked to an accepted issue are closed automatically" ([CONTRIBUTING.md#L13](https://github.com/UKGovernmentBEIS/inspect_ai/blob/main/CONTRIBUTING.md#L13)). Exception: docs-only fixes under 25 lines. All 40 sampled bot closes were this gate, e.g. [#5272](https://github.com/UKGovernmentBEIS/inspect_ai/pull/5272). 8 open `good first issue` issues.
- AI: "disclose agent involvement in the PR description" and run a review "on a strong (frontier-class) model" for non-trivial changes ([AGENTS.md#L59](https://github.com/UKGovernmentBEIS/inspect_ai/blob/main/AGENTS.md#L59)). CLA: none found.
- Tests: `uv sync --locked`, `pytest`, `make check`, `make test`.

**promptfoo/promptfoo** (TypeScript)
- Gate, CLA: none found. AI: "Never attribute commits or PR bodies to Claude / Claude Code." ([AGENTS.md#L246](https://github.com/promptfoo/promptfoo/blob/main/AGENTS.md#L246)): no AI trailers, not a ban.
- Tests: `npm test`, `npm run test:integration`.

**strands-agents/harness-sdk** (monorepo; the Python SDK is `strands-py/`)
- Gate: "Open an issue first for anything significant" ([CONTRIBUTING.md#L244](https://github.com/strands-agents/harness-sdk/blob/main/CONTRIBUTING.md#L244)). CLA: none found.
- AI: welcome, with ownership: "We love AI. We build with coding agents every day, and you're welcome to use them too" and "**you are the author of your pull request, not your agent.**" ([#L237](https://github.com/strands-agents/harness-sdk/blob/main/CONTRIBUTING.md#L237)). The PR template asks you to confirm you understand every line (AGENTS.md#L89).
- Tests: most tests run with no cloud setup: "Most tests do not need it — they run without provisioned infrastructure." ([AGENTS.md#L71](https://github.com/strands-agents/harness-sdk/blob/main/AGENTS.md#L71)); the Python SDK uses hatch.

**comet-ml/opik** (Python SDK; repo also Java and TypeScript)
- Gate: "Open or confirm a tracked issue first (`Fixes #...` or `Resolves #...`)." ([CONTRIBUTING.md#L43](https://github.com/comet-ml/opik/blob/main/CONTRIBUTING.md#L43)); "**Up to 3 open pull requests at a time.**" and "**Respond within 2 weeks of a review.**" (#L53-54).
- CLA: "Please review the CLA before contributing" ([#L13](https://github.com/comet-ml/opik/blob/main/CONTRIBUTING.md#L13)).
- AI: "AI assistance is allowed, but human authors remain accountable for correctness, licensing, and security." ... "Never submit unreviewed AI output." ... "Include the PR template AI watermark/disclosure block when AI is used." ([#L123](https://github.com/comet-ml/opik/blob/main/CONTRIBUTING.md#L123)).
- Tests: the full stack runs in Docker (`./opik.sh`, AGENTS.md#L17); the Python SDK test command is not in the saved files (unknown).

**Arize-ai/openinference** (Python)
- Gate: approval first in practice: "An open issue is not an invitation to submit a PR. Even if an issue is labeled or acknowledged, please wait for explicit confirmation from a maintainer before starting work on it." ([CONTRIBUTING#L40](https://github.com/Arize-ai/openinference/blob/main/CONTRIBUTING#L40)).
- CLA: yes, reply "I have read the CLA Document and I hereby sign the CLA" ([#L140](https://github.com/Arize-ai/openinference/blob/main/CONTRIBUTING#L140)). AI: none found.
- Tests: tox-uv per package; `make lint` ([#L80](https://github.com/Arize-ai/openinference/blob/main/CONTRIBUTING#L80)).

**pydantic/logfire** (Python)
- Gate, CLA, AI rule: none found (CONTRIBUTING is 23 lines of setup).
- Tests: "Run `make test` to run unit tests", "Run `make lint` to lint code" ([CONTRIBUTING.md#L11](https://github.com/pydantic/logfire/blob/main/CONTRIBUTING.md#L11)).

**Arize-ai/phoenix** (Python + TypeScript)
- Gate: "You can still open an issue or PR, but please do so knowing there is a good chance we close it or never get to it." ([CONTRIBUTING.md#L7](https://github.com/Arize-ai/phoenix/blob/main/CONTRIBUTING.md#L7)).
- CLA: yes; bot closes PRs when "the CLA was still unsigned 24 hours after the reminder" ([#14076](https://github.com/Arize-ai/phoenix/pull/14076)). Its bot can also take a PR over: "The factory is finishing this pull request as #17728, on a branch in this repository, because it cannot push to a fork. Your commits and their authorship are kept there" ([#9882](https://github.com/Arize-ai/phoenix/pull/9882)). AI: none found.

**qdrant/qdrant-client** (Python)
- Only a PR template: "Contributions should target the `dev` branch." ([.github/PULL_REQUEST_TEMPLATE.md](https://github.com/qdrant/qdrant-client/blob/master/.github/PULL_REQUEST_TEMPLATE.md)). Gate, CLA, AI rule: none found. Test setup: unknown (no CONTRIBUTING).

**temporalio/sdk-python** (Python)
- Gate: none; only "Before taking on an issue, check whether it is already assigned" ([CONTRIBUTING.md#L18](https://github.com/temporalio/sdk-python/blob/main/CONTRIBUTING.md#L18)).
- CLA: "All contributors must complete the Temporal Contributor License Agreement (CLA) before changes can be merged." ([#L159](https://github.com/temporalio/sdk-python/blob/main/CONTRIBUTING.md#L159)).
- AI: "Using AI tools while contributing is acceptable." ... "If a contribution's interaction appears entirely AI-driven, maintainers may close it" ([#L141](https://github.com/temporalio/sdk-python/blob/main/CONTRIBUTING.md#L141)).
- Tests: `poe test`, `poe lint-types` ([AGENTS.md#L42](https://github.com/temporalio/sdk-python/blob/main/AGENTS.md#L42)).

**BerriAI/litellm** (Python)
- CLA: yes ([.github/CONTRIBUTING.md#L9](https://github.com/BerriAI/litellm/blob/main/.github/CONTRIBUTING.md#L9)). Gate: no issue or assignment rule found (whole CONTRIBUTING checked), but each PR needs proof: "start the proxy from your branch with a config that has the model you changed" and "Send the request a user would send with `curl`" ([#L258](https://github.com/BerriAI/litellm/blob/main/.github/CONTRIBUTING.md#L258)); AGENTS.md#L45 asks for "real provider calls where applicable", so some PRs need paid API keys.
- AI: "Do not add `Co-Authored-By: Claude` or any Claude attribution to commit messages." ([AGENTS.md#L79](https://github.com/BerriAI/litellm/blob/main/AGENTS.md#L79)); "**AI coding agents** (Claude Code, Copilot, Cursor, etc.): follow `AGENTS.md` and run `make format` before committing." ([.github/CONTRIBUTING.md#L168](https://github.com/BerriAI/litellm/blob/main/.github/CONTRIBUTING.md#L168)). Bot closes: stale, and "superseded" when main fixed it first ([#35630](https://github.com/BerriAI/litellm/pull/35630)).

**mlflow/mlflow** (Python)
- Gate: issue needs the `ready` label: "This PR was automatically closed because #24610 is missing the `ready` label." ([#25877](https://github.com/mlflow/mlflow/pull/25877)).
- DCO: "DCO sign-off: All commits MUST use the `-s` flag (otherwise CI will reject them)" ([AGENTS.md#L148](https://github.com/mlflow/mlflow/blob/master/AGENTS.md#L148)).
- AI: "Bugs found by inspecting, probing, or fuzzing the source code (manually or with AI tools), with no workload that reaches them through documented usage, are treated as hardening suggestions rather than bugs and may be closed." ([ISSUE_POLICY.md#L61](https://github.com/mlflow/mlflow/blob/master/ISSUE_POLICY.md#L61)). Tests: `uv sync`, `uv run pytest tests/`.

**vercel/ai** (TypeScript)
- Gate: "Before investing in an implementation, please review how we value contributions and open or improve an issue first." ([CONTRIBUTING.md#L110](https://github.com/vercel/ai/blob/main/CONTRIBUTING.md#L110)); bot closes PRs whose issue closed: "Closing this orphaned pull request." ([#12221](https://github.com/vercel/ai/pull/12221)). CLA, AI rule: none found.

**agno-agi/agno** (Python)
- Gate: "Open an issue first and wait for a maintainer to triage it. Only start work once a maintainer has added the `ready` label." ([CONTRIBUTING.md#L25](https://github.com/agno-agi/agno/blob/main/CONTRIBUTING.md#L25)); unlinked PRs "are closed automatically" (#L26).
- AI: "If your PR was entirely generated by an AI tool (Copilot, Claude Code, Cursor, etc.), you must disclose this in the PR template." ([#L30](https://github.com/agno-agi/agno/blob/main/CONTRIBUTING.md#L30)).

**pydantic/pydantic-ai** (Python)
- Gate: assignment first: "**Have a fix or code to share?** Make sure a maintainer has agreed to the approach on the issue and assigned you. Then open a PR." ([CONTRIBUTING.md#L14](https://github.com/pydantic/pydantic-ai/blob/main/CONTRIBUTING.md#L14)). Trivial fixes need no issue (#L24). Bot: "please wait to be assigned before opening a PR. This PR has been closed automatically because issue #8170 is not assigned to you." ([#8341](https://github.com/pydantic/pydantic-ai/pull/8341)).
- AI: no ban; "overly lengthy AI-generated issues, comments, and proposals are less likely to be helpful and more likely to be ignored" ([AGENTS.md#L50](https://github.com/pydantic/pydantic-ai/blob/main/AGENTS.md#L50)). CLA: none found. Tests use recorded requests, so no live keys for normal tests (AGENTS.md#L79).

**open-telemetry/opentelemetry-python-contrib** (Python)
- CLA: yes, Linux Foundation EasyCLA ([CONTRIBUTING.md#L16](https://github.com/open-telemetry/opentelemetry-python-contrib/blob/main/CONTRIBUTING.md#L16)).
- AI: "The most important rule is not to post comments on issues or PRs that are AI-generated." and "We appreciate it if users disclose the use of AI tools" ([AGENTS.md#L10](https://github.com/open-telemetry/opentelemetry-python-contrib/blob/main/AGENTS.md#L10), #L106). Tests: `uv sync --frozen --all-packages`, ruff via pre-commit.

**langfuse/langfuse** (TypeScript): "Before making any significant changes, please open an issue." ([CONTRIBUTING.md#L36](https://github.com/langfuse/langfuse/blob/main/CONTRIBUTING.md#L36)). CLA, AI rule for contributors: none found.

**langchain-ai/langchain-aws** (Python)
- Gate, CLA, AI rule: none found. Tests: `make test`; `make integration_test` ([.github/CONTRIBUTING.md#L80](https://github.com/langchain-ai/langchain-aws/blob/main/.github/CONTRIBUTING.md#L80)). "Integration tests cover the end-to-end service calls as much as possible." but "you can mock the service response for these tests" (#L71-73), so unit work needs no AWS account.

**openai/openai-agents-python** (Python): "**Pull requests are limited to repository collaborators. We do not accept pull requests from non-collaborators**, including documentation or example changes." ([CONTRIBUTING.md#L7](https://github.com/openai/openai-agents-python/blob/main/CONTRIBUTING.md#L7)). Closed to us.

**confident-ai/deepeval** (Python): CONTRIBUTING only says "We close issues with no activity for **≥ 12 months**." (#L49). Gate, CLA, AI rule: none found.

**langchain-ai/langchainjs** (TypeScript): "**Important**: We no longer accept new integrations to this repository." ([CONTRIBUTING.md#L54](https://github.com/langchain-ai/langchainjs/blob/main/CONTRIBUTING.md#L54)).

**dbos-inc/dbos-transact-py** (Python): no gate, CLA or AI rule found. "NOTE: The tests need a Postgres database running on `localhost:5432`." ([DEVELOPING.md#L51](https://github.com/dbos-inc/dbos-transact-py/blob/main/DEVELOPING.md#L51)). Docker is off here, so a local Postgres would be needed.

Other AI policies seen (repos dropped for their numbers): NVIDIA-NeMo/Guardrails: "Issues must be opened manually by a human through the repository issue templates. AI tools may help draft an issue, but agents must not submit issues directly." ([AI_POLICY.md](https://github.com/NVIDIA-NeMo/Guardrails/blob/develop/AI_POLICY.md)). letta-ai/letta: "**All AI usage in any form must be disclosed.**" ([AI_POLICY.md](https://github.com/letta-ai/letta/blob/main/AI_POLICY.md)). None of the files read bans AI-assisted PRs outright. The strictest: letta ("If you can't explain what your changes do and how they interact with the greater system without the aid of AI tools, do not contribute to this project."), agent-framework (closes undisclosed AI use, above) and temporal (closes "entirely AI-driven" PRs). Attribution rules conflict: fastmcp wants agents to identify themselves, while litellm and promptfoo forbid Claude attribution lines.

## Dropped

- langchain-ai/langchain-mcp-adapters: archived; README: "MCP support has moved into LangChain under the `langchain.mcp` namespace."
- langchain-ai/langchain: 11 outside merged, 2% merge rate; bot closed 424 outside PRs, e.g. "because you are not assigned to the linked issue" ([#40453](https://github.com/langchain-ai/langchain/pull/40453)).
- langchain-ai/langgraph: 2 merged, 0% rate; "External contributors must be assigned to an issue before opening a PR for it" ([#8926](https://github.com/langchain-ai/langgraph/pull/8926)).
- langchain-ai/langchainjs (TS): 313 of 446 open outside PRs stale, 0% issue reply, "We no longer accept new integrations to this repository."
- langchain-ai/langgraphjs (TS): 4 merged, 8% rate.
- langchain-ai/langchain-postgres: 0 outside merged (4 by staff), 42 of 53 open outside PRs stale.
- langchain-ai/openevals: 7 merged; median first maintainer reply 838 hours.
- langchain-ai/agentevals: 0 merged; last push 2026-07-14.
- openai/openai-agents-python: "We do not accept pull requests from non-collaborators".
- openai/openai-agents-js (TS): 1 outside merged (504 of the 505 by-label merges were by staff); 6% rate.
- huggingface/smolagents: 0 outside merged; 496 of 639 open outside PRs stale.
- crewAIInc/crewAI: 11% rate, 0% issue reply; bot: "First-time contributors need an associated open issue before we can review a PR." ([#4229](https://github.com/crewAIInc/crewAI/pull/4229)).
- stanfordnlp/dspy: 33 merged, 24% rate, 224 of 317 stale.
- agno-agi/agno: 32% rate, 719 of 789 open outside PRs stale, `ready` label gate.
- modelcontextprotocol/python-sdk: 0 outside merged; bot keeps PRs only from "a contributor a maintainer has assigned to the linked issue" ([#3506](https://github.com/modelcontextprotocol/python-sdk/pull/3506)).
- modelcontextprotocol/typescript-sdk (TS): 21 merged, 19% rate, 21.3-day median.
- vercel/ai (TS): 24% rate, 496 of 788 stale, 1,018 staff PRs vs 123 outside.
- mastra-ai/mastra (TS): 3% outsider share, 18% rate; bot: "Closing this PR because it has no linked issue." ([#24186](https://github.com/mastra-ai/mastra/pull/24186)).
- letta-ai/letta: 0 outside merged; its AI_POLICY.md says "the code in this repo is ARCHIVED".
- run-llama/llama_index: 7% rate, 516 of 951 stale; bot closes after "stalled for 10 days with no activity".
- pgvector/pgvector-python: 1 outside PR merged; 5 other outside PRs were closed by a commit on the main branch instead of a merge (small, one-maintainer repo).
- chroma-core/chroma: Rust; 3 outside merged, 6% rate.
- weaviate/weaviate-python-client: 14 merged, 32% rate, median first reply 1,416 hours.
- 567-labs/instructor: 9 merged, 3% rate.
- mem0ai/mem0: 6% rate, 36-day median; bot: "We only review pull requests that fix an issue we have already agreed to take on" ([#7335](https://github.com/mem0ai/mem0/pull/7335)).
- microsoft/graphrag: 0 outside merged; 29 of 29 open outside PRs stale.
- topoteretes/cognee: 17% rate, 7% outsider share.
- vibrantlabsai/ragas: 6 merged, 84.7-day median, 236 of 267 stale.
- confident-ai/deepeval: 358 of 483 stale, 0% issue reply; the top 2 "outside" authors list Confident AI on their profiles, so real outside merges are fewer than 32.
- langfuse/langfuse (TS): 3% outsider share, 25% rate, 406 of 555 stale.
- langfuse/langfuse-python: 17 merged, 11 of them by one person; 36% rate.
- traceloop/openllmetry: 19 merged, 9 by one person; 243 of 341 stale; 0% issue reply.
- NVIDIA-NeMo/Guardrails: 8 outside merged.
- jd/tenacity: 4 outside merged.
- dottxt-ai/outlines: 0 outside merged; last push 2026-09-21.
- guardrails-ai/guardrails: 0 outside merged; bot closes after "stalled for 14 days".

## Method

- **Seeds:** 56 seed repos. 4 were renamed and followed (jlowin/fastmcp, strands-agents/sdk-python, explodinggradients/ragas, NVIDIA/NeMo-Guardrails). 1 is archived (langchain-mcp-adapters), so 55 were measured. strands-agents/sdk-python now redirects to the strands-agents/harness-sdk monorepo; its Python SDK is the `strands-py/` folder.
- **Window:** PRs merged from 2026-09-15 00:00 UTC to 2026-11-14 23:59 UTC. "Stale" = open, not a draft, created before 2026-10-15, and no review from a maintainer (comments do not count). Drafts are left out of stale on purpose.
- **Insider/outsider:** the literal rule is author_association MEMBER, OWNER or COLLABORATOR = insider; CONTRIBUTOR, FIRST_TIME_CONTRIBUTOR, FIRST_TIMER, NONE = outsider. GitHub hides private org membership, so staff often show as CONTRIBUTOR (pydantic-ai: 1,996 "outside" merges by label, 105 after the fix). The main numbers therefore also count as insider anyone who merged a PR or closed someone else's PR in the fetched data. Both need repo rights. The literal number is in brackets in the table. Staff who never merge or close still count as outside; a profile check of top authors found some (deepeval, maybe phoenix and litellm). Bots: type Bot, `[bot]`, `-bot`/`_bot` names, and a list (dependabot, renovate, pre-commit-ci, github-actions, copilot-swe-agent and others).
- **First-timer PRs:** GraphQL never returned FIRST_TIME_CONTRIBUTOR or FIRST_TIMER here, so open PRs with NONE (no commit in the repo yet) count as first-timer.
- **Merge rate:** outside merged / (outside merged + outside closed without merge), both in the window.
- **Copybara:** google/adk-python never merges on GitHub. Its bot closes PRs with "successfully imported and merged via Copybara" (all 392 bot closes of non-staff PRs that were read), so those count as merged at the close time. Its outsider share is n/a, because staff commit internally.
- **Issue reply:** the 20 newest issues opened before 2026-11-07 by outsiders (not bots, not maintainers). Measured: did a maintainer comment within 7 days, and the median hours to that first comment. Only the first 30 comments are read. A close or label with no comment counts as no reply.
- **Helper labels:** open counts of labels like "good first issue" and "help wanted" were collected and used by the issue analysts.
- **Calls (all read-only, no search API), in two passes on 2026-11-14 (18:45-22:15 UTC):**
  - First pass: `gh api repos/O/R` to follow renames; GraphQL queries for closed PRs (newest updated first, with closing events), open PRs (with reviews and comments), issues (with comments) and labels; REST GETs for the rule files.
  - Second pass, for the big repos whose first pass failed with HTTP 502: resumed paging with a lighter query for vercel/ai, mastra and litellm; fetched closing events and labels for langchain, mlflow, vercel/ai and mastra.
  - Also read the last comment on bot-closed outside PRs (21 repo/bot pairs), checked 22 top authors' public profiles for staff, one commit (adk #7398), one README (langchain-mcp-adapters) and 2 more rule files (fastmcp, mlflow).
- **Checks:** the compute script was checked against a REST page for dbos-transact-py. The counts by label match exactly (27 outside, 29 insider merged).
- **Limits:**
  - Resuming a cursor some hours later can miss PRs updated in between (small).
  - Reviews are capped at 30 per PR.
  - The strands numbers cover the whole monorepo.
