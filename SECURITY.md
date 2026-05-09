# Security Policy

Penge holds highly sensitive personal-finance data (DK + DE accounts, tax records, salary data). This policy is what we expect from contributors and what we expect from the system itself.

## Threat model (informal)

- **Primary asset:** raw financial data (statements, holdings, transactions, salaries, tax filings).
- **Adversaries:** (1) accidental leakage via commits or logs; (2) unauthorized access to the home server; (3) data exfiltration through compromised dependencies; (4) over-broad LLM access.
- **Out of scope (for now):** nation-state attackers, physical-access attacks on the home server.

## Reporting a vulnerability

This is a private repository for personal use. If you have access and find a vulnerability, open a private security advisory via *Security → Advisories → Report a vulnerability* on GitHub.

## Engineering rules

### Secrets

- Plaintext secrets must never be committed. `gitleaks` runs in pre-commit and CI; GitHub secret-scanning is enabled.
- Local development uses `.env` (gitignored). Commit `.env.example` with safe placeholders.
- Shared/encrypted secrets use `sops` + `age`; the `age` recipient public key is committed, the private key is not.

### Dependencies

- Lockfiles (`uv.lock`, `pnpm-lock.yaml`) are committed. Builds must be reproducible from lockfiles.
- Dependabot opens PRs for security updates. (CodeQL static analysis is parked until the repo goes public or GitHub Advanced Security is purchased; SARIF upload requires code scanning to be enabled on the repository.)
- Adding a new dependency requires (a) noting why an existing one cannot be used, (b) checking maintenance status and license, and (c) recording it in the relevant ADR if it crosses a boundary.

### Container & deploy hardening

- Docker images are pinned by digest, multi-stage, and run on a `distroless` runtime where possible.
- Non-root user inside containers. No `--privileged`. Minimal capabilities.
- All deployed image versions are recorded in `deploy/` and reproducible (digest pin).

### Supply-chain

- All GitHub Actions are pinned by SHA, not by tag.
- Releases produce an SBOM (`syft`) and a build-provenance attestation (`actions/attest-build-provenance`).

### Data handling

- The `data/` directory is gitignored and never committed.
- Backups are encrypted with `age` before leaving the home server.
- LLM access goes exclusively through the MCP server's typed tools — no bulk data is sent to LLMs.
- Personally-identifying fields in logs are redacted via `structlog` processors.

### Authentication

- Web UIs are reachable only via Tailscale or behind Caddy with strong auth.
- API tokens (GoCardless, etc.) are scoped to the minimum required permissions and rotated yearly.

## Disclosure

Until this project goes public (if ever), all security issues are handled privately between maintainers.
