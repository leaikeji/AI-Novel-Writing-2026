"""Stage-0 HTTP Range/strong-ETag prototype for authorized narration media.

This module is deliberately independent from the PawApp API.  Callers construct an
``AuthorizedAssetRegistry`` from explicit server-side asset-id/file mappings; no
request value is ever interpreted as a filesystem path.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import mimetypes
from pathlib import Path
import re
from types import MappingProxyType
from typing import Mapping
from urllib.parse import unquote, urlsplit


_SAFE_ASSET_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SHA256_HEX = re.compile(r"^[a-f0-9]{64}$")
_STRONG_SHA256_ETAG = re.compile(r'^"[a-f0-9]{64}"$')


@dataclass(frozen=True, slots=True)
class AuthorizedAsset:
    """Immutable representation captured from an explicitly authorized file."""

    asset_id: str
    audit_path: Path
    content: bytes
    content_type: str
    sha256_hex: str

    @property
    def etag(self) -> str:
        # A quoted entity-tag without W/ is a strong validator.
        return f'"{self.sha256_hex}"'


class AuthorizedAssetRegistry:
    """Read-only asset registry whose keys, not paths, are exposed to HTTP."""

    def __init__(self, files: Mapping[str, str | Path]) -> None:
        assets: dict[str, AuthorizedAsset] = {}
        for asset_id, candidate in files.items():
            if not _SAFE_ASSET_ID.fullmatch(asset_id):
                raise ValueError(f"unsafe asset id: {asset_id!r}")
            if asset_id in assets:
                raise ValueError(f"duplicate asset id: {asset_id!r}")

            path = Path(candidate).resolve(strict=True)
            if not path.is_file():
                raise ValueError(f"authorized asset is not a regular file: {path}")
            # Stage 0 deliberately snapshots bytes.  This makes the advertised
            # digest exactly match every response and avoids mutable-file TOCTOU.
            content = path.read_bytes()
            content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            assets[asset_id] = AuthorizedAsset(
                asset_id=asset_id,
                audit_path=path,
                content=content,
                content_type=content_type,
                sha256_hex=sha256(content).hexdigest(),
            )
        self._assets = MappingProxyType(assets)

    def get(self, asset_id: str) -> AuthorizedAsset | None:
        return self._assets.get(asset_id)


@dataclass(frozen=True, slots=True)
class ByteRange:
    start: int
    end_inclusive: int

    @property
    def length(self) -> int:
        return self.end_inclusive - self.start + 1


class UnsatisfiableRange(ValueError):
    """Raised for malformed, multiple, or unsatisfiable byte ranges."""


def parse_single_byte_range(value: str, size: int) -> ByteRange:
    """Parse one RFC-style ``bytes`` range; reject multiple/invalid ranges."""

    if size < 0:
        raise ValueError("size must be non-negative")
    if not value.startswith("bytes="):
        raise UnsatisfiableRange("only bytes ranges are supported")
    spec = value[6:].strip()
    if not spec or "," in spec or spec.count("-") != 1:
        raise UnsatisfiableRange("exactly one byte range is required")
    first, last = (part.strip() for part in spec.split("-", 1))
    if first:
        if not first.isascii() or not first.isdecimal():
            raise UnsatisfiableRange("range start must be decimal")
        start = int(first)
        if start >= size:
            raise UnsatisfiableRange("range starts beyond the representation")
        if last:
            if not last.isascii() or not last.isdecimal():
                raise UnsatisfiableRange("range end must be decimal")
            requested_end = int(last)
            if requested_end < start:
                raise UnsatisfiableRange("range end precedes start")
            end = min(requested_end, size - 1)
        else:
            end = size - 1
        return ByteRange(start=start, end_inclusive=end)

    if not last or not last.isascii() or not last.isdecimal():
        raise UnsatisfiableRange("suffix length must be decimal")
    suffix_length = int(last)
    if suffix_length <= 0 or size == 0:
        raise UnsatisfiableRange("suffix range is empty")
    length = min(suffix_length, size)
    return ByteRange(start=size - length, end_inclusive=size - 1)


def _if_none_match_matches(value: str | None, etag: str) -> bool:
    if value is None:
        return False
    # If-None-Match uses weak comparison for GET/HEAD.  The server nevertheless
    # emits only a strong validator for the immutable representation.
    expected_opaque = etag.removeprefix("W/")
    for token in value.split(","):
        candidate = token.strip()
        if candidate == "*" or candidate.removeprefix("W/") == expected_opaque:
            return True
    return False


def _if_range_allows_range(value: str | None, etag: str) -> bool:
    if value is None:
        return True
    # A weak entity tag or HTTP date cannot satisfy a strong If-Range comparison.
    return not value.startswith("W/") and value.strip() == etag


def make_media_handler(
    registry: AuthorizedAssetRegistry,
) -> type[BaseHTTPRequestHandler]:
    """Create a handler bound to one immutable, server-owned registry."""

    class AuthorizedMediaHandler(BaseHTTPRequestHandler):
        server_version = "MossTTSRangePrototype/0.1"
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:  # noqa: N802 - stdlib HTTP method name
            self._serve(include_body=True)

        def do_HEAD(self) -> None:  # noqa: N802 - stdlib HTTP method name
            self._serve(include_body=False)

        def _serve(self, *, include_body: bool) -> None:
            asset = self._resolve_asset()
            if asset is None:
                self._empty_response(404)
                return

            if _if_none_match_matches(self.headers.get("If-None-Match"), asset.etag):
                self.send_response(304)
                self.send_header("ETag", asset.etag)
                self.send_header("Accept-Ranges", "bytes")
                self.end_headers()
                return

            byte_range: ByteRange | None = None
            range_header = self.headers.get("Range")
            if range_header and _if_range_allows_range(self.headers.get("If-Range"), asset.etag):
                try:
                    byte_range = parse_single_byte_range(range_header, len(asset.content))
                except UnsatisfiableRange:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{len(asset.content)}")
                    self.send_header("Accept-Ranges", "bytes")
                    self.send_header("ETag", asset.etag)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return

            if byte_range is None:
                payload = asset.content
                self.send_response(200)
            else:
                payload = asset.content[byte_range.start : byte_range.end_inclusive + 1]
                self.send_response(206)
                self.send_header(
                    "Content-Range",
                    f"bytes {byte_range.start}-{byte_range.end_inclusive}/{len(asset.content)}",
                )
            self.send_header("Content-Type", asset.content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("ETag", asset.etag)
            self.send_header("Cache-Control", "private, max-age=0, must-revalidate")
            self.end_headers()
            if include_body:
                self.wfile.write(payload)

        def _resolve_asset(self) -> AuthorizedAsset | None:
            path = urlsplit(self.path).path
            prefix = "/media/"
            if not path.startswith(prefix):
                return None
            encoded_id = path[len(prefix) :]
            try:
                asset_id = unquote(encoded_id, errors="strict")
            except UnicodeError:
                return None
            # Decode before validation so %2f, %5c and encoded dot traversal are
            # rejected rather than treated as registry keys.
            if not _SAFE_ASSET_ID.fullmatch(asset_id):
                return None
            return registry.get(asset_id)

        def _empty_response(self, status: int) -> None:
            self.send_response(status)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            # The embedding test/application owns logging and must not leak paths.
            return

    return AuthorizedMediaHandler


def make_server(
    registry: AuthorizedAssetRegistry,
    address: tuple[str, int] = ("127.0.0.1", 0),
) -> ThreadingHTTPServer:
    """Create, but do not start, a loopback HTTP server for the prototype."""

    return ThreadingHTTPServer(address, make_media_handler(registry))


@dataclass(frozen=True, slots=True)
class ManifestVersion:
    edition_id: str
    source_revision_id: str
    source_sha256: str
    manifest_revision: int
    etag: str

    def __post_init__(self) -> None:
        if not self.edition_id or not self.source_revision_id:
            raise ValueError("Manifest identity fields must not be empty")
        if not _SHA256_HEX.fullmatch(self.source_sha256):
            raise ValueError("source_sha256 must be lowercase SHA-256 hex")
        if isinstance(self.manifest_revision, bool) or self.manifest_revision < 1:
            raise ValueError("manifest_revision must be an integer >= 1")
        if not _STRONG_SHA256_ETAG.fullmatch(self.etag):
            raise ValueError("Manifest ETag must be a quoted strong SHA-256 validator")


@dataclass(frozen=True, slots=True)
class ManifestRefreshDecision:
    accepted: bool
    reason: str


def accept_manifest_refresh(
    current: ManifestVersion,
    incoming: ManifestVersion,
) -> ManifestRefreshDecision:
    """Apply the isolated Manifest refresh CAS contract.

    Switching Edition/source is a separate product operation.  Within one source,
    revisions are monotonic; an equal revision is only an idempotent replay when its
    entity tag is unchanged.
    """

    if incoming.edition_id != current.edition_id:
        return ManifestRefreshDecision(False, "edition_mismatch")
    if (
        incoming.source_revision_id != current.source_revision_id
        or incoming.source_sha256 != current.source_sha256
    ):
        return ManifestRefreshDecision(False, "source_mismatch")
    if incoming.manifest_revision < current.manifest_revision:
        return ManifestRefreshDecision(False, "stale_revision")
    if (
        incoming.manifest_revision == current.manifest_revision
        and incoming.etag != current.etag
    ):
        return ManifestRefreshDecision(False, "revision_collision")
    if incoming.manifest_revision == current.manifest_revision:
        return ManifestRefreshDecision(True, "idempotent")
    return ManifestRefreshDecision(True, "advanced")
