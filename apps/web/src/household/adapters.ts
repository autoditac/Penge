import type { AccountSummary } from "../api/schemas";
import type {
  HouseholdAliasResponse,
  HouseholdCategoryResponse,
  HouseholdMerchantResponse,
  HouseholdPaymentDetailResponse,
  HouseholdRuleResponse,
  HouseholdTransactionResponse,
  VendorReferenceIndexStatusResponse,
  VendorReferenceSearchResponse,
} from "../api/schemas";
import type {
  HouseholdCategory,
  HouseholdMerchant,
  HouseholdMerchantAlias,
  HouseholdPaymentDetail,
  HouseholdRuleSummary,
  HouseholdTransactionDetail,
  ReviewTransaction,
  UnmatchedHouseholdPaymentDetail,
  VendorIndexStatus,
  VendorReferenceSearchResult,
} from "./types";
import { flattenHouseholdCategories } from "./categories";

type MutableCategory = {
  readonly row: HouseholdCategoryResponse;
  readonly children: MutableCategory[];
};

export function householdCategoryTree(
  rows: readonly HouseholdCategoryResponse[],
): readonly HouseholdCategory[] {
  const byId = new Map<string, MutableCategory>();
  for (const row of rows) {
    if (byId.has(row.id)) {
      throw new Error(`The household category response repeats category ${row.id}.`);
    }
    byId.set(row.id, { row, children: [] });
  }

  const roots: MutableCategory[] = [];
  for (const node of byId.values()) {
    if (node.row.parent_id === null) {
      roots.push(node);
      continue;
    }
    const parent = byId.get(node.row.parent_id);
    if (parent === undefined) {
      throw new Error(`Household category ${node.row.id} has a missing parent.`);
    }
    if (parent.row.kind !== node.row.kind) {
      throw new Error(`Household category ${node.row.id} has a parent with a different kind.`);
    }
    parent.children.push(node);
  }

  let visited = 0;
  const mapNode = (node: MutableCategory): HouseholdCategory => {
    visited += 1;
    return {
      id: node.row.id,
      label: node.row.name,
      kind: node.row.kind,
      parentId: node.row.parent_id,
      archived: node.row.archived,
      revision: node.row.revision,
      sortOrder: node.row.sort_order,
      children: node.children
        .sort((left, right) => left.row.sort_order - right.row.sort_order)
        .map(mapNode),
    };
  };
  const tree = roots.sort((left, right) => left.row.sort_order - right.row.sort_order).map(mapNode);
  if (visited !== rows.length) {
    throw new Error("The household category response contains a cycle.");
  }
  return tree;
}

export function mapHouseholdMerchants(
  rows: readonly HouseholdMerchantResponse[],
): readonly HouseholdMerchant[] {
  return rows.map((row) => ({
    id: row.id,
    name: row.name,
    identityKind: row.identity_kind,
    confirmed: row.confirmed,
    archived: row.archived,
    revision: row.revision,
    referenceSource: row.reference_source,
    referenceKey: row.reference_key,
    referenceVersion: row.reference_version,
  }));
}

export function mapVendorReferenceStatus(
  row: VendorReferenceIndexStatusResponse,
): VendorIndexStatus {
  return {
    status: row.status,
    sourceId: row.source_id,
    sourceVersion: row.source_version,
    checksum: row.checksum_sha256,
    packageIntegrity: row.package_integrity,
    candidateIntegrity: row.candidate_integrity,
    sourceUrl: row.source_url,
    license: row.license,
    attribution: row.attribution,
    attributionUrl: row.attribution_url,
    sourceGeneratedAt: row.source_generated_at,
    lastCheckedAt: row.last_checked_at,
    lastAttemptAt: row.last_attempt_at,
    lastSuccessAt: row.last_success_at,
    snapshotStartedAt: row.snapshot_started_at,
    snapshotCompletedAt: row.snapshot_completed_at,
    candidateVersion: row.candidate_version,
    activeGenerationId: row.active_generation_id,
    recordCount: row.record_count,
    errorCode: row.error_code,
    errorMessage: row.error_message,
  };
}

export function mapVendorReferenceSearch(
  row: VendorReferenceSearchResponse,
): VendorReferenceSearchResult {
  return {
    matchStatus: row.match_status,
    sourceStatus: row.source_status,
    sourceVersion: row.source_version,
    limit: row.limit,
    truncated: row.truncated,
    candidates: row.matches.map((match) => ({
      sourceKey: match.source_entity_id,
      sourceVersion: match.source_version,
      name: match.label,
      categoryPath: match.category_path,
      aliases: match.aliases,
      sourceUrl: match.source_url,
      license: match.license,
      wikidataId: match.wikidata_id,
      matchKind: match.match_kind,
    })),
  };
}

export function mapHouseholdAliases(
  rows: readonly HouseholdAliasResponse[],
): readonly HouseholdMerchantAlias[] {
  return rows.map((row) => ({
    id: row.id,
    merchantId: row.merchant_id,
    provider: row.provider,
    label: row.normalized,
    normalizedKey: row.normalized,
    confirmed: row.confirmed,
    revision: row.revision,
  }));
}

export function mapHouseholdRules(
  rows: readonly HouseholdRuleResponse[],
  merchants: readonly HouseholdMerchant[],
  categories: readonly HouseholdCategory[],
): readonly HouseholdRuleSummary[] {
  const merchantNames = new Map(merchants.map(({ id, name }) => [id, name]));
  const categoryPaths = new Map(
    flattenHouseholdCategories(categories).map(({ id, path }) => [id, path]),
  );
  return rows.map((row) => ({
    id: row.id,
    merchantName: merchantNames.get(row.merchant_id) ?? "Unknown household merchant",
    categoryPath:
      row.category_id === null ? null : (categoryPaths.get(row.category_id) ?? "Archived category"),
    treatment: row.treatment ?? "unclassified",
    version: row.version,
    state: row.state,
    explanation: row.explanation,
  }));
}

export function mapReviewTransaction(
  row: HouseholdTransactionResponse,
  merchants: readonly HouseholdMerchant[],
  categories: readonly HouseholdCategory[],
): ReviewTransaction {
  const classification = row.classification;
  const merchant = merchants.find(({ id }) => id === classification?.merchant_id);
  const categoryPaths = new Map(
    flattenHouseholdCategories(categories).map(({ id, path }) => [id, path]),
  );
  const categoryLabel =
    classification === null
      ? null
      : classification.allocations.length > 0
        ? classification.allocations
            .map(({ category_id }) => categoryPaths.get(category_id) ?? "Archived category")
            .join(" + ")
        : classification.treatment === "transfer"
          ? "Own-account transfer"
          : classification.treatment === "excluded"
            ? "Excluded"
            : classification.treatment === "unclassified"
              ? "Unclassified"
              : null;
  return {
    id: row.transaction_id,
    date: row.ts.slice(0, 10),
    description: row.description ?? row.counterparty ?? "Bank transaction",
    merchant: merchant?.name ?? row.counterparty,
    amount: row.amount,
    currency: row.currency,
    categoryLabel,
    reviewState:
      classification === null || classification.review_state === "unclassified"
        ? "unclassified"
        : classification.review_state === "needs_review"
          ? "needs_review"
          : "classified",
    assignmentReason: classification?.explanation ?? null,
    manuallyAssigned: classification?.provenance === "manual",
  };
}

export function mapHouseholdTransactionDetail(
  row: HouseholdTransactionResponse,
  accounts: readonly AccountSummary[],
  merchants: readonly HouseholdMerchant[],
  categories: readonly HouseholdCategory[],
  paymentDetails: readonly HouseholdPaymentDetailResponse[],
): HouseholdTransactionDetail {
  const classification = row.classification;
  const transaction = mapReviewTransaction(row, merchants, categories);
  const account = accounts.find(({ account_id }) => account_id === row.account_id);
  const detailRows = new Map(paymentDetails.map((payment) => [payment.id, payment]));
  const splits = classification?.allocations.map((allocation, index) => ({
    id: `${row.transaction_id}:${allocation.category_id}:${index}`,
    categoryId: allocation.category_id,
    amount: allocation.amount,
  }));
  const linkedPaymentDetails: HouseholdPaymentDetail[] = (
    classification?.detail_links ?? []
  ).flatMap((link) => {
    const payment = detailRows.get(link.detail_id);
    if (payment === undefined) {
      return [];
    }
    const current = link.detail_revision === payment.revision;
    return [
      {
        id: payment.id,
        revision: payment.revision,
        status: current ? "approved" : "stale",
        merchant: payment.merchant_name ?? null,
        reference: payment.reference ?? null,
        eventKind: payment.event_kind,
        originalAmount: payment.amount,
        originalCurrency: payment.currency,
        originalDate: payment.ts.slice(0, 10),
        bankAmount: link.bank_amount,
      },
    ];
  });
  return {
    transaction,
    accountLabel: account?.name ?? "Unknown account",
    entityLabel: account?.entity_name ?? "Unknown household member",
    treatment: classification?.treatment ?? "unclassified",
    classificationRevision: classification?.revision ?? 0,
    provenance: classification?.provenance ?? "none",
    ruleId: classification?.rule_id ?? null,
    explanation: classification?.explanation ?? null,
    sourceChanged: classification?.source_changed ?? false,
    detailChanged: classification?.detail_changed ?? false,
    splits: splits ?? [],
    paymentDetails: linkedPaymentDetails,
  };
}

export function mapUnmatchedPaymentDetail(
  row: HouseholdPaymentDetailResponse,
): UnmatchedHouseholdPaymentDetail {
  return {
    id: row.id,
    revision: row.revision,
    eventKind: row.event_kind,
    merchant: row.merchant_name ?? null,
    reference: row.reference ?? null,
    originalAmount: row.amount,
    originalCurrency: row.currency,
    originalDate: row.ts.slice(0, 10),
  };
}
