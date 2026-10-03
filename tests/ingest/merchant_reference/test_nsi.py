from __future__ import annotations

import base64
import hashlib
import io
import json
import tarfile

import httpx
import pytest

from penge.ingest.merchant_reference.nsi import (
    NPM_RELEASE_URL,
    NsiClient,
    NsiSourceError,
)

_VERSION = "8.0.20260918"
_TARBALL_URL = (
    f"https://registry.npmjs.org/name-suggestion-index/-/name-suggestion-index-{_VERSION}.tgz"
)
_CATALOG_URL = f"https://cdn.jsdelivr.net/npm/name-suggestion-index@{_VERSION}/dist/json/nsi.json"


def _catalog(
    *,
    version: str = _VERSION,
    brand_items: list[dict[str, object]] | None = None,
) -> bytes:
    payload = {
        "_meta": {
            "version": version,
            "generated": "2026-09-18T19:50:18.997Z",
            "url": (
                f"https://cdn.jsdelivr.net/npm/name-suggestion-index@{version}/dist/json/nsi.json"
            ),
        },
        "nsi": {
            "brands/shop/supermarket": {
                "properties": {"exclude": {"generic": ["^supermarket$"]}},
                "items": brand_items
                or [
                    {
                        "displayName": "365discount",
                        "id": "365discount-072052",
                        "locationSet": {"include": ["dk"]},
                        "matchNames": ["Coop 365", "Coop 365discount"],
                        "tags": {
                            "brand": "365discount",
                            "brand:wikidata": "Q104671354",
                            "name": "365discount",
                            "shop": "supermarket",
                        },
                    }
                ],
            },
            "operators/shop/supermarket": {
                "items": [
                    {
                        "displayName": "Private operator example",
                        "id": "operator-1",
                        "tags": {"name": "Private operator example"},
                    }
                ]
            },
        },
    }
    return json.dumps(payload, ensure_ascii=False).encode()


def _package() -> tuple[bytes, bytes]:
    files = {
        "package/package.json": json.dumps(
            {
                "name": "name-suggestion-index",
                "version": _VERSION,
                "license": "BSD-3-Clause",
            }
        ).encode(),
        "package/LICENSE.md": b"## BSD 3-Clause\nSynthetic license text.",
        "package/dist/json/nsi.json": _catalog(),
    }
    archive_bytes = io.BytesIO()
    with tarfile.open(fileobj=archive_bytes, mode="w:gz") as archive:
        for path, content in files.items():
            member = tarfile.TarInfo(path)
            member.size = len(content)
            archive.addfile(member, io.BytesIO(content))
    tarball = archive_bytes.getvalue()
    integrity = "sha512-" + base64.b64encode(hashlib.sha512(tarball).digest()).decode()
    return tarball, integrity.encode()


def _metadata(integrity: bytes, *, version: str = _VERSION, license: str = "BSD-3-Clause") -> bytes:
    return json.dumps(
        {
            "name": "name-suggestion-index",
            "version": version,
            "license": license,
            "dist": {
                "tarball": (
                    "https://registry.npmjs.org/name-suggestion-index/-/name-suggestion-index-"
                    f"{version}.tgz"
                ),
                "integrity": integrity.decode(),
            },
        }
    ).encode()


def _handler(
    *,
    integrity: bytes | None = None,
    metadata_body: bytes | None = None,
    tarball: bytes | None = None,
    requested: list[str] | None = None,
) -> httpx.MockTransport:
    package, package_integrity = _package()

    def respond(request: httpx.Request) -> httpx.Response:
        if requested is not None:
            requested.append(str(request.url))
        if str(request.url) == NPM_RELEASE_URL:
            body = metadata_body or _metadata(integrity or package_integrity)
            return httpx.Response(200, content=body)
        if str(request.url) == _TARBALL_URL:
            return httpx.Response(200, content=tarball or package)
        return httpx.Response(404)

    return httpx.MockTransport(respond)


def test_fetch_latest_pins_version_checks_integrity_and_parses_public_brands() -> None:
    requested: list[str] = []

    with NsiClient(transport=_handler(requested=requested)) as client:
        snapshot = client.fetch_latest_snapshot()

    assert requested == [NPM_RELEASE_URL, _TARBALL_URL]
    assert snapshot.source_version == _VERSION
    assert snapshot.license == "BSD-3-Clause"
    assert snapshot.source_url == _CATALOG_URL
    assert snapshot.record_count == 1
    reference = snapshot.records[0]
    assert reference.source_entity_id == "365discount-072052"
    assert reference.label == "365discount"
    assert reference.aliases == ("365discount", "Coop 365", "Coop 365discount")
    assert reference.category_path == "brands/shop/supermarket"
    assert reference.wikidata_id == "Q104671354"
    assert reference.source_revision_at.isoformat() == "2026-09-18T19:50:18.997000+00:00"
    assert snapshot.sha256 == hashlib.sha256(_catalog()).hexdigest()


def test_parser_keeps_duplicate_public_names_separate_for_conservative_matching() -> None:
    brand_items: list[dict[str, object]] = [
        {"displayName": "Acme", "id": "acme-de", "tags": {"brand": "Acme"}},
        {"displayName": "Acme", "id": "acme-dk", "tags": {"brand": "Acme"}},
    ]
    package = _package_with_catalog(brand_items)
    integrity = "sha512-" + base64.b64encode(hashlib.sha512(package).digest()).decode()

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == NPM_RELEASE_URL:
            return httpx.Response(200, content=_metadata(integrity.encode()))
        if str(request.url) == _TARBALL_URL:
            return httpx.Response(200, content=package)
        return httpx.Response(404)

    with NsiClient(transport=httpx.MockTransport(handler)) as client:
        snapshot = client.fetch_latest_snapshot()

    assert [record.source_entity_id for record in snapshot.records] == ["acme-de", "acme-dk"]
    assert [record.label for record in snapshot.records] == ["Acme", "Acme"]


def test_invalid_checksum_fails_before_catalog_validation() -> None:
    package, _ = _package()

    with (
        NsiClient(
            transport=_handler(integrity=b"sha512-" + base64.b64encode(b"wrong digest")),
            max_tarball_bytes=len(package) + 1,
        ) as client,
        pytest.raises(NsiSourceError, match="checksum did not match"),
    ):
        client.fetch_latest_snapshot()


def test_rejects_non_bsd_release_without_fetching_tarball() -> None:
    package, integrity = _package()
    requested: list[str] = []

    with (
        NsiClient(
            transport=_handler(
                integrity=integrity,
                metadata_body=_metadata(integrity, license="MIT"),
                requested=requested,
            )
        ) as client,
        pytest.raises(NsiSourceError, match="license is not BSD-3-Clause"),
    ):
        client.fetch_latest_snapshot()

    assert requested == [NPM_RELEASE_URL]
    assert package


def test_rejects_tarball_url_outside_allowlisted_registry() -> None:
    package, integrity = _package()
    metadata = json.loads(_metadata(integrity))
    metadata["dist"]["tarball"] = "https://attacker.invalid/package.tgz"
    requested: list[str] = []

    with (
        NsiClient(
            transport=_handler(
                metadata_body=json.dumps(metadata).encode(),
                requested=requested,
            )
        ) as client,
        pytest.raises(NsiSourceError, match="outside the official package registry"),
    ):
        client.fetch_latest_snapshot()

    assert requested == [NPM_RELEASE_URL]
    assert package


def test_rejects_release_catalog_version_mismatch() -> None:
    package = _package_with_catalog(
        [],
        version="8.0.20260919",
        package_version=_VERSION,
    )
    integrity = "sha512-" + base64.b64encode(hashlib.sha512(package).digest()).decode()

    with (
        NsiClient(
            transport=_handler(
                metadata_body=_metadata(integrity.encode()),
                tarball=package,
            )
        ) as client,
        pytest.raises(NsiSourceError, match="catalog version did not match"),
    ):
        client.fetch_latest_snapshot()


def test_rejects_oversized_tarball_before_reading_archive() -> None:
    package, integrity = _package()

    with (
        NsiClient(
            transport=_handler(integrity=integrity, tarball=package),
            max_tarball_bytes=1,
        ) as client,
        pytest.raises(NsiSourceError, match="response exceeded 1 bytes"),
    ):
        client.fetch_latest_snapshot()


def _package_with_catalog(
    brand_items: list[dict[str, object]],
    *,
    version: str = _VERSION,
    package_version: str | None = None,
) -> bytes:
    files = {
        "package/package.json": json.dumps(
            {
                "name": "name-suggestion-index",
                "version": package_version or version,
                "license": "BSD-3-Clause",
            }
        ).encode(),
        "package/LICENSE.md": b"## BSD 3-Clause\nSynthetic license text.",
        "package/dist/json/nsi.json": _catalog(
            version=version,
            brand_items=brand_items,
        ),
    }
    archive_bytes = io.BytesIO()
    with tarfile.open(fileobj=archive_bytes, mode="w:gz") as archive:
        for path, content in files.items():
            member = tarfile.TarInfo(path)
            member.size = len(content)
            archive.addfile(member, io.BytesIO(content))
    return archive_bytes.getvalue()


def test_release_metadata_rejects_wrong_package_name() -> None:
    package, integrity = _package()
    metadata = json.loads(_metadata(integrity))
    metadata["name"] = "another-package"

    with (
        NsiClient(
            transport=_handler(metadata_body=json.dumps(metadata).encode()),
            max_tarball_bytes=len(package) + 1,
        ) as client,
        pytest.raises(NsiSourceError, match="unexpected package"),
    ):
        client.fetch_latest_snapshot()


def test_public_match_names_are_literals_and_source_regex_rules_are_not_imported() -> None:
    package = _package_with_catalog(
        [
            {
                "displayName": "Literal (Brand)",
                "id": "literal-brand",
                "matchNames": ["brand.*", "^literal$"],
                "tags": {"brand": "Literal (Brand)", "brand:wikidata": "not-a-qid"},
            }
        ]
    )
    integrity = "sha512-" + base64.b64encode(hashlib.sha512(package).digest()).decode()

    with NsiClient(
        transport=_handler(
            metadata_body=_metadata(integrity.encode()),
            tarball=package,
        )
    ) as client:
        snapshot = client.fetch_latest_snapshot()

    assert snapshot.records[0].aliases == ("Literal (Brand)", "brand.*", "^literal$")
    assert snapshot.records[0].wikidata_id is None


def test_release_discovery_version_changes_pin_exact_tarball_path() -> None:
    changed_version = "8.0.20260919"
    package = _package_with_catalog([], version=changed_version)
    integrity = "sha512-" + base64.b64encode(hashlib.sha512(package).digest()).decode()
    metadata = json.loads(_metadata(integrity.encode(), version=changed_version))
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        if str(request.url) == NPM_RELEASE_URL:
            return httpx.Response(200, content=json.dumps(metadata).encode())
        if str(request.url).endswith(f"{changed_version}.tgz"):
            return httpx.Response(200, content=package)
        return httpx.Response(404)

    with NsiClient(transport=httpx.MockTransport(handler)) as client:
        snapshot = client.fetch_latest_snapshot()

    assert snapshot.source_version == changed_version
    assert requested[1].endswith(f"{changed_version}.tgz")
