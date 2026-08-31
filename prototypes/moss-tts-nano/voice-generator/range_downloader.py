"""Resumable parallel HTTPS range downloader writing one sparse target file."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import threading
from typing import Callable, Literal
from urllib.parse import urlparse
from urllib.request import Request, urlopen


MIB = 1024**2
CONTENT_RANGE = re.compile(r"^bytes ([0-9]+)-([0-9]+)/([0-9]+)$")


class RangeDownloadError(RuntimeError):
    pass


def parallel_range_download(
    *,
    url: str,
    target: Path,
    expected_bytes: int,
    expected_sha256: str,
    workers: int = 8,
    range_bytes: int = 64 * MIB,
    opener: Callable[..., object] = urlopen,
    transport: Literal["urllib", "curl_ipv4"] = "urllib",
) -> dict[str, object]:
    if urlparse(url).scheme != "https":
        raise RangeDownloadError("range URL must use HTTPS")
    if workers < 1 or workers > 16 or range_bytes < MIB:
        raise ValueError("range downloader policy is outside bounds")
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if target.is_symlink():
        raise RangeDownloadError("target may not be a symlink")
    state_path = target.with_name(f".{target.name}.ranges.json")
    ranges = [
        (index, start, min(expected_bytes - 1, start + range_bytes - 1))
        for index, start in enumerate(range(0, expected_bytes, range_bytes))
    ]
    url_sha256 = hashlib.sha256(url.encode("utf-8")).hexdigest()
    completed = _load_state(
        state_path, expected_bytes, expected_sha256, range_bytes, url_sha256
    )
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(target, flags, 0o600)
    progress_lock = threading.Lock()
    try:
        if os.fstat(descriptor).st_nlink != 1:
            raise RangeDownloadError("target must have an exclusive inode")
        os.ftruncate(descriptor, expected_bytes)

        def fetch(item: tuple[int, int, int]) -> int:
            index, start, end = item
            if transport == "curl_ipv4":
                return _fetch_with_curl(
                    url=url,
                    descriptor=descriptor,
                    staging_dir=target.parent,
                    target_name=target.name,
                    item=item,
                    expected_bytes=expected_bytes,
                )
            if transport != "urllib":
                raise ValueError("unknown range transport")
            request = Request(
                url,
                headers={
                    "Range": f"bytes={start}-{end}",
                    "User-Agent": "AI-Novel-World-VG40/1",
                },
            )
            last_error: Exception | None = None
            for _attempt in range(5):
                try:
                    with opener(request, timeout=60) as response:  # type: ignore[misc]
                        final_url = response.geturl()  # type: ignore[attr-defined]
                        if urlparse(final_url).scheme != "https":
                            raise RangeDownloadError("redirect left HTTPS")
                        if response.status != 206:  # type: ignore[attr-defined]
                            raise RangeDownloadError("server did not honor range request")
                        header = response.headers.get("Content-Range")  # type: ignore[attr-defined]
                        match = CONTENT_RANGE.fullmatch(header or "")
                        if match is None or tuple(map(int, match.groups())) != (
                            start,
                            end,
                            expected_bytes,
                        ):
                            raise RangeDownloadError("Content-Range did not match")
                        offset = start
                        while chunk := response.read(MIB):  # type: ignore[attr-defined]
                            if offset + len(chunk) > end + 1:
                                raise RangeDownloadError("range response exceeded bound")
                            os.pwrite(descriptor, chunk, offset)
                            offset += len(chunk)
                        if offset != end + 1:
                            raise RangeDownloadError("range response was truncated")
                    return index
                except Exception as error:
                    last_error = error
            raise RangeDownloadError("range failed after retries") from last_error

        pending = [item for item in ranges if item[0] not in completed]
        scheduler_failures: dict[int, int] = {}
        while pending:
            failed: list[tuple[int, int, int]] = []
            terminal_error: Exception | None = None
            with ThreadPoolExecutor(
                max_workers=workers, thread_name_prefix="vg40-range"
            ) as pool:
                futures = {pool.submit(fetch, item): item for item in pending}
                for future in as_completed(futures):
                    item = futures[future]
                    try:
                        completed_index = future.result()
                    except Exception as error:
                        scheduler_failures[item[0]] = scheduler_failures.get(item[0], 0) + 1
                        if scheduler_failures[item[0]] > 5:
                            terminal_error = error
                        else:
                            failed.append(item)
                        continue
                    completed.add(completed_index)
                    with progress_lock:
                        os.fsync(descriptor)
                        _write_state(
                            state_path,
                            expected_bytes,
                            expected_sha256,
                            range_bytes,
                            url_sha256,
                            completed,
                        )
                        print(
                            f"VG40_RANGE_PROGRESS={len(completed)}/{len(ranges)}",
                            flush=True,
                        )
            if terminal_error is not None:
                raise RangeDownloadError("range exhausted scheduler retries") from terminal_error
            pending = failed
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    digest = _sha256(target)
    if digest != expected_sha256:
        raise RangeDownloadError("completed file SHA-256 did not match")
    return {
        "bytes": expected_bytes,
        "sha256": digest,
        "ranges": len(ranges),
        "workers": workers,
        "transport": transport,
    }


def _fetch_with_curl(
    *,
    url: str,
    descriptor: int,
    staging_dir: Path,
    target_name: str,
    item: tuple[int, int, int],
    expected_bytes: int,
) -> int:
    """Fetch one range through macOS curl with bounded IPv4/HTTP1 retries."""

    index, start, end = item
    network_range_bytes = 8 * MIB
    for chunk_start in range(start, end + 1, network_range_bytes):
        chunk_end = min(end, chunk_start + network_range_bytes - 1)
        _fetch_curl_subrange(
            url=url,
            descriptor=descriptor,
            staging_dir=staging_dir,
            target_name=target_name,
            index=index,
            start=chunk_start,
            end=chunk_end,
            expected_bytes=expected_bytes,
        )
    return index


def _fetch_curl_subrange(
    *,
    url: str,
    descriptor: int,
    staging_dir: Path,
    target_name: str,
    index: int,
    start: int,
    end: int,
    expected_bytes: int,
) -> None:
    expected_range_bytes = end - start + 1
    last_error: Exception | None = None
    for _attempt in range(5):
        token = secrets.token_hex(4)
        body_path = staging_dir / (
            f".{target_name}.range-{index}-{start}-{token}.part"
        )
        header_path = staging_dir / (
            f".{target_name}.range-{index}-{start}-{token}.headers"
        )
        try:
            result = subprocess.run(
                [
                    "/usr/bin/curl",
                    "--ipv4",
                    "--http1.1",
                    "--location",
                    "--fail",
                    "--silent",
                    "--show-error",
                    "--connect-timeout",
                    "15",
                    "--max-time",
                    "600",
                    "--speed-limit",
                    "1024",
                    "--speed-time",
                    "120",
                    "--retry",
                    "1",
                    "--retry-all-errors",
                    "--retry-delay",
                    "2",
                    "--range",
                    f"{start}-{end}",
                    "--dump-header",
                    str(header_path),
                    "--output",
                    str(body_path),
                    url,
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=630,
            )
            if result.returncode != 0:
                message = result.stderr.strip()[-500:]
                raise RangeDownloadError(f"curl range failed: {message}")
            if body_path.stat().st_size != expected_range_bytes:
                raise RangeDownloadError("curl range response size did not match")
            content_range = _last_content_range(header_path)
            if content_range != (start, end, expected_bytes):
                raise RangeDownloadError("curl Content-Range did not match")
            offset = start
            with body_path.open("rb") as source:
                while chunk := source.read(MIB):
                    os.pwrite(descriptor, chunk, offset)
                    offset += len(chunk)
            if offset != end + 1:
                raise RangeDownloadError("curl staged range was truncated")
            return
        except Exception as error:
            last_error = error
        finally:
            body_path.unlink(missing_ok=True)
            header_path.unlink(missing_ok=True)
    raise RangeDownloadError("curl subrange failed after retries") from last_error


def _last_content_range(path: Path) -> tuple[int, int, int] | None:
    value: tuple[int, int, int] | None = None
    for line in path.read_text(encoding="iso-8859-1").splitlines():
        name, separator, raw_value = line.partition(":")
        if separator and name.lower() == "content-range":
            match = CONTENT_RANGE.fullmatch(raw_value.strip())
            if match is not None:
                value = tuple(map(int, match.groups()))
    return value


def _load_state(
    path: Path,
    expected_bytes: int,
    expected_sha256: str,
    range_bytes: int,
    url_sha256: str,
) -> set[int]:
    if not path.exists():
        return set()
    if path.is_symlink() or not path.is_file():
        raise RangeDownloadError("range state is not a regular file")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if (
        payload.get("schema_version") != "vg40-range-download/1"
        or payload.get("expected_bytes") != expected_bytes
        or payload.get("expected_sha256") != expected_sha256
        or payload.get("range_bytes") != range_bytes
        or payload.get("url_sha256", url_sha256) != url_sha256
    ):
        raise RangeDownloadError("range state identity mismatch")
    completed = payload.get("completed")
    if not isinstance(completed, list) or any(not isinstance(item, int) for item in completed):
        raise RangeDownloadError("range state completed set is invalid")
    return set(completed)


def _write_state(
    path: Path,
    expected_bytes: int,
    expected_sha256: str,
    range_bytes: int,
    url_sha256: str,
    completed: set[int],
) -> None:
    payload = {
        "schema_version": "vg40-range-download/1",
        "expected_bytes": expected_bytes,
        "expected_sha256": expected_sha256,
        "range_bytes": range_bytes,
        "url_sha256": url_sha256,
        "completed": sorted(completed),
    }
    encoded = (json.dumps(payload, sort_keys=True, allow_nan=False) + "\n").encode()
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        with os.fdopen(descriptor, "wb") as target:
            target.write(encoded)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(4 * MIB):
            digest.update(chunk)
    return digest.hexdigest()
