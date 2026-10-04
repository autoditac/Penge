/** Live household review and correction surfaces backed by `/household` APIs. */

import { useState } from "react";
import { useLocation, useNavigate } from "react-router";
import Alert from "@mui/material/Alert";
import Button from "@mui/material/Button";
import Tab from "@mui/material/Tab";
import Tabs from "@mui/material/Tabs";
import Stack from "@mui/material/Stack";

import { useAccounts } from "../api/queries";
import {
  useHouseholdReportCategories,
  useHouseholdReportSummary,
  useHouseholdReportTransactions,
} from "../api/householdReportQueries";
import {
  useApplyHouseholdPreview,
  useControlHouseholdRule,
  useCorrectHouseholdTransaction,
  useHouseholdAudit,
  useHouseholdAliases,
  useHouseholdCategories,
  useHouseholdMerchants,
  useHouseholdPaymentDetails,
  useHouseholdPreview,
  useHouseholdRules,
  useHouseholdTransaction,
  useInfiniteHouseholdTransactions,
  usePreviewHouseholdRule,
  useSaveHouseholdAlias,
  useSaveHouseholdCategory,
  useSaveHouseholdMerchant,
  useUndoHouseholdTransaction,
  useUnmatchedHouseholdPaymentDetails,
} from "../api/householdQueries";
import {
  useVendorReferenceIndexStatus,
  useVendorReferenceSearch,
} from "../api/vendorReferenceQueries";
import type { components } from "../api/schema";
import type { HouseholdTransactionResponse } from "../api/schemas";
import { useNotify } from "../components/Notifications";
import { CategoryManagementPanel } from "../components/household/CategoryManagementPanel";
import { HouseholdDashboardView } from "../components/household/HouseholdDashboardView";
import { MerchantManagementPanel } from "../components/household/MerchantManagementPanel";
import { RuleManagementPanel } from "../components/household/RuleManagementPanel";
import { TransactionDetailPanel } from "../components/household/TransactionDetailPanel";
import { TransactionReviewList } from "../components/household/TransactionReviewList";
import {
  householdCategoryTree,
  mapHouseholdTransactionDetail,
  mapHouseholdAliases,
  mapReviewTransaction,
  mapUnmatchedPaymentDetail,
  mapHouseholdRules,
  mapHouseholdMerchants,
  mapVendorReferenceSearch,
  mapVendorReferenceStatus,
} from "../household/adapters";
import { flattenHouseholdCategories } from "../household/categories";
import { isHouseholdClassificationCurrency } from "../household/money";
import { householdReportViewData } from "../household/reporting";
import { EmptyState, ErrorState, LoadingState, PageHeader, Panel } from "../components/primitives";
import type {
  HouseholdCategory,
  HouseholdFilters,
  HouseholdTreatment,
  TransactionSplitDraft,
} from "../household/types";

type CategoryWrite = components["schemas"]["CategoryWrite"];
type ClassificationWrite = components["schemas"]["ClassificationWrite"];
type PaymentDetailLinkInput = components["schemas"]["PaymentDetailLink-Input"];
type ReconciliationLink = components["schemas"]["ReconciliationLink"];
type SplitInput = components["schemas"]["Split-Input"];

const householdTabs = [
  { path: "/household/report", label: "Overview" },
  { path: "/household", label: "Transactions" },
  { path: "/household/categories", label: "Categories" },
  { path: "/household/merchants", label: "Merchants" },
  { path: "/household/rules", label: "Rules" },
] as const;

export function HouseholdPage(): React.JSX.Element {
  const location = useLocation();
  const navigate = useNavigate();
  const selectedTab =
    householdTabs.find(({ path }) => path === location.pathname)?.path ?? "/household/report";
  return (
    <>
      <PageHeader
        title="Household income and expenses"
        description="Review actual household income, expenses, classifications and source coverage."
      />
      <Tabs
        value={selectedTab}
        onChange={(_event, value: string) => navigate(value)}
        variant="scrollable"
        scrollButtons="auto"
        aria-label="Household spending surfaces"
      >
        {householdTabs.map(({ path, label }) => (
          <Tab key={path} value={path} label={label} sx={{ minHeight: 48 }} />
        ))}
      </Tabs>
      {selectedTab === "/household/categories" ? (
        <HouseholdCategoriesPage />
      ) : selectedTab === "/household/merchants" ? (
        <HouseholdMerchantsPage />
      ) : selectedTab === "/household/rules" ? (
        <HouseholdRulesPage />
      ) : selectedTab === "/household/report" ? (
        <HouseholdDashboardPage />
      ) : (
        <HouseholdReviewPage />
      )}
    </>
  );
}

function HouseholdDashboardPage(): React.JSX.Element {
  const accounts = useAccounts();
  const categoriesQuery = useHouseholdCategories();
  const [filters, setFilters] = useState<HouseholdFilters>(() => initialHouseholdFilters());
  const [drilldownFilters, setDrilldownFilters] = useState<HouseholdFilters | null>(null);
  const transactionLimit = 100;
  const report = useHouseholdReportSummary(filters);
  const categoryReport = useHouseholdReportCategories(filters);
  const activeDrilldown = drilldownFilters ?? filters;
  const reportTransactions = useHouseholdReportTransactions(
    activeDrilldown,
    transactionLimit,
    drilldownFilters !== null,
  );

  const queryError =
    accounts.error ?? categoriesQuery.error ?? report.error ?? categoryReport.error ?? null;
  if (
    accounts.isPending ||
    categoriesQuery.isPending ||
    report.isPending ||
    categoryReport.isPending
  ) {
    return <LoadingState label="household income and expense report" />;
  }
  if (queryError !== null) {
    return (
      <ErrorState
        label="household income and expense report"
        error={queryError}
        onRetry={() => {
          void accounts.refetch();
          void categoriesQuery.refetch();
          void report.refetch();
          void categoryReport.refetch();
        }}
      />
    );
  }
  if (
    accounts.data === undefined ||
    categoriesQuery.data === undefined ||
    report.data === undefined ||
    categoryReport.data === undefined
  ) {
    return (
      <ErrorState
        label="household income and expense report"
        error={new Error("Household report data was not returned.")}
        onRetry={() => {
          void accounts.refetch();
          void categoriesQuery.refetch();
          void report.refetch();
          void categoryReport.refetch();
        }}
      />
    );
  }
  const categories = householdCategoryTree(categoriesQuery.data);
  const filterOptions = {
    accounts: accounts.data
      .filter(({ reporting_kind }) => reporting_kind === "checking")
      .map(({ account_id, name, entity_name }) => ({
        id: account_id,
        label: `${name} · ${entity_name}`,
      })),
    householdMembers: [
      ...new Map(
        accounts.data
          .filter(({ reporting_kind }) => reporting_kind === "checking")
          .map(({ entity_id, entity_name }) => [entity_id, entity_name]),
      ).entries(),
    ].map(([id, label]) => ({ id, label })),
    categories: flattenHouseholdCategories(categories).map(({ id, path }) => ({
      id,
      label: path,
    })),
  };
  const viewData = householdReportViewData(report.data, categoryReport.data);
  const onDrilldown = (next: HouseholdFilters): void => {
    setFilters(next);
    setDrilldownFilters(next);
  };
  return (
    <HouseholdDashboardView
      filters={filters}
      filterOptions={filterOptions}
      report={viewData}
      onFiltersChange={(next) => {
        setFilters(next);
        setDrilldownFilters(null);
      }}
      onDrilldown={onDrilldown}
      showTransactions={drilldownFilters !== null}
      transactions={reportTransactions.data?.pages.flatMap(({ items }) => items)}
      transactionTotal={reportTransactions.data?.pages.at(-1)?.total}
      transactionOffset={
        reportTransactions.data?.pages
          .slice(0, -1)
          .reduce((total, page) => total + page.items.length, 0) ?? 0
      }
      transactionsLoading={reportTransactions.isPending}
      transactionsError={reportTransactions.error}
      onRetryTransactions={() => void reportTransactions.refetch()}
      onLoadMoreTransactions={() => {
        void reportTransactions.fetchNextPage();
      }}
    />
  );
}

function initialHouseholdFilters(): HouseholdFilters {
  const today = localDateInputValue(new Date());
  return {
    since: `${today.slice(0, 7)}-01`,
    until: today,
    granularity: "month",
    accountIds: [],
    entityIds: [],
    categoryId: null,
  };
}

function localDateInputValue(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function HouseholdCategoriesPage(): React.JSX.Element {
  const categories = useHouseholdCategories();
  const saveCategory = useSaveHouseholdCategory();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const notify = useNotify();

  if (categories.isPending) {
    return <LoadingState label="household categories" />;
  }
  if (categories.isError) {
    return (
      <ErrorState
        label="household categories"
        error={categories.error}
        onRetry={() => void categories.refetch()}
      />
    );
  }

  const categoryTree = householdCategoryTree(categories.data);
  return (
    <CategoryManagementPanel
      categories={categoryTree}
      selectedId={selectedId}
      saving={saveCategory.isPending}
      error={saveCategory.error?.message ?? null}
      onSelect={setSelectedId}
      onSave={(categoryId, values) => {
        const body: CategoryWrite = {
          archived: values.archived,
          expected_revision: values.expectedRevision,
          kind: values.kind,
          name: values.name,
          parent_id: values.parentId,
          sort_order: values.sortOrder,
        };
        saveCategory.mutate(
          { id: categoryId, body },
          {
            onSuccess: () => notify("Household category saved.", "success"),
            onError: (error) => notify(error.message, "error"),
          },
        );
      }}
    />
  );
}

function HouseholdMerchantsPage(): React.JSX.Element {
  const merchantResponse = useHouseholdMerchants();
  const aliasResponse = useHouseholdAliases();
  const saveMerchant = useSaveHouseholdMerchant();
  const saveAlias = useSaveHouseholdAlias();
  const vendorStatusResponse = useVendorReferenceIndexStatus();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [referenceQuery, setReferenceQuery] = useState<string | null>(null);
  const referenceSearchResponse = useVendorReferenceSearch(referenceQuery);
  const notify = useNotify();

  if (merchantResponse.isPending || aliasResponse.isPending) {
    return <LoadingState label="household merchant identities" />;
  }
  const error = merchantResponse.error ?? aliasResponse.error;
  if (error !== null) {
    return (
      <ErrorState
        label="household merchant identities"
        error={error}
        onRetry={() => {
          void merchantResponse.refetch();
          void aliasResponse.refetch();
        }}
      />
    );
  }
  if (merchantResponse.data === undefined || aliasResponse.data === undefined) {
    return (
      <ErrorState
        label="household merchant identities"
        error={new Error("Household merchant data was not returned.")}
        onRetry={() => {
          void merchantResponse.refetch();
          void aliasResponse.refetch();
        }}
      />
    );
  }

  const merchantRows = mapHouseholdMerchants(merchantResponse.data);
  const aliasRows = mapHouseholdAliases(aliasResponse.data);
  return (
    <MerchantManagementPanel
      merchants={merchantRows}
      aliases={aliasRows}
      selectedMerchantId={selectedId}
      vendorStatus={
        vendorStatusResponse.data === undefined
          ? undefined
          : mapVendorReferenceStatus(vendorStatusResponse.data)
      }
      vendorStatusLoading={vendorStatusResponse.isPending}
      vendorStatusError={vendorStatusResponse.error?.message ?? null}
      saving={saveMerchant.isPending || saveAlias.isPending}
      error={saveMerchant.error?.message ?? saveAlias.error?.message ?? null}
      referenceSearch={
        referenceSearchResponse.data === undefined
          ? null
          : mapVendorReferenceSearch(referenceSearchResponse.data)
      }
      referenceSearchLoading={referenceSearchResponse.isFetching}
      referenceSearchError={referenceSearchResponse.error?.message ?? null}
      onSelectMerchant={setSelectedId}
      onSearchReference={(query) => setReferenceQuery(query)}
      onSelectReference={(candidate) => {
        const merchant = merchantRows.find(({ id }) => id === selectedId);
        if (merchant === undefined) {
          notify("Select a household merchant before linking a public reference.", "error");
          return;
        }
        saveMerchant.mutate(
          {
            id: merchant.id,
            body: {
              archived: merchant.archived,
              confirmed: merchant.confirmed,
              expected_revision: merchant.revision,
              identity_kind: merchant.identityKind,
              name: merchant.name,
              reference_key: candidate.sourceKey,
              reference_source: "name-suggestion-index",
              reference_version: candidate.sourceVersion,
            },
          },
          {
            onSuccess: () => notify("Public reference provenance linked.", "success"),
            onError: (mutationError) => notify(mutationError.message, "error"),
          },
        );
      }}
      onCreateMerchant={(update) => {
        saveMerchant.mutate(
          {
            id: null,
            body: {
              archived: false,
              confirmed: update.confirmed,
              expected_revision: 0,
              identity_kind: update.identityKind,
              name: update.name,
            },
          },
          {
            onSuccess: (merchant) => {
              setSelectedId(merchant.id);
              notify("Household merchant created.", "success");
            },
            onError: (mutationError) => notify(mutationError.message, "error"),
          },
        );
      }}
      onSaveMerchant={(merchantId, expectedRevision, update) => {
        const merchant = merchantRows.find(({ id }) => id === merchantId);
        if (merchant === undefined) {
          notify("The selected merchant is no longer available. Reload before saving.", "error");
          return;
        }
        saveMerchant.mutate(
          {
            id: merchantId,
            body: {
              archived: merchant.archived,
              confirmed: update.confirmed,
              expected_revision: expectedRevision,
              identity_kind: update.identityKind,
              name: update.name,
              reference_key: merchant.referenceKey,
              reference_source: merchant.referenceSource,
              reference_version: merchant.referenceVersion,
            },
          },
          {
            onSuccess: () => notify("Household merchant identity saved.", "success"),
            onError: (mutationError) => notify(mutationError.message, "error"),
          },
        );
      }}
      onArchiveMerchant={(merchantId, expectedRevision) => {
        const merchant = merchantRows.find(({ id }) => id === merchantId);
        if (merchant === undefined) {
          notify("The selected merchant is no longer available. Reload before archiving.", "error");
          return;
        }
        saveMerchant.mutate(
          {
            id: merchantId,
            body: {
              archived: true,
              confirmed: merchant.confirmed,
              expected_revision: expectedRevision,
              identity_kind: merchant.identityKind,
              name: merchant.name,
              reference_key: merchant.referenceKey,
              reference_source: merchant.referenceSource,
              reference_version: merchant.referenceVersion,
            },
          },
          {
            onSuccess: () => notify("Household merchant archived.", "success"),
            onError: (mutationError) => notify(mutationError.message, "error"),
          },
        );
      }}
      onSaveAlias={(alias, update) => {
        saveAlias.mutate(
          {
            id: alias?.id ?? null,
            body: {
              confirmed: update.confirmed,
              expected_revision: alias?.revision ?? 0,
              label: update.label,
              merchant_id: update.merchantId,
              provider: update.provider,
            },
          },
          {
            onSuccess: () => notify("Normalized household provider alias saved.", "success"),
            onError: (mutationError) => notify(mutationError.message, "error"),
          },
        );
      }}
    />
  );
}

function HouseholdRulesPage(): React.JSX.Element {
  const ruleResponse = useHouseholdRules();
  const merchantResponse = useHouseholdMerchants();
  const categoryResponse = useHouseholdCategories();
  const controlRule = useControlHouseholdRule();
  const createPreview = usePreviewHouseholdRule();
  const applyPreview = useApplyHouseholdPreview();
  const [previewId, setPreviewId] = useState<string | null>(null);
  const previewQuery = useHouseholdPreview(previewId);
  const notify = useNotify();

  const initialError =
    ruleResponse.error ?? merchantResponse.error ?? categoryResponse.error ?? null;
  if (ruleResponse.isPending || merchantResponse.isPending || categoryResponse.isPending) {
    return <LoadingState label="household rules" />;
  }
  if (initialError !== null) {
    return (
      <ErrorState
        label="household rules"
        error={initialError}
        onRetry={() => {
          void ruleResponse.refetch();
          void merchantResponse.refetch();
          void categoryResponse.refetch();
        }}
      />
    );
  }
  if (
    ruleResponse.data === undefined ||
    merchantResponse.data === undefined ||
    categoryResponse.data === undefined
  ) {
    return (
      <ErrorState
        label="household rules"
        error={new Error("Household rule data was not returned.")}
        onRetry={() => {
          void ruleResponse.refetch();
          void merchantResponse.refetch();
          void categoryResponse.refetch();
        }}
      />
    );
  }
  const categories = householdCategoryTree(categoryResponse.data);
  const merchants = mapHouseholdMerchants(merchantResponse.data);
  const rules = mapHouseholdRules(ruleResponse.data, merchants, categories);
  const categoryPaths = new Map(
    flattenHouseholdCategories(categories).map(({ id, path }) => [id, path]),
  );
  const rawPreview = previewQuery.data;
  const rawRule =
    rawPreview === undefined
      ? null
      : (ruleResponse.data.find(({ id }) => id === rawPreview.rule_id) ?? null);
  const preview =
    rawPreview === undefined
      ? null
      : {
          id: rawPreview.id,
          applied: rawPreview.applied,
          candidates: rawPreview.candidates.map((candidate) => ({
            transactionId: candidate.transaction_id,
            date: candidate.source_ts.slice(0, 10),
            description:
              candidate.source_counterparty ?? candidate.normalized_counterparty ?? "Bank movement",
            currentCategory: null,
            proposedCategory:
              rawRule?.category_id === null || rawRule?.category_id === undefined
                ? null
                : (categoryPaths.get(rawRule.category_id) ?? "Archived category"),
            outcome: "will_change" as const,
            reason: [
              `Source revision ${candidate.expected_revision}`,
              `provider ${candidate.provider}`,
              `kind ${candidate.source_kind}`,
              `${candidate.source_amount} ${candidate.source_currency}`,
              candidate.alias_revision === null
                ? "no alias snapshot"
                : `alias revision ${candidate.alias_revision}`,
            ].join(" · "),
          })),
        };
  const pageError =
    controlRule.error ?? createPreview.error ?? applyPreview.error ?? previewQuery.error ?? null;

  return (
    <Stack spacing={2}>
      {pageError !== null ? <Alert severity="error">{pageError.message}</Alert> : null}
      <RuleManagementPanel
        rules={rules}
        preview={preview}
        saving={controlRule.isPending || createPreview.isPending || applyPreview.isPending}
        error={null}
        onDisable={(ruleId, expectedVersion) => {
          controlRule.mutate(
            { ruleId, body: { disabled: true, expected_version: expectedVersion } },
            {
              onSuccess: () =>
                notify("Rule disabled; previous automatic assignments need review.", "success"),
              onError: (error) => notify(error.message, "error"),
            },
          );
        }}
        onPreview={(ruleId) => {
          createPreview.mutate(ruleId, {
            onSuccess: (created) => {
              setPreviewId(created.id);
              notify(
                "Persisted historical preview created; no transactions were changed.",
                "success",
              );
            },
            onError: (error) => notify(error.message, "error"),
          });
        }}
        onApplyPreview={(id) => {
          applyPreview.mutate(id, {
            onSuccess: () => notify("Approved historical preview applied.", "success"),
            onError: (error) => notify(error.message, "error"),
          });
        }}
      />
      {previewId !== null && previewQuery.isError ? (
        <ErrorState
          label="persisted historical preview"
          error={previewQuery.error}
          onRetry={() => void previewQuery.refetch()}
        />
      ) : null}
    </Stack>
  );
}

function HouseholdReviewPage(): React.JSX.Element {
  const navigate = useNavigate();
  const [search, setSearch] = useState("");
  const [selectedTransactionId, setSelectedTransactionId] = useState<string | null>(null);
  const transactions = useInfiniteHouseholdTransactions(search);
  const accounts = useAccounts();
  const categories = useHouseholdCategories();
  const merchants = useHouseholdMerchants();
  const aliases = useHouseholdAliases();
  const rules = useHouseholdRules();
  const paymentDetails = useHouseholdPaymentDetails();
  const unmatchedPaymentDetails = useUnmatchedHouseholdPaymentDetails();
  const detailQuery = useHouseholdTransaction(selectedTransactionId);
  const auditQuery = useHouseholdAudit(selectedTransactionId);
  const correct = useCorrectHouseholdTransaction();
  const undo = useUndoHouseholdTransaction();
  const controlRule = useControlHouseholdRule();
  const notify = useNotify();

  const requiredQueries = [
    transactions,
    accounts,
    categories,
    merchants,
    aliases,
    rules,
    paymentDetails,
    unmatchedPaymentDetails,
  ] as const;
  const loading = requiredQueries.some((query) => query.isPending);
  const error = requiredQueries.find((query) => query.isError)?.error ?? null;
  if (loading) {
    return <LoadingState label="household transaction review" />;
  }
  if (error !== null) {
    return (
      <ErrorState
        label="household transaction review"
        error={error}
        onRetry={() => {
          for (const query of requiredQueries) {
            void query.refetch();
          }
        }}
      />
    );
  }
  if (
    transactions.data === undefined ||
    accounts.data === undefined ||
    categories.data === undefined ||
    merchants.data === undefined ||
    aliases.data === undefined ||
    rules.data === undefined ||
    paymentDetails.data === undefined ||
    unmatchedPaymentDetails.data === undefined
  ) {
    return (
      <ErrorState
        label="household transaction review"
        error={new Error("Household transaction review data was not returned.")}
        onRetry={() => {
          for (const query of requiredQueries) {
            void query.refetch();
          }
        }}
      />
    );
  }

  const categoryTree = householdCategoryTree(categories.data);
  const merchantRows = mapHouseholdMerchants(merchants.data);
  const ruleRows = rules.data;
  const transactionRows = transactions.data.pages.flat();
  const reviewRows = transactionRows.map((row) =>
    mapReviewTransaction(row, merchantRows, categoryTree),
  );
  const selectedRow = detailQuery.data;
  const detail =
    selectedRow === undefined
      ? null
      : mapHouseholdTransactionDetail(
          selectedRow,
          accounts.data,
          merchantRows,
          categoryTree,
          paymentDetails.data,
        );
  const saving = correct.isPending || undo.isPending || controlRule.isPending;
  const detailError = detailQuery.error ?? auditQuery.error;

  function makeClassificationWrite(
    treatment: HouseholdTreatment,
    allocations: readonly SplitInput[],
    detailLinks?: readonly PaymentDetailLinkInput[],
    identity?: {
      readonly merchantId: string | null;
      readonly confirmed: boolean;
    },
  ): ClassificationWrite {
    if (selectedRow === undefined) {
      throw new Error("The selected household transaction is not loaded.");
    }
    const current = selectedRow.classification;
    return {
      expected_revision: current?.revision ?? 0,
      treatment,
      merchant_id: identity === undefined ? (current?.merchant_id ?? null) : identity.merchantId,
      identity_confirmed: identity?.confirmed ?? current?.identity_confirmed ?? false,
      allocations: [...allocations],
      links: [...(current?.links ?? [])] satisfies ReconciliationLink[],
      detail_links: [...(detailLinks ?? current?.detail_links ?? [])],
      explanation: "Household correction approved in transaction review.",
    };
  }

  function saveCorrection(input: {
    readonly treatment: HouseholdTreatment;
    readonly categoryId: string | null;
    readonly merchantId: string | null;
    readonly identityConfirmed: boolean;
  }): void {
    if (detail === null) {
      return;
    }
    const category = categoryTree
      .flatMap((item) => flattenHouseholdCategories([item]))
      .find(({ id }) => id === input.categoryId);
    const splits: SplitInput[] =
      input.categoryId !== null &&
      input.treatment !== "transfer" &&
      input.treatment !== "excluded" &&
      input.treatment !== "unclassified"
        ? [{ category_id: input.categoryId, amount: detail.transaction.amount }]
        : [];
    if (input.categoryId !== null && category === undefined) {
      notify("The selected category is no longer available. Reload before saving.", "error");
      return;
    }
    correct.mutate(
      {
        transactionId: detail.transaction.id,
        body: makeClassificationWrite(input.treatment, splits, undefined, {
          merchantId: input.merchantId,
          confirmed: input.identityConfirmed,
        }),
      },
      {
        onSuccess: () => notify("Transaction correction saved.", "success"),
        onError: (mutationError) => notify(mutationError.message, "error"),
      },
    );
  }

  function saveSplits(input: {
    readonly treatment: HouseholdTreatment;
    readonly splits: readonly TransactionSplitDraft[];
  }): void {
    if (detail === null) {
      return;
    }
    correct.mutate(
      {
        transactionId: detail.transaction.id,
        body: makeClassificationWrite(
          input.treatment,
          input.splits.map(({ categoryId, amount }) => ({ category_id: categoryId, amount })),
        ),
      },
      {
        onSuccess: () => notify("Transaction allocations saved.", "success"),
        onError: (mutationError) => notify(mutationError.message, "error"),
      },
    );
  }

  function approvePaymentLinks(
    links: readonly {
      readonly detailId: string;
      readonly detailRevision: number;
      readonly bankAmount: string;
    }[],
  ): void {
    if (detail === null) {
      return;
    }
    correct.mutate(
      {
        transactionId: detail.transaction.id,
        body: makeClassificationWrite(
          detail.treatment,
          selectedRow?.classification?.allocations ?? [],
          links.map((link) => ({
            detail_id: link.detailId,
            detail_revision: link.detailRevision,
            bank_amount: link.bankAmount,
          })),
        ),
      },
      {
        onSuccess: () => notify("PayPal details linked to the bank movement.", "success"),
        onError: (mutationError) => notify(mutationError.message, "error"),
      },
    );
  }

  function undoOverride(): void {
    const latest = auditQuery.data?.[0];
    if (detail === null || latest === undefined || selectedRow?.classification === null) {
      notify("No correction history is available to undo. Reload transaction history.", "warning");
      return;
    }
    undo.mutate(
      {
        transactionId: detail.transaction.id,
        body: {
          audit_id: latest.id,
          expected_revision: detail.classificationRevision,
        },
      },
      {
        onSuccess: () =>
          notify("The previous classification was restored as a new manual revision.", "success"),
        onError: (mutationError) => notify(mutationError.message, "error"),
      },
    );
  }

  function disableCurrentRule(ruleId: string): void {
    const rule = ruleRows.find((candidate) => candidate.id === ruleId);
    if (rule === undefined) {
      notify("The current rule is no longer available. Reload before changing it.", "error");
      return;
    }
    controlRule.mutate(
      { ruleId, body: { disabled: true, expected_version: rule.version } },
      {
        onSuccess: () =>
          notify("Rule disabled; previous automatic assignments need review.", "success"),
        onError: (mutationError) => notify(mutationError.message, "error"),
      },
    );
  }

  return (
    <Stack spacing={2}>
      <Panel title="Review bank transactions">
        <TransactionReviewList
          transactions={reviewRows}
          categories={categoryTree}
          onOpen={setSelectedTransactionId}
          onBulkAssign={(transactionIds, categoryId) => {
            void bulkAssignTransactions({
              ids: transactionIds,
              categoryId,
              rows: transactionRows,
              categories: categoryTree,
              correct,
              notify,
            });
          }}
          searchValue={search}
          onSearchChange={setSearch}
          onLoadMore={() => void transactions.fetchNextPage()}
          hasMore={transactions.hasNextPage}
          loadingMore={transactions.isFetchingNextPage}
        />
      </Panel>
      {transactions.isFetchNextPageError ? (
        <Alert severity="error">
          More transactions could not be loaded: {transactions.error.message}
          <Button onClick={() => void transactions.fetchNextPage()}>Retry</Button>
        </Alert>
      ) : null}
      {selectedTransactionId !== null ? (
        <Panel title="Selected transaction">
          {detailQuery.isPending ? (
            <LoadingState label="selected transaction" />
          ) : detailError !== null ? (
            <ErrorState
              label="selected transaction"
              error={detailError}
              onRetry={() => {
                void detailQuery.refetch();
                void auditQuery.refetch();
              }}
            />
          ) : detail === null ? (
            <EmptyState label="selected transaction detail" />
          ) : (
            <TransactionDetailPanel
              key={`${detail.transaction.id}:${detail.classificationRevision}`}
              detail={detail}
              audit={auditQuery.data ?? null}
              auditLoading={auditQuery.isPending}
              categories={categoryTree}
              merchants={merchantRows}
              saving={saving}
              onManageMerchants={() => navigate("/household/merchants")}
              onClose={() => setSelectedTransactionId(null)}
              onSaveCorrection={saveCorrection}
              onSaveSplits={saveSplits}
              onUndoOverride={undoOverride}
              onDisableRule={disableCurrentRule}
              unmatchedPaymentDetails={unmatchedPaymentDetails.data
                .filter(({ id }) => !detail.paymentDetails.some((linked) => linked.id === id))
                .map(mapUnmatchedPaymentDetail)}
              onApprovePaymentDetails={approvePaymentLinks}
            />
          )}
        </Panel>
      ) : null}
    </Stack>
  );
}

async function bulkAssignTransactions({
  ids,
  categoryId,
  rows,
  categories,
  correct,
  notify,
}: {
  readonly ids: readonly string[];
  readonly categoryId: string;
  readonly rows: readonly HouseholdTransactionResponse[];
  readonly categories: readonly HouseholdCategory[];
  readonly correct: ReturnType<typeof useCorrectHouseholdTransaction>;
  readonly notify: ReturnType<typeof useNotify>;
}): Promise<void> {
  const category = flattenHouseholdCategories(categories).find(({ id }) => id === categoryId);
  if (category === undefined || category.archived) {
    notify("Choose an active category before applying the bulk correction.", "error");
    return;
  }
  const selectedRows = ids.map((id) => rows.find((row) => row.transaction_id === id));
  if (selectedRows.some((row) => row === undefined)) {
    notify(
      "Some selected transactions are no longer loaded. Refresh the list before retrying.",
      "error",
    );
    return;
  }
  const writes = selectedRows.map((row) => {
    if (row === undefined) {
      return null;
    }
    const sign = householdAmountSign(row.amount);
    const treatment: HouseholdTreatment =
      category.kind === "income" ? "income" : sign > 0 ? "refund" : "expense";
    if (
      sign === 0 ||
      !isHouseholdClassificationCurrency(row.currency) ||
      (category.kind === "income" && sign < 0)
    ) {
      return null;
    }
    const current = row.classification;
    return {
      row,
      body: {
        expected_revision: current?.revision ?? 0,
        treatment,
        merchant_id: current?.merchant_id ?? null,
        identity_confirmed: current?.identity_confirmed ?? false,
        allocations: [{ category_id: categoryId, amount: row.amount }],
        links: current?.links ?? [],
        detail_links: current?.detail_links ?? [],
        explanation: "Household bulk correction approved in transaction review.",
      } satisfies ClassificationWrite,
    };
  });
  if (writes.some((write) => write === null)) {
    notify(
      "The selected category and transaction signs are incompatible. Nothing was changed.",
      "error",
    );
    return;
  }

  let saved = 0;
  for (const write of writes) {
    if (write === null) {
      continue;
    }
    try {
      await correct.mutateAsync({ transactionId: write.row.transaction_id, body: write.body });
      saved += 1;
    } catch (error) {
      notify(
        `${saved} of ${writes.length} corrections were saved before a guarded write failed: ${error instanceof Error ? error.message : "Unknown API error"}`,
        "error",
      );
      return;
    }
  }
  notify(`${saved} transaction correction${saved === 1 ? "" : "s"} saved.`, "success");
}

function householdAmountSign(amount: string): -1 | 0 | 1 {
  const magnitude = amount.replace(/[+-]/g, "").replace(".", "");
  if (!/^\d+$/.test(magnitude) || /^0+$/.test(magnitude)) {
    return 0;
  }
  return amount.startsWith("-") ? -1 : 1;
}
