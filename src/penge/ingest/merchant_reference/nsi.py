"""Versioned Name Suggestion Index snapshot source.

Only the official, compiled NSI catalog is downloaded. Its literal names
are data; upstream matching and exclusion expressions are never executed.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import io
import json
import re
import tarfile
from datetime import UTC, datetime
from typing import Literal

import httpx
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

NPM_RELEASE_URL = "https://registry.npmjs.org/name-suggestion-index/latest"
NPM_TARBALL_BASE_URL = "https://registry.npmjs.org/name-suggestion-index/-/name-suggestion-index-"
NSI_SOURCE_ID = "name-suggestion-index"
NSI_PACKAGE_NAME = "name-suggestion-index"
NSI_LICENSE = "BSD-3-Clause"
NSI_PROJECT_URL = "https://github.com/osmlab/name-suggestion-index"
NSI_CATALOG_PATH = "package/dist/json/nsi.json"
NSI_LICENSE_PATH = "package/LICENSE.md"
MAX_METADATA_BYTES = 100_000
MAX_TARBALL_BYTES = 30_000_000
MAX_PACKAGE_UNPACKED_BYTES = 120_000_000
MAX_CATALOG_BYTES = 20_000_000
MAX_BRAND_RECORDS = 50_000
MAX_ALIASES_PER_RECORD = 100
MAX_TEXT_LENGTH = 256
_HTTP_ERROR_STATUS = 400
DEFAULT_TIMEOUT_SECONDS = 60.0
_USER_AGENT = "PengeMerchantReference/1.0 (https://github.com/autoditac/Penge)"
_VERSION_PATTERN = re.compile(r"[0-9]+\.[0-9]+\.[0-9]{8}\Z")
_INTEGRITY_PATTERN = re.compile(r"sha512-[A-Za-z0-9+/]+={0,2}\Z")
_QID_PATTERN = re.compile(r"Q[1-9][0-9]{0,11}\Z")
_ALIAS_TAGS = (
    "brand",
    "brand:en",
    "name",
    "name:en",
    "alt_name",
    "short_name",
)


class NsiSourceError(RuntimeError):
    """A sanitized error raised when a public catalog cannot be validated."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class NsiRelease(BaseModel):
    """Pinned release metadata for one official package version."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]{8}$")
    license: Literal["BSD-3-Clause"]
    integrity: str = Field(pattern=r"^sha512-[A-Za-z0-9+/]+={0,2}$")
    tarball_url: str


class PublicMerchantReference(BaseModel):
    """One validated public brand suggestion with upstream provenance."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    source_id: Literal["name-suggestion-index"] = "name-suggestion-index"
    source_entity_id: str = Field(min_length=1, max_length=200)
    label: str = Field(min_length=1, max_length=MAX_TEXT_LENGTH)
    aliases: tuple[str, ...] = Field(max_length=MAX_ALIASES_PER_RECORD)
    category_path: str = Field(pattern=r"^brands/.{1,190}$")
    wikidata_id: str | None = Field(default=None, pattern=r"^Q[1-9][0-9]{0,11}$")
    source_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]{8}$")
    source_revision_at: datetime
    source_url: str
    license: Literal["BSD-3-Clause"] = "BSD-3-Clause"


class NsiSnapshot(BaseModel):
    """An all-or-nothing, fully validated published NSI snapshot."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: Literal["name-suggestion-index"] = "name-suggestion-index"
    source_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]{8}$")
    source_generated_at: datetime
    retrieved_at: datetime
    source_url: str
    license: Literal["BSD-3-Clause"] = "BSD-3-Clause"
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    record_count: int = Field(ge=1, le=MAX_BRAND_RECORDS)
    records: tuple[PublicMerchantReference, ...]

    @model_validator(mode="after")
    def validate_record_set(self) -> NsiSnapshot:
        if self.record_count != len(self.records):
            raise ValueError("record_count must equal the number of records")
        if any(record.source_version != self.source_version for record in self.records):
            raise ValueError("every reference must use the snapshot source version")
        if len({record.source_entity_id for record in self.records}) != len(self.records):
            raise ValueError("source entity identifiers must be unique")
        return self


class _ReleaseDistribution(BaseModel):
    model_config = ConfigDict(extra="ignore")

    tarball: str
    integrity: str


class _ReleaseMetadata(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    version: str
    license: str
    dist: _ReleaseDistribution


class _NsiEntry(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    display_name: str = Field(alias="displayName", min_length=1, max_length=MAX_TEXT_LENGTH)
    entity_id: str = Field(alias="id", min_length=1, max_length=200)
    match_names: list[str] = Field(default_factory=list, alias="matchNames")
    tags: dict[str, str]

    @field_validator("match_names")
    @classmethod
    def bound_match_names(cls, values: list[str]) -> list[str]:
        if len(values) > MAX_ALIASES_PER_RECORD:
            raise ValueError("too many match names")
        if any(len(value) > MAX_TEXT_LENGTH for value in values):
            raise ValueError("match name is too long")
        return values


class _NsiCategory(BaseModel):
    model_config = ConfigDict(extra="ignore")

    items: list[_NsiEntry]


class _NsiMetadata(BaseModel):
    model_config = ConfigDict(extra="ignore")

    version: str
    generated: datetime
    url: str


class _NsiDocument(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    metadata: _NsiMetadata = Field(alias="_meta")
    nsi: dict[str, _NsiCategory]


class _PackageMetadata(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    version: str
    license: str


class NsiClient:
    """Discover and fetch exact-version NSI releases with strict size bounds."""

    def __init__(
        self,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        max_tarball_bytes: int = MAX_TARBALL_BYTES,
        max_catalog_bytes: int = MAX_CATALOG_BYTES,
    ) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        if not 1 <= max_tarball_bytes <= MAX_TARBALL_BYTES:
            raise ValueError(f"max_tarball_bytes must be between 1 and {MAX_TARBALL_BYTES}")
        if not 1 <= max_catalog_bytes <= MAX_CATALOG_BYTES:
            raise ValueError(f"max_catalog_bytes must be between 1 and {MAX_CATALOG_BYTES}")
        self._http = httpx.Client(
            timeout=timeout,
            transport=transport,
            headers={"Accept": "application/json", "User-Agent": _USER_AGENT},
        )
        self._max_tarball_bytes = max_tarball_bytes
        self._max_catalog_bytes = max_catalog_bytes

    def __enter__(self) -> NsiClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        """Close the underlying HTTP connection pool."""
        self._http.close()

    def discover_release(self) -> NsiRelease:
        """Discover the published version, then pin all following requests to it."""
        response_body = self._get_bytes(NPM_RELEASE_URL, max_bytes=MAX_METADATA_BYTES)
        try:
            raw = json.loads(response_body)
            metadata = _ReleaseMetadata.model_validate(raw)
            if metadata.name != NSI_PACKAGE_NAME:
                raise NsiSourceError("unexpected_package", "NPM returned an unexpected package")
            if metadata.license != NSI_LICENSE:
                raise NsiSourceError(
                    "unsupported_license",
                    "NSI release license is not BSD-3-Clause",
                )
            if _VERSION_PATTERN.fullmatch(metadata.version) is None:
                raise NsiSourceError("invalid_version", "NPM returned an invalid NSI version")
            if _INTEGRITY_PATTERN.fullmatch(metadata.dist.integrity) is None:
                raise NsiSourceError("invalid_integrity", "NPM returned invalid package integrity")
            expected_url = f"{NPM_TARBALL_BASE_URL}{metadata.version}.tgz"
            if metadata.dist.tarball != expected_url:
                raise NsiSourceError(
                    "unexpected_tarball",
                    "NPM returned a tarball outside the official package registry",
                )
            return NsiRelease(
                version=metadata.version,
                license="BSD-3-Clause",
                integrity=metadata.dist.integrity,
                tarball_url=expected_url,
            )
        except (json.JSONDecodeError, UnicodeDecodeError, ValidationError) as exc:
            raise NsiSourceError(
                "invalid_release_metadata",
                f"NPM returned invalid release metadata ({type(exc).__name__})",
            ) from exc

    def fetch_snapshot(self, release: NsiRelease | None = None) -> NsiSnapshot:
        """Fetch, checksum, and validate the complete compiled brand catalog."""
        pinned_release = release or self.discover_release()
        _validate_release(pinned_release)
        tarball = self._get_bytes(
            pinned_release.tarball_url,
            max_bytes=self._max_tarball_bytes,
        )
        _verify_integrity(tarball, pinned_release.integrity)
        catalog_bytes, package_bytes, license_bytes = _read_package_files(tarball)
        if len(catalog_bytes) > self._max_catalog_bytes:
            raise NsiSourceError(
                "catalog_too_large",
                f"NSI catalog exceeded {self._max_catalog_bytes} bytes",
            )
        try:
            package = _PackageMetadata.model_validate(json.loads(package_bytes))
            if (
                package.name != NSI_PACKAGE_NAME
                or package.version != pinned_release.version
                or package.license != NSI_LICENSE
            ):
                raise NsiSourceError(
                    "package_metadata_mismatch",
                    "NSI tarball metadata did not match the pinned release",
                )
            if b"BSD 3-Clause" not in license_bytes:
                raise NsiSourceError(
                    "license_notice_missing",
                    "NSI tarball did not include its BSD 3-Clause license notice",
                )
            document = _NsiDocument.model_validate(json.loads(catalog_bytes))
            if document.metadata.version != pinned_release.version:
                raise NsiSourceError(
                    "catalog_version_mismatch",
                    "NSI catalog version did not match the pinned release",
                )
            expected_source_url = (
                f"https://cdn.jsdelivr.net/npm/{NSI_PACKAGE_NAME}@"
                f"{pinned_release.version}/dist/json/nsi.json"
            )
            if document.metadata.url != expected_source_url:
                raise NsiSourceError(
                    "catalog_source_mismatch",
                    "NSI catalog URL did not match the pinned release",
                )
            records = _parse_records(document)
        except (json.JSONDecodeError, UnicodeDecodeError, ValidationError) as exc:
            raise NsiSourceError(
                "invalid_catalog",
                f"NSI catalog failed validation ({type(exc).__name__})",
            ) from exc

        if not records:
            raise NsiSourceError("empty_catalog", "NSI catalog contained no brand records")
        if len(records) > MAX_BRAND_RECORDS:
            raise NsiSourceError(
                "too_many_records",
                f"NSI catalog exceeded {MAX_BRAND_RECORDS} brand records",
            )
        try:
            return NsiSnapshot(
                source_version=pinned_release.version,
                source_generated_at=_as_utc(document.metadata.generated),
                retrieved_at=datetime.now(UTC),
                source_url=document.metadata.url,
                sha256=hashlib.sha256(catalog_bytes).hexdigest(),
                record_count=len(records),
                records=tuple(records),
            )
        except ValidationError as exc:
            raise NsiSourceError(
                "invalid_snapshot",
                f"NSI snapshot failed validation ({type(exc).__name__})",
            ) from exc

    def fetch_latest_snapshot(self) -> NsiSnapshot:
        """Discover and fetch a fully validated current release."""
        return self.fetch_snapshot(self.discover_release())

    def _get_bytes(self, url: str, *, max_bytes: int) -> bytes:
        try:
            with self._http.stream("GET", url) as response:
                if response.status_code >= _HTTP_ERROR_STATUS:
                    raise NsiSourceError(
                        "http_status",
                        f"NSI source returned HTTP {response.status_code}",
                    )
                body = _read_limited(response, max_bytes=max_bytes)
        except httpx.HTTPError as exc:
            raise NsiSourceError(
                "transport_error",
                f"NSI source request failed ({type(exc).__name__})",
            ) from exc
        return body


def _read_limited(response: httpx.Response, *, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    size = 0
    for chunk in response.iter_bytes():
        size += len(chunk)
        if size > max_bytes:
            raise NsiSourceError(
                "response_too_large",
                f"NSI response exceeded {max_bytes} bytes",
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _validate_release(release: NsiRelease) -> None:
    expected_url = f"{NPM_TARBALL_BASE_URL}{release.version}.tgz"
    if release.license != NSI_LICENSE or release.tarball_url != expected_url:
        raise ValueError("release must be a pinned BSD-3-Clause NSI package from npm")
    if _VERSION_PATTERN.fullmatch(release.version) is None:
        raise ValueError("release version is invalid")
    if _INTEGRITY_PATTERN.fullmatch(release.integrity) is None:
        raise ValueError("release integrity is invalid")


def _verify_integrity(tarball: bytes, integrity: str) -> None:
    try:
        expected = base64.b64decode(integrity.removeprefix("sha512-"), validate=True)
    except binascii.Error as exc:
        raise NsiSourceError("invalid_integrity", "NSI package integrity was invalid") from exc
    actual = hashlib.sha512(tarball).digest()
    if actual != expected:
        raise NsiSourceError("integrity_mismatch", "NSI package checksum did not match metadata")


def _read_package_files(tarball: bytes) -> tuple[bytes, bytes, bytes]:
    expected_files = {
        NSI_CATALOG_PATH: MAX_CATALOG_BYTES,
        "package/package.json": MAX_METADATA_BYTES,
        NSI_LICENSE_PATH: MAX_METADATA_BYTES,
    }
    files: dict[str, bytes] = {}
    unpacked_size = 0
    try:
        with tarfile.open(fileobj=io.BytesIO(tarball), mode="r|gz") as archive:
            for member in archive:
                unpacked_size += member.size
                if unpacked_size > MAX_PACKAGE_UNPACKED_BYTES:
                    raise NsiSourceError(
                        "package_too_large",
                        f"NSI package exceeded {MAX_PACKAGE_UNPACKED_BYTES} unpacked bytes",
                    )
                max_bytes = expected_files.get(member.name)
                if max_bytes is None:
                    continue
                if member.name in files:
                    raise NsiSourceError(
                        "duplicate_package_file",
                        f"NSI tarball contains duplicate {member.name}",
                    )
                if not member.isfile() or member.size > max_bytes:
                    raise NsiSourceError(
                        "invalid_package_file",
                        f"NSI tarball contains invalid {member.name}",
                    )
                stream = archive.extractfile(member)
                if stream is None:
                    raise NsiSourceError(
                        "invalid_package_file",
                        f"NSI tarball contains unreadable {member.name}",
                    )
                with stream:
                    contents = stream.read(max_bytes + 1)
                if len(contents) > max_bytes:
                    raise NsiSourceError(
                        "package_file_too_large",
                        f"NSI {member.name} exceeded {max_bytes} bytes",
                    )
                files[member.name] = contents
    except (tarfile.TarError, OSError) as exc:
        raise NsiSourceError(
            "invalid_package",
            f"NSI tarball could not be read ({type(exc).__name__})",
        ) from exc
    missing = set(expected_files) - set(files)
    if missing:
        name = min(missing)
        raise NsiSourceError("missing_package_file", f"NSI tarball is missing {name}")
    return files[NSI_CATALOG_PATH], files["package/package.json"], files[NSI_LICENSE_PATH]


def _parse_records(document: _NsiDocument) -> list[PublicMerchantReference]:
    references: list[PublicMerchantReference] = []
    for category_path, category in document.nsi.items():
        if not category_path.startswith("brands/"):
            continue
        for entry in category.items:
            aliases = _entry_aliases(entry)
            wikidata_id = entry.tags.get("brand:wikidata")
            if wikidata_id is not None and _QID_PATTERN.fullmatch(wikidata_id) is None:
                wikidata_id = None
            references.append(
                PublicMerchantReference(
                    source_entity_id=entry.entity_id,
                    label=entry.display_name,
                    aliases=tuple(aliases),
                    category_path=category_path,
                    wikidata_id=wikidata_id,
                    source_version=document.metadata.version,
                    source_revision_at=_as_utc(document.metadata.generated),
                    source_url=document.metadata.url,
                )
            )
    return references


def _entry_aliases(entry: _NsiEntry) -> list[str]:
    candidates = [entry.display_name, *entry.match_names]
    candidates.extend(entry.tags[tag] for tag in _ALIAS_TAGS if tag in entry.tags)
    aliases: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        alias = candidate.strip()
        folded = alias.casefold()
        if not alias or len(alias) > MAX_TEXT_LENGTH or folded in seen:
            continue
        seen.add(folded)
        aliases.append(alias)
    if len(aliases) > MAX_ALIASES_PER_RECORD:
        raise NsiSourceError("too_many_aliases", "NSI brand contained too many literal aliases")
    return aliases


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise NsiSourceError("invalid_timestamp", "NSI timestamp did not include a timezone")
    return value.astimezone(UTC)


__all__ = [
    "NsiClient",
    "NsiRelease",
    "NsiSnapshot",
    "NsiSourceError",
    "PublicMerchantReference",
]
