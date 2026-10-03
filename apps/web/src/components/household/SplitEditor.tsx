import { useState } from "react";
import AddOutlinedIcon from "@mui/icons-material/AddOutlined";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import FormControl from "@mui/material/FormControl";
import InputLabel from "@mui/material/InputLabel";
import MenuItem from "@mui/material/MenuItem";
import Select from "@mui/material/Select";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { formatMoney, parseDecimal } from "../../money";
import type { Currency } from "../../money";
import { flattenHouseholdCategories } from "../../household/categories";
import { splitsMatchTransaction } from "../../household/splits";
import type { HouseholdCategory, TransactionSplitDraft } from "../../household/types";

type SplitEditorProps = {
  readonly transactionAmount: string;
  readonly currency: Currency;
  readonly categories: readonly HouseholdCategory[];
  readonly initialSplits: readonly TransactionSplitDraft[];
  readonly onSave: (splits: readonly TransactionSplitDraft[]) => void;
};

export function SplitEditor({
  transactionAmount,
  currency,
  categories,
  initialSplits,
  onSave,
}: SplitEditorProps): React.JSX.Element {
  const [splits, setSplits] = useState<readonly TransactionSplitDraft[]>(initialSplits);
  const isBalanced =
    splits.length > 0 &&
    splitsMatchTransaction(
      transactionAmount,
      splits.map(({ amount }) => amount),
    );
  const allCategories = flattenHouseholdCategories(categories);
  function canKeepCategory(split: TransactionSplitDraft, categoryId: string): boolean {
    const category = allCategories.find((item) => item.id === categoryId);
    return (
      category !== undefined &&
      (!category.archived ||
        initialSplits.some(
          (initial) => initial.id === split.id && initial.categoryId === categoryId,
        ))
    );
  }

  function updateSplit(id: string, patch: Partial<TransactionSplitDraft>): void {
    setSplits((current) =>
      current.map((split) => (split.id === id ? { ...split, ...patch } : split)),
    );
  }

  function addSplit(): void {
    setSplits((current) => [...current, { id: crypto.randomUUID(), categoryId: "", amount: "" }]);
  }

  function removeSplit(id: string): void {
    setSplits((current) => current.filter((split) => split.id !== id));
  }

  return (
    <Stack spacing={1.5} aria-label="Transaction split editor">
      <Typography color="text.secondary">
        Split the original bank amount of{" "}
        <Box component="strong" sx={{ color: "text.primary" }}>
          {formatMoney(parseDecimal(transactionAmount), currency)}
        </Box>
        . Amounts must add up exactly in {currency}.
      </Typography>
      {splits.map((split, index) => (
        <Stack
          key={split.id}
          direction={{ xs: "column", sm: "row" }}
          spacing={1}
          sx={{ alignItems: { sm: "flex-end" } }}
        >
          <FormControl size="small" fullWidth>
            <InputLabel id={`split-category-label-${split.id}`}>Category {index + 1}</InputLabel>
            <Select
              labelId={`split-category-label-${split.id}`}
              label={`Category ${index + 1}`}
              value={split.categoryId}
              onChange={(event) => updateSplit(split.id, { categoryId: event.target.value })}
            >
              {allCategories
                .filter((category) => !category.archived || category.id === split.categoryId)
                .map((category) => (
                  <MenuItem key={category.id} value={category.id} disabled={category.archived}>
                    {category.path}
                  </MenuItem>
                ))}
            </Select>
          </FormControl>
          <TextField
            label={`Amount ${index + 1} (${currency})`}
            size="small"
            inputMode="decimal"
            value={split.amount}
            onChange={(event) => updateSplit(split.id, { amount: event.target.value })}
            sx={{ width: { xs: "100%", sm: 220 } }}
          />
          <Button
            aria-label={`Remove split ${index + 1}`}
            color="inherit"
            onClick={() => removeSplit(split.id)}
          >
            Remove
          </Button>
        </Stack>
      ))}
      <Button onClick={addSplit} startIcon={<AddOutlinedIcon />} sx={{ alignSelf: "flex-start" }}>
        Add split
      </Button>
      <Alert severity={isBalanced ? "success" : "warning"} role="status">
        {isBalanced
          ? "Split amounts match the original bank amount exactly."
          : "Split amounts must match the original bank amount exactly before saving."}
      </Alert>
      <Button
        variant="contained"
        disabled={
          !isBalanced ||
          splits.some(
            (split) => split.categoryId === "" || !canKeepCategory(split, split.categoryId),
          )
        }
        onClick={() => onSave(splits)}
        sx={{ alignSelf: "flex-start" }}
      >
        Save split
      </Button>
    </Stack>
  );
}
