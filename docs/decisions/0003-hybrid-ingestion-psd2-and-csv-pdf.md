# 0003 — Hybrid ingestion: PSD2 (GoCardless) + CSV/PDF parsers

- **Status:** Superseded by [ADR-0026](0026-retire-gocardless-for-enable-banking.md)
- **Date:** 2026-05-06
- **Deciders:** @autoditac
- **Tags:** ingest, security

## Context and Problem Statement

Penge must continuously ingest data from accounts in two jurisdictions:
DK retail banks (e.g. Lunar), DE retail banks (e.g. GLS Bank, Evangelische
Bank), Nordnet (DK + SE brokerage), pension providers, and various
document-only sources (annual statements, K-form variants, payslips).
No single API or aggregator covers all of these.

## Decision Drivers

- Coverage: must handle PSD2 banks **and** brokerages / pension providers
  that have no PSD2 endpoint.
- Sovereignty: avoid sharing credentials with US-based aggregators when
  possible; prefer EU-regulated providers.
- Determinism: parsers must be testable against fixture files, with stable
  output schemas.
- Resilience: an outage at one provider must not block the others.

## Considered Options

1. **Hybrid: GoCardless Bank Account Data (PSD2) + custom CSV/PDF parsers** — PSD2 where supported, file-based ingestion otherwise.
2. **PSD2-only via GoCardless** — accept that brokerage and pension data must be entered manually.
3. **Plaid / SaltEdge** — single aggregator covering more institutions.
4. **CSV-only** — no PSD2; manual export from every institution.

## Decision

We chose **Option 1: hybrid ingestion**.

- **PSD2** via GoCardless Bank Account Data (formerly Nordigen) for retail
  banks in DK + DE.
- **CSV/PDF parsers** for Nordnet, pension providers, and any institution
  GoCardless does not cover. Parsers live under `connectors/<provider>/`
  with golden-file tests.
- All ingestion writes through a common normalization layer into Postgres
  and emits a Parquet snapshot (see ADR-0001).

## Consequences

### Positive

- Broad coverage without proprietary aggregator fees.
- File-based connectors are deterministic and auditable.
- A failure in one connector is isolated.

### Negative

- More code to maintain (one parser per non-PSD2 provider).
- PDF parsers are brittle when banks change layouts.

### Neutral

- GoCardless requires periodic SCA re-authentication (≈ every 90–180 days).
- We must own consent expiry monitoring.

## Alternatives in detail

### PSD2-only

Rejected: leaves brokerage (Nordnet) and pension data outside the system,
which defeats net-worth and FIRE goals.

### Plaid / SaltEdge

Rejected: weaker EU/Nordic coverage for our specific banks, higher cost,
and a US-anchored data path that conflicts with the sovereignty driver
(see ADR-0001).

### CSV-only

Rejected: too much manual work to be sustained for a decade.

## Links

- ADR-0001 (stack)
- `connectors/`
