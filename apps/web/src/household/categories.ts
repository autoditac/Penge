import type { HouseholdCategory } from "./types";

export type HouseholdCategoryOption = {
  readonly id: string;
  readonly path: string;
  readonly kind: HouseholdCategory["kind"];
  readonly archived: boolean;
};

export function flattenHouseholdCategories(
  categories: readonly HouseholdCategory[],
  parentPath = "",
): readonly HouseholdCategoryOption[] {
  return categories.flatMap((category) => {
    const path = parentPath === "" ? category.label : `${parentPath} / ${category.label}`;
    return [
      { id: category.id, path, kind: category.kind, archived: category.archived },
      ...flattenHouseholdCategories(category.children, path),
    ];
  });
}
