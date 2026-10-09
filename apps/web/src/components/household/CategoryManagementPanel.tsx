import { useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import FormControl from "@mui/material/FormControl";
import InputLabel from "@mui/material/InputLabel";
import MenuItem from "@mui/material/MenuItem";
import Paper from "@mui/material/Paper";
import Select from "@mui/material/Select";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { flattenHouseholdCategories } from "../../household/categories";
import type { HouseholdCategory } from "../../household/types";
import { CategoryTree } from "./CategoryTree";

type CategoryWriteValues = {
  readonly expectedRevision: number;
  readonly name: string;
  readonly kind: HouseholdCategory["kind"];
  readonly parentId: string | null;
  readonly sortOrder: number;
  readonly archived: boolean;
};

type CategoryEditorState = {
  readonly operation: "create" | "rename" | "reparent";
  readonly category: HouseholdCategory | null;
  readonly name: string;
  readonly kind: HouseholdCategory["kind"];
  readonly parentId: string | null;
  readonly sortOrder: number;
};

type CategoryManagementPanelProps = {
  readonly categories: readonly HouseholdCategory[];
  readonly selectedId: string | null;
  readonly saving: boolean;
  readonly error: string | null;
  readonly onSelect: (categoryId: string | null) => void;
  readonly onSave: (categoryId: string | null, values: CategoryWriteValues) => void;
};

export function CategoryManagementPanel({
  categories,
  selectedId,
  saving,
  error,
  onSelect,
  onSave,
}: CategoryManagementPanelProps): React.JSX.Element {
  const [editor, setEditor] = useState<CategoryEditorState | null>(null);
  const [archiveCandidate, setArchiveCandidate] = useState<HouseholdCategory | null>(null);
  const flatOptions = flattenHouseholdCategories(categories);

  function createRoot(kind: HouseholdCategory["kind"]): void {
    setArchiveCandidate(null);
    setEditor({
      operation: "create",
      category: null,
      name: "",
      kind,
      parentId: null,
      sortOrder: 0,
    });
  }

  function createChild(parentId: string): void {
    const parent = findCategory(categories, parentId);
    if (parent === null || parent.archived) {
      return;
    }
    setArchiveCandidate(null);
    setEditor({
      operation: "create",
      category: null,
      name: "",
      kind: parent.kind,
      parentId: parent.id,
      sortOrder: parent.children.length,
    });
  }

  function editCategory(operation: "rename" | "reparent", category: HouseholdCategory): void {
    setArchiveCandidate(null);
    setEditor({
      operation,
      category,
      name: category.label,
      kind: category.kind,
      parentId: category.parentId,
      sortOrder: category.sortOrder,
    });
  }

  function saveCategory(): void {
    if (editor === null || editor.name.trim() === "") {
      return;
    }
    const existing = editor.category;
    onSave(existing?.id ?? null, {
      expectedRevision: existing?.revision ?? 0,
      name: editor.name.trim(),
      kind: editor.kind,
      parentId: editor.parentId,
      sortOrder: editor.sortOrder,
      archived: existing?.archived ?? false,
    });
  }

  function confirmArchive(): void {
    if (archiveCandidate === null) {
      return;
    }
    onSave(archiveCandidate.id, {
      expectedRevision: archiveCandidate.revision,
      name: archiveCandidate.label,
      kind: archiveCandidate.kind,
      parentId: archiveCandidate.parentId,
      sortOrder: archiveCandidate.sortOrder,
      archived: true,
    });
    setArchiveCandidate(null);
  }

  return (
    <Stack spacing={2}>
      {error !== null ? <Alert severity="error">{error}</Alert> : null}
      <Paper variant="outlined" sx={{ p: { xs: 1.75, sm: 2.25 }, borderRadius: 3.5 }}>
        <Typography component="h2" variant="h6" sx={{ fontWeight: 700, mb: 1.5 }}>
          Household categories
        </Typography>
        <CategoryTree
          categories={categories}
          selectedId={selectedId}
          onSelect={(categoryId) => {
            setEditor(null);
            setArchiveCandidate(null);
            onSelect(categoryId);
          }}
          onCreateRoot={createRoot}
          onCreateChild={createChild}
          onRename={(category) => editCategory("rename", category)}
          onReparent={(category) => editCategory("reparent", category)}
          onArchive={(category) => {
            setEditor(null);
            setArchiveCandidate(category);
          }}
        />
      </Paper>
      {editor !== null ? (
        <CategoryEditor
          editor={editor}
          categories={categories}
          flatOptions={flatOptions}
          saving={saving}
          onChange={setEditor}
          onCancel={() => setEditor(null)}
          onSave={saveCategory}
        />
      ) : null}
      {archiveCandidate !== null ? (
        <Paper
          component="section"
          variant="outlined"
          aria-label="Confirm category archive"
          sx={{ p: 2, borderRadius: 3 }}
        >
          <Stack spacing={1.25} sx={{ alignItems: "flex-start" }}>
            <Alert severity="warning">
              Archive “{archiveCandidate.label}”? Existing transaction assignments and history will
              be preserved.
            </Alert>
            <Stack direction="row" spacing={1}>
              <Button
                variant="contained"
                color="warning"
                disabled={saving}
                onClick={confirmArchive}
              >
                Confirm archive category
              </Button>
              <Button disabled={saving} onClick={() => setArchiveCandidate(null)}>
                Cancel
              </Button>
            </Stack>
          </Stack>
        </Paper>
      ) : null}
    </Stack>
  );
}

function CategoryEditor({
  editor,
  categories,
  flatOptions,
  saving,
  onChange,
  onCancel,
  onSave,
}: {
  readonly editor: CategoryEditorState;
  readonly categories: readonly HouseholdCategory[];
  readonly flatOptions: ReturnType<typeof flattenHouseholdCategories>;
  readonly saving: boolean;
  readonly onChange: (editor: CategoryEditorState) => void;
  readonly onCancel: () => void;
  readonly onSave: () => void;
}): React.JSX.Element {
  const categoryId = editor.category?.id ?? null;
  const blockedIds =
    editor.operation === "reparent" && categoryId !== null
      ? collectSubtreeIds(findCategory(categories, categoryId))
      : new Set<string>();
  const parentOptions = flatOptions.filter(
    (option) => option.kind === editor.kind && !option.archived && !blockedIds.has(option.id),
  );
  const title =
    editor.operation === "create"
      ? "Create category"
      : editor.operation === "rename"
        ? "Rename category"
        : "Move category";
  const saveLabel =
    editor.operation === "create"
      ? "Create category"
      : editor.operation === "rename"
        ? "Save category name"
        : "Save category move";

  function changeParent(value: string): void {
    const parentId = value === "" ? null : value;
    if (parentId === editor.parentId) {
      return;
    }
    const targetCount =
      parentId === null
        ? categories.length
        : (findCategory(categories, parentId)?.children.length ?? 0);
    onChange({ ...editor, parentId, sortOrder: targetCount });
  }

  return (
    <Paper
      component="section"
      variant="outlined"
      aria-label={title}
      sx={{ p: { xs: 1.75, sm: 2.25 }, borderRadius: 3.5 }}
    >
      <Stack spacing={1.5}>
        <Box>
          <Typography component="h2" variant="h6" sx={{ fontWeight: 700 }}>
            {title}
          </Typography>
          {editor.operation !== "create" ? (
            <Typography color="text.secondary">
              Category type is fixed. Existing assignments stay attached to this category.
            </Typography>
          ) : null}
        </Box>
        <TextField
          label="Category name"
          value={editor.name}
          onChange={(event) => onChange({ ...editor, name: event.target.value })}
          autoFocus
        />
        {editor.operation !== "rename" ? (
          <FormControl size="small" fullWidth>
            <InputLabel id="category-parent-label">Parent category</InputLabel>
            <Select
              labelId="category-parent-label"
              label="Parent category"
              value={editor.parentId ?? ""}
              onChange={(event) => changeParent(event.target.value)}
            >
              <MenuItem value="">Top-level category</MenuItem>
              {parentOptions.map((option) => (
                <MenuItem key={option.id} value={option.id}>
                  {option.path}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
        ) : null}
        {editor.operation === "create" ? (
          <Typography color="text.secondary">
            Type: {editor.kind === "income" ? "Income" : "Expense"}
          </Typography>
        ) : null}
        <Stack direction="row" spacing={1} useFlexGap sx={{ flexWrap: "wrap" }}>
          <Button
            variant="contained"
            disabled={saving || editor.name.trim() === ""}
            onClick={onSave}
          >
            {saveLabel}
          </Button>
          <Button disabled={saving} onClick={onCancel}>
            Cancel
          </Button>
        </Stack>
      </Stack>
    </Paper>
  );
}

function findCategory(
  categories: readonly HouseholdCategory[],
  categoryId: string,
): HouseholdCategory | null {
  for (const category of categories) {
    if (category.id === categoryId) {
      return category;
    }
    const child = findCategory(category.children, categoryId);
    if (child !== null) {
      return child;
    }
  }
  return null;
}

function collectSubtreeIds(category: HouseholdCategory | null): ReadonlySet<string> {
  if (category === null) {
    return new Set();
  }
  return new Set([
    category.id,
    ...category.children.flatMap((child) => [...collectSubtreeIds(child)]),
  ]);
}
