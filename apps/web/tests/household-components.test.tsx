/** Household review controls use only synthetic transaction and category data.
 * @vitest-environment jsdom
 */
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { CategoryTree } from "../src/components/household/CategoryTree";
import { CategoryPicker } from "../src/components/household/CategoryPicker";
import { CategoryManagementPanel } from "../src/components/household/CategoryManagementPanel";
import { MerchantManagementPanel } from "../src/components/household/MerchantManagementPanel";
import { HouseholdFilters } from "../src/components/household/HouseholdFilters";
import { ReportingMoneyPair } from "../src/components/household/ReportingMoneyPair";
import { RuleManagementPanel } from "../src/components/household/RuleManagementPanel";
import { SplitEditor } from "../src/components/household/SplitEditor";
import { TransactionDetailPanel } from "../src/components/household/TransactionDetailPanel";
import { TransactionReviewList } from "../src/components/household/TransactionReviewList";
import type {
  HouseholdCategory,
  HouseholdFilters as HouseholdFilterValues,
  HouseholdMerchant,
  HouseholdMerchantAlias,
  HouseholdRuleSummary,
  HistoricalRulePreview,
  HouseholdTransactionDetail,
  ReviewTransaction,
  TransactionSplitDraft,
  VendorIndexStatus,
  VendorReferenceCandidate,
  VendorReferenceSearchResult,
} from "../src/household/types";
import {
  categoryDrilldownFilters,
  householdTrendSeries,
  periodDrilldownFilters,
} from "../src/household/reporting";
import type { HouseholdTrendPoint } from "../src/household/reporting";
import { splitsMatchTransaction } from "../src/household/splits";
import { renderWithTheme } from "./test-utils";

const syntheticCategories: readonly HouseholdCategory[] = [
  {
    id: "housing",
    label: "Housing",
    kind: "expense",
    parentId: null,
    archived: false,
    revision: 1,
    sortOrder: 1,
    children: [
      {
        id: "utilities",
        label: "Utilities",
        kind: "expense",
        parentId: "housing",
        archived: false,
        revision: 1,
        sortOrder: 1,
        children: [],
      },
    ],
  },
  {
    id: "salary",
    label: "Salary",
    kind: "income",
    parentId: null,
    archived: false,
    revision: 1,
    sortOrder: 1,
    children: [],
  },
];

const syntheticTransactions: readonly ReviewTransaction[] = [
  {
    id: "bank-tx-1",
    date: "2026-04-03",
    description: "Synthetic card payment 1",
    merchant: "Example Market",
    amount: "-42.30",
    currency: "EUR",
    categoryLabel: null,
    reviewState: "unclassified",
    assignmentReason: null,
    manuallyAssigned: false,
  },
  {
    id: "bank-tx-2",
    date: "2026-04-04",
    description: "Synthetic recurring payment",
    merchant: "Example Utility",
    amount: "-20.00",
    currency: "EUR",
    categoryLabel: "Housing / Utilities",
    reviewState: "needs_review",
    assignmentReason: "Two matching vendor rules",
    manuallyAssigned: false,
  },
  {
    id: "bank-tx-3",
    date: "2026-04-05",
    description: "Synthetic salary payment",
    merchant: "Example Employer",
    amount: "1000.00",
    currency: "DKK",
    categoryLabel: "Salary",
    reviewState: "classified",
    assignmentReason: "Exact merchant rule",
    manuallyAssigned: true,
  },
];

const syntheticMerchants: readonly HouseholdMerchant[] = [
  {
    id: "merchant-market",
    name: "Example Market",
    identityKind: "stable",
    confirmed: true,
    archived: false,
    revision: 2,
    referenceSource: null,
    referenceKey: null,
    referenceVersion: null,
  },
  {
    id: "merchant-processor",
    name: "Example Processor",
    identityKind: "processor",
    confirmed: true,
    archived: false,
    revision: 1,
    referenceSource: null,
    referenceKey: null,
    referenceVersion: null,
  },
];

describe("HouseholdFilters", () => {
  it("updates one filter while retaining all other selected filters", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn<(next: HouseholdFilterValues) => void>();
    const filters: HouseholdFilterValues = {
      since: "2026-04-01",
      until: "2026-04-30",
      granularity: "month",
      accountIds: ["account-1"],
      entityIds: ["member-1"],
      categoryId: "housing",
    };

    renderWithTheme(
      <HouseholdFilters
        value={filters}
        options={{
          accounts: [{ id: "account-1", label: "Daily account" }],
          householdMembers: [{ id: "member-1", label: "Member one" }],
          categories: [{ id: "housing", label: "Housing" }],
        }}
        onChange={onChange}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Yearly" }));
    expect(onChange).toHaveBeenCalledWith({ ...filters, granularity: "year" });
  });
});

describe("CategoryTree", () => {
  it("exposes nested categories and invokes the category management actions", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    const onCreateChild = vi.fn();
    const onRename = vi.fn();
    const onReparent = vi.fn();
    const onArchive = vi.fn();

    renderWithTheme(
      <CategoryTree
        categories={syntheticCategories}
        selectedId={null}
        onSelect={onSelect}
        onCreateChild={onCreateChild}
        onRename={onRename}
        onReparent={onReparent}
        onArchive={onArchive}
      />,
    );

    const tree = screen.getByRole("tree", { name: "Household categories" });
    expect(within(tree).getByRole("treeitem", { name: /Utilities/ })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Add subcategory under Housing" }));
    await user.click(screen.getByRole("button", { name: "Rename Housing" }));
    await user.click(screen.getByRole("button", { name: "Move Housing" }));
    await user.click(screen.getByRole("button", { name: "Archive Housing" }));
    await user.click(screen.getByRole("button", { name: "Salary" }));

    expect(onCreateChild).toHaveBeenCalledWith("housing");
    expect(onRename).toHaveBeenCalledWith(syntheticCategories[0]);
    expect(onReparent).toHaveBeenCalledWith(syntheticCategories[0]);
    expect(onArchive).toHaveBeenCalledWith(syntheticCategories[0]);
    expect(onSelect).toHaveBeenCalledWith("salary");
  });

  describe("CategoryManagementPanel", () => {
    it("creates a child category within the same income/expense tree", async () => {
      const user = userEvent.setup();
      const onSave = vi.fn();
      renderWithTheme(
        <CategoryManagementPanel
          categories={syntheticCategories}
          selectedId={null}
          saving={false}
          error={null}
          onSelect={vi.fn()}
          onSave={onSave}
        />,
      );

      await user.click(screen.getByRole("button", { name: "Add expense category" }));
      await user.type(screen.getByRole("textbox", { name: "Category name" }), "Repairs");
      await user.click(screen.getByRole("combobox", { name: "Parent category" }));
      await user.click(screen.getByRole("option", { name: "Housing" }));

      expect(screen.queryByRole("option", { name: "Salary" })).not.toBeInTheDocument();
      await user.click(screen.getByRole("button", { name: "Create category" }));

      expect(onSave).toHaveBeenCalledWith(null, {
        expectedRevision: 0,
        name: "Repairs",
        kind: "expense",
        parentId: "housing",
        sortOrder: 1,
        archived: false,
      });
    });

    it("requires confirmation before archiving without removing existing assignments", async () => {
      const user = userEvent.setup();
      const onSave = vi.fn();
      renderWithTheme(
        <CategoryManagementPanel
          categories={syntheticCategories}
          selectedId={null}
          saving={false}
          error={null}
          onSelect={vi.fn()}
          onSave={onSave}
        />,
      );

      await user.click(screen.getByRole("button", { name: "Archive Housing" }));
      expect(
        screen.getByText(/Existing transaction assignments and history will be preserved/),
      ).toBeInTheDocument();
      await user.click(screen.getByRole("button", { name: "Confirm archive category" }));

      expect(onSave).toHaveBeenCalledWith("housing", {
        expectedRevision: 1,
        name: "Housing",
        kind: "expense",
        parentId: null,
        sortOrder: 1,
        archived: true,
      });
    });
  });

  describe("CategoryPicker", () => {
    it("retains a selected archived assignment but prevents choosing it again", async () => {
      const user = userEvent.setup();
      const archived = { ...syntheticCategories[0]!, archived: true };
      const onSelect = vi.fn();
      renderWithTheme(
        <CategoryPicker categories={[archived]} selectedId={archived.id} onSelect={onSelect} />,
      );
      const picker = screen.getByRole("combobox", { name: "Category" });
      expect(picker).toHaveValue(archived.label);
      await user.click(picker);
      expect(screen.getByRole("option", { name: archived.label })).toHaveAttribute(
        "aria-disabled",
        "true",
      );
      expect(onSelect).not.toHaveBeenCalled();
    });

    it("searches by nested path and returns the selected category id", async () => {
      const user = userEvent.setup();
      const onSelect = vi.fn();
      renderWithTheme(
        <CategoryPicker categories={syntheticCategories} selectedId={null} onSelect={onSelect} />,
      );

      const picker = screen.getByRole("combobox", { name: "Category" });
      await user.type(picker, "Housing / Utilities");
      await user.click(await screen.findByRole("option", { name: "Housing / Utilities" }));

      expect(onSelect).toHaveBeenCalledWith("utilities");
    });
  });
});

describe("TransactionReviewList", () => {
  it("searches, filters review states, and applies a bulk category to selected bank rows", async () => {
    const user = userEvent.setup();
    const onOpen = vi.fn();
    const onBulkAssign = vi.fn();

    renderWithTheme(
      <TransactionReviewList
        transactions={syntheticTransactions}
        categories={syntheticCategories}
        onOpen={onOpen}
        onBulkAssign={onBulkAssign}
      />,
    );

    expect(screen.getByRole("table", { name: "Transactions for review" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Unclassified" }));
    expect(screen.getByText("Example Market")).toBeInTheDocument();
    expect(screen.queryByText("Example Utility")).not.toBeInTheDocument();

    await user.click(screen.getByRole("checkbox", { name: "Select Synthetic card payment 1" }));
    expect(screen.getByText(/never confirm a new merchant identity/i)).toBeInTheDocument();
    const categorySelect = screen.getByRole("combobox", { name: "Assign category" });
    await user.click(categorySelect);
    await user.click(screen.getByRole("option", { name: "Housing" }));
    await user.click(screen.getByRole("button", { name: "Apply to selected" }));

    expect(onBulkAssign).toHaveBeenCalledWith(["bank-tx-1"], "housing");
    await user.click(
      screen.getByRole("button", { name: "Example Market Synthetic card payment 1" }),
    );
    expect(onOpen).toHaveBeenCalledWith("bank-tx-1");
  });
});

describe("SplitEditor", () => {
  it("preserves an existing archived split without offering it to new lines", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn();
    const archived = { ...syntheticCategories[0]!, archived: true, children: [] };
    const initial = [{ id: "historical", categoryId: archived.id, amount: "-12.34" }];
    renderWithTheme(
      <SplitEditor
        transactionAmount="-12.34"
        currency="EUR"
        categories={[archived]}
        initialSplits={initial}
        onSave={onSave}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Save split" }));
    expect(onSave).toHaveBeenCalledWith(initial);
    await user.click(screen.getByRole("button", { name: "Add split" }));
    await user.click(screen.getByRole("combobox", { name: "Category 2" }));
    expect(screen.queryByRole("option", { name: archived.label })).not.toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.getByRole("button", { name: "Save split" })).toBeDisabled();
  });

  it("blocks an unbalanced split and saves only once the exact source total is matched", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn<(splits: readonly TransactionSplitDraft[]) => void>();
    const initialSplits: readonly TransactionSplitDraft[] = [
      { id: "split-1", categoryId: "housing", amount: "-10.10" },
      { id: "split-2", categoryId: "utilities", amount: "-32.19" },
    ];

    renderWithTheme(
      <SplitEditor
        transactionAmount="-42.30"
        currency="EUR"
        categories={syntheticCategories}
        initialSplits={initialSplits}
        onSave={onSave}
      />,
    );

    expect(screen.getByRole("button", { name: "Save split" })).toBeDisabled();
    const amount = screen.getByRole("textbox", { name: "Amount 2 (EUR)" });
    await user.clear(amount);
    await user.type(amount, "-32.20");
    expect(
      screen.getByText("Split amounts match the original bank amount exactly."),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Save split" }));
    expect(onSave).toHaveBeenCalledWith([
      { id: "split-1", categoryId: "housing", amount: "-10.10" },
      { id: "split-2", categoryId: "utilities", amount: "-32.20" },
    ]);
  });

  it("compares decimals exactly and rejects malformed or over-precision amounts", () => {
    expect(splitsMatchTransaction("0.30", ["0.10", "0.20"])).toBe(true);
    expect(splitsMatchTransaction("-42.30", ["-10.10", "-32.20"])).toBe(true);
    expect(splitsMatchTransaction("-42.30", ["-10.10", "-32.19"])).toBe(false);
    expect(splitsMatchTransaction("1.00", ["1.001"])).toBe(false);
    expect(splitsMatchTransaction("1.00", ["not-an-amount"])).toBe(false);
  });
});

describe("ReportingMoneyPair", () => {
  it("labels incomplete FX as a known subtotal instead of showing it as a complete total", () => {
    renderWithTheme(
      <ReportingMoneyPair
        dkk={{ complete: false, amount: null, knownSubtotal: "850.00" }}
        eur={{ complete: true, amount: "100.00", knownSubtotal: "100.00" }}
      />,
    );

    expect(screen.getByText("Known subtotal · DKK total incomplete")).toBeInTheDocument();
    expect(screen.getByText(/€100/)).toBeInTheDocument();
    expect(screen.getByText(/850/)).toBeInTheDocument();
    expect(screen.queryByText(/DKK\s+0/)).not.toBeInTheDocument();
  });
});

describe("TransactionDetailPanel", () => {
  it("protects manual choices and explicitly approves a PayPal detail against the bank amount", async () => {
    const user = userEvent.setup();
    const onUndoOverride = vi.fn();
    const onApprovePaymentDetails = vi.fn();
    const detail: HouseholdTransactionDetail = {
      transaction: {
        id: "bank-tx-1",
        date: "2026-04-03",
        description: "Synthetic card payment 1",
        merchant: "Example Market",
        amount: "-42.30",
        currency: "EUR",
        categoryLabel: "Housing",
        reviewState: "classified",
        assignmentReason: "Manually corrected after review",
        manuallyAssigned: true,
      },
      accountLabel: "Synthetic checking",
      entityLabel: "Member one",
      provider: "synthetic-bank",
      sourceCounterparty: "EXAMPLE MARKET 004",
      merchantId: "merchant-market",
      identityConfirmed: true,
      treatment: "expense",
      classificationRevision: 3,
      provenance: "manual",
      ruleId: null,
      explanation: "Manually corrected after review.",
      sourceChanged: false,
      detailChanged: false,
      splits: [{ id: "allocation-1", categoryId: "housing", amount: "-42.30" }],
      paymentDetails: [
        {
          id: "detail-1",
          revision: 5,
          status: "approved",
          merchant: "Example Market",
          reference: "ORDER-42",
          eventKind: "unknown",
          originalAmount: "50.00",
          originalCurrency: "USD",
          originalDate: "2026-04-03",
          bankAmount: "-42.30",
        },
      ],
    };

    renderWithTheme(
      <TransactionDetailPanel
        detail={detail}
        audit={[]}
        auditLoading={false}
        categories={syntheticCategories}
        merchants={syntheticMerchants}
        saving={false}
        onManageMerchants={vi.fn()}
        onClose={vi.fn()}
        onSaveCorrection={vi.fn()}
        onSaveSplits={vi.fn()}
        onUndoOverride={onUndoOverride}
        onDisableRule={vi.fn()}
        unmatchedPaymentDetails={[
          {
            id: "detail-2",
            revision: 1,
            eventKind: "purchase",
            merchant: "Synthetic Market",
            reference: "receipt-2",
            originalAmount: "-50.00",
            originalCurrency: "USD",
            originalDate: "2026-04-03",
          },
        ]}
        onApprovePaymentDetails={onApprovePaymentDetails}
      />,
    );

    expect(screen.getByText(/Automatic rules will not overwrite it/)).toBeInTheDocument();
    expect(screen.getByText("50.00 USD")).toBeInTheDocument();
    expect(screen.getAllByText("-42.30 EUR")).toHaveLength(2);
    expect(
      screen.queryByText(/payer email|shipping address|full payload/i),
    ).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Undo" }));
    await user.click(
      screen.getByRole("checkbox", { name: "Select PayPal detail Synthetic Market" }),
    );
    await user.clear(screen.getByRole("textbox", { name: "Approved bank allocation (EUR)" }));
    await user.type(
      screen.getByRole("textbox", { name: "Approved bank allocation (EUR)" }),
      "-20.00",
    );
    await user.type(screen.getByRole("textbox", { name: "Signed bank amount (EUR)" }), "-22.30");
    const approveLinks = screen.getByRole("button", { name: "Approve selected PayPal links" });
    expect(approveLinks).toBeDisabled();
    await user.click(
      screen.getByRole("checkbox", {
        name: "I verified these provider details belong to this bank movement",
      }),
    );
    await user.click(approveLinks);

    expect(onUndoOverride).toHaveBeenCalledOnce();
    expect(onApprovePaymentDetails).toHaveBeenCalledWith([
      { detailId: "detail-1", detailRevision: 5, bankAmount: "-20.00" },
      { detailId: "detail-2", detailRevision: 1, bankAmount: "-22.30" },
    ]);
  });

  it("confirms a first merchant identity with keyboard controls before saving learning evidence", async () => {
    const user = userEvent.setup();
    const onSaveCorrection = vi.fn();
    const onManageMerchants = vi.fn();
    const detail: HouseholdTransactionDetail = {
      transaction: {
        ...syntheticTransactions[0]!,
        merchant: "EXAMPLE MARKET 004",
      },
      accountLabel: "Synthetic checking",
      entityLabel: "Member one",
      provider: "synthetic-bank",
      sourceCounterparty: "EXAMPLE MARKET 004",
      merchantId: null,
      identityConfirmed: false,
      treatment: "expense",
      classificationRevision: 0,
      provenance: "none",
      ruleId: null,
      explanation: null,
      sourceChanged: false,
      detailChanged: false,
      splits: [],
      paymentDetails: [],
    };

    renderWithTheme(
      <TransactionDetailPanel
        detail={detail}
        audit={[]}
        auditLoading={false}
        categories={syntheticCategories}
        merchants={syntheticMerchants}
        saving={false}
        onManageMerchants={onManageMerchants}
        onClose={vi.fn()}
        onSaveCorrection={onSaveCorrection}
        onSaveSplits={vi.fn()}
        onUndoOverride={vi.fn()}
        onDisableRule={vi.fn()}
        unmatchedPaymentDetails={[]}
        onApprovePaymentDetails={vi.fn()}
      />,
    );

    const merchantSelect = screen.getByRole("combobox", { name: "Household merchant" });
    merchantSelect.focus();
    await user.keyboard("{ArrowDown}");
    await user.click(await screen.findByRole("option", { name: "Example Market" }));
    const identityConfirmation = screen.getByRole("checkbox", {
      name: "I confirm this transaction is from the selected merchant",
    });
    expect(identityConfirmation).toBeEnabled();
    await user.click(identityConfirmation);
    await user.click(screen.getByRole("combobox", { name: "Category" }));
    await user.click(await screen.findByRole("option", { name: "Housing" }));
    await user.click(screen.getByRole("button", { name: "Save correction" }));

    expect(onSaveCorrection).toHaveBeenCalledWith({
      treatment: "expense",
      categoryId: "housing",
      merchantId: "merchant-market",
      identityConfirmed: true,
    });
    expect(screen.getByText(/Existing transactions remain unchanged/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Manage merchants" }));
    expect(onManageMerchants).toHaveBeenCalledOnce();
  });

  it("does not allow processor identities to become learning evidence", async () => {
    const user = userEvent.setup();
    const detail: HouseholdTransactionDetail = {
      transaction: syntheticTransactions[0]!,
      accountLabel: "Synthetic checking",
      entityLabel: "Member one",
      provider: "synthetic-bank",
      sourceCounterparty: "EXAMPLE PROCESSOR",
      merchantId: null,
      identityConfirmed: false,
      treatment: "expense",
      classificationRevision: 0,
      provenance: "none",
      ruleId: null,
      explanation: null,
      sourceChanged: false,
      detailChanged: false,
      splits: [],
      paymentDetails: [],
    };

    renderWithTheme(
      <TransactionDetailPanel
        detail={detail}
        audit={[]}
        auditLoading={false}
        categories={syntheticCategories}
        merchants={syntheticMerchants}
        saving={false}
        onManageMerchants={vi.fn()}
        onClose={vi.fn()}
        onSaveCorrection={vi.fn()}
        onSaveSplits={vi.fn()}
        onUndoOverride={vi.fn()}
        onDisableRule={vi.fn()}
        unmatchedPaymentDetails={[]}
        onApprovePaymentDetails={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("combobox", { name: "Household merchant" }));
    await user.click(await screen.findByRole("option", { name: "Example Processor (processor)" }));
    expect(
      screen.getByRole("checkbox", {
        name: "I confirm this transaction is from the selected merchant",
      }),
    ).toBeDisabled();
    expect(screen.getByText(/not a stable identity/i)).toBeInTheDocument();
  });

  describe("RuleManagementPanel", () => {
    it("requires explicit review of a persisted preview before applying history", async () => {
      const user = userEvent.setup();
      const onDisable = vi.fn();
      const onPreview = vi.fn();
      const onApplyPreview = vi.fn();
      const rules: readonly HouseholdRuleSummary[] = [
        {
          id: "rule-1",
          merchantName: "Example Utility",
          categoryPath: "Housing / Utilities",
          treatment: "expense",
          version: 4,
          state: "active",
          explanation: "Exact confirmed merchant identity.",
        },
      ];
      const preview: HistoricalRulePreview = {
        id: "preview-1",
        applied: false,
        candidates: [
          {
            transactionId: "bank-tx-2",
            date: "2026-04-04",
            description: "Synthetic recurring payment",
            currentCategory: null,
            proposedCategory: "Housing / Utilities",
            outcome: "will_change",
            reason: "Persisted source and alias snapshot; no source changes detected.",
          },
        ],
      };

      renderWithTheme(
        <RuleManagementPanel
          rules={rules}
          preview={preview}
          saving={false}
          error={null}
          onDisable={onDisable}
          onPreview={onPreview}
          onApplyPreview={onApplyPreview}
        />,
      );

      expect(
        screen.getByRole("region", { name: "Rule for Example Utility, version 4" }),
      ).toContainElement(screen.getByRole("button", { name: "Preview historical reapply" }));
      await user.click(screen.getByRole("button", { name: "Preview historical reapply" }));
      expect(onPreview).toHaveBeenCalledWith("rule-1");
      expect(screen.getByRole("button", { name: "Apply approved preview" })).toBeDisabled();
      expect(screen.getByText(/Manual classifications are protected/)).toBeInTheDocument();
      expect(
        screen.getByText(/1 eligible transaction in this persisted preview/i),
      ).toBeInTheDocument();

      await user.click(
        screen.getByRole("checkbox", {
          name: "I reviewed this historical reapplication preview",
        }),
      );
      await user.click(screen.getByRole("button", { name: "Apply approved preview" }));

      expect(onApplyPreview).toHaveBeenCalledWith("preview-1");
      await user.click(screen.getByRole("button", { name: "Disable rule" }));
      expect(onDisable).toHaveBeenCalledWith("rule-1", 4);
    });
  });

  describe("MerchantManagementPanel", () => {
    it("retains modal scroll locking, focus trapping and Escape for merchant selection", async () => {
      const user = userEvent.setup();
      const merchant: HouseholdMerchant = {
        id: "merchant-scroll",
        name: "Synthetic scroll merchant",
        identityKind: "stable",
        confirmed: true,
        archived: false,
        revision: 1,
        referenceSource: null,
        referenceKey: null,
        referenceVersion: null,
      };
      renderWithTheme(
        <MerchantManagementPanel
          merchants={[merchant]}
          aliases={[]}
          selectedMerchantId={merchant.id}
          saving={false}
          error={null}
          onSelectMerchant={vi.fn()}
          onSaveMerchant={vi.fn()}
          onArchiveMerchant={vi.fn()}
          onSaveAlias={vi.fn()}
        />,
      );
      await user.click(screen.getByRole("combobox", { name: "Merchant" }));
      expect(screen.getByRole("listbox")).toBeVisible();
      expect(document.body.style.overflow).toBe("hidden");
      expect(screen.getByRole("listbox").contains(document.activeElement)).toBe(true);
      await user.keyboard("{Escape}");
      expect(screen.getByRole("combobox", { name: "Merchant" })).toHaveAttribute(
        "aria-expanded",
        "false",
      );
    });

    it("shows local index status and only explicit local reference matches", async () => {
      const user = userEvent.setup();
      const onSearchReference = vi.fn();
      const onSelectReference = vi.fn();
      const merchant: HouseholdMerchant = {
        id: "merchant-1",
        name: "Example Market",
        identityKind: "stable",
        confirmed: true,
        archived: false,
        revision: 2,
        referenceSource: "NSI",
        referenceKey: "nsi-brand-1",
        referenceVersion: "8.0.20260918",
      };
      const alias: HouseholdMerchantAlias = {
        id: "alias-1",
        merchantId: merchant.id,
        provider: "synthetic-bank",
        label: "EXAMPLE MARKET 004",
        normalizedKey: "example market 004",
        confirmed: false,
        revision: 1,
      };
      const status: VendorIndexStatus = {
        status: "stale",
        sourceId: "name-suggestion-index",
        sourceVersion: "8.0.20260918",
        checksum: "a".repeat(64),
        packageIntegrity: `sha512-${"b".repeat(88)}`,
        candidateIntegrity: null,
        sourceUrl: "https://example.invalid/catalog",
        license: "BSD-3-Clause",
        attribution: "Name Suggestion Index",
        attributionUrl: "https://example.invalid/attribution",
        sourceGeneratedAt: "2026-10-01T10:00:00Z",
        lastCheckedAt: "2026-10-03T09:00:00Z",
        lastAttemptAt: "2026-10-03T10:00:00Z",
        lastSuccessAt: "2026-10-02T10:00:00Z",
        snapshotStartedAt: "2026-10-02T10:00:00Z",
        snapshotCompletedAt: "2026-10-02T10:05:00Z",
        candidateVersion: null,
        activeGenerationId: "synthetic-generation",
        recordCount: 1200,
        errorCode: "refresh_delayed",
        errorMessage: "A newer source snapshot is not yet available.",
      };
      const candidate: VendorReferenceCandidate = {
        sourceKey: "nsi-brand-1",
        sourceVersion: "8.0.20260918",
        name: "Example Market",
        categoryPath: "shop/supermarket",
        aliases: ["Example Markets"],
        sourceUrl: "https://example.invalid/brand/nsi-brand-1",
        license: "BSD-3-Clause",
        wikidataId: null,
        matchKind: "exact_alias",
      };
      const referenceSearch: VendorReferenceSearchResult = {
        matchStatus: "ambiguous",
        sourceStatus: "stale",
        sourceVersion: "8.0.20260918",
        limit: 20,
        truncated: false,
        candidates: [
          candidate,
          { ...candidate, sourceKey: "nsi-brand-2", name: "Example Market Two" },
        ],
      };

      renderWithTheme(
        <MerchantManagementPanel
          merchants={[merchant]}
          aliases={[alias]}
          selectedMerchantId={merchant.id}
          vendorStatus={status}
          saving={false}
          error={null}
          referenceSearch={referenceSearch}
          onSelectMerchant={vi.fn()}
          onSaveMerchant={vi.fn()}
          onArchiveMerchant={vi.fn()}
          onSaveAlias={vi.fn()}
          onSearchReference={onSearchReference}
          onSelectReference={onSelectReference}
        />,
      );

      const statusSection = screen.getByRole("region", {
        name: "Public merchant reference status",
      });
      expect(statusSection).toHaveStyle({ overflowWrap: "anywhere" });
      expect(statusSection).toHaveTextContent("a".repeat(64));
      expect(statusSection).toHaveTextContent(`sha512-${"b".repeat(88)}`);
      expect(within(statusSection).getByText(/version 8\.0\.20260918/)).toBeInTheDocument();
      expect(within(statusSection).getByText(/BSD-3-Clause/)).toBeInTheDocument();
      expect(screen.getByText(/A newer source snapshot is not yet available/)).toBeInTheDocument();
      expect(
        screen.queryByRole("button", { name: "Refresh reference index" }),
      ).not.toBeInTheDocument();
      expect(screen.queryByText("ambiguous")).not.toBeInTheDocument();
      await user.type(screen.getByRole("textbox", { name: "Merchant name or alias" }), "Example");
      await user.click(screen.getByRole("button", { name: "Search index" }));
      expect(onSearchReference).toHaveBeenCalledWith("Example");
      expect(screen.getByText("ambiguous")).toBeInTheDocument();
      const referenceButtons = screen.getAllByRole("button", { name: /Link reference/ });
      await user.click(referenceButtons[0]!);
      expect(onSelectReference).toHaveBeenCalledWith(candidate);
    });
  });
});

describe("household report drilldown", () => {
  const filters: HouseholdFilterValues = {
    since: "2026-04-01",
    until: "2026-04-30",
    granularity: "month",
    accountIds: ["account-1", "account-2"],
    entityIds: ["member-1"],
    categoryId: "housing",
  };

  it("changes only the period dates when opening a trend bucket", () => {
    const point = {
      periodStart: "2026-04-01",
      periodEnd: "2026-04-30",
    } satisfies Pick<HouseholdTrendPoint, "periodStart" | "periodEnd">;

    expect(periodDrilldownFilters(filters, point)).toEqual({
      ...filters,
      since: point.periodStart,
      until: point.periodEnd,
    });
  });

  it("changes only the category when opening a category rollup", () => {
    expect(categoryDrilldownFilters(filters, "utilities")).toEqual({
      ...filters,
      categoryId: "utilities",
    });
  });

  it("represents an incomplete FX bucket as a chart gap, never as zero", () => {
    const point = {
      periodStart: "2026-04-01",
      periodEnd: "2026-04-30",
      income: {
        eur: { complete: true, amount: "100.00", knownSubtotal: "100.00" },
        dkk: { complete: false, amount: null, knownSubtotal: "745.00" },
      },
      grossExpenses: {
        eur: { complete: true, amount: "40.00", knownSubtotal: "40.00" },
        dkk: { complete: true, amount: "300.00", knownSubtotal: "300.00" },
      },
      refunds: {
        eur: { complete: true, amount: "0.00", knownSubtotal: "0.00" },
        dkk: { complete: true, amount: "0.00", knownSubtotal: "0.00" },
      },
      netExpenses: {
        eur: { complete: true, amount: "40.00", knownSubtotal: "40.00" },
        dkk: { complete: false, amount: null, knownSubtotal: "300.00" },
      },
      surplus: {
        eur: { complete: true, amount: "60.00", knownSubtotal: "60.00" },
        dkk: { complete: false, amount: null, knownSubtotal: "445.00" },
      },
    } satisfies HouseholdTrendPoint;

    expect(householdTrendSeries([point], "DKK")).toEqual({
      income: [null],
      netExpenses: [null],
      surplus: [null],
    });
    expect(householdTrendSeries([point], "EUR")).toEqual({
      income: [100],
      netExpenses: [40],
      surplus: [60],
    });
  });
});
