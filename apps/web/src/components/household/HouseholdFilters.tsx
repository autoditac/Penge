import Box from "@mui/material/Box";
import FormControl from "@mui/material/FormControl";
import InputLabel from "@mui/material/InputLabel";
import MenuItem from "@mui/material/MenuItem";
import Select from "@mui/material/Select";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";

import { SegmentedControl } from "../primitives";
import type { SegmentedOption } from "../primitives";
import type {
  HouseholdFilterOptions,
  HouseholdFilters as HouseholdFilterValues,
  HouseholdGranularity,
} from "../../household/types";

const granularityOptions: readonly SegmentedOption<HouseholdGranularity>[] = [
  { value: "day", label: "Daily" },
  { value: "month", label: "Monthly" },
  { value: "year", label: "Yearly" },
];

type HouseholdFiltersProps = {
  readonly value: HouseholdFilterValues;
  readonly options: HouseholdFilterOptions;
  readonly onChange: (next: HouseholdFilterValues) => void;
};

export function HouseholdFilters({
  value,
  options,
  onChange,
}: HouseholdFiltersProps): React.JSX.Element {
  return (
    <Box
      component="form"
      aria-label="Household report filters"
      onSubmit={(event) => event.preventDefault()}
    >
      <Stack
        direction="row"
        useFlexGap
        spacing={1.5}
        sx={{ alignItems: "flex-end", flexWrap: "wrap", minWidth: 0 }}
      >
        <TextField
          label="From"
          type="date"
          size="small"
          value={value.since}
          onChange={(event) => onChange({ ...value, since: event.target.value })}
          slotProps={{ inputLabel: { shrink: true }, htmlInput: { "aria-label": "From date" } }}
        />
        <TextField
          label="To"
          type="date"
          size="small"
          value={value.until}
          onChange={(event) => onChange({ ...value, until: event.target.value })}
          slotProps={{ inputLabel: { shrink: true }, htmlInput: { "aria-label": "To date" } }}
        />
        <FilterSelect
          id="household-account-filter"
          label="Accounts"
          options={options.accounts}
          value={value.accountIds}
          onChange={(accountIds) => onChange({ ...value, accountIds })}
        />
        <FilterSelect
          id="household-member-filter"
          label="Household members"
          options={options.householdMembers}
          value={value.entityIds}
          onChange={(entityIds) => onChange({ ...value, entityIds })}
        />
        <FormControl size="small" sx={{ minWidth: 180 }}>
          <InputLabel id="household-category-filter-label">Category</InputLabel>
          <Select
            labelId="household-category-filter-label"
            id="household-category-filter"
            label="Category"
            value={value.categoryId ?? ""}
            onChange={(event) =>
              onChange({
                ...value,
                categoryId: event.target.value === "" ? null : event.target.value,
              })
            }
          >
            <MenuItem value="">All categories</MenuItem>
            {options.categories.map((category) => (
              <MenuItem key={category.id} value={category.id}>
                {category.label}
              </MenuItem>
            ))}
          </Select>
        </FormControl>
        <SegmentedControl
          options={granularityOptions}
          value={value.granularity}
          onChange={(granularity) => onChange({ ...value, granularity })}
          ariaLabel="Report time granularity"
        />
      </Stack>
    </Box>
  );
}

function FilterSelect({
  id,
  label,
  options,
  value,
  onChange,
}: {
  readonly id: string;
  readonly label: string;
  readonly options: readonly { readonly id: string; readonly label: string }[];
  readonly value: readonly string[];
  readonly onChange: (next: readonly string[]) => void;
}): React.JSX.Element {
  return (
    <FormControl size="small" sx={{ minWidth: 180 }}>
      <InputLabel id={`${id}-label`}>{label}</InputLabel>
      <Select
        id={id}
        labelId={`${id}-label`}
        multiple
        label={label}
        value={[...value]}
        onChange={(event) => {
          const nextValue = event.target.value;
          onChange(typeof nextValue === "string" ? nextValue.split(",") : nextValue);
        }}
        renderValue={(selected) =>
          options
            .filter((option) => selected.includes(option.id))
            .map((option) => option.label)
            .join(", ")
        }
      >
        {options.map((option) => (
          <MenuItem key={option.id} value={option.id}>
            {option.label}
          </MenuItem>
        ))}
      </Select>
    </FormControl>
  );
}
