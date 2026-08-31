from __future__ import annotations

import hashlib
import importlib.util
import io
from pathlib import Path
import re
import subprocess
import sys
import tempfile


MODULE_PATH = Path(__file__).with_name("range_downloader.py")
SPEC = importlib.util.spec_from_file_location("vg40_range_downloader", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class Response(io.BytesIO):
    def __init__(self, payload: bytes, start: int, end: int, total: int):
        super().__init__(payload[start : end + 1])
        self.status = 206
        self.headers = {"Content-Range": f"bytes {start}-{end}/{total}"}

    def geturl(self):
        return "https://cdn.example/fixed"

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def test_parallel_ranges_write_one_verified_file_and_resume():
    payload = (b"0123456789abcdef" * (MODULE.MIB // 16)) * 3
    pattern = re.compile(r"bytes=([0-9]+)-([0-9]+)")

    def opener(request, timeout):
        match = pattern.fullmatch(request.headers["Range"])
        assert match is not None and timeout == 60
        start, end = map(int, match.groups())
        return Response(payload, start, end, len(payload))

    with tempfile.TemporaryDirectory() as temporary:
        target = Path(temporary).resolve() / "model.bin"
        result = MODULE.parallel_range_download(
            url="https://example.invalid/model",
            target=target,
            expected_bytes=len(payload),
            expected_sha256=hashlib.sha256(payload).hexdigest(),
            workers=3,
            range_bytes=MODULE.MIB,
            opener=opener,
        )
        assert result["ranges"] == 3
        assert target.read_bytes() == payload
        resumed = MODULE.parallel_range_download(
            url="https://example.invalid/model",
            target=target,
            expected_bytes=len(payload),
            expected_sha256=hashlib.sha256(payload).hexdigest(),
            workers=3,
            range_bytes=MODULE.MIB,
            opener=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError()),
        )
        assert resumed["sha256"] == hashlib.sha256(payload).hexdigest()


def test_curl_transport_validates_headers_and_writes_range(monkeypatch):
    payload = b"x" * MODULE.MIB

    def fake_run(command, **kwargs):
        start, end = map(int, command[command.index("--range") + 1].split("-"))
        header_path = Path(command[command.index("--dump-header") + 1])
        body_path = Path(command[command.index("--output") + 1])
        header_path.write_text(
            "HTTP/1.1 206 Partial Content\r\n"
            f"Content-Range: bytes {start}-{end}/{len(payload)}\r\n\r\n",
            encoding="iso-8859-1",
        )
        body_path.write_bytes(payload[start : end + 1])
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(MODULE.subprocess, "run", fake_run)
    with tempfile.TemporaryDirectory() as temporary:
        target = Path(temporary).resolve() / "model.bin"
        result = MODULE.parallel_range_download(
            url="https://example.invalid/model",
            target=target,
            expected_bytes=len(payload),
            expected_sha256=hashlib.sha256(payload).hexdigest(),
            workers=1,
            range_bytes=MODULE.MIB,
            transport="curl_ipv4",
        )
        assert result["transport"] == "curl_ipv4"
        assert target.read_bytes() == payload


def test_scheduler_retries_one_exhausted_fetch_without_losing_other_ranges():
    payload = b"a" * MODULE.MIB + b"b" * MODULE.MIB
    pattern = re.compile(r"bytes=([0-9]+)-([0-9]+)")
    calls = {0: 0}

    def opener(request, timeout):
        match = pattern.fullmatch(request.headers["Range"])
        assert match is not None
        start, end = map(int, match.groups())
        if start == 0:
            calls[0] += 1
            if calls[0] <= 5:
                raise TimeoutError("injected")
        return Response(payload, start, end, len(payload))

    with tempfile.TemporaryDirectory() as temporary:
        target = Path(temporary).resolve() / "model.bin"
        result = MODULE.parallel_range_download(
            url="https://example.invalid/model",
            target=target,
            expected_bytes=len(payload),
            expected_sha256=hashlib.sha256(payload).hexdigest(),
            workers=2,
            range_bytes=MODULE.MIB,
            opener=opener,
        )
        assert calls[0] == 6
        assert result["ranges"] == 2
        assert target.read_bytes() == payload
