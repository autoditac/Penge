export type HouseholdGranularity = "day" | "month" | "year";

export type HouseholdFilters = {
  readonly since: string;
  readonly until: string;
  readonly granularity: HouseholdGranularity;
  readonly accountIds: readonly string[];
  readonly entityIds: readonly string[];
  readonly categoryId: string | null;
};

export type HouseholdFilterOptions = {
  readonly accounts: readonly { readonly id: string; readonly label: string }[];
  readonly householdMembers: readonly { readonly id: string; readonly label: string }[];
  readonly categories: readonly { readonly id: string; readonly label: string }[];
};

export type HouseholdCategory = {
  readonly id: string;
  readonly label: string;
  readonly kind: "income" | "expense";
  readonly parentId: string | null;
  readonly archived: boolean;
  readonly revision: number;
  readonly sortOrder: number;
  readonly children: readonly HouseholdCategory[];
};

export type ReviewTransaction = {
  readonly id: string;
  readonly date: string;
  readonly description: string;
  readonly merchant: string | null;
  readonly amount: string;
  readonly currency: string;
  readonly categoryLabel: string | null;
  readonly reviewState: "unclassified" | "needs_review" | "classified";
  readonly assignmentReason: string | null;
  readonly manuallyAssigned: boolean;
};

export type TransactionSplitDraft = {
  readonly id: string;
  readonly categoryId: string;
  readonly amount: string;
};

export type HouseholdTreatment =
  "expense" | "income" | "refund" | "transfer" | "excluded" | "unclassified";

export type HouseholdPaymentDetail = {
  readonly id: string;
  readonly revision: number;
  readonly status: "review" | "approved" | "stale" | "mismatch";
  readonly merchant: string | null;
  readonly reference: string | null;
  readonly eventKind: string;
  readonly originalAmount: string;
  readonly originalCurrency: string;
  readonly originalDate: string;
  readonly bankAmount: string;
};

export type UnmatchedHouseholdPaymentDetail = {
  readonly id: string;
  readonly revision: number;
  readonly eventKind: "purchase" | "refund" | "funding" | "unknown";
  readonly merchant: string | null;
  readonly reference: string | null;
  readonly originalAmount: string;
  readonly originalCurrency: string;
  readonly originalDate: string;
};

export type HouseholdTransactionDetail = {
  readonly transaction: ReviewTransaction;
  readonly accountLabel: string;
  readonly entityLabel: string;
  readonly provider: string;
  readonly sourceCounterparty: string | null;
  readonly merchantId: string | null;
  readonly identityConfirmed: boolean;
  readonly treatment: HouseholdTreatment;
  readonly classificationRevision: number;
  readonly provenance: "manual" | "rule" | "none";
  readonly ruleId: string | null;
  readonly explanation: string | null;
  readonly sourceChanged: boolean;
  readonly detailChanged: boolean;
  readonly splits: readonly TransactionSplitDraft[];
  readonly paymentDetails: readonly HouseholdPaymentDetail[];
};

export type HouseholdRuleSummary = {
  readonly id: string;
  readonly merchantName: string;
  readonly categoryPath: string | null;
  readonly treatment: HouseholdTreatment;
  readonly version: number;
  readonly state: "active" | "conflict" | "disabled" | "insufficient";
  readonly explanation: string;
};

export type HistoricalRuleCandidate = {
  readonly transactionId: string;
  readonly date: string;
  readonly description: string;
  readonly currentCategory: string | null;
  readonly proposedCategory: string | null;
  readonly outcome: "will_change" | "manual_protected" | "conflict" | "already_matches";
  readonly reason: string;
};

export type HistoricalRulePreview = {
  readonly id: string;
  readonly applied: boolean;
  readonly candidates: readonly HistoricalRuleCandidate[];
};

export type HouseholdMerchant = {
  readonly id: string;
  readonly name: string;
  readonly identityKind: "stable" | "processor" | "marketplace" | "mixed" | "unknown";
  readonly confirmed: boolean;
  readonly archived: boolean;
  readonly revision: number;
  readonly referenceSource: string | null;
  readonly referenceKey: string | null;
  readonly referenceVersion: string | null;
};

export type HouseholdMerchantAlias = {
  readonly id: string;
  readonly merchantId: string;
  readonly provider: string;
  readonly label: string;
  readonly normalizedKey: string;
  readonly confirmed: boolean;
  readonly revision: number;
};

export type VendorIndexStatus = {
  readonly status: "never_refreshed" | "refreshing" | "current" | "stale" | "failed";
  readonly sourceId: string;
  readonly sourceVersion: string | null;
  readonly checksum: string | null;
  readonly packageIntegrity: string | null;
  readonly candidateIntegrity: string | null;
  readonly sourceUrl: string | null;
  readonly license: string | null;
  readonly attribution: string;
  readonly attributionUrl: string;
  readonly sourceGeneratedAt: string | null;
  readonly lastCheckedAt: string | null;
  readonly lastAttemptAt: string | null;
  readonly lastSuccessAt: string | null;
  readonly snapshotStartedAt: string | null;
  readonly snapshotCompletedAt: string | null;
  readonly candidateVersion: string | null;
  readonly activeGenerationId: string | null;
  readonly recordCount: number | null;
  readonly errorCode: string | null;
  readonly errorMessage: string | null;
};

export type VendorReferenceCandidate = {
  readonly sourceKey: string;
  readonly sourceVersion: string;
  readonly name: string;
  readonly categoryPath: string;
  readonly aliases: readonly string[];
  readonly sourceUrl: string;
  readonly license: string;
  readonly wikidataId: string | null;
  readonly matchKind: "exact_alias" | "substring";
};

export type VendorReferenceSearchResult = {
  readonly matchStatus: "no_match" | "unique" | "ambiguous";
  readonly sourceStatus: VendorIndexStatus["status"];
  readonly sourceVersion: string | null;
  readonly limit: number;
  readonly truncated: boolean;
  readonly candidates: readonly VendorReferenceCandidate[];
};
