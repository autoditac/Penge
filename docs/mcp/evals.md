# MCP golden-question evals

The MCP server is the only sanctioned LLM data path in Penge. Every
new release of the tool layer is gated by a deterministic eval suite:
twenty fixture-backed "golden questions" that exercise the real tool
handlers and assert structural and numeric invariants.

The suite is **not** an LLM-in-the-loop test. It runs entirely in
TypeScript with pre-seeded fixtures so it is fast (sub-second locally)
and 100 % reproducible in CI.

## Running the suite

Locally:

```sh
just mcp-evals
```

CI runs the suite automatically on any pull request that touches:

- `apps/mcp/**`
- `src/penge/sim/**`
- `src/penge/tax/**`
- `.github/workflows/mcp-evals.yml`

The workflow is `.github/workflows/mcp-evals.yml`. The unit tests for
the eval harness itself (assertion helpers, fixture loaders) live in
`apps/mcp/tests/evalsHarness.test.ts` and run as part of
`just mcp-test`.

## Layout

```text
apps/mcp/evals/
├── assertions.ts           # tolerance/ordering/leak helpers
├── fixtures/
│   ├── cashflowRows.ts     # synthetic mart_cashflow_daily rows
│   ├── netWorthRows.ts     # synthetic mart_net_worth_daily rows
│   ├── scenarioPayloads.ts # canned run_scenario payloads
│   ├── taxPayloads.ts      # canned compute_tax_year payloads
│   └── vaultDocs.ts        # synthetic vault layout + helpers
├── goldens.ts              # the 20 golden questions
└── runner.ts               # vitest harness (one it() per golden)
```

## Coverage (20 goldens)

| Area              | Count | Topics                                                                                                                                                |
| ----------------- | ----- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| DK tax            | 5     | lagerbeskatning mark-to-market; AKS 17 %; PAL-skat 15.3 %; årsopgørelse summary ↔ line-items consistency; loss carry-forward                          |
| DE tax            | 3     | Vorabpauschale base = Basiszins × NAV; Teilfreistellung 70 % equity; mixed-depot line-item completeness                                               |
| FIRE / sim        | 4     | p10 ≤ p50 ≤ p90 ordering; work-reduction shifts FIRE later; house-purchase keeps FIRE no earlier; fixed-seed determinism                              |
| Cashflow          | 3     | monthly ≡ Σ daily; year ↔ month rollup invariant; net sign preserved across EUR ↔ DKK                                                                 |
| Net worth         | 3     | Σ per-account = total; asset_class rollup = total; cross-currency parity within 0.5 % under fixed FX                                                  |
| Vault search      | 2     | classifier-typed lookup never leaks across types; excerpts never carry raw IBAN / CPR / long digit runs                                               |

## Adding a new golden

1. Open `apps/mcp/evals/goldens.ts` and append an entry to `GOLDENS`:

   ```ts
   {
     id: "kebab-case-id-unique-across-the-suite",
     question: "Human-readable question — appears verbatim in test names and failures.",
     rationale: "One sentence: why does this matter? What does drift here imply?",
     tool: "query_net_worth", // or another ToolName
     async run() {
       // Wire fixtures into the *real* tool handler. For DB-backed
       // tools use a `queuedXRunner([rowsForCall1, rowsForCall2, …])`.
       // For subprocess-backed tools use `fixedRunner(payload)`.
       // For search_documents use `buildVault(tempRoot, docs)`.
       const runner = queuedNetWorthRunner([NW_TOTAL_EUR]);
       const tool = queryNetWorthTool({ runner });
       const out = await tool.handler({ /* … */ }, CTX);
       tool.outputSchema.parse(out);                  // structural check
       approxEqual(out[0]!.value, 600_000, 0.0001,    // numeric check
         "household total");
     },
   },
   ```

2. If the new golden needs synthetic data that isn't already in
   `evals/fixtures/`, **add it there**. Fixtures must be synthetic. Do
   not copy real statements, real account numbers, or real names into
   the repo — the suite is checked into git and pushed to GitHub.

3. Update the count in the dataset-shape check at the top of
   `runner.ts` if the new golden changes the total count (the runner
   asserts `GOLDENS.length === 20`).

4. Run the suite locally:

   ```sh
   just mcp-evals
   ```

5. If the assertion you need isn't yet in `assertions.ts`, add it
   there with a unit test in `tests/evalsHarness.test.ts`. Keep helper
   error messages structured (`label: expected …, got …`) so failures
   read as a diff in CI logs.

## Why deterministic, not LLM-in-the-loop?

Issue #54 originally proposed running questions through Claude / GPT
and checking the LLM's answer. That has two failure modes Penge can't
absorb:

1. **Non-determinism in CI.** LLM output drifts across versions. A
   green main branch must stay green.
2. **Cost and review latency.** Hitting an API on every PR slows the
   review loop and adds an external dependency.

Instead, the harness validates the tool layer itself — the LLM-visible
contract. If the tool returns the right numbers in the right shape,
any well-behaved LLM has the information it needs.

### Scope of this PR vs issue #54

Issue #54 originally asked for "all 20 questions pass against the live
LLM". That requirement is intentionally **out of scope for CI**: a
live-model gate is non-deterministic and would block green builds on
upstream model drift. What ships here is the deterministic tool-layer
half of that contract — the half that *can* be a CI gate.

The live-LLM walk-through is still expected as a manual pre-release
check (see `docs/mcp/tools.md` for the question list and the local
`mcp-server` invocation). Re-running it monthly is a release-checklist
item, not a CI job. If we ever want to automate it, that should be a
separate scheduled workflow (e.g. nightly `workflow_dispatch` with a
report-only outcome) and a separate ADR — not a merge gate.

## When a golden fails

Vitest reports each golden as `[<id>] <question>`. The failure block
includes:

- the golden id and tool
- the original question text
- the rationale (so you understand the invariant without scrolling)
- the assertion message (which contains the actual vs expected diff)

If the failure looks legitimate (the new behaviour is correct and the
golden is stale), update the fixture or the golden with a clear commit
message. Do not delete a golden — replace it. If you genuinely need
to drop one, link the ADR or issue that motivated the removal.
