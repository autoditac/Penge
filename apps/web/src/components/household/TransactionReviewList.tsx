import { useMemo, useState } from "react";
import SearchOutlinedIcon from "@mui/icons-material/SearchOutlined";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Checkbox from "@mui/material/Checkbox";
import FormControl from "@mui/material/FormControl";
import InputLabel from "@mui/material/InputLabel";
import MenuItem from "@mui/material/MenuItem";
import Paper from "@mui/material/Paper";
import Select from "@mui/material/Select";
import Stack from "@mui/material/Stack";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { flattenHouseholdCategories } from "../../household/categories";
import { formatHouseholdSourceAmount } from "../../household/money";
import type { HouseholdCategory, ReviewTransaction } from "../../household/types";
import { EmptyState, Pill, SegmentedControl, TableScroll } from "../primitives";
import type { SegmentedOption } from "../primitives";

type ReviewStateFilter = "all" | "unclassified" | "needs_review";

const reviewStateOptions: readonly SegmentedOption<ReviewStateFilter>[] = [
  { value: "all", label: "All" },
  { value: "unclassified", label: "Unclassified" },
  { value: "needs_review", label: "Needs review" },
];

type TransactionReviewListProps = {
  readonly transactions: readonly ReviewTransaction[];
  readonly categories: readonly HouseholdCategory[];
  readonly onOpen: (transactionId: string) => void;
  readonly onBulkAssign: (transactionIds: readonly string[], categoryId: string) => void;
  readonly searchValue?: string | undefined;
  readonly onSearchChange?: ((value: string) => void) | undefined;
  readonly onLoadMore?: (() => void) | undefined;
  readonly hasMore?: boolean | undefined;
  readonly loadingMore?: boolean | undefined;
};

export function TransactionReviewList({
  transactions,
  categories,
  onOpen,
  onBulkAssign,
  searchValue,
  onSearchChange,
  onLoadMore,
  hasMore = false,
  loadingMore = false,
}: TransactionReviewListProps): React.JSX.Element {
  const [internalSearch, setInternalSearch] = useState("");
  const search = searchValue ?? internalSearch;
  const [reviewState, setReviewState] = useState<ReviewStateFilter>("all");
  const [selectedIds, setSelectedIds] = useState<ReadonlySet<string>>(() => new Set());
  const [bulkCategoryId, setBulkCategoryId] = useState("");
  const visibleTransactions = useMemo(() => {
    const query = search.trim().toLocaleLowerCase();
    return transactions.filter((transaction) => {
      const matchesState = reviewState === "all" || transaction.reviewState === reviewState;
      const matchesSearch =
        query === "" ||
        [transaction.description, transaction.merchant ?? "", transaction.categoryLabel ?? ""]
          .join(" ")
          .toLocaleLowerCase()
          .includes(query);
      return matchesState && matchesSearch;
    });
  }, [reviewState, search, transactions]);
  const activeCategoryOptions = flattenHouseholdCategories(categories).filter(
    (category) => !category.archived,
  );
  const allVisibleSelected =
    visibleTransactions.length > 0 && visibleTransactions.every(({ id }) => selectedIds.has(id));

  function toggleTransaction(id: string): void {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }

  function toggleVisible(): void {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (allVisibleSelected) {
        visibleTransactions.forEach(({ id }) => next.delete(id));
      } else {
        visibleTransactions.forEach(({ id }) => next.add(id));
      }
      return next;
    });
  }

  return (
    <Stack spacing={1.5}>
      <Stack
        direction={{ xs: "column", sm: "row" }}
        spacing={1}
        sx={{ alignItems: { sm: "center" }, justifyContent: "space-between" }}
      >
        <TextField
          size="small"
          label="Search transactions"
          value={search}
          onChange={(event) => {
            const next = event.target.value;
            setInternalSearch(next);
            onSearchChange?.(next);
          }}
          slotProps={{ input: { startAdornment: <SearchOutlinedIcon fontSize="small" /> } }}
          sx={{ width: { xs: "100%", sm: 320 } }}
        />
        <SegmentedControl
          options={reviewStateOptions}
          value={reviewState}
          onChange={setReviewState}
          ariaLabel="Transaction review status"
        />
        <Stack
          direction="row"
          useFlexGap
          spacing={1}
          sx={{ alignItems: "center", flexWrap: "wrap" }}
        >
          <Typography color="text.secondary" aria-live="polite">
            {selectedIds.size} selected
          </Typography>
          <FormControl size="small" sx={{ minWidth: 190 }}>
            <InputLabel id="bulk-category-label">Assign category</InputLabel>
            <Select
              labelId="bulk-category-label"
              label="Assign category"
              value={bulkCategoryId}
              onChange={(event) => setBulkCategoryId(event.target.value)}
            >
              {activeCategoryOptions.map((category) => (
                <MenuItem key={category.id} value={category.id}>
                  {category.path}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          <Button
            variant="contained"
            disabled={selectedIds.size === 0 || bulkCategoryId === ""}
            onClick={() => onBulkAssign([...selectedIds], bulkCategoryId)}
          >
            Apply to selected
          </Button>
        </Stack>
      </Stack>
      {visibleTransactions.length === 0 ? (
        <EmptyState label={transactions.length === 0 ? "transactions" : "matching transactions"} />
      ) : (
        <Paper variant="outlined" sx={{ minWidth: 0 }}>
          <TableScroll>
            <Table size="small" aria-label="Transactions for review">
              <TableHead>
                <TableRow>
                  <TableCell padding="checkbox">
                    <Checkbox
                      checked={allVisibleSelected}
                      indeterminate={
                        !allVisibleSelected &&
                        visibleTransactions.some(({ id }) => selectedIds.has(id))
                      }
                      onChange={toggleVisible}
                      slotProps={{ input: { "aria-label": "Select all visible transactions" } }}
                    />
                  </TableCell>
                  <TableCell>Date</TableCell>
                  <TableCell>Transaction</TableCell>
                  <TableCell>Category</TableCell>
                  <TableCell>Review</TableCell>
                  <TableCell align="right">Original amount</TableCell>
                  <TableCell>Assignment</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {visibleTransactions.map((transaction) => (
                  <TableRow key={transaction.id} hover selected={selectedIds.has(transaction.id)}>
                    <TableCell padding="checkbox">
                      <Checkbox
                        checked={selectedIds.has(transaction.id)}
                        onChange={() => toggleTransaction(transaction.id)}
                        slotProps={{ input: { "aria-label": `Select ${transaction.description}` } }}
                      />
                    </TableCell>
                    <TableCell>{transaction.date}</TableCell>
                    <TableCell>
                      <Button
                        variant="text"
                        onClick={() => onOpen(transaction.id)}
                        sx={{
                          textTransform: "none",
                          justifyContent: "flex-start",
                          textAlign: "left",
                        }}
                      >
                        <Box>
                          <Typography component="span" sx={{ display: "block", fontWeight: 600 }}>
                            {transaction.merchant ?? transaction.description}
                          </Typography>
                          {transaction.merchant !== null ? (
                            <Typography component="span" color="text.secondary" variant="caption">
                              {transaction.description}
                            </Typography>
                          ) : null}
                        </Box>
                      </Button>
                    </TableCell>
                    <TableCell>{transaction.categoryLabel ?? "Unclassified"}</TableCell>
                    <TableCell>
                      <Pill tone={transaction.reviewState === "classified" ? "good" : "watch"}>
                        {transaction.reviewState}
                      </Pill>
                    </TableCell>
                    <TableCell align="right">
                      {formatHouseholdSourceAmount(transaction.amount, transaction.currency)}
                    </TableCell>
                    <TableCell>
                      {transaction.manuallyAssigned ? (
                        <Pill tone="info">Manual</Pill>
                      ) : (
                        (transaction.assignmentReason ?? "—")
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableScroll>
        </Paper>
      )}
      {onLoadMore !== undefined && hasMore ? (
        <Button
          variant="outlined"
          disabled={loadingMore}
          onClick={onLoadMore}
          sx={{ alignSelf: "center", minHeight: 44 }}
        >
          {loadingMore ? "Loading more transactions…" : "Load more transactions"}
        </Button>
      ) : null}
    </Stack>
  );
}
