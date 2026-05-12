# Privacy Policy

**Service:** Penge  
**Operator:** autoditac (private individual)  
**Last updated:** 2026-05-12

## 1. What is Penge?

Penge is a **self-hosted, single-user personal finance platform** operated
exclusively for the private use of its owner. It is not a commercial service,
not offered to the public, and has no users other than the operator.

## 2. Data collected

Penge aggregates financial account data from the following sources on behalf
of the operator:

- **Bank account transactions and balances** — fetched via the Enable Banking
  PSD2 AISP API for accounts held at GLS Bank (DE), Evangelische Bank (DE),
  and Lunar (DK).
- **Brokerage and pension data** — imported from CSV/PDF exports provided by
  Nordnet, PFA, and Growney.
- **Manual entries** — entered directly by the operator (cash holdings, real
  estate valuations).

All data belongs to the operator and is processed solely for the purpose of
personal net-worth tracking and long-term financial planning (FIRE modeling).

## 3. Where data is stored

All data is stored **exclusively on operator-owned infrastructure**:

- A self-hosted PostgreSQL database running on the operator's local network.
- Encrypted local backups using `age` encryption; private keys are kept
  exclusively by the operator.
- No data is stored in any cloud database, third-party SaaS, or analytics
  platform.

## 4. Data sharing

Penge does **not** share financial data with any third party, with two
narrow technical exceptions:

1. **Enable Banking AG** — the PSD2 aggregator that proxies read-only
   requests to the banks listed above. Enable Banking acts as a regulated
   AISP and processes data in accordance with their own
   [privacy policy](https://enablebanking.com/privacy-policy/). Penge only
   reads account data; no payment initiation takes place.
2. **ECB Exchange Rate API** — daily EUR/DKK reference rates are fetched from
   the European Central Bank's public endpoint. No personal data is sent.

No financial data is sent to LLMs, analytics services, or advertising
networks. The optional MCP server provides read-only access to aggregated
data strictly within the operator's own LLM toolchain.

## 5. Retention

The operator may delete all data at any time by dropping the local database.
Enable Banking consent can be revoked at any time via the Enable Banking
dashboard; revocation stops all future data fetches immediately.

## 6. Legal basis (GDPR)

Processing is based on **Article 6(1)(a) — consent** (the operator is also
the data subject) and **Article 6(1)(f) — legitimate interests** (personal
financial management). No special categories of data under Article 9 are
intentionally processed.

## 7. Contact

For any privacy-related question or erasure request, contact the operator
directly via the [GitHub repository](https://github.com/autoditac/Penge).
