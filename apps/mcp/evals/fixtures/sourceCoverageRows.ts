export const EVAL_TRANSACTION_ID = "11111111-1111-4111-8111-111111111111";
export const EVAL_ACCOUNT_ID = "22222222-2222-4222-8222-222222222222";
export const EVAL_CATEGORY_ID = "33333333-3333-4333-8333-333333333333";
export const EVAL_MERCHANT_ID = "44444444-4444-4444-8444-444444444444";
export const EVAL_AUDIT_ID = "55555555-5555-4555-8555-555555555555";
export const EVAL_DETAIL_ID = "66666666-6666-4666-8666-666666666666";

export const STALE_ECB_COVERAGE_ROW = {
  source_id: "ecb_fx",
  account_count: 0,
  transaction_count: 0,
  holding_count: 0,
  evidence_count: 10,
  latest_observed_at: "2026-09-20T00:00:00.000Z",
};

export const MISSING_FX_REPORT_ROW = {
  as_of: "2026-06-02",
  treatment: "expense",
  known_allocation_amount_eur: "-50.00000000",
  known_allocation_amount_dkk: "-373.00000000",
  missing_fx_count_eur: 1,
  missing_fx_count_dkk: 0,
};

export const TRANSACTION_DETAIL_ROW = {
  stable_id: EVAL_TRANSACTION_ID,
  source: "gls",
  account_id: EVAL_ACCOUNT_ID,
  booked_at: "2026-06-02T10:00:00.000Z",
  value_date: "2026-06-02",
  kind: "card",
  amount: "-125.4000",
  fee: "0.0000",
  tax: "0.0000",
  currency: "EUR",
  description: "Synthetic purchase",
  counterparty: "Synthetic Market",
  treatment: "expense",
  review_state: "classified",
  merchant_id: EVAL_MERCHANT_ID,
  merchant_name: "Synthetic Market",
  identity_confirmed: true,
  provenance: "manual",
  rule_id: null,
  revision: 2,
  explanation: "Synthetic manual classification",
};

export const ALLOCATION_DETAIL_ROW = {
  category_id: EVAL_CATEGORY_ID,
  category_name: "Groceries",
  category_kind: "expense",
  amount: "-125.4000",
  currency: "EUR",
  allocation_total: "-125.4000",
};

export const AUDIT_DETAIL_ROW = {
  audit_id: EVAL_AUDIT_ID,
  subject_type: "classification",
  action: "update",
  created_at: "2026-06-03T00:00:00.000Z",
};

export const PAYPAL_DETAIL_ROW = {
  detail_id: EVAL_DETAIL_ID,
  occurred_at: "2026-06-02T09:59:00.000Z",
  amount: "-125.4000",
  currency: "EUR",
  merchant_name: "Synthetic Market",
  reference: "Synthetic basket",
  event_kind: "purchase",
  detail_revision: 2,
  approved_detail_revision: 2,
  bank_amount: "-125.4000",
};
