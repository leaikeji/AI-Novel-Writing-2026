from __future__ import annotations

from hashlib import sha256
import http.client
from pathlib import Path
import tempfile
import threading
import unittest

from range_etag_server import (
    AuthorizedAssetRegistry,
    ManifestVersion,
    UnsatisfiableRange,
    accept_manifest_refresh,
    make_server,
    parse_single_byte_range,
)


class RangeEtagServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary_directory = tempfile.TemporaryDirectory()
        cls.fixture_path = Path(cls._temporary_directory.name) / "not-the-public-id.wav"
        cls.fixture_bytes = b"RIFF" + bytes(range(64)) + b"WAVE"
        cls.fixture_path.write_bytes(cls.fixture_bytes)
        cls.etag = f'"{sha256(cls.fixture_bytes).hexdigest()}"'
        cls.registry = AuthorizedAssetRegistry({"voice-segment-001": cls.fixture_path})
        cls.server = make_server(cls.registry)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        host, port = cls.server.server_address
        cls.host = str(host)
        cls.port = int(port)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)
        cls._temporary_directory.cleanup()

    def request(
        self,
        method: str = "GET",
        path: str = "/media/voice-segment-001",
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
        connection = http.client.HTTPConnection(self.host, self.port, timeout=5)
        try:
            connection.request(method, path, headers=headers or {})
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def test_full_get_uses_actual_sha256_as_strong_etag(self) -> None:
        status, headers, body = self.request()
        self.assertEqual(status, 200)
        self.assertEqual(body, self.fixture_bytes)
        self.assertEqual(headers["ETag"], self.etag)
        self.assertNotIn("W/", headers["ETag"])
        self.assertEqual(headers["Accept-Ranges"], "bytes")
        self.assertEqual(int(headers["Content-Length"]), len(self.fixture_bytes))

    def test_head_has_get_headers_without_body(self) -> None:
        status, headers, body = self.request("HEAD")
        self.assertEqual(status, 200)
        self.assertEqual(body, b"")
        self.assertEqual(headers["ETag"], self.etag)
        self.assertEqual(int(headers["Content-Length"]), len(self.fixture_bytes))

    def test_closed_range_returns_206_and_safe_content_range(self) -> None:
        status, headers, body = self.request(headers={"Range": "bytes=4-11"})
        self.assertEqual(status, 206)
        self.assertEqual(body, self.fixture_bytes[4:12])
        self.assertEqual(headers["Content-Range"], f"bytes 4-11/{len(self.fixture_bytes)}")
        self.assertEqual(headers["Content-Length"], "8")

    def test_open_ended_and_suffix_ranges(self) -> None:
        open_status, open_headers, open_body = self.request(headers={"Range": "bytes=68-"})
        suffix_status, suffix_headers, suffix_body = self.request(headers={"Range": "bytes=-4"})
        self.assertEqual(open_status, 206)
        self.assertEqual(open_body, b"WAVE")
        self.assertEqual(open_headers["Content-Range"], "bytes 68-71/72")
        self.assertEqual(suffix_status, 206)
        self.assertEqual(suffix_body, b"WAVE")
        self.assertEqual(suffix_headers["Content-Range"], "bytes 68-71/72")

    def test_range_end_is_clamped_to_representation(self) -> None:
        status, headers, body = self.request(headers={"Range": "bytes=70-9999"})
        self.assertEqual(status, 206)
        self.assertEqual(body, b"VE")
        self.assertEqual(headers["Content-Range"], "bytes 70-71/72")

    def test_head_range_returns_206_without_body(self) -> None:
        status, headers, body = self.request("HEAD", headers={"Range": "bytes=1-3"})
        self.assertEqual(status, 206)
        self.assertEqual(body, b"")
        self.assertEqual(headers["Content-Range"], "bytes 1-3/72")
        self.assertEqual(headers["Content-Length"], "3")

    def test_invalid_or_multiple_ranges_return_416(self) -> None:
        for value in ("items=0-2", "bytes=0-1,4-5", "bytes=999-", "bytes=8-2", "bytes=-0"):
            with self.subTest(value=value):
                status, headers, body = self.request(headers={"Range": value})
                self.assertEqual(status, 416)
                self.assertEqual(body, b"")
                self.assertEqual(headers["Content-Range"], "bytes */72")
                self.assertEqual(headers["Content-Length"], "0")

    def test_if_none_match_handles_strong_weak_list_and_wildcard(self) -> None:
        for value in (self.etag, f'"other", {self.etag}', f"W/{self.etag}", "*"):
            with self.subTest(value=value):
                status, headers, body = self.request(headers={"If-None-Match": value})
                self.assertEqual(status, 304)
                self.assertEqual(headers["ETag"], self.etag)
                self.assertEqual(body, b"")

    def test_if_range_requires_exact_strong_etag(self) -> None:
        matched_status, _, matched_body = self.request(
            headers={"Range": "bytes=0-3", "If-Range": self.etag},
        )
        weak_status, _, weak_body = self.request(
            headers={"Range": "bytes=0-3", "If-Range": f"W/{self.etag}"},
        )
        stale_status, _, stale_body = self.request(
            headers={"Range": "bytes=0-3", "If-Range": '"stale"'},
        )
        self.assertEqual((matched_status, matched_body), (206, b"RIFF"))
        self.assertEqual((weak_status, weak_body), (200, self.fixture_bytes))
        self.assertEqual((stale_status, stale_body), (200, self.fixture_bytes))

    def test_if_range_mismatch_ignores_even_malformed_range(self) -> None:
        status, _, body = self.request(
            headers={"Range": "bytes=0-1,4-5", "If-Range": '"stale"'},
        )
        self.assertEqual((status, body), (200, self.fixture_bytes))

    def test_unknown_id_and_path_injection_do_not_resolve_files(self) -> None:
        for path in (
            "/media/not-the-public-id.wav",
            "/media/%2e%2e%2fnot-the-public-id.wav",
            "/media/..%5cnot-the-public-id.wav",
            "/media/voice-segment-001/../anything",
            "/etc/passwd",
        ):
            with self.subTest(path=path):
                status, headers, body = self.request(path=path)
                self.assertEqual(status, 404)
                self.assertEqual(headers["Content-Length"], "0")
                self.assertEqual(body, b"")

    def test_registry_rejects_unsafe_asset_ids(self) -> None:
        for asset_id in ("../secret", "has/slash", "has\\slash", "", "."):
            with self.subTest(asset_id=asset_id):
                with self.assertRaises(ValueError):
                    AuthorizedAssetRegistry({asset_id: self.fixture_path})

    def test_registry_snapshot_keeps_etag_and_content_consistent(self) -> None:
        original = self.fixture_path.read_bytes()
        try:
            self.fixture_path.write_bytes(b"mutated after registry construction")
            status, headers, body = self.request()
            self.assertEqual(status, 200)
            self.assertEqual(body, self.fixture_bytes)
            self.assertEqual(headers["ETag"], self.etag)
        finally:
            self.fixture_path.write_bytes(original)


class ByteRangeParserTests(unittest.TestCase):
    def test_empty_representation_has_no_satisfiable_range(self) -> None:
        for value in ("bytes=0-", "bytes=-1"):
            with self.subTest(value=value), self.assertRaises(UnsatisfiableRange):
                parse_single_byte_range(value, 0)

    def test_negative_size_is_programmer_error(self) -> None:
        with self.assertRaises(ValueError):
            parse_single_byte_range("bytes=0-1", -1)


class ManifestRefreshCasTests(unittest.TestCase):
    def setUp(self) -> None:
        self.current = ManifestVersion(
            edition_id="edition-1",
            source_revision_id="source-revision-7",
            source_sha256="a" * 64,
            manifest_revision=4,
            etag=f'"{"1" * 64}"',
        )

    def incoming(self, **changes: object) -> ManifestVersion:
        values: dict[str, object] = {
            "edition_id": self.current.edition_id,
            "source_revision_id": self.current.source_revision_id,
            "source_sha256": self.current.source_sha256,
            "manifest_revision": self.current.manifest_revision,
            "etag": self.current.etag,
        }
        values.update(changes)
        return ManifestVersion(**values)  # type: ignore[arg-type]

    def test_newer_same_edition_and_source_is_accepted(self) -> None:
        decision = accept_manifest_refresh(
            self.current,
            self.incoming(manifest_revision=5, etag=f'"{"2" * 64}"'),
        )
        self.assertEqual((decision.accepted, decision.reason), (True, "advanced"))

    def test_equal_revision_same_etag_is_idempotent(self) -> None:
        decision = accept_manifest_refresh(self.current, self.incoming())
        self.assertEqual((decision.accepted, decision.reason), (True, "idempotent"))

    def test_equal_revision_different_etag_is_collision(self) -> None:
        decision = accept_manifest_refresh(self.current, self.incoming(etag=f'"{"3" * 64}"'))
        self.assertEqual((decision.accepted, decision.reason), (False, "revision_collision"))

    def test_manifest_identity_rejects_revision_zero_or_weak_etag(self) -> None:
        scenarios = (
            {"manifest_revision": 0},
            {"etag": f'W/"{"4" * 64}"'},
            {"etag": '"not-a-sha256"'},
            {"source_sha256": "not-a-sha256"},
        )
        for changes in scenarios:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.incoming(**changes)

    def test_stale_revision_is_rejected(self) -> None:
        decision = accept_manifest_refresh(self.current, self.incoming(manifest_revision=3))
        self.assertEqual((decision.accepted, decision.reason), (False, "stale_revision"))

    def test_edition_or_source_switch_is_rejected(self) -> None:
        scenarios = (
            (self.incoming(edition_id="edition-2", manifest_revision=5), "edition_mismatch"),
            (self.incoming(source_revision_id="source-revision-8", manifest_revision=5), "source_mismatch"),
            (self.incoming(source_sha256="b" * 64, manifest_revision=5), "source_mismatch"),
        )
        for incoming, reason in scenarios:
            with self.subTest(reason=reason):
                decision = accept_manifest_refresh(self.current, incoming)
                self.assertEqual((decision.accepted, decision.reason), (False, reason))


if __name__ == "__main__":
    unittest.main(verbosity=2)
