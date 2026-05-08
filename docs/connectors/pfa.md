# PFA Pensionsoversigt

Provider slug: `pfa`.
Account kinds: `aldersopsparing`, `ratepension`, `livrente` (one
account per scheme on the policy).
Account currency: `DKK`.
Source format: **PDF** (the annual *Pensionsoversigt* mailed by
PFA).

PFA's customer portal does not expose a stable export endpoint
that covers historical scheme-level balances, contributions and
PAL-skat. The annual *Pensionsoversigt* PDF is the source of
record customers actually receive, so the connector targets it
directly. Both pdfplumber (text-embedded PDFs) and a Tesseract
OCR fallback (scanned image-only PDFs) are supported.

## What gets ingested

| PFA section | Penge target |
|---|---|
| `Policenr.: …` header | identifies the policy (used for `account.external_id`) |
| `Opgjort pr. …` header | `holding_snapshot.as_of` |
| `Optjeningsperiode: … - …` header | `period_from`, `period_to` (used as `transaction.value_date`) |
| Per-scheme summary table (`Aldersopsparing` / `Ratepension` / `Livsvarig livrente`) | one `account` + summary `transaction` rows |
| Per-scheme `Investeringsprofil` table | `holding_snapshot` rows + synthesised `instrument` rows (one per fund name) |

Each scheme on the policy becomes its own account. The
`account.external_id` is `<policy>:<scheme_kind>:<sub_policy_id>`
so a single PFA policy with three schemes yields three rows in
`account` (and the loader's `LoadResult.accounts` reflects that).

## Scheme summary mapping

Each non-zero line of the per-scheme financial summary is posted
as one `transaction` row dated on `period_to` (or `as_of` when
`period_to` is missing from the statement):

| PFA label | Penge `transaction.kind` | Sign |
|---|---|---|
| `Indbetaling - Arbejdsgiver` / `…firma` | `deposit` (description: `Contribution (employer)`) | positive |
| `Indbetaling - Privat` / `Egen indbetaling` | `deposit` (description: `Contribution (employee)`) | positive |
| `Afkast` | `dividend` (description: `Investment return`) | as printed |
| `Omkostninger` / `Gebyr` / `Administration` | `fee` (description: `Fees (Omkostninger)`) | negated to negative |
| `PAL-skat` / `Pensionsafkastskat` | `tax` (description: `PAL-skat`) | negated to negative |

`Primo` and `Ultimo` (opening / closing balances) are not posted
as transactions — they are reconciliation reference points only.
The reconciliation invariant the parser tests enforce is:

```text
opening + sum(contributions) + return - fees - pal_skat ≈ closing  (±0.01 DKK)
```

`Udbetaling` rows (withdrawals) are not yet emitted by the
parser; statements that contain them will skip those rows
silently. Filing a sample is welcome (#18 follow-up).

## Holdings (`Investeringsprofil`)

Each PFA fund line becomes one `holding_snapshot` row plus a
synthetic `instrument` row. The instrument ticker is generated
from the fund display name with the `PFA:` prefix:

```text
"PFA Plus AA"            -> "PFA:PFAPLUSAA"
"PFA Globale Aktier"     -> "PFA:PFAGLOBALEAKTIER"
"Hedge Lav Risiko"       -> "PFA:HEDGELAVRISIKO"
```

`quantity` is taken from the `Andele` column when present and
defaults to `1` otherwise (older PFA layouts only print
percentages and DKK market values).

## Stable transaction id

PFA's PDF does not assign a transaction id and the
financial-summary lines are aggregated across the whole
statement period. The loader synthesises a stable id by
hashing `(policy_number, scheme_kind, sub_policy_id, txn_kind,
period_to, detail)` with sha256 and prefixing the first 16
hex chars with `pfa:`. See `synthesize_external_id`
in `penge.ingest.pfa.parser`. Re-running an ingest of the same
statement is therefore a no-op.

## OCR fallback

When pdfplumber returns less than 200 characters of embedded
text from the PDF (configurable via `_MIN_EMBEDDED_TEXT_LEN`),
the parser falls back to OCR via `pdf2image` + `pytesseract`,
rendered at 300 dpi and run with `lang="dan+deu"`. The tests
mock pytesseract so a successful CI run does not require Danish
language data; production hosts however do.

### Host dependencies

The OCR path shells out to native binaries; install them on
the ingest host before running with scanned PDFs:

```bash
# Debian/Ubuntu
sudo apt-get install tesseract-ocr tesseract-ocr-dan tesseract-ocr-deu poppler-utils

# Fedora
sudo dnf install tesseract tesseract-langpack-dan tesseract-langpack-deu poppler-utils

# macOS
brew install tesseract tesseract-lang poppler
```

The CI runner installs `tesseract-ocr`, `tesseract-ocr-dan`,
`tesseract-ocr-deu` and `poppler-utils` in the `pytest` job (see
`.github/workflows/ci.yml`).

## CLI

```bash
just ingest-pfa --entity-name "Your Name" \
    ~/Nextcloud/Documents/PFA/pensionsoversigt-2025.pdf
```

Or directly:

```bash
uv run --group db --group http --group parsers --group ocr \
    penge-pfa --entity-name "Your Name" \
    ~/Nextcloud/Documents/PFA/pensionsoversigt-2025.pdf
```

Pass `--no-ocr` to disable the OCR fallback (useful when ingesting
known-good text PDFs and you want a hard error on missing text).

## Test fixtures

`tools/generate_pfa_fixture.py` regenerates two synthetic PDFs
under `tests/ingest/pfa/fixtures/`:

- `sample_pensionsoversigt.pdf` — text-embedded, exercises
  pdfplumber's table extraction;
- `sample_pensionsoversigt_scanned.pdf` — image-only (the text
  PDF rasterised at 110 dpi), exercises the OCR fallback path.

The fixture builder uses synthetic policy numbers and amounts;
no real customer data is committed to the repository.
