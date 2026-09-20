from pathlib import Path

ROOT = Path(__file__).parents[2]


def test_every_buildx_setup_has_an_explicit_teardown() -> None:
    workflows = (
        ROOT / ".github/workflows/ci.yml",
        ROOT / ".github/workflows/release.yml",
    )

    setup_count = 0
    teardown_count = 0
    for workflow in workflows:
        content = workflow.read_text()
        setup_count += content.count("docker/setup-buildx-action@")
        teardown_count += content.count(
            'docker buildx rm --force "${{ steps.buildx.outputs.name }}"'
        )

    assert setup_count == 3
    assert teardown_count == setup_count


def test_image_matrix_jobs_isolate_docker_configuration() -> None:
    ci = (ROOT / ".github/workflows/ci.yml").read_text()
    release = (ROOT / ".github/workflows/release.yml").read_text()
    docker_config = (
        "DOCKER_CONFIG: ${{ runner.temp }}/docker-config-${{ github.job }}-${{ matrix.app }}"
    )

    assert ci.count(docker_config) == 2
    assert release.count(docker_config) == 1


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
