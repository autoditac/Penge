const decimalPattern = /^([+-]?)(\d+)(?:\.(\d+))?$/;

function decimalToInteger(value: string, scale: number): bigint | null {
  const match = decimalPattern.exec(value.trim());
  if (match === null) {
    return null;
  }

  const fraction = match[3] ?? "";
  if (fraction.length > scale) {
    return null;
  }
  const magnitude = BigInt(`${match[2]}${fraction.padEnd(scale, "0")}`);
  return match[1] === "-" ? -magnitude : magnitude;
}

/** Compares decimal amounts exactly without converting financial values to floating point. */
export function splitsMatchTransaction(
  transactionAmount: string,
  splitAmounts: readonly string[],
): boolean {
  const amounts = [transactionAmount, ...splitAmounts];
  const scale = amounts.reduce<number>((current, amount) => {
    const match = decimalPattern.exec(amount.trim());
    return match === null ? current : Math.max(current, (match[3] ?? "").length);
  }, 0);
  const values = amounts.map((amount) => decimalToInteger(amount, scale));
  if (values.some((value) => value === null)) {
    return false;
  }

  const [transaction, ...splits] = values;
  if (transaction === undefined || transaction === null) {
    return false;
  }
  const splitTotal = splits.reduce<bigint>((total, amount) => {
    return amount === null || amount === undefined ? total : total + amount;
  }, 0n);
  return splits.every((amount) => amount !== null) && transaction === splitTotal;
}
