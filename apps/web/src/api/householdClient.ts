/** Validated client for audited household classification APIs (#330/#334). */

import { getJson, requestJson } from "./client";
import type { components, operations } from "./schema";
import type { ZodType } from "zod";
import {
  householdAliasesResponseSchema,
  householdAuditResponseSchema,
  householdCategoriesResponseSchema,
  householdMerchantsResponseSchema,
  householdPaymentDetailsResponseSchema,
  householdPreviewSchema,
  householdRulesResponseSchema,
  householdSuggestionSchema,
  householdTransactionSchema,
  householdTransactionsResponseSchema,
  householdClassificationSchema,
} from "./schemas";
import type {
  HouseholdAliasResponse,
  HouseholdAuditResponse,
  HouseholdCategoryResponse,
  HouseholdClassificationResponse,
  HouseholdMerchantResponse,
  HouseholdPaymentDetailResponse,
  HouseholdPreviewResponse,
  HouseholdRuleResponse,
  HouseholdSuggestionResponse,
  HouseholdTransactionResponse,
} from "./schemas";

type Schemas = components["schemas"];
type TransactionQuery = NonNullable<
  operations["transactions_household_transactions_get"]["parameters"]["query"]
>;

const listPageSize = 500;

async function fetchAllPages<T>(
  path: string,
  schema: ZodType<T[]>,
  extraParams: Readonly<Record<string, string | number | undefined>> = {},
): Promise<T[]> {
  const items: T[] = [];
  let offset = 0;
  while (true) {
    const page = await getJson(path, { ...extraParams, limit: listPageSize, offset }, schema);
    items.push(...page);
    if (page.length < listPageSize) {
      return items;
    }
    offset += page.length;
  }
}

export function fetchAllHouseholdCategories(): Promise<HouseholdCategoryResponse[]> {
  return fetchAllPages("/household/categories", householdCategoriesResponseSchema);
}

export function createHouseholdCategory(
  body: Schemas["CategoryWrite"],
): Promise<HouseholdCategoryResponse> {
  return requestJson(
    "/household/categories",
    { method: "POST", jsonBody: body },
    householdCategoriesResponseSchema.element,
  );
}

export function updateHouseholdCategory(
  categoryId: string,
  body: Schemas["CategoryWrite"],
): Promise<HouseholdCategoryResponse> {
  return requestJson(
    `/household/categories/${encodeURIComponent(categoryId)}`,
    { method: "PATCH", jsonBody: body },
    householdCategoriesResponseSchema.element,
  );
}

export function fetchAllHouseholdMerchants(): Promise<HouseholdMerchantResponse[]> {
  return fetchAllPages("/household/merchants", householdMerchantsResponseSchema);
}

export function createHouseholdMerchant(
  body: Schemas["MerchantWrite"],
): Promise<HouseholdMerchantResponse> {
  return requestJson(
    "/household/merchants",
    { method: "POST", jsonBody: body },
    householdMerchantsResponseSchema.element,
  );
}

export function updateHouseholdMerchant(
  merchantId: string,
  body: Schemas["MerchantWrite"],
): Promise<HouseholdMerchantResponse> {
  return requestJson(
    `/household/merchants/${encodeURIComponent(merchantId)}`,
    { method: "PATCH", jsonBody: body },
    householdMerchantsResponseSchema.element,
  );
}

export function fetchAllHouseholdAliases(): Promise<HouseholdAliasResponse[]> {
  return fetchAllPages("/household/aliases", householdAliasesResponseSchema);
}

export function createHouseholdAlias(body: Schemas["AliasWrite"]): Promise<HouseholdAliasResponse> {
  return requestJson(
    "/household/aliases",
    { method: "POST", jsonBody: body },
    householdAliasesResponseSchema.element,
  );
}

export function updateHouseholdAlias(
  aliasId: string,
  body: Schemas["AliasWrite"],
): Promise<HouseholdAliasResponse> {
  return requestJson(
    `/household/aliases/${encodeURIComponent(aliasId)}`,
    { method: "PATCH", jsonBody: body },
    householdAliasesResponseSchema.element,
  );
}

export function fetchAllHouseholdRules(): Promise<HouseholdRuleResponse[]> {
  return fetchAllPages("/household/rules", householdRulesResponseSchema);
}

export function updateHouseholdRule(
  ruleId: string,
  body: Schemas["RuleControl"],
): Promise<HouseholdRuleResponse> {
  return requestJson(
    `/household/rules/${encodeURIComponent(ruleId)}`,
    { method: "PATCH", jsonBody: body },
    householdRulesResponseSchema.element,
  );
}

export function previewHouseholdRule(
  ruleId: string,
  limit = listPageSize,
  offset = 0,
): Promise<HouseholdPreviewResponse> {
  return requestJson(
    `/household/rules/${encodeURIComponent(ruleId)}/preview`,
    { method: "POST", params: { limit, offset } },
    householdPreviewSchema,
  );
}

export function fetchHouseholdPreview(previewId: string): Promise<HouseholdPreviewResponse> {
  return getJson(
    `/household/previews/${encodeURIComponent(previewId)}`,
    {},
    householdPreviewSchema,
  );
}

export function applyHouseholdPreview(previewId: string): Promise<HouseholdPreviewResponse> {
  return requestJson(
    `/household/previews/${encodeURIComponent(previewId)}/apply`,
    { method: "POST", jsonBody: { approve: true } satisfies Schemas["ApplyPreview"] },
    householdPreviewSchema,
  );
}

export function fetchHouseholdTransactions(
  query: TransactionQuery = {},
): Promise<HouseholdTransactionResponse[]> {
  return getJson(
    "/household/transactions",
    {
      account_id: query.account_id ?? undefined,
      category_id: query.category_id ?? undefined,
      currency: query.currency ?? undefined,
      from_date: query.from_date ?? undefined,
      limit: query.limit ?? undefined,
      merchant_id: query.merchant_id ?? undefined,
      offset: query.offset ?? undefined,
      provider: query.provider ?? undefined,
      review_state: query.review_state ?? undefined,
      search: query.search ?? undefined,
      to_date: query.to_date ?? undefined,
      treatment: query.treatment ?? undefined,
    },
    householdTransactionsResponseSchema,
  );
}

export function fetchHouseholdTransaction(
  transactionId: string,
): Promise<HouseholdTransactionResponse> {
  return getJson(
    `/household/transactions/${encodeURIComponent(transactionId)}`,
    {},
    householdTransactionSchema,
  );
}

export function correctHouseholdTransaction(
  transactionId: string,
  body: Schemas["ClassificationWrite"],
): Promise<HouseholdClassificationResponse> {
  return requestJson(
    `/household/transactions/${encodeURIComponent(transactionId)}/classification`,
    { method: "PATCH", jsonBody: body },
    householdClassificationSchema,
  );
}

export function undoHouseholdTransaction(
  transactionId: string,
  body: Schemas["Undo"],
): Promise<HouseholdClassificationResponse> {
  return requestJson(
    `/household/transactions/${encodeURIComponent(transactionId)}/undo`,
    { method: "POST", jsonBody: body },
    householdClassificationSchema,
  );
}

export function fetchHouseholdSuggestion(
  transactionId: string,
): Promise<HouseholdSuggestionResponse> {
  return getJson(
    `/household/transactions/${encodeURIComponent(transactionId)}/suggestion`,
    {},
    householdSuggestionSchema,
  );
}

export function fetchHouseholdAudit(subjectId: string): Promise<HouseholdAuditResponse[]> {
  return fetchAllPages("/household/audit", householdAuditResponseSchema, { subject_id: subjectId });
}

export function fetchAllHouseholdPaymentDetails(): Promise<HouseholdPaymentDetailResponse[]> {
  return fetchAllPages("/household/payment-details", householdPaymentDetailsResponseSchema);
}

export function fetchUnmatchedHouseholdPaymentDetails(): Promise<HouseholdPaymentDetailResponse[]> {
  return fetchAllPages("/household/payment-details", householdPaymentDetailsResponseSchema, {
    unmatched: "true",
  });
}
