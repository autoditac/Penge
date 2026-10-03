import { useState } from "react";
import WarningAmberOutlinedIcon from "@mui/icons-material/WarningAmberOutlined";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Checkbox from "@mui/material/Checkbox";
import Chip from "@mui/material/Chip";
import FormControl from "@mui/material/FormControl";
import FormControlLabel from "@mui/material/FormControlLabel";
import InputLabel from "@mui/material/InputLabel";
import MenuItem from "@mui/material/MenuItem";
import Paper from "@mui/material/Paper";
import Select from "@mui/material/Select";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import type {
  HouseholdCategory,
  HouseholdTreatment,
  HouseholdTransactionDetail,
  UnmatchedHouseholdPaymentDetail,
} from "../../household/types";
import type { HouseholdAuditResponse } from "../../api/schemas";
import type { TransactionSplitDraft } from "../../household/types";
import {
  formatHouseholdSourceAmount,
  isHouseholdClassificationCurrency,
} from "../../household/money";
import { CategoryPicker } from "./CategoryPicker";
import { SplitEditor } from "./SplitEditor";
import { Pill } from "../primitives";
import { splitsMatchTransaction } from "../../household/splits";

const treatmentLabels: Record<HouseholdTreatment, string> = {
  expense: "Expense",
  income: "Income",
  refund: "Refund",
  transfer: "Own-account transfer",
  excluded: "Exclude from household spending",
  unclassified: "Unclassified",
};

const treatmentOptions: readonly HouseholdTreatment[] = [
  "expense",
  "income",
  "refund",
  "transfer",
  "excluded",
  "unclassified",
];

type TransactionDetailPanelProps = {
  readonly detail: HouseholdTransactionDetail;
  readonly audit: readonly HouseholdAuditResponse[] | null;
  readonly auditLoading: boolean;
  readonly categories: readonly HouseholdCategory[];
  readonly saving: boolean;
  readonly onClose: () => void;
  readonly onSaveCorrection: (correction: {
    readonly treatment: HouseholdTreatment;
    readonly categoryId: string | null;
  }) => void;
  readonly onSaveSplits: (input: {
    readonly treatment: HouseholdTreatment;
    readonly splits: readonly TransactionSplitDraft[];
  }) => void;
  readonly onUndoOverride: () => void;
  readonly onDisableRule: (ruleId: string) => void;
  readonly unmatchedPaymentDetails: readonly UnmatchedHouseholdPaymentDetail[];
  readonly onApprovePaymentDetails: (
    links: readonly {
      readonly detailId: string;
      readonly detailRevision: number;
      readonly bankAmount: string;
    }[],
  ) => void;
};

export function TransactionDetailPanel({
  detail,
  audit,
  auditLoading,
  categories,
  saving,
  onClose,
  onSaveCorrection,
  onSaveSplits,
  onUndoOverride,
  onDisableRule,
  unmatchedPaymentDetails,
  onApprovePaymentDetails,
}: TransactionDetailPanelProps): React.JSX.Element {
  const [treatment, setTreatment] = useState(detail.treatment);
  const [categoryId, setCategoryId] = useState(
    detail.splits.length === 1 ? (detail.splits[0]?.categoryId ?? null) : null,
  );
  const categoryRequired =
    treatment === "expense" || treatment === "income" || treatment === "refund";
  const allocationCurrency = isHouseholdClassificationCurrency(detail.transaction.currency)
    ? detail.transaction.currency
    : null;

  return (
    <Paper
      component="section"
      variant="outlined"
      aria-label={`Transaction detail: ${detail.transaction.description}`}
      sx={{ p: { xs: 1.75, sm: 2.25 }, borderRadius: 3.5, minWidth: 0 }}
    >
      <Stack
        direction="row"
        sx={{ justifyContent: "space-between", alignItems: "flex-start", gap: 1 }}
      >
        <Box>
          <Typography component="h2" variant="h6" sx={{ fontWeight: 700 }}>
            Transaction detail
          </Typography>
          <Typography color="text.secondary">{detail.transaction.description}</Typography>
        </Box>
        <Button onClick={onClose} aria-label="Close transaction detail">
          Close
        </Button>
      </Stack>
      <Stack spacing={2} sx={{ mt: 2 }}>
        <SourceFacts detail={detail} />
        <AuditHistory entries={audit} loading={auditLoading} />
        <ClassificationControls
          detail={detail}
          categories={categories}
          treatment={treatment}
          categoryId={categoryId}
          categoryRequired={categoryRequired}
          canCategorize={allocationCurrency !== null}
          saving={saving}
          onTreatmentChange={setTreatment}
          onCategoryChange={setCategoryId}
          onSave={() =>
            onSaveCorrection({ treatment, categoryId: categoryRequired ? categoryId : null })
          }
          onUndoOverride={onUndoOverride}
          onDisableRule={onDisableRule}
        />
        {categoryRequired && allocationCurrency !== null ? (
          <Paper variant="outlined" sx={{ p: 1.5, bgcolor: "background.default" }}>
            <Typography component="h3" variant="subtitle1" sx={{ fontWeight: 700, mb: 1 }}>
              Split transaction
            </Typography>
            <SplitEditor
              key={`${detail.transaction.id}:${detail.classificationRevision}`}
              transactionAmount={detail.transaction.amount}
              currency={allocationCurrency}
              categories={categories}
              initialSplits={detail.splits}
              onSave={(splits) => onSaveSplits({ treatment, splits })}
            />
          </Paper>
        ) : null}
        {categoryRequired && allocationCurrency === null ? (
          <Alert severity="warning">
            Category allocations require EUR or DKK source precision. Choose transfer, excluded or
            unclassified until this source currency is supported.
          </Alert>
        ) : null}
        <PaymentDetails
          key={detail.paymentDetails
            .map((payment) => `${payment.id}:${payment.revision}:${payment.bankAmount}`)
            .join("|")}
          details={detail.paymentDetails}
          unmatchedDetails={unmatchedPaymentDetails}
          bankCurrency={detail.transaction.currency}
          bankAmount={detail.transaction.amount}
          onApprove={onApprovePaymentDetails}
          saving={saving}
        />
      </Stack>
    </Paper>
  );
}

function AuditHistory({
  entries,
  loading,
}: {
  readonly entries: readonly HouseholdAuditResponse[] | null;
  readonly loading: boolean;
}): React.JSX.Element {
  return (
    <Box component="section" aria-label="Classification audit history">
      <Typography component="h3" variant="subtitle1" sx={{ fontWeight: 700, mb: 0.75 }}>
        Classification history
      </Typography>
      {loading ? (
        <Typography color="text.secondary">Loading classification history…</Typography>
      ) : entries === null ? (
        <Typography color="text.secondary">Classification history is unavailable.</Typography>
      ) : entries.length === 0 ? (
        <Typography color="text.secondary">
          No classification changes have been recorded.
        </Typography>
      ) : (
        <Stack component="ol" spacing={0.75} sx={{ m: 0, pl: 2.5 }}>
          {entries.map((entry) => (
            <Box component="li" key={entry.id}>
              <Typography>
                {entry.action.replaceAll("_", " ")} · {entry.actor} ·{" "}
                <time dateTime={entry.created_at}>{entry.created_at}</time>
              </Typography>
            </Box>
          ))}
        </Stack>
      )}
    </Box>
  );
}

function SourceFacts({
  detail,
}: {
  readonly detail: HouseholdTransactionDetail;
}): React.JSX.Element {
  const transaction = detail.transaction;
  return (
    <Box
      component="dl"
      sx={{
        display: "grid",
        gridTemplateColumns: { xs: "1fr", sm: "max-content minmax(0, 1fr)" },
        columnGap: 2,
        rowGap: 0.5,
        m: 0,
        "& dt": { color: "text.secondary", fontWeight: 600 },
        "& dd": { m: 0, minWidth: 0, overflowWrap: "anywhere" },
      }}
    >
      <Box component="dt">Date</Box>
      <Box component="dd">{transaction.date}</Box>
      <Box component="dt">Original bank amount</Box>
      <Box component="dd">
        <strong>{formatHouseholdSourceAmount(transaction.amount, transaction.currency)}</strong>
        <Typography component="span" color="text.secondary" sx={{ ml: 1 }}>
          {transaction.amount} {transaction.currency}
        </Typography>
      </Box>
      <Box component="dt">Account</Box>
      <Box component="dd">{detail.accountLabel}</Box>
      <Box component="dt">Household member</Box>
      <Box component="dd">{detail.entityLabel}</Box>
      <Box component="dt">Merchant</Box>
      <Box component="dd">{transaction.merchant ?? "Not confirmed"}</Box>
      {detail.sourceChanged ? (
        <>
          <Box component="dt">Source status</Box>
          <Box component="dd">
            <Pill tone="watch">Bank transaction changed since classification</Pill>
          </Box>
        </>
      ) : null}
      {detail.detailChanged ? (
        <>
          <Box component="dt">Payment detail status</Box>
          <Box component="dd">
            <Pill tone="watch">Linked payment detail changed; review before relying on it</Pill>
          </Box>
        </>
      ) : null}
    </Box>
  );
}

function ClassificationControls({
  detail,
  categories,
  treatment,
  categoryId,
  categoryRequired,
  canCategorize,
  saving,
  onTreatmentChange,
  onCategoryChange,
  onSave,
  onUndoOverride,
  onDisableRule,
}: {
  readonly detail: HouseholdTransactionDetail;
  readonly categories: readonly HouseholdCategory[];
  readonly treatment: HouseholdTreatment;
  readonly categoryId: string | null;
  readonly categoryRequired: boolean;
  readonly canCategorize: boolean;
  readonly saving: boolean;
  readonly onTreatmentChange: (treatment: HouseholdTreatment) => void;
  readonly onCategoryChange: (categoryId: string | null) => void;
  readonly onSave: () => void;
  readonly onUndoOverride: () => void;
  readonly onDisableRule: (ruleId: string) => void;
}): React.JSX.Element {
  function changeTreatment(value: string): void {
    const nextTreatment = treatmentOptions.find((option) => option === value);
    if (nextTreatment !== undefined) {
      onTreatmentChange(nextTreatment);
    }
  }

  function disableCurrentRule(): void {
    if (detail.ruleId !== null) {
      onDisableRule(detail.ruleId);
    }
  }

  return (
    <Stack spacing={1.5}>
      {detail.provenance === "manual" ? (
        <Alert
          severity="info"
          action={
            <Button onClick={onUndoOverride} disabled={saving}>
              Undo
            </Button>
          }
        >
          This transaction has a protected manual classification. Automatic rules will not overwrite
          it.
        </Alert>
      ) : detail.provenance === "rule" ? (
        <Alert
          severity="info"
          action={
            detail.ruleId === null ? undefined : (
              <Button onClick={disableCurrentRule} disabled={saving}>
                Disable rule
              </Button>
            )
          }
        >
          {detail.explanation ?? "Assigned by an automatic rule."}
        </Alert>
      ) : (
        <Alert severity="warning">This transaction has no confirmed classification.</Alert>
      )}
      {detail.explanation !== null && detail.provenance !== "rule" ? (
        <Typography color="text.secondary">{detail.explanation}</Typography>
      ) : null}
      <FormControl size="small" fullWidth>
        <InputLabel id="transaction-treatment-label">Treatment</InputLabel>
        <Select
          labelId="transaction-treatment-label"
          label="Treatment"
          value={treatment}
          onChange={(event) => changeTreatment(event.target.value)}
        >
          {treatmentOptions.map((option) => (
            <MenuItem key={option} value={option}>
              {treatmentLabels[option]}
            </MenuItem>
          ))}
        </Select>
      </FormControl>
      <CategoryPicker
        categories={categories}
        selectedId={categoryId}
        onSelect={onCategoryChange}
        disabled={!categoryRequired || !canCategorize}
      />
      <Button
        variant="contained"
        disabled={saving || (categoryRequired && (categoryId === null || !canCategorize))}
        onClick={onSave}
        sx={{ alignSelf: "flex-start" }}
      >
        Save correction
      </Button>
    </Stack>
  );
}

function PaymentDetails({
  details,
  unmatchedDetails,
  bankCurrency,
  bankAmount,
  onApprove,
  saving,
}: {
  readonly details: HouseholdTransactionDetail["paymentDetails"];
  readonly unmatchedDetails: readonly UnmatchedHouseholdPaymentDetail[];
  readonly bankCurrency: string;
  readonly bankAmount: string;
  readonly onApprove: TransactionDetailPanelProps["onApprovePaymentDetails"];
  readonly saving: boolean;
}): React.JSX.Element {
  const [selectedAmounts, setSelectedAmounts] = useState<Readonly<Record<string, string>>>(() =>
    Object.fromEntries(details.map((payment) => [payment.id, payment.bankAmount])),
  );
  const [reviewed, setReviewed] = useState(false);
  const selectedDetails = unmatchedDetails.filter(
    (payment) => selectedAmounts[payment.id] !== undefined,
  );
  const allLinkedDetails = details.every(({ id, eventKind }) => {
    const amount = selectedAmounts[id] ?? "";
    return eventKind !== "funding" && isSignedBankAmount(amount, bankAmount);
  });
  const allNewDetails = selectedDetails.every(({ id, eventKind }) => {
    const amount = selectedAmounts[id] ?? "";
    return eventKind !== "funding" && isSignedBankAmount(amount, bankAmount);
  });
  const conserved = splitsMatchTransaction(bankAmount, [
    ...details.map(({ id }) => selectedAmounts[id] ?? ""),
    ...selectedDetails.map(({ id }) => selectedAmounts[id] ?? ""),
  ]);
  const validAmounts = allLinkedDetails && allNewDetails;

  function toggleDetail(payment: UnmatchedHouseholdPaymentDetail, checked: boolean): void {
    setReviewed(false);
    setSelectedAmounts((current) => {
      const next: Record<string, string> = { ...current };
      if (checked) {
        next[payment.id] = "";
      } else {
        delete next[payment.id];
      }
      return next;
    });
  }

  function approveLinks(): void {
    if (!reviewed || selectedDetails.length === 0 || !validAmounts || !conserved) {
      return;
    }
    onApprove([
      ...details.map((payment) => ({
        detailId: payment.id,
        detailRevision: payment.revision,
        bankAmount: selectedAmounts[payment.id] ?? payment.bankAmount,
      })),
      ...selectedDetails.map((payment) => ({
        detailId: payment.id,
        detailRevision: payment.revision,
        bankAmount: selectedAmounts[payment.id] ?? "",
      })),
    ]);
  }

  if (details.length === 0 && unmatchedDetails.length === 0) {
    return (
      <Alert severity="info">
        No approved PayPal payment details are linked. This bank transaction remains the only
        spending record.
      </Alert>
    );
  }

  return (
    <Stack spacing={1.5}>
      {details.length > 0 ? (
        <>
          <Typography component="h3" variant="subtitle1" sx={{ fontWeight: 700 }}>
            Linked payment details
          </Typography>
          {details.map((payment) => (
            <Paper
              key={payment.id}
              variant="outlined"
              sx={{ p: 1.5, bgcolor: "background.default" }}
            >
              <Stack spacing={1}>
                <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
                  {payment.status === "approved" ? (
                    <Chip label="Approved detail" color="success" size="small" />
                  ) : (
                    <Chip label={`PayPal detail: ${payment.status}`} color="error" size="small" />
                  )}
                  {payment.eventKind === "unknown" ? (
                    <Chip
                      icon={<WarningAmberOutlinedIcon />}
                      label="Event kind unknown"
                      size="small"
                    />
                  ) : (
                    <Chip label={payment.eventKind} size="small" />
                  )}
                </Stack>
                <PaymentDetailFacts payment={payment} bankCurrency={bankCurrency} />
                <TextField
                  label={`Approved bank allocation (${bankCurrency})`}
                  value={selectedAmounts[payment.id] ?? payment.bankAmount}
                  onChange={(event) => {
                    setReviewed(false);
                    setSelectedAmounts((current) => ({
                      ...current,
                      [payment.id]: event.target.value,
                    }));
                  }}
                  disabled={saving}
                  size="small"
                  slotProps={{ htmlInput: { inputMode: "decimal" } }}
                  sx={{ maxWidth: { sm: 280 } }}
                />
                {payment.status === "stale" || payment.status === "mismatch" ? (
                  <Alert severity="warning">
                    Link details changed or no longer reconcile exactly. The bank amount remains
                    authoritative; review the link before relying on its detail.
                  </Alert>
                ) : null}
              </Stack>
            </Paper>
          ))}
        </>
      ) : null}
      {unmatchedDetails.length > 0 ? (
        <Paper
          component="section"
          variant="outlined"
          aria-label="Unmatched PayPal details"
          sx={{ p: 1.5, bgcolor: "background.default" }}
        >
          <Stack spacing={1.25}>
            <Box>
              <Typography component="h3" variant="subtitle1" sx={{ fontWeight: 700 }}>
                Unmatched PayPal details
              </Typography>
              <Typography color="text.secondary">
                Select only details that belong to this bank movement. Enter each signed amount in
                {` ${bankCurrency}`}; their sum must exactly equal the authoritative bank amount of
                {` ${bankAmount} ${bankCurrency}`}. Provider gross amounts never replace bank facts.
              </Typography>
            </Box>
            <Stack spacing={1}>
              {unmatchedDetails.map((payment) => (
                <Stack
                  key={payment.id}
                  direction={{ xs: "column", sm: "row" }}
                  spacing={1}
                  sx={{ alignItems: { sm: "center" }, justifyContent: "space-between" }}
                >
                  <FormControlLabel
                    control={
                      <Checkbox
                        checked={selectedAmounts[payment.id] !== undefined}
                        disabled={saving || payment.eventKind === "funding"}
                        onChange={(event) => toggleDetail(payment, event.target.checked)}
                        slotProps={{
                          input: {
                            "aria-label": `Select PayPal detail ${payment.merchant ?? payment.reference ?? payment.id}`,
                          },
                        }}
                      />
                    }
                    label={
                      <Box>
                        <Typography component="span" sx={{ display: "block", fontWeight: 600 }}>
                          {payment.merchant ?? payment.reference ?? "PayPal detail"}
                        </Typography>
                        <Typography component="span" color="text.secondary" variant="caption">
                          {payment.eventKind} · {payment.originalAmount} {payment.originalCurrency}{" "}
                          · {payment.originalDate} · revision {payment.revision}
                          {payment.eventKind === "funding"
                            ? " · wallet funding cannot be linked"
                            : ""}
                        </Typography>
                      </Box>
                    }
                  />
                  {selectedAmounts[payment.id] !== undefined ? (
                    <TextField
                      label={`Signed bank amount (${bankCurrency})`}
                      value={selectedAmounts[payment.id] ?? ""}
                      onChange={(event) => {
                        setReviewed(false);
                        setSelectedAmounts((current) => ({
                          ...current,
                          [payment.id]: event.target.value,
                        }));
                      }}
                      disabled={saving}
                      size="small"
                      slotProps={{ htmlInput: { inputMode: "decimal" } }}
                      sx={{ width: { xs: "100%", sm: 240 } }}
                    />
                  ) : null}
                </Stack>
              ))}
            </Stack>
            {selectedDetails.length > 0 ? (
              <>
                {!validAmounts || !conserved ? (
                  <Alert severity="warning">
                    Selected signed bank amounts must use cents, match the bank movement sign and
                    sum exactly to {bankAmount} {bankCurrency}.
                  </Alert>
                ) : null}
                <FormControlLabel
                  control={
                    <Checkbox
                      checked={reviewed}
                      onChange={(event) => setReviewed(event.target.checked)}
                      slotProps={{
                        input: {
                          "aria-label":
                            "I verified these provider details belong to this bank movement",
                        },
                      }}
                    />
                  }
                  label="I verified these details belong to this bank movement and approve the link."
                />
                <Button
                  variant="contained"
                  disabled={saving || !reviewed || !validAmounts || !conserved}
                  onClick={approveLinks}
                  sx={{ alignSelf: "flex-start" }}
                >
                  Approve selected PayPal links
                </Button>
              </>
            ) : null}
          </Stack>
        </Paper>
      ) : null}
    </Stack>
  );
}

function isSignedBankAmount(value: string, transactionAmount: string): boolean {
  const trimmed = value.trim();
  if (!/^-?(?:0|[1-9]\d*)(?:\.\d{1,2})?$/.test(trimmed) || /^-?0(?:\.0{1,2})?$/.test(trimmed)) {
    return false;
  }
  return trimmed.startsWith("-") === transactionAmount.trim().startsWith("-");
}

function PaymentDetailFacts({
  payment,
  bankCurrency,
}: {
  readonly payment: HouseholdTransactionDetail["paymentDetails"][number];
  readonly bankCurrency: string;
}): React.JSX.Element {
  return (
    <Box
      component="dl"
      sx={{ display: "grid", gridTemplateColumns: "max-content 1fr", gap: 0.5, m: 0 }}
    >
      <Box component="dt" sx={{ color: "text.secondary" }}>
        Merchant
      </Box>
      <Box component="dd" sx={{ m: 0 }}>
        {payment.merchant ?? "Not provided"}
      </Box>
      <Box component="dt" sx={{ color: "text.secondary" }}>
        Reference
      </Box>
      <Box component="dd" sx={{ m: 0 }}>
        {payment.reference ?? "Not provided"}
      </Box>
      <Box component="dt" sx={{ color: "text.secondary" }}>
        Provider amount
      </Box>
      <Box component="dd" sx={{ m: 0 }}>
        {payment.originalAmount} {payment.originalCurrency}
      </Box>
      <Box component="dt" sx={{ color: "text.secondary" }}>
        Provider date
      </Box>
      <Box component="dd" sx={{ m: 0 }}>
        {payment.originalDate}
      </Box>
      <Box component="dt" sx={{ color: "text.secondary" }}>
        Authoritative bank amount
      </Box>
      <Box component="dd" sx={{ m: 0 }}>
        {payment.bankAmount} {bankCurrency}
      </Box>
    </Box>
  );
}
