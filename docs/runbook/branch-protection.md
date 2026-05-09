# `main` branch protection — current state and rationale

This is a **solo-maintainer** repo. GitHub does not allow a user to approve their
own pull requests, so the textbook "require 1 approval" rule would either block
every PR or force the use of a second account. The protection on `main` is
therefore tuned for "no silent bypass" rather than "human approval gate".

## Active rules (ruleset `main: PR + green CI + linear history`)

- **No deletion**, **no force-push** to `main`.
- **Linear history required** — only squash or rebase merges land.
- **Required status checks** (must be green on the latest commit):
  Conventional Commit PR title, Markdown lint, YAML lint,
  Secret scan (gitleaks), Bootstrap smoke.
- **Required review thread resolution** — every review thread must be marked
  resolved before merge.
- **Stale reviews dismissed on push** — any new commit invalidates earlier
  approvals.
- **`required_approving_review_count: 0`** — see trade-off below.
- **`bypass_actors: []`** — nobody, including the repo admin, can bypass the
  ruleset. `gh pr merge --admin` is therefore a no-op against these rules.
  This was verified on 2026-05-09.

## Why approval count is 0

Setting it to 1 would either:

1. block every solo PR (GitHub forbids self-approval), or
2. require a second human/account, or
3. require Copilot's review to count as an approval — but Copilot leaves
   `COMMENTED` reviews, not `APPROVED` ones, so it does not satisfy the rule.

The accepted trade-off: the **agent-level rule** (see
[`.github/agents/implementer.agent.md`](https://github.com/autoditac/Penge/blob/main/.github/agents/implementer.agent.md)
and [`AGENTS.md`](https://github.com/autoditac/Penge/blob/main/AGENTS.md))
forbids merging before the Copilot review bot has posted, and forbids
`gh pr merge --admin`. Combined with `required_review_thread_resolution: true`,
this means: if Copilot opens any thread, the merge is mechanically blocked
until the thread is resolved.

## What to do if an agent merges before review again

Happened on PRs #86 and #89.

1. Open a follow-up branch named `chore/<issue>-pr-review-followups`.
2. Address every Copilot comment with a fix commit or a written rationale.
3. Open a PR that references the merged PR.
4. File a `chore` issue against `.github/agents/` if the rule needs further
   tightening.

## Re-evaluation triggers

Revisit the trade-off and consider raising `required_approving_review_count`
to 1 when any of the following becomes true:

- A second human maintainer joins the project.
- Copilot Code Review starts producing `APPROVED` reviews that GitHub counts.
- The repo goes public (the blast radius of a bad merge increases).
