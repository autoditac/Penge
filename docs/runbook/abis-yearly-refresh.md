# ABIS list — yearly refresh

Skat publishes an updated **ABIS list** (Aktiebaserede
Investeringsselskaber) every December covering the rolling
6-year tax window. This runbook describes the refresh procedure.

## When

By **31 January** of each tax year, after Skat's December
publication. Before this date, the latest CSV in the repo's
local store is still authoritative for the prior tax year.

## Steps

1. Download the new CSV from Skat. The file is normally named
   `abis-listen-YYYY-YYYY-month-YY.csv`. Save it to the local
   data store (never commit it — the file contains real ISINs of
   Danish-recognised funds and is large).
2. Verify the header still matches `EXPECTED_HEADERS` in
   `src/penge/tax/abis/constants.py`. If Skat changed the
   headers, the parser will refuse the file with a clear error;
   open a PR to update `EXPECTED_HEADERS` and add a regression
   test.
3. Run the ingestor:

   ```sh
   just ingest-abis ingest path/to/abis-listen-YYYY.csv
   ```

4. Read the one-line summary printed by the CLI. Record `matched`,
   `unmatched`, `classified`, `cleared` in your tax log so a future
   reviewer can see how the list moved year-over-year.
5. Inspect every instrument the loader **cleared** (set
   `dk_tax_treatment` to `NULL`). These funds fell off the ABIS
   list and may need a manual `realisation` decision:

   ```sql
   select isin, name, dk_tax_treatment, dk_tax_treatment_source
   from instrument
   where dk_tax_treatment is null
     and exists (
       select 1 from instrument_dk_abis_listing l
       where l.instrument_id = instrument.id
     );
   ```

6. For each cleared instrument, decide and stick a manual
   decision:

   ```sh
   just ingest-abis override --isin DEnnnnnnnnnn --treatment realisation
   ```

7. Audit any instruments with
   `dk_tax_treatment_source = 'manual'` to confirm the manual
   decision still reflects reality (e.g., the fund did not move
   back onto the list this year).
8. Commit nothing. The CSV stays out of the repo; the database
   carries the state.

## Failure modes

- **Header drift**: parser raises `ValueError`. Update
  `EXPECTED_HEADERS`, add a test, ship a PR.
- **New separator / placeholder**: parser drops malformed tokens
  with `WARNING`-level logs. Inspect the warnings; if a
  systematic new format appears, extend the parser.
- **Unmatched ISINs that *should* match**: usually means the
  custodian connector has not yet run for that holding. Run the
  relevant `just ingest-*` first, then re-run `just ingest-abis`.
