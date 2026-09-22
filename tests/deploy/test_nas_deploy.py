from pathlib import Path

ROOT = Path(__file__).parents[2]


def test_every_buildx_setup_has_an_explicit_unique_builder_name() -> None:
    """Teardown must not depend on a generated name or a step output.

    `steps.buildx.outputs.name` is unset if the setup step dies after creating
    the builder, and a generated `builder-<uuid>` is unattributable, so a
    leaked builder cannot be swept safely. Guards #287.
    """
    builder_names = {
        ".github/workflows/ci.yml": [
            "BUILDX_BUILDER_NAME: penge-ci-build-"
            "${{ github.run_id }}-${{ github.run_attempt }}-${{ matrix.app }}",
            "BUILDX_BUILDER_NAME: penge-ci-publish-"
            "${{ github.run_id }}-${{ github.run_attempt }}-${{ matrix.app }}",
        ],
        ".github/workflows/release.yml": [
            "BUILDX_BUILDER_NAME: penge-release-"
            "${{ github.run_id }}-${{ github.run_attempt }}-${{ matrix.app }}",
        ],
    }

    seen: list[str] = []
    for workflow, names in builder_names.items():
        content = (ROOT / workflow).read_text()
        for name in names:
            assert content.count(name) == 1, f"{workflow}: {name}"
            seen.append(name)
        # Every setup step consumes the env var rather than defaulting to a
        # generated name.
        assert content.count("name: ${{ env.BUILDX_BUILDER_NAME }}") == len(names)

    assert len(set(seen)) == len(seen), "builder names must be unique per job"


def test_every_buildx_setup_has_an_explicit_teardown() -> None:
    workflows = (
        ROOT / ".github/workflows/ci.yml",
        ROOT / ".github/workflows/release.yml",
    )

    setup_count = 0
    teardown_count = 0
    volume_teardown_count = 0
    for workflow in workflows:
        content = workflow.read_text()
        setup_count += content.count("docker/setup-buildx-action@")
        teardown_count += content.count('docker buildx rm --force "$BUILDX_BUILDER_NAME" || true')
        # A running BuildKit container pins its *named* state volume, so
        # `docker volume prune` alone never reclaims it.
        volume_teardown_count += content.count(
            'docker volume rm --force "buildx_buildkit_${BUILDX_BUILDER_NAME}0_state"'
        )

    assert setup_count == 3
    assert teardown_count == setup_count
    assert volume_teardown_count == setup_count
    # The stale teardown condition silently skipped cleanup whenever the setup
    # step failed before publishing outputs.
    for workflow in workflows:
        assert "${{ steps.buildx.outputs.name }}" not in workflow.read_text()


def test_teardown_never_prunes_beyond_its_own_job() -> None:
    """A blanket prune would destroy a concurrent matrix job's cache."""
    for workflow in (".github/workflows/ci.yml", ".github/workflows/release.yml"):
        content = (ROOT / workflow).read_text()
        assert "docker system prune" not in content
        assert "buildx prune" not in content
        assert "docker volume prune" not in content


def test_ci_images_are_run_scoped_and_removed() -> None:
    """A shared `:ci` tag leaks the superseded image on every run."""
    ci = (ROOT / ".github/workflows/ci.yml").read_text()
    tag = (
        "CI_IMAGE_TAG: penge/${{ matrix.app }}:ci-" "${{ github.run_id }}-${{ github.run_attempt }}"
    )

    assert ci.count(tag) == 1
    assert "tags: penge/${{ matrix.app }}:ci\n" not in ci
    assert ci.count("tags: ${{ env.CI_IMAGE_TAG }}") == 1
    assert ci.count('docker run --rm "$CI_IMAGE_TAG"') == 1
    assert ci.count('docker image rm --force "$CI_IMAGE_TAG"') == 1


def test_buildkit_cache_cap_uses_a_real_ceiling() -> None:
    """`keepBytes`/`reservedSpace` is a floor, not a cap: it bounds nothing."""
    for workflow in (".github/workflows/ci.yml", ".github/workflows/release.yml"):
        content = (ROOT / workflow).read_text()
        assert content.count('                maxUsedSpace = "2GB"') == content.count(
            "docker/setup-buildx-action@"
        )
        assert "keepBytes =" not in content
        assert "reservedSpace =" not in content


def test_runner_maintenance_is_concurrency_safe() -> None:
    workflow = (ROOT / ".github/workflows/runner-maintenance.yml").read_text()

    assert "group: runner-maintenance" in workflow
    # Cancelling a sweep mid-prune is how half-removed state accumulates.
    assert "cancel-in-progress: false" in workflow
    assert "./deploy/runner/docker-gc.sh --max-age-hours" in workflow


def test_runner_gc_units_are_scheduled_within_the_age_threshold() -> None:
    """The host timer must fire far more often than resources can pile up."""
    service = (ROOT / "deploy/runner/penge-docker-gc.service").read_text()
    timer = (ROOT / "deploy/runner/penge-docker-gc.timer").read_text()

    assert "ExecStart=/usr/local/bin/penge-docker-gc --max-age-hours 2" in service
    assert "OnCalendar=hourly" in timer
    # Reboots are one of the ways a builder leaks; catch up after one.
    assert "Persistent=true" in timer


def test_image_matrix_jobs_isolate_docker_configuration() -> None:
    ci = (ROOT / ".github/workflows/ci.yml").read_text()
    release = (ROOT / ".github/workflows/release.yml").read_text()
    docker_config = (
        "DOCKER_CONFIG: /tmp/penge-docker-"
        "${{ github.run_id }}-${{ github.run_attempt }}-${{ matrix.app }}"
    )

    assert ci.count(docker_config) == 2
    assert release.count(docker_config) == 1
    assert ci.count('cp "$DOCKER_CONFIG/config.json" "$ATTEST_HOME/.docker/config.json"') == 1
    assert release.count('cp "$DOCKER_CONFIG/config.json" "$ATTEST_HOME/.docker/config.json"') == 1
    attest_home = "\n          HOME: ${{ runner.temp }}/attest-home-${{ matrix.app }}"
    assert ci.count(attest_home) == 1
    assert release.count(attest_home) == 1


def test_nas_web_container_is_loopback_only_and_auto_updated() -> None:
    quadlet = (ROOT / "deploy/nas/penge-web.container").read_text()

    assert "Image=ghcr.io/autoditac/penge/web:main" in quadlet
    assert "AutoUpdate=registry" in quadlet
    assert "PublishPort=127.0.0.1:8082:8080" in quadlet
    assert "Notify=healthy" in quadlet


def test_nas_nginx_routes_spa_to_web_container_and_api_separately() -> None:
    nginx = (ROOT / "deploy/nas/penge.eigmueller.de.conf").read_text()

    assert "proxy_pass http://127.0.0.1:8082;" in nginx
    assert "proxy_pass http://127.0.0.1:8001;" in nginx
    assert "root  /var/www/penge;" not in nginx


def test_web_image_targets_the_production_api_origin() -> None:
    containerfile = (ROOT / "apps/web/Containerfile").read_text()

    assert "ARG VITE_PENGE_API_URL=https://penge.eigmueller.de" in containerfile
    assert "ENV VITE_PENGE_API_URL=${VITE_PENGE_API_URL}" in containerfile
