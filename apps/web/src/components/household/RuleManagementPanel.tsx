import { useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Checkbox from "@mui/material/Checkbox";
import FormControlLabel from "@mui/material/FormControlLabel";
import Paper from "@mui/material/Paper";
import Stack from "@mui/material/Stack";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import Typography from "@mui/material/Typography";

import type { HistoricalRulePreview, HouseholdRuleSummary } from "../../household/types";
import { EmptyState, Pill, TableScroll } from "../primitives";

type RuleManagementPanelProps = {
  readonly rules: readonly HouseholdRuleSummary[];
  readonly preview: HistoricalRulePreview | null;
  readonly saving: boolean;
  readonly error: string | null;
  readonly onDisable: (ruleId: string, expectedVersion: number) => void;
  readonly onPreview: (ruleId: string) => void;
  readonly onApplyPreview: (previewId: string) => void;
};

export function RuleManagementPanel({
  rules,
  preview,
  saving,
  error,
  onDisable,
  onPreview,
  onApplyPreview,
}: RuleManagementPanelProps): React.JSX.Element {
  const [reviewedPreviewId, setReviewedPreviewId] = useState<string | null>(null);
  const previewReviewed = preview !== null && reviewedPreviewId === preview.id;

  return (
    <Stack spacing={2}>
      {error !== null ? <Alert severity="error">{error}</Alert> : null}
      <Paper variant="outlined" sx={{ p: { xs: 1.75, sm: 2.25 }, borderRadius: 3.5 }}>
        <Typography component="h2" variant="h6" sx={{ fontWeight: 700, mb: 1.5 }}>
          Automatic category rules
        </Typography>
        {rules.length === 0 ? (
          <EmptyState label="automatic household rules" />
        ) : (
          <Stack spacing={1}>
            {rules.map((rule) => (
              <Box
                key={rule.id}
                sx={{
                  display: "flex",
                  flexWrap: "wrap",
                  alignItems: "center",
                  justifyContent: "space-between",
                  gap: 1.5,
                  borderBottom: "1px solid",
                  borderColor: "divider",
                  py: 1.25,
                }}
              >
                <Box sx={{ minWidth: 0, flex: "1 1 18rem" }}>
                  <Stack direction="row" spacing={1} sx={{ alignItems: "center", mb: 0.5 }}>
                    <Typography component="h3" sx={{ fontWeight: 700 }}>
                      {rule.merchantName}
                    </Typography>
                    <Pill
                      tone={
                        rule.state === "active"
                          ? "good"
                          : rule.state === "conflict"
                            ? "critical"
                            : rule.state === "insufficient"
                              ? "watch"
                              : "neutral"
                      }
                    >
                      {rule.state}
                    </Pill>
                  </Stack>
                  <Typography color="text.secondary" sx={{ fontSize: "0.88rem" }}>
                    {rule.explanation}
                  </Typography>
                  <Typography color="text.secondary" sx={{ fontSize: "0.8rem" }}>
                    {rule.categoryPath ?? rule.treatment ?? "No treatment"} · version {rule.version}
                  </Typography>
                </Box>
                <Stack direction="row" useFlexGap spacing={1} sx={{ flexWrap: "wrap" }}>
                  <Button
                    onClick={() => onPreview(rule.id)}
                    disabled={saving || rule.state !== "active"}
                    sx={{ minHeight: 44 }}
                  >
                    Preview historical reapply
                  </Button>
                  {rule.state === "active" ? (
                    <Button
                      color="warning"
                      onClick={() => onDisable(rule.id, rule.version)}
                      disabled={saving}
                      sx={{ minHeight: 44 }}
                    >
                      Disable rule
                    </Button>
                  ) : null}
                </Stack>
              </Box>
            ))}
          </Stack>
        )}
      </Paper>
      {preview !== null ? (
        <HistoricalPreview
          preview={preview}
          saving={saving}
          reviewed={previewReviewed}
          onReviewedChange={(reviewed) => setReviewedPreviewId(reviewed ? preview.id : null)}
          onApply={() => onApplyPreview(preview.id)}
        />
      ) : null}
    </Stack>
  );
}

function HistoricalPreview({
  preview,
  saving,
  reviewed,
  onReviewedChange,
  onApply,
}: {
  readonly preview: HistoricalRulePreview;
  readonly saving: boolean;
  readonly reviewed: boolean;
  readonly onReviewedChange: (reviewed: boolean) => void;
  readonly onApply: () => void;
}): React.JSX.Element {
  return (
    <Paper
      component="section"
      variant="outlined"
      aria-label="Historical rule reapplication preview"
      sx={{ p: { xs: 1.75, sm: 2.25 }, borderRadius: 3.5 }}
    >
      <Stack spacing={1.5}>
        <Box>
          <Typography component="h2" variant="h6" sx={{ fontWeight: 700 }}>
            Review historical changes
          </Typography>
          <Typography color="text.secondary">
            This preview does not change transactions. Manual classifications are protected and
            excluded from the apply operation.
          </Typography>
        </Box>
        {preview.applied ? (
          <Alert severity="success">This persisted preview has already been applied.</Alert>
        ) : null}
        <Pill tone="info">
          {preview.candidates.length} eligible transaction
          {preview.candidates.length === 1 ? "" : "s"} in this persisted preview
        </Pill>
        {preview.candidates.length === 0 ? (
          <EmptyState label="preview candidates" />
        ) : (
          <TableScroll>
            <Table size="small" aria-label="Historical rule preview candidates">
              <TableHead>
                <TableRow>
                  <TableCell>Date</TableCell>
                  <TableCell>Transaction</TableCell>
                  <TableCell>Current category</TableCell>
                  <TableCell>Proposed category</TableCell>
                  <TableCell>Outcome</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {preview.candidates.map((candidate) => (
                  <TableRow key={candidate.transactionId}>
                    <TableCell>{candidate.date}</TableCell>
                    <TableCell>
                      <Box>
                        <Typography component="span" sx={{ display: "block", fontWeight: 600 }}>
                          {candidate.description}
                        </Typography>
                        <Typography component="span" variant="caption" color="text.secondary">
                          {candidate.reason}
                        </Typography>
                      </Box>
                    </TableCell>
                    <TableCell>{candidate.currentCategory ?? "Not returned by API"}</TableCell>
                    <TableCell>{candidate.proposedCategory ?? "—"}</TableCell>
                    <TableCell>
                      <Pill
                        tone={
                          candidate.outcome === "conflict"
                            ? "critical"
                            : candidate.outcome === "manual_protected"
                              ? "info"
                              : candidate.outcome === "will_change"
                                ? "watch"
                                : "good"
                        }
                      >
                        {candidate.outcome.replaceAll("_", " ")}
                      </Pill>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableScroll>
        )}
        <FormControlLabel
          control={
            <Checkbox
              checked={reviewed}
              onChange={(event) => onReviewedChange(event.target.checked)}
              slotProps={{
                input: { "aria-label": "I reviewed this historical reapplication preview" },
              }}
            />
          }
          label="I reviewed this preview and approve the listed changes."
        />
        <Button
          variant="contained"
          disabled={saving || !reviewed || preview.applied || preview.candidates.length === 0}
          onClick={onApply}
          sx={{ alignSelf: "flex-start" }}
        >
          Apply approved preview
        </Button>
      </Stack>
    </Paper>
  );
}
