from __future__ import annotations

from http.client import HTTPConnection
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
import wave


SIDECAR_ROOT = Path(__file__).resolve().parent
if str(SIDECAR_ROOT) not in sys.path:
    sys.path.insert(0, str(SIDECAR_ROOT))

from sidecar_client import SidecarClient
from sidecar_protocol import (
    MAX_REQUEST_BYTES,
    MAX_REFERENCE_AUDIO_BYTES,
    PROTOCOL_VERSION,
    TOKEN_HEADER,
    VERSION_HEADER,
    ProtocolError,
    ReferenceAudio,
    SynthesisRequest,
    build_multipart_body,
    canonical_json_bytes,
    parse_request_bytes,
    request_payload,
)
from sidecar_server import FakeBackend, SidecarHTTPServer, SidecarState


TOKEN = "test-only-random-token-0123456789abcdef"


def wav_bytes(duration_seconds: float = 3.0, *, sample_rate: int = 8_000) -> bytes:
    stream = io.BytesIO()
    with wave.open(stream, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(b"\x00\x00" * int(duration_seconds * sample_rate))
    return stream.getvalue()


def reference(payload: bytes | None = None, *, audio_format: str = "wav") -> ReferenceAudio:
    value = payload if payload is not None else wav_bytes()
    return ReferenceAudio(
        reference_asset_id="reference-00000001",
        declared_sha256=hashlib.sha256(value).hexdigest(),
        audio_format=audio_format,
        declared_size_bytes=len(value),
        duration_seconds=3.0,
        payload=value,
    )


def request(
    index: int = 1,
    *,
    text: str = "授权测试文本",
    reference_audio: ReferenceAudio | None = None,
) -> SynthesisRequest:
    return SynthesisRequest(
        request_id=f"request-{index:08d}",
        asset_id=f"asset-{index:08d}",
        text=text,
        voice="Junhao",
        seed=42,
        max_new_frames=100,
        sample_mode="fixed",
        reference_audio=reference_audio,
    )


class RunningServer:
    def __init__(self, backend: FakeBackend | None = None) -> None:
        self.state = SidecarState(TOKEN, backend or FakeBackend())
        self.server = SidecarHTTPServer(("127.0.0.1", 0), self.state)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def port(self) -> int:
        return int(self.server.server_address[1])

    def __enter__(self) -> "RunningServer":
        self.thread.start()
        return self

    def __exit__(self, *_args: object) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        if self.thread.is_alive():
            raise AssertionError("HTTP server thread leaked")


def headers(token: str = TOKEN, *, version: str = PROTOCOL_VERSION, length: int = 0) -> dict[str, str]:
    result = {TOKEN_HEADER: token, VERSION_HEADER: version}
    if length:
        result.update({"Content-Type": "application/json", "Content-Length": str(length)})
    return result


class RequestValidationTests(unittest.TestCase):
    def test_valid_request_contains_no_path_or_secret_field(self) -> None:
        raw = canonical_json_bytes(request_payload(request()))
        parsed = parse_request_bytes(raw)
        self.assertEqual(parsed.asset_id, "asset-00000001")
        self.assertNotIn(b"path", raw.lower())
        self.assertNotIn(TOKEN.encode(), raw)

    def test_any_nested_path_or_secret_field_is_rejected(self) -> None:
        for field in ("output_path", "database_dsn", "callback_url", "auth_token"):
            payload = request_payload(request())
            payload["parameters"][field] = "/forbidden"  # type: ignore[index]
            with self.subTest(field=field), self.assertRaisesRegex(
                ProtocolError, "forbidden field"
            ):
                parse_request_bytes(canonical_json_bytes(payload))

    def test_traversal_identifier_and_oversize_body_are_rejected(self) -> None:
        payload = request_payload(request())
        payload["asset_id"] = "../../novel-media"
        with self.assertRaisesRegex(ProtocolError, "identifier"):
            parse_request_bytes(canonical_json_bytes(payload))
        with self.assertRaisesRegex(ProtocolError, "size"):
            parse_request_bytes(b"{" + b"x" * MAX_REQUEST_BYTES + b"}")

    def test_reference_hash_size_format_duration_and_missing_bytes_fail_closed(self) -> None:
        valid = reference()
        payload = request_payload(request(reference_audio=valid))
        parsed = parse_request_bytes(canonical_json_bytes(payload), reference_audio_bytes=valid.payload)
        self.assertEqual(parsed.reference_audio.duration_seconds, 3.0)  # type: ignore[union-attr]

        bad_hash = json.loads(json.dumps(payload))
        bad_hash["reference_audio"]["declared_sha256"] = "0" * 64
        with self.assertRaisesRegex(ProtocolError, "hash mismatch"):
            parse_request_bytes(canonical_json_bytes(bad_hash), reference_audio_bytes=valid.payload)

        with self.assertRaisesRegex(ProtocolError, "bytes are required"):
            parse_request_bytes(canonical_json_bytes(payload))

        too_large = b"R" * (MAX_REFERENCE_AUDIO_BYTES + 1)
        oversized = request_payload(request(reference_audio=reference(too_large)))
        with self.assertRaisesRegex(ProtocolError, "size"):
            parse_request_bytes(canonical_json_bytes(oversized), reference_audio_bytes=too_large)

        bad_format = json.loads(json.dumps(payload))
        bad_format["reference_audio"]["format"] = "mp3"
        with self.assertRaisesRegex(ProtocolError, "unsupported"):
            parse_request_bytes(canonical_json_bytes(bad_format), reference_audio_bytes=valid.payload)

        too_long = wav_bytes(13.0)
        long_metadata = request_payload(request(reference_audio=reference(too_long)))
        with self.assertRaisesRegex(ProtocolError, "duration"):
            parse_request_bytes(canonical_json_bytes(long_metadata), reference_audio_bytes=too_long)

    def test_reference_path_url_and_multipart_filename_are_rejected(self) -> None:
        valid = reference()
        payload = request_payload(request(reference_audio=valid))
        for field in ("reference_path", "reference_url"):
            mutated = json.loads(json.dumps(payload))
            mutated["reference_audio"][field] = "/private/audio.wav"
            with self.subTest(field=field), self.assertRaisesRegex(ProtocolError, "forbidden field"):
                parse_request_bytes(canonical_json_bytes(mutated), reference_audio_bytes=valid.payload)

        body, content_type = build_multipart_body(request(reference_audio=valid), "0123456789abcdef01234567")
        body = body.replace(
            b'name="reference_audio"',
            b'name="reference_audio"; filename="private.wav"',
        )
        from sidecar_protocol import parse_multipart_body

        with self.assertRaisesRegex(ProtocolError, "filename"):
            parse_multipart_body(body, content_type)


class HTTPProtocolTests(unittest.TestCase):
    def test_capability_handshake_requires_header_token_and_version(self) -> None:
        with RunningServer() as running:
            client = SidecarClient("127.0.0.1", running.port, TOKEN)
            capability = client.capabilities()
            self.assertEqual(capability["protocol_version"], PROTOCOL_VERSION)

            connection = HTTPConnection("127.0.0.1", running.port, timeout=2)
            connection.request("GET", "/v1/capabilities", headers={VERSION_HEADER: PROTOCOL_VERSION})
            response = connection.getresponse()
            body = response.read()
            self.assertEqual(response.status, 401)
            self.assertNotIn(TOKEN.encode(), body)
            connection.close()

            connection = HTTPConnection("127.0.0.1", running.port, timeout=2)
            connection.request(
                "GET",
                "/v1/capabilities",
                headers=headers(version="moss-tts-sidecar/0.0"),
            )
            response = connection.getresponse()
            self.assertEqual(response.status, 400)
            connection.close()

    def test_synthesis_returns_bounded_bytes_and_pawapp_atomically_publishes(self) -> None:
        with RunningServer() as running, tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            client = SidecarClient("127.0.0.1", running.port, TOKEN)
            result = client.synthesize_and_publish(request(), root)
            self.assertEqual(result["status"], "published")
            self.assertEqual(result["file_name"], "asset-00000001.wav")
            self.assertTrue((root / "asset-00000001.wav").is_file())
            self.assertFalse(list(root.glob("*.part")))
            before_reuse = client.capabilities()["process"]["completed_request_count"]  # type: ignore[index]
            reused = client.synthesize_and_publish(request(), root)
            self.assertEqual(reused["status"], "reused")
            self.assertEqual(reused["sha256"], result["sha256"])
            self.assertTrue(reused["sidecar_request_skipped"])
            after_reuse = client.capabilities()["process"]["completed_request_count"]  # type: ignore[index]
            self.assertEqual(after_reuse, before_reuse)

    def test_private_reference_bytes_use_multipart_and_pawapp_still_owns_publish(self) -> None:
        with RunningServer() as running, tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            client = SidecarClient("127.0.0.1", running.port, TOKEN)
            result = client.synthesize_and_publish(request(reference_audio=reference()), root)
            self.assertEqual(result["status"], "published")
            self.assertTrue((root / "asset-00000001.wav").is_file())
            self.assertFalse(list(root.rglob("*.part")))

    def test_reference_media_type_mismatch_is_classified_and_not_published(self) -> None:
        valid = reference()
        multipart, content_type = build_multipart_body(
            request(reference_audio=valid), "0123456789abcdef01234567"
        )
        multipart = multipart.replace(b"Content-Type: audio/wav", b"Content-Type: audio/flac")
        with RunningServer() as running:
            connection = HTTPConnection("127.0.0.1", running.port, timeout=2)
            connection.request(
                "POST",
                "/v1/synthesize",
                body=multipart,
                headers=headers(length=len(multipart))
                | {"Content-Type": content_type},
            )
            response = connection.getresponse()
            row = json.loads(response.read())
            connection.close()
            self.assertEqual(response.status, 400)
            self.assertEqual(row["error"]["code"], "REFERENCE_MEDIA_TYPE_MISMATCH")

    def test_server_rejects_path_field_without_echoing_text_or_token(self) -> None:
        with RunningServer() as running:
            payload = request_payload(request(text="不得回显的正文"))
            payload["output_path"] = "/novel-media/escape.wav"
            body = canonical_json_bytes(payload)
            connection = HTTPConnection("127.0.0.1", running.port, timeout=2)
            connection.request("POST", "/v1/synthesize", body=body, headers=headers(length=len(body)))
            response = connection.getresponse()
            response_body = response.read()
            connection.close()
            self.assertEqual(response.status, 400)
            self.assertNotIn("不得回显的正文".encode(), response_body)
            self.assertNotIn(TOKEN.encode(), response_body)
            self.assertNotIn(b"novel-media", response_body)

    def test_live_cancel_is_acknowledged_and_no_asset_is_published(self) -> None:
        with RunningServer(FakeBackend(step_delay_seconds=0.01)) as running, tempfile.TemporaryDirectory() as directory:
            client = SidecarClient("127.0.0.1", running.port, TOKEN, timeout_seconds=5)
            errors: list[BaseException] = []

            def synthesize() -> None:
                try:
                    client.synthesize_and_publish(request(), Path(directory))
                except BaseException as error:
                    errors.append(error)

            thread = threading.Thread(target=synthesize)
            thread.start()
            deadline = time.monotonic() + 2
            while "request-00000001" not in running.state.active and time.monotonic() < deadline:
                time.sleep(0.005)
            self.assertIn("request-00000001", running.state.active)
            response_body = client.cancel("request-00000001", "asset-00000001")
            self.assertEqual(response_body["status"], "cancel_requested")
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())
            self.assertEqual(len(errors), 1)
            self.assertIsInstance(errors[0], ProtocolError)
            self.assertFalse(list(Path(directory).iterdir()))

    def test_token_is_never_accepted_in_url_or_host(self) -> None:
        with self.assertRaisesRegex(ProtocolError, "service identity"):
            SidecarClient(f"http://sidecar?token={TOKEN}", 8765, TOKEN)


if __name__ == "__main__":
    unittest.main()
    build_multipart_body,
