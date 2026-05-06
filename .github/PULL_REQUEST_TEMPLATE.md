<!-- PR title MUST follow Conventional Commits, e.g.:
     feat(ingest): add Nordnet CSV parser
     fix(sim): correct FX rounding in EUR↔DKK
     docs(adr): record decision to use DuckDB
-->

## Summary

<!-- One paragraph: what this PR does and why. -->

Closes #

## Type of change

- [ ] feat — new user-visible capability
- [ ] fix — bug fix
- [ ] refactor — no behavior change
- [ ] perf — performance change
- [ ] docs — documentation only
- [ ] test — tests only
- [ ] build / ci / chore — tooling, deps, infra
- [ ] revert

## Architecture impact

- [ ] No architectural change
- [ ] ADR included or referenced: `docs/decisions/NNNN-...`

## Definition of Done

- [ ] Linked to an issue
- [ ] Tests added or updated; coverage of touched code does not regress
- [ ] Documentation updated (user docs, runbook, ADR, or inline) where relevant
- [ ] Database migrations include a tested downgrade (N/A if no migrations)
- [ ] No secrets, PII, or real financial data in the diff
- [ ] CI green (lint, typecheck, tests, container build, dbt parse, sqlfluff, codeql, gitleaks)
- [ ] Self-reviewed in the GitHub UI
- [ ] Screenshots / log excerpts attached if behavior is observable

## How to verify

<!-- Commands the reviewer can run; expected outputs; screenshots. -->

```bash
just test
```

## Notes for the reviewer

<!-- Anything non-obvious, trade-offs taken, follow-ups deferred. -->
