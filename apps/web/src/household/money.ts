import { formatMoney, parseDecimal } from "../money";

export function formatHouseholdSourceAmount(amount: string, currency: string): string {
  if (currency === "EUR" || currency === "DKK") {
    return formatMoney(parseDecimal(amount), currency);
  }
  return `${amount} ${currency}`;
}

export function isHouseholdClassificationCurrency(value: string): value is "EUR" | "DKK" {
  return value === "EUR" || value === "DKK";
}
