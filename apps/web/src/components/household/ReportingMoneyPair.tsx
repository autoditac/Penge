import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";

import { formatMoney, parseDecimal } from "../../money";
import type { Currency } from "../../money";
import { MoneyPair } from "../primitives";

export type ReportCurrencyAmount =
  | {
      readonly complete: true;
      readonly amount: string;
      readonly knownSubtotal: string;
    }
  | {
      readonly complete: false;
      readonly amount: null;
      readonly knownSubtotal: string;
    };

type ReportingMoneyPairProps = {
  readonly eur: ReportCurrencyAmount;
  readonly dkk: ReportCurrencyAmount;
};

/** Shows report currencies in parallel without presenting incomplete FX as a total. */
export function ReportingMoneyPair({ eur, dkk }: ReportingMoneyPairProps): React.JSX.Element {
  if (eur.complete && dkk.complete) {
    return (
      <MoneyPair eur={parseDecimal(eur.amount)} dkk={parseDecimal(dkk.amount)} primary="DKK" />
    );
  }

  return (
    <Stack
      spacing={0}
      aria-label="EUR and DKK totals; incomplete currencies show known subtotals"
      sx={{ fontVariantNumeric: "tabular-nums" }}
    >
      <CurrencyAmountLine currency="DKK" value={dkk} />
      <CurrencyAmountLine currency="EUR" value={eur} />
    </Stack>
  );
}

function CurrencyAmountLine({
  currency,
  value,
}: {
  readonly currency: Currency;
  readonly value: ReportCurrencyAmount;
}): React.JSX.Element {
  const amount = value.complete ? value.amount : value.knownSubtotal;
  return (
    <Box component="span" sx={{ display: "block" }}>
      <Box component="strong" sx={{ fontWeight: 700, fontSize: "1rem" }}>
        {formatMoney(parseDecimal(amount), currency)}
      </Box>
      {!value.complete ? (
        <Box
          component="small"
          sx={{ display: "block", color: "text.secondary", fontSize: "0.75rem" }}
        >
          Known subtotal · {currency} total incomplete
        </Box>
      ) : null}
    </Box>
  );
}
