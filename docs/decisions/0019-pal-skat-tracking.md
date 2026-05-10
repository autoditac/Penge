# 0019 — PAL-skat tracking on Danish pension accounts

- **Status:** Proposed
- **Date:** 2026-05-10
- **Deciders:** @autoditac
- **Tags:** tax, dk, pension

## Context and Problem Statement

Danish pension providers (PFA, Velliv, AP Pension, ...) pay an annual
*pensionsafkastskat* (PAL-skat) of **15.3 %** on the return generated
by pension assets. The provider withholds and remits the tax
automatically, so the saver only ever sees the net-of-tax balance.

For Phase-3 simulations and tax projections, Penge needs a deterministic
shadow calculation so that:

1. Net-of-tax pension trajectories agree with what PFA actually credits
   to the account.
2. The SKAT report generator (#39) can record PAL-skat for completeness
   even though it is not "owed" by the saver.
3. The Phase-2 simulation overlay continues to use the same 15.3 %
   constant via a single source of truth (`PAL_RATE`).

## Decision

| Item | Choice |
|---|---|
| **Module** | `penge.tax.pal` |
| **Formula** | `return = end_mv − start_mv − Σ contributions + Σ withdrawals` then `tax = max(return, 0) × 0.153` |
| **Currency** | DKK only on every input/output; non-DKK raises `PalError` |
| **Scope** | One calculator call ↔ one `(account_id, tax_year)` pair |
| **Loss handling** | Negative return → `tax_due = 0`, magnitude returned as `loss_carry_forward`. Cross-year roll-forward bookkeeping is the SKAT report generator's (#39) job |
| **State** | None — the calculator is a pure function |
| **Precision** | All outputs quantized to 0.01 DKK using ROUND_HALF_EVEN |

The 15.3 % rate is exposed as the constant `PAL_RATE` so that the
Phase-2 simulation overlay (`penge.sim.tax`) can import it instead of
duplicating the literal.

## Consequences

### Positive

- Mirrors the lager / ASK calculator structure (ADR-0017 / ADR-0018):
  same input shape, same output shape, same loss-carry-forward
  protocol. The SKAT report generator can treat PAL the same way it
  treats ASK.
- Single source of truth for the 15.3 % rate via `PAL_RATE`.
- No FX risk: PFA reports in DKK so the calculator is DKK-only.

### Negative

- Caller must keep `PAL_RATE` in sync with statutory changes. We
  accept this — PAL-skat changes infrequently, and an ADR amendment
  is the right way to record any change.

## Rejected Alternatives

- **Bake PAL into `penge.tax.lager`** with a special "pension" account
  type. Rejected: lager applies to taxable funds (capital income),
  PAL applies to pension assets (separate tax base). Mixing them
  would obscure both.
- **Deduct PAL inline from observed gross pension returns** in the
  ingestion pipeline. Rejected: PFA already withholds; the value we
  observe in PFA exports is *already net*. The PAL calculator is for
  projection / shadow computation only.

## References

- ADR-0017 — Lagerbeskatning calculator
- ADR-0018 — Aktiesparekonto handling
- `docs/tax/dk.md` — PAL-skat section
- SKAT — *Pensionsafkastskat*
