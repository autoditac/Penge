# Dependency updates (Dependabot)

Dependabot keeps GitHub Actions, container base images, Python and npm dependencies current.
The policy lives in [`.github/dependabot.yml`](https://github.com/autoditac/Penge/blob/main/.github/dependabot.yml).

## Policy

| Update type                                  | How it arrives                                       |
| -------------------------------------------- | ---------------------------------------------------- |
| Minor and patch                              | One grouped PR per ecosystem per week                |
| Major                                        | One PR per dependency, reviewed and tested on its own |
| Node / Python runtime version of a base image | Never; upgrade deliberately (see below)              |
| Digest refresh of a pinned base-image tag    | Grouped with the minor/patch PR of the `docker` ecosystem |

Grouping keeps the backlog small.
Without it, the per-ecosystem limit of five open PRs fills up with individual bumps that go stale as soon as `main` moves.

## Reviewing a Dependabot PR

1. Check that the PR is still relevant.
   If `main` already carries the same or a newer version, close it with a comment naming the commit that superseded it.
2. For GitHub Actions, verify that the pinned SHA matches the upstream tag
   (`gh api repos/<owner>/<repo>/git/ref/tags/<tag>`) and read the release notes for removed inputs or runtime changes.
   Self-hosted runners must meet the minimum runner version the action requires.
3. For container images, confirm the digest is the multi-arch **index** digest of the tag and build the image locally
   (see [Container images](container-images.md)).
4. Merge only after CI is green and the Copilot review threads are resolved.

## Runtime upgrades (Node, Python)

Language runtimes of the container base images are ignored by Dependabot on purpose:

- **Node** only moves between LTS lines.
  Odd majors are never LTS and are not used.
- **Python** upgrades must move `requires-python`, ruff `target-version`, mypy `python_version`,
  CI and *both* stages of `apps/api/Containerfile` (the `uv` build image and the slim runtime image) together.
  A runtime-only bump would ship a virtualenv built for a different interpreter.

Open an issue for the upgrade and do it as a single, tested PR.
