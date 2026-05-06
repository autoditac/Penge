# Skill: release

Recipe for cutting a release of Penge and deploying to the home server.

## Cadence

- Releases are cut on demand, typically when a phase milestone closes or a notable feature lands.
- Patch releases for fixes can be cut at any time.

## Tooling

- [release-please](https://github.com/googleapis/release-please) drives version bumps and changelogs from Conventional Commit history.
- Container images are pushed to GHCR (`ghcr.io/autoditac/penge/<service>`).
- SBOM via `syft`; provenance via `actions/attest-build-provenance`.

## Steps

1. **Verify `main` is green.** All checks must be passing for the latest commit.
2. **Review the open release-please PR.** If none exists, no release-worthy changes have landed since the last release.
3. **Sanity-check the changelog.** Edit only typos; otherwise rewrite the offending commit history (rare).
4. **Merge the release-please PR.** This:
   - Bumps versions in `pyproject.toml` / `package.json`.
   - Updates `CHANGELOG.md`.
   - Creates a Git tag `vX.Y.Z`.
   - Drafts a GitHub Release.
5. **CI on the tag** builds and pushes images to GHCR with provenance + SBOM. Wait for green.
6. **Pin digests:** copy the resulting image digests from the release workflow logs into `deploy/compose.prod.yaml`. Open a PR (`chore(deploy): pin vX.Y.Z digests`).
7. **Deploy:** on the home server, `just deploy <tag>` (which pulls by digest from the pinned compose file).
8. **Verify:** check `just deploy-status`, run `just smoke-test` against the live instance.
9. **Publish the GitHub Release** (flip from draft) once deploy is verified.
10. **Move closed issues** to *Done* on the project board. Close the milestone if the release closes one.

## Rollback

- All deploys are by image digest; rolling back is `just deploy <previous-tag>` followed by `alembic downgrade <previous-rev>` if migrations need reversing.
- Database backups (`age`-encrypted) are taken before every deploy. Restore procedure: `docs/runbook/backup-restore.md`.

## Hotfix

1. Branch from the release tag: `git switch -c fix/<issue>-<slug> vX.Y.Z`.
2. Implement the fix with a test.
3. PR to `main`. After merge, release-please opens a new release PR with a `fix:` patch bump.
4. Cherry-pick to any active maintenance branches (currently none).
