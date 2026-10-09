import Autocomplete from "@mui/material/Autocomplete";
import TextField from "@mui/material/TextField";

import { flattenHouseholdCategories } from "../../household/categories";
import type { HouseholdCategory } from "../../household/types";

type CategoryPickerProps = {
  readonly categories: readonly HouseholdCategory[];
  readonly selectedId: string | null;
  readonly onSelect: (categoryId: string | null) => void;
  readonly disabled?: boolean | undefined;
};

export function CategoryPicker({
  categories,
  selectedId,
  onSelect,
  disabled = false,
}: CategoryPickerProps): React.JSX.Element {
  const options = flattenHouseholdCategories(categories).filter(
    (category) => !category.archived || category.id === selectedId,
  );
  const selected = options.find((category) => category.id === selectedId) ?? null;

  return (
    <Autocomplete
      options={options}
      value={selected}
      disabled={disabled}
      getOptionLabel={(option) => option.path}
      getOptionDisabled={(option) => option.archived}
      isOptionEqualToValue={(option, value) => option.id === value.id}
      onChange={(_event, option) => onSelect(option?.id ?? null)}
      renderInput={(params) => <TextField {...params} label="Category" />}
      noOptionsText="No categories match this search."
      clearOnEscape
    />
  );
}
