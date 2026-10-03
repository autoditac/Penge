import { useState } from "react";
import AddOutlinedIcon from "@mui/icons-material/AddOutlined";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Checkbox from "@mui/material/Checkbox";
import FormControl from "@mui/material/FormControl";
import FormControlLabel from "@mui/material/FormControlLabel";
import InputLabel from "@mui/material/InputLabel";
import MenuItem from "@mui/material/MenuItem";
import Paper from "@mui/material/Paper";
import Select from "@mui/material/Select";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import type {
  HouseholdMerchant,
  HouseholdMerchantAlias,
  VendorIndexStatus,
  VendorReferenceCandidate,
  VendorReferenceSearchResult,
} from "../../household/types";
import { EmptyState, Pill } from "../primitives";

type MerchantManagementPanelProps = {
  readonly merchants: readonly HouseholdMerchant[];
  readonly aliases: readonly HouseholdMerchantAlias[];
  readonly selectedMerchantId: string | null;
  readonly vendorStatus?: VendorIndexStatus | undefined;
  readonly vendorStatusLoading?: boolean;
  readonly vendorStatusError?: string | null;
  readonly saving: boolean;
  readonly error: string | null;
  readonly referenceSearch?: VendorReferenceSearchResult | null | undefined;
  readonly referenceSearchLoading?: boolean;
  readonly referenceSearchError?: string | null;
  readonly onSelectMerchant: (merchantId: string | null) => void;
  readonly onSaveMerchant: (
    merchantId: string,
    expectedRevision: number,
    update: {
      readonly name: string;
      readonly identityKind: HouseholdMerchant["identityKind"];
      readonly confirmed: boolean;
    },
  ) => void;
  readonly onCreateMerchant?: (update: {
    readonly name: string;
    readonly identityKind: HouseholdMerchant["identityKind"];
    readonly confirmed: boolean;
  }) => void;
  readonly onArchiveMerchant: (merchantId: string, expectedRevision: number) => void;
  readonly onSaveAlias: (
    alias: HouseholdMerchantAlias | null,
    update: {
      readonly merchantId: string;
      readonly provider: string;
      readonly label: string;
      readonly confirmed: boolean;
    },
  ) => void;
  readonly onSearchReference?: ((query: string) => void) | undefined;
  readonly onSelectReference?: ((candidate: VendorReferenceCandidate) => void) | undefined;
};

const identityKinds: readonly HouseholdMerchant["identityKind"][] = [
  "stable",
  "processor",
  "marketplace",
  "mixed",
  "unknown",
];

export function MerchantManagementPanel({
  merchants,
  aliases,
  selectedMerchantId,
  vendorStatus,
  vendorStatusLoading = false,
  vendorStatusError = null,
  onCreateMerchant,
  saving,
  error,
  referenceSearch = null,
  referenceSearchLoading = false,
  referenceSearchError = null,
  onSelectMerchant,
  onSaveMerchant,
  onArchiveMerchant,
  onSaveAlias,
  onSearchReference,
  onSelectReference,
}: MerchantManagementPanelProps): React.JSX.Element {
  const [referenceQuery, setReferenceQuery] = useState("");
  const [submittedReferenceQuery, setSubmittedReferenceQuery] = useState<string | null>(null);
  const selectedMerchant = merchants.find((merchant) => merchant.id === selectedMerchantId) ?? null;
  const selectedAliases =
    selectedMerchant === null
      ? []
      : aliases.filter((alias) => alias.merchantId === selectedMerchant.id);

  return (
    <Stack spacing={2}>
      {vendorStatus !== undefined ? <VendorReferenceStatus status={vendorStatus} /> : null}
      {vendorStatusLoading ? (
        <Alert severity="info">Loading public merchant reference status…</Alert>
      ) : null}
      {vendorStatusError !== null ? (
        <Alert severity="error">Public merchant reference status: {vendorStatusError}</Alert>
      ) : null}
      {error !== null ? <Alert severity="error">{error}</Alert> : null}
      {onSearchReference !== undefined && onSelectReference !== undefined ? (
        <VendorReferenceSearch
          query={referenceQuery}
          result={submittedReferenceQuery === referenceQuery.trim() ? referenceSearch : null}
          loading={referenceSearchLoading}
          error={referenceSearchError}
          saving={saving}
          hasSelectedMerchant={selectedMerchantId !== null}
          onQueryChange={setReferenceQuery}
          onSearch={() => {
            const query = referenceQuery.trim();
            setSubmittedReferenceQuery(query);
            onSearchReference(query);
          }}
          onSelect={onSelectReference}
        />
      ) : null}
      <Paper variant="outlined" sx={{ p: { xs: 1.75, sm: 2.25 }, borderRadius: 3.5 }}>
        <Typography component="h2" variant="h6" sx={{ fontWeight: 700, mb: 1 }}>
          Merchant identities and aliases
        </Typography>
        <Typography color="text.secondary" sx={{ mb: 2 }}>
          Identity corrections and household aliases take precedence over public reference
          suggestions. Matching happens locally; transaction data is never sent to a vendor source.
        </Typography>
        {onCreateMerchant !== undefined ? (
          <Button
            variant="outlined"
            startIcon={<AddOutlinedIcon />}
            onClick={() => onSelectMerchant(null)}
            sx={{ mb: 1.5 }}
          >
            Add household merchant
          </Button>
        ) : null}
        {merchants.length === 0 ? (
          <EmptyState label="household merchants" />
        ) : (
          <FormControl size="small" fullWidth sx={{ mb: 2 }}>
            <InputLabel id="merchant-identity-label">Merchant</InputLabel>
            <Select
              labelId="merchant-identity-label"
              label="Merchant"
              value={selectedMerchantId ?? ""}
              onChange={(event) =>
                onSelectMerchant(event.target.value === "" ? null : event.target.value)
              }
            >
              {merchants.map((merchant) => (
                <MenuItem key={merchant.id} value={merchant.id}>
                  {merchant.name}
                  {merchant.archived ? " (archived)" : ""}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
        )}
        {selectedMerchant !== null ? (
          <Stack spacing={2}>
            <MerchantIdentityEditor
              key={`${selectedMerchant.id}:${selectedMerchant.revision}`}
              merchant={selectedMerchant}
              saving={saving}
              onSave={(update) =>
                onSaveMerchant(selectedMerchant.id, selectedMerchant.revision, update)
              }
              onArchive={() => onArchiveMerchant(selectedMerchant.id, selectedMerchant.revision)}
            />
            <AliasManager
              key={`${selectedMerchant.id}:${selectedAliases
                .map((alias) => `${alias.id}-${alias.revision}`)
                .join(":")}`}
              merchantId={selectedMerchant.id}
              aliases={selectedAliases}
              saving={saving}
              onSave={onSaveAlias}
            />
          </Stack>
        ) : onCreateMerchant !== undefined ? (
          <NewMerchantEditor saving={saving} onSave={onCreateMerchant} />
        ) : null}
      </Paper>
    </Stack>
  );
}

function NewMerchantEditor({
  saving,
  onSave,
}: {
  readonly saving: boolean;
  readonly onSave: NonNullable<MerchantManagementPanelProps["onCreateMerchant"]>;
}): React.JSX.Element {
  const [name, setName] = useState("");
  const [identityKind, setIdentityKind] = useState<HouseholdMerchant["identityKind"]>("unknown");
  const [confirmed, setConfirmed] = useState(false);
  return (
    <Stack spacing={1.25} aria-label="Create household merchant">
      <TextField
        label="Normalized merchant name"
        value={name}
        onChange={(event) => setName(event.target.value)}
        fullWidth
      />
      <FormControl size="small" sx={{ maxWidth: 240 }}>
        <InputLabel id="new-merchant-identity-kind-label">Identity type</InputLabel>
        <Select
          labelId="new-merchant-identity-kind-label"
          label="Identity type"
          value={identityKind}
          onChange={(event) => {
            const next = identityKinds.find((kind) => kind === event.target.value);
            if (next !== undefined) {
              setIdentityKind(next);
            }
          }}
        >
          {identityKinds.map((kind) => (
            <MenuItem key={kind} value={kind}>
              {kind}
            </MenuItem>
          ))}
        </Select>
      </FormControl>
      <FormControlLabel
        control={
          <Checkbox
            checked={confirmed}
            onChange={(event) => setConfirmed(event.target.checked)}
            slotProps={{ input: { "aria-label": "Confirm new merchant identity" } }}
          />
        }
        label="Confirm this merchant identity"
      />
      <Button
        variant="contained"
        disabled={saving || name.trim() === ""}
        onClick={() => onSave({ name: name.trim(), identityKind, confirmed })}
        sx={{ alignSelf: "flex-start" }}
      >
        Create merchant identity
      </Button>
    </Stack>
  );
}

function MerchantIdentityEditor({
  merchant,
  saving,
  onSave,
  onArchive,
}: {
  readonly merchant: HouseholdMerchant;
  readonly saving: boolean;
  readonly onSave: (update: {
    readonly name: string;
    readonly identityKind: HouseholdMerchant["identityKind"];
    readonly confirmed: boolean;
  }) => void;
  readonly onArchive: () => void;
}): React.JSX.Element {
  const [name, setName] = useState(merchant.name);
  const [identityKind, setIdentityKind] = useState(merchant.identityKind);
  const [confirmed, setConfirmed] = useState(merchant.confirmed);
  const isValid = name.trim() !== "";

  return (
    <Stack spacing={1.25}>
      <Stack direction={{ xs: "column", sm: "row" }} spacing={1.25}>
        <TextField
          label="Normalized merchant name"
          value={name}
          onChange={(event) => setName(event.target.value)}
          fullWidth
        />
        <FormControl size="small" sx={{ minWidth: { sm: 200 } }}>
          <InputLabel id="merchant-identity-kind-label">Identity type</InputLabel>
          <Select
            labelId="merchant-identity-kind-label"
            label="Identity type"
            value={identityKind}
            onChange={(event) => {
              const next = identityKinds.find((kind) => kind === event.target.value);
              if (next !== undefined) {
                setIdentityKind(next);
              }
            }}
          >
            {identityKinds.map((kind) => (
              <MenuItem key={kind} value={kind}>
                {kind}
              </MenuItem>
            ))}
          </Select>
        </FormControl>
      </Stack>
      <FormControlLabel
        control={
          <Checkbox
            checked={confirmed}
            onChange={(event) => setConfirmed(event.target.checked)}
            slotProps={{ input: { "aria-label": "Confirm merchant identity" } }}
          />
        }
        label="Confirm this merchant identity"
      />
      <Stack direction="row" useFlexGap spacing={1} sx={{ flexWrap: "wrap" }}>
        <Button
          variant="contained"
          disabled={saving || !isValid || merchant.archived}
          onClick={() => onSave({ name: name.trim(), identityKind, confirmed })}
        >
          Save merchant identity
        </Button>
        {!merchant.archived ? (
          <Button color="warning" disabled={saving} onClick={onArchive}>
            Archive merchant
          </Button>
        ) : (
          <Pill tone="neutral">Archived</Pill>
        )}
      </Stack>
      {merchant.referenceSource !== null ? (
        <Typography color="text.secondary" sx={{ fontSize: "0.82rem" }}>
          Public reference: {merchant.referenceSource} · {merchant.referenceKey ?? "no source key"}{" "}
          · version {merchant.referenceVersion ?? "unknown"}
        </Typography>
      ) : null}
    </Stack>
  );
}

function AliasManager({
  merchantId,
  aliases,
  saving,
  onSave,
}: {
  readonly merchantId: string;
  readonly aliases: readonly HouseholdMerchantAlias[];
  readonly saving: boolean;
  readonly onSave: MerchantManagementPanelProps["onSaveAlias"];
}): React.JSX.Element {
  const [provider, setProvider] = useState("");
  const [label, setLabel] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [editingAlias, setEditingAlias] = useState<HouseholdMerchantAlias | null>(null);

  function editAlias(alias: HouseholdMerchantAlias): void {
    setEditingAlias(alias);
    setProvider(alias.provider);
    setLabel(alias.label);
    setConfirmed(alias.confirmed);
  }

  return (
    <Box>
      <Typography component="h3" variant="subtitle1" sx={{ fontWeight: 700, mb: 1 }}>
        Household aliases
      </Typography>
      {aliases.length === 0 ? (
        <Typography color="text.secondary" sx={{ mb: 1 }}>
          No aliases have been recorded for this merchant.
        </Typography>
      ) : (
        <Stack spacing={0.75} component="ul" sx={{ m: 0, mb: 1.5, p: 0, listStyle: "none" }}>
          {aliases.map((alias) => (
            <Box
              component="li"
              key={alias.id}
              sx={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                flexWrap: "wrap",
                gap: 1,
                py: 0.75,
                borderBottom: "1px solid",
                borderColor: "divider",
              }}
            >
              <Box sx={{ minWidth: 0 }}>
                <Typography component="strong">{alias.label}</Typography>
                <Typography component="small" color="text.secondary" sx={{ display: "block" }}>
                  {alias.provider} · normalized “{alias.normalizedKey}” · revision {alias.revision}
                </Typography>
              </Box>
              <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
                <Pill tone={alias.confirmed ? "good" : "watch"}>
                  {alias.confirmed ? "Confirmed" : "Needs confirmation"}
                </Pill>
                <Button
                  onClick={() => editAlias(alias)}
                  disabled={saving}
                  aria-label={`Edit alias ${alias.label}`}
                >
                  Edit
                </Button>
              </Stack>
            </Box>
          ))}
        </Stack>
      )}
      <Stack spacing={1.25}>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={1.25}>
          <TextField
            label="Provider"
            value={provider}
            onChange={(event) => setProvider(event.target.value)}
            sx={{ minWidth: { sm: 180 } }}
          />
          <TextField
            label="Normalized provider alias"
            value={label}
            onChange={(event) => setLabel(event.target.value)}
            fullWidth
          />
        </Stack>
        <FormControlLabel
          control={
            <Checkbox
              checked={confirmed}
              onChange={(event) => setConfirmed(event.target.checked)}
              slotProps={{ input: { "aria-label": "Confirm this household alias" } }}
            />
          }
          label="I confirm this alias belongs to the selected merchant"
        />
        <Button
          variant="outlined"
          startIcon={<AddOutlinedIcon />}
          disabled={saving || provider.trim() === "" || label.trim() === ""}
          onClick={() =>
            onSave(editingAlias, {
              merchantId,
              provider: provider.trim(),
              label: label.trim(),
              confirmed,
            })
          }
          sx={{ alignSelf: "flex-start" }}
        >
          {editingAlias === null ? "Add alias" : "Save alias"}
        </Button>
        {editingAlias !== null ? (
          <Button
            onClick={() => {
              setEditingAlias(null);
              setProvider("");
              setLabel("");
              setConfirmed(false);
            }}
            disabled={saving}
            sx={{ alignSelf: "flex-start" }}
          >
            Cancel alias edit
          </Button>
        ) : null}
      </Stack>
    </Box>
  );
}

function VendorReferenceStatus({
  status,
}: {
  readonly status: VendorIndexStatus;
}): React.JSX.Element {
  const statusTone =
    status.status === "current"
      ? "good"
      : status.status === "failed" || status.status === "stale"
        ? "watch"
        : "info";

  return (
    <Paper
      component="section"
      variant="outlined"
      aria-label="Public merchant reference status"
      sx={{ p: { xs: 1.75, sm: 2.25 }, borderRadius: 3.5 }}
    >
      <Stack spacing={1}>
        <Stack
          direction="row"
          useFlexGap
          spacing={1}
          sx={{ alignItems: "center", flexWrap: "wrap" }}
        >
          <Typography component="h2" variant="h6" sx={{ fontWeight: 700 }}>
            Public merchant reference
          </Typography>
          <Pill tone={statusTone}>{status.status.replaceAll("_", " ")}</Pill>
        </Stack>
        <Typography color="text.secondary">
          {status.sourceId}
          {status.sourceVersion === null ? "" : ` · version ${status.sourceVersion}`}
          {status.recordCount === null ? "" : ` · ${status.recordCount.toLocaleString()} entries`}
          {status.checksum === null ? "" : ` · SHA-256 ${status.checksum}`}
        </Typography>
        {status.packageIntegrity !== null || status.candidateIntegrity !== null ? (
          <Typography color="text.secondary" sx={{ fontSize: "0.84rem" }}>
            Package integrity: {status.packageIntegrity ?? "not available"} · Candidate integrity:{" "}
            {status.candidateIntegrity ?? "not available"}
          </Typography>
        ) : null}
        <Typography color="text.secondary" sx={{ fontSize: "0.84rem" }}>
          Source generated: {status.sourceGeneratedAt ?? "not available"} · Last checked:{" "}
          {status.lastCheckedAt ?? "not available"} · Last attempt:{" "}
          {status.lastAttemptAt ?? "not available"} · Last successful refresh:{" "}
          {status.lastSuccessAt ?? "not available"}
        </Typography>
        <Typography color="text.secondary" sx={{ fontSize: "0.84rem" }}>
          Snapshot: {status.snapshotStartedAt ?? "not started"} →{" "}
          {status.snapshotCompletedAt ?? "not completed"} · Candidate version:{" "}
          {status.candidateVersion ?? "none"} · Active generation:{" "}
          {status.activeGenerationId ?? "none"}
        </Typography>
        {status.errorMessage !== null ? (
          <Alert severity="warning">
            {status.errorCode === null ? "" : `${status.errorCode}: `}
            {status.errorMessage}
          </Alert>
        ) : status.status === "never_refreshed" ? (
          <Alert severity="info">The public merchant reference has not been imported yet.</Alert>
        ) : null}
        <Stack direction="row" useFlexGap spacing={1.5} sx={{ flexWrap: "wrap" }}>
          <ExternalProvenanceLink label="Source provenance" url={status.sourceUrl} />
          <ExternalProvenanceLink label={status.attribution} url={status.attributionUrl} />
          {status.license === null ? null : (
            <Typography color="text.secondary" sx={{ fontSize: "0.82rem" }}>
              Source license: {status.license}
            </Typography>
          )}
        </Stack>
      </Stack>
    </Paper>
  );
}

function VendorReferenceSearch({
  query,
  result,
  loading,
  error,
  saving,
  hasSelectedMerchant,
  onQueryChange,
  onSearch,
  onSelect,
}: {
  readonly query: string;
  readonly result: VendorReferenceSearchResult | null;
  readonly loading: boolean;
  readonly error: string | null;
  readonly saving: boolean;
  readonly hasSelectedMerchant: boolean;
  readonly onQueryChange: (query: string) => void;
  readonly onSearch: () => void;
  readonly onSelect: (candidate: VendorReferenceCandidate) => void;
}): React.JSX.Element {
  return (
    <Paper
      component="section"
      variant="outlined"
      aria-label="Search public merchant references"
      sx={{ p: { xs: 1.75, sm: 2.25 }, borderRadius: 3.5 }}
    >
      <Stack spacing={1.5}>
        <Box>
          <Typography component="h2" variant="h6" sx={{ fontWeight: 700 }}>
            Find a public reference
          </Typography>
          <Typography color="text.secondary">
            Search the locally stored index. Choosing a match links provenance only; it does not
            overwrite a confirmed household identity or alias.
          </Typography>
        </Box>
        <Stack
          component="form"
          direction={{ xs: "column", sm: "row" }}
          spacing={1}
          onSubmit={(event) => {
            event.preventDefault();
            onSearch();
          }}
        >
          <TextField
            label="Merchant name or alias"
            value={query}
            onChange={(event) => onQueryChange(event.target.value)}
            fullWidth
          />
          <Button
            type="submit"
            variant="contained"
            disabled={saving || query.trim() === ""}
            sx={{ minWidth: 140, minHeight: 44 }}
          >
            Search index
          </Button>
        </Stack>
        {error !== null ? <Alert severity="error">{error}</Alert> : null}
        {loading ? <Alert severity="info">Searching the local reference index…</Alert> : null}
        {!hasSelectedMerchant ? (
          <Alert severity="info">
            Select a household merchant before linking a public reference.
          </Alert>
        ) : null}
        {result !== null ? (
          <Stack spacing={1}>
            {result.sourceStatus === "stale" || result.sourceStatus === "failed" ? (
              <Alert severity="warning">
                Search results use a {result.sourceStatus.replaceAll("_", " ")} source index.
              </Alert>
            ) : null}
            <Pill
              tone={
                result.matchStatus === "unique"
                  ? "good"
                  : result.matchStatus === "ambiguous"
                    ? "watch"
                    : "neutral"
              }
            >
              {result.matchStatus.replaceAll("_", " ")}
            </Pill>
            {result.matchStatus === "no_match" ? (
              <Typography color="text.secondary">
                No public references matched this search.
              </Typography>
            ) : (
              <Stack component="ul" spacing={1} sx={{ m: 0, p: 0, listStyle: "none" }}>
                {result.candidates.map((candidate) => (
                  <VendorReferenceCandidateRow
                    key={`${candidate.sourceVersion}:${candidate.sourceKey}`}
                    candidate={candidate}
                    saving={saving}
                    onSelect={() => onSelect(candidate)}
                  />
                ))}
              </Stack>
            )}
            {result.truncated ? (
              <Alert severity="info">
                Showing the first {result.limit} matches. Refine the search to see more specific
                results.
              </Alert>
            ) : null}
          </Stack>
        ) : null}
      </Stack>
    </Paper>
  );
}

function VendorReferenceCandidateRow({
  candidate,
  saving,
  onSelect,
}: {
  readonly candidate: VendorReferenceCandidate;
  readonly saving: boolean;
  readonly onSelect: () => void;
}): React.JSX.Element {
  return (
    <Box
      component="li"
      sx={{
        display: "flex",
        flexWrap: "wrap",
        alignItems: "center",
        justifyContent: "space-between",
        gap: 1,
        py: 1,
        borderBottom: "1px solid",
        borderColor: "divider",
      }}
    >
      <Box sx={{ minWidth: 0, flex: "1 1 18rem" }}>
        <Typography component="strong">{candidate.name}</Typography>
        <Typography component="small" color="text.secondary" sx={{ display: "block" }}>
          {candidate.categoryPath ?? "No category hint"} · source key {candidate.sourceKey} ·
          version {candidate.sourceVersion} · {candidate.license}
        </Typography>
        {candidate.aliases.length > 0 ? (
          <Typography component="small" color="text.secondary" sx={{ display: "block" }}>
            Aliases: {candidate.aliases.join(", ")}
          </Typography>
        ) : null}
      </Box>
      <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
        <ExternalProvenanceLink label="Reference source" url={candidate.sourceUrl} />
        <Button
          disabled={saving}
          onClick={onSelect}
          aria-label={`Link reference ${candidate.name}`}
        >
          Link reference
        </Button>
      </Stack>
    </Box>
  );
}

function ExternalProvenanceLink({
  label,
  url,
}: {
  readonly label: string;
  readonly url: string | null;
}): React.JSX.Element | null {
  const safeUrl = safeHttpUrl(url);
  if (safeUrl === null) {
    return null;
  }
  return (
    <Typography component="a" href={safeUrl} target="_blank" rel="noopener noreferrer">
      {label}
    </Typography>
  );
}

function safeHttpUrl(value: string | null): string | null {
  if (value === null) {
    return null;
  }
  try {
    const url = new URL(value);
    return url.protocol === "https:" || url.protocol === "http:" ? url.toString() : null;
  } catch {
    return null;
  }
}
