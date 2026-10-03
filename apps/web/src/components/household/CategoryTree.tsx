import { useState } from "react";
import AddOutlinedIcon from "@mui/icons-material/AddOutlined";
import ArchiveOutlinedIcon from "@mui/icons-material/ArchiveOutlined";
import EditOutlinedIcon from "@mui/icons-material/EditOutlined";
import DriveFileMoveOutlinedIcon from "@mui/icons-material/DriveFileMoveOutlined";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import IconButton from "@mui/material/IconButton";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import type { HouseholdCategory } from "../../household/types";

type CategoryTreeProps = {
  readonly categories: readonly HouseholdCategory[];
  readonly selectedId: string | null;
  readonly onSelect: (categoryId: string) => void;
  readonly onCreateRoot?: (kind: HouseholdCategory["kind"]) => void;
  readonly onCreateChild?: (parentId: string) => void;
  readonly onRename?: (category: HouseholdCategory) => void;
  readonly onReparent?: (category: HouseholdCategory) => void;
  readonly onArchive?: (category: HouseholdCategory) => void;
};

export function CategoryTree({
  categories,
  selectedId,
  onSelect,
  onCreateRoot,
  onCreateChild,
  onRename,
  onReparent,
  onArchive,
}: CategoryTreeProps): React.JSX.Element {
  const [expandedIds, setExpandedIds] = useState<ReadonlySet<string>>(
    () => new Set(categories.map((category) => category.id)),
  );

  return (
    <Stack spacing={1.5}>
      <Stack direction="row" useFlexGap spacing={1} sx={{ flexWrap: "wrap" }}>
        {onCreateRoot !== undefined ? (
          <>
            <Button
              size="small"
              startIcon={<AddOutlinedIcon />}
              onClick={() => onCreateRoot("expense")}
            >
              Add expense category
            </Button>
            <Button
              size="small"
              startIcon={<AddOutlinedIcon />}
              onClick={() => onCreateRoot("income")}
            >
              Add income category
            </Button>
          </>
        ) : null}
      </Stack>
      {categories.length === 0 ? (
        <Typography role="status" color="text.secondary">
          No categories yet.
        </Typography>
      ) : (
        <Box component="ul" role="tree" aria-label="Household categories" sx={treeListSx}>
          {categories.map((category) => (
            <CategoryTreeItem
              key={category.id}
              category={category}
              level={1}
              selectedId={selectedId}
              expandedIds={expandedIds}
              setExpandedIds={setExpandedIds}
              onSelect={onSelect}
              onCreateChild={onCreateChild}
              onRename={onRename}
              onReparent={onReparent}
              onArchive={onArchive}
            />
          ))}
        </Box>
      )}
    </Stack>
  );
}

function CategoryTreeItem({
  category,
  level,
  selectedId,
  expandedIds,
  setExpandedIds,
  onSelect,
  onCreateChild,
  onRename,
  onReparent,
  onArchive,
}: {
  readonly category: HouseholdCategory;
  readonly level: number;
  readonly selectedId: string | null;
  readonly expandedIds: ReadonlySet<string>;
  readonly setExpandedIds: (update: (current: ReadonlySet<string>) => ReadonlySet<string>) => void;
  readonly onSelect: (categoryId: string) => void;
  readonly onCreateChild?: ((parentId: string) => void) | undefined;
  readonly onRename?: ((category: HouseholdCategory) => void) | undefined;
  readonly onReparent?: ((category: HouseholdCategory) => void) | undefined;
  readonly onArchive?: ((category: HouseholdCategory) => void) | undefined;
}): React.JSX.Element {
  const hasChildren = category.children.length > 0;
  const expanded = expandedIds.has(category.id);
  const selected = selectedId === category.id;

  return (
    <Box
      component="li"
      role="treeitem"
      aria-label={category.label}
      aria-level={level}
      aria-expanded={hasChildren ? expanded : undefined}
    >
      <Stack
        direction="row"
        useFlexGap
        spacing={0.5}
        sx={{
          alignItems: "center",
          flexWrap: "wrap",
          minHeight: 44,
          pl: (level - 1) * 2,
        }}
      >
        {hasChildren ? (
          <IconButton
            size="small"
            aria-label={`${expanded ? "Collapse" : "Expand"} ${category.label}`}
            onClick={() =>
              setExpandedIds((current) => {
                const next = new Set(current);
                if (next.has(category.id)) {
                  next.delete(category.id);
                } else {
                  next.add(category.id);
                }
                return next;
              })
            }
          >
            <Box component="span" aria-hidden="true">
              {expanded ? "−" : "+"}
            </Box>
          </IconButton>
        ) : (
          <Box aria-hidden="true" sx={{ width: 40, flexShrink: 0 }} />
        )}
        <Button
          variant={selected ? "contained" : "text"}
          aria-current={selected ? "true" : undefined}
          disabled={category.archived}
          onClick={() => onSelect(category.id)}
          sx={{ justifyContent: "flex-start", textTransform: "none", minHeight: 40 }}
        >
          {category.label}
          {category.archived ? " (archived)" : ""}
        </Button>
        {onCreateChild !== undefined && !category.archived ? (
          <IconButton
            size="small"
            aria-label={`Add subcategory under ${category.label}`}
            onClick={() => onCreateChild(category.id)}
          >
            <AddOutlinedIcon fontSize="small" />
          </IconButton>
        ) : null}
        {onRename !== undefined && !category.archived ? (
          <IconButton
            size="small"
            aria-label={`Rename ${category.label}`}
            onClick={() => onRename(category)}
          >
            <EditOutlinedIcon fontSize="small" />
          </IconButton>
        ) : null}
        {onReparent !== undefined && !category.archived ? (
          <IconButton
            size="small"
            aria-label={`Move ${category.label}`}
            onClick={() => onReparent(category)}
          >
            <DriveFileMoveOutlinedIcon fontSize="small" />
          </IconButton>
        ) : null}
        {onArchive !== undefined && !category.archived ? (
          <IconButton
            size="small"
            aria-label={`Archive ${category.label}`}
            onClick={() => onArchive(category)}
          >
            <ArchiveOutlinedIcon fontSize="small" />
          </IconButton>
        ) : null}
      </Stack>
      {hasChildren && expanded ? (
        <Box component="ul" role="group" sx={treeListSx}>
          {category.children.map((child) => (
            <CategoryTreeItem
              key={child.id}
              category={child}
              level={level + 1}
              selectedId={selectedId}
              expandedIds={expandedIds}
              setExpandedIds={setExpandedIds}
              onSelect={onSelect}
              onCreateChild={onCreateChild}
              onRename={onRename}
              onReparent={onReparent}
              onArchive={onArchive}
            />
          ))}
        </Box>
      ) : null}
    </Box>
  );
}

const treeListSx = {
  listStyle: "none",
  m: 0,
  p: 0,
} as const;
