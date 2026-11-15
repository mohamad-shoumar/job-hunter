# Open-source contributions for an applied AI / backend profile (2026-11-15)

Which open-source PRs are worth doing, in which order, and what each one needs. Measured by merged,
substantive PRs, their relevance to applied AI and backend work, and the effort per merged PR.
Research only: nothing was posted to any project, and every public step needs your OK.

## The short version

- **Start here:** [opik #8134](https://github.com/comet-ml/opik/issues/8134). It is ready today:
  about 3.5 hours, 45% odds. A small but real fix: protecting an LLM judge from prompt injection by
  the output it grades.
- **Send four short comments the same day**, because answers take days. Each one needs your OK:
  - agent-framework #10286: propose a design;
  - adk-python #6361: ask the reporter;
  - strands #3156: ask whether an outside PR is welcome;
  - optionally phoenix #12266: say you're picking it up.

  Write no code for these until someone says yes, and drop each after 14 days of silence.
- **Expect 1-2 merged PRs in 4-6 weeks**, for about 40 hours of work across all five.
- **Why so few:** the healthy AI repos are crowded. A confirmed bug usually gets a PR within hours to
  3 days, often from the person who reported it. LangChain and LangGraph are worse for outsiders: in
  the last 60 days they merged 2% and 0% of the outside PRs they closed.
- **The better long-term bet:** bugs you find yourself while using these tools, sent as an issue and
  a PR together. Nobody else is racing for those.

## What needs your OK

| Item | Public step | Kind | Also needed |
|---|---|---|---|
| opik #8134 | open a draft PR | PR | read `CLA.md` (submitting means agreeing); fill the AI disclosure block |
| agent-framework #10286 | propose the design on the issue, saying AI helped | comment | later: the Microsoft CLA |
| adk-python #6361 | ask the reporter; ask maintainers to confirm the design | comment | later: the Google CLA, with your commit email matching it |
| strands #3156 | ask whether an outside PR is welcome | comment | |
| phoenix #12266 (optional) | "picking this up" with one design question, then the PR | comment, then PR | the repo's CLA bot |

Drafts of each comment are in [contribution-plans.md](contribution-plans.md), as starting points.
Write the comments and the code yourself, make sure you understand every line, and disclose AI help
wherever a repo asks for it (several do: see [repos.md](repos.md)).

## Files

- [issues-ranked.md](issues-ranked.md): the ranked list with direct links, plus the killed and taken
  items and a dated watch list.
- [contribution-plans.md](contribution-plans.md): per issue, the reproduction, files, fix, tests and
  first step.
- [effort-and-tests.md](effort-and-tests.md): hours, cost per merged PR, test commands and CI checks.
- [critical-review.md](critical-review.md): the independent review, with its verdicts, the sequence
  and strategy suggestions.
- [repos.md](repos.md): 55 repos measured. Who merges outside PRs, how fast, and their rules and AI
  policies.

## How it was done

Agents in stages: a repo researcher, four issue analysts, four planners, and an independent reviewer
who tried to kill each candidate and re-ran four of the reproductions. The orchestrator assembled these files
and re-checked every link before publishing. All GitHub access was read-only, and repository code
ran in a sandbox with no API keys and no access to real credentials.
