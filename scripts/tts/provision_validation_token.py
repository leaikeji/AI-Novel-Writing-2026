#!/usr/bin/env python3
"""Provision or verify the one private T4-K HTTP validation token.

The token is generated once in a repository-external 0600 host file, copied
without command-line or environment exposure, and atomically installed into
the existing QwenPaw secret volume.  Retries never overwrite either copy and
only succeed when their SHA-256 digests match.  No token or digest is printed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
from typing import Callable, Final, Protocol, Sequence
from uuid import uuid4


PROJECT_ROOT: Final = Path(__file__).resolve().parents[2]
QWENPAW_CONTAINER: Final = "ai-novel-2026-qwenpaw-lab"
CONTAINER_TOKEN_DIRECTORY: Final = (
    "/app/working.secret/ai-novel-world-2026/t4k-validation"
)
CONTAINER_TOKEN_FILE: Final = f"{CONTAINER_TOKEN_DIRECTORY}/token"
CONFIRMATION: Final = "PROVISION-T4K-VALIDATION-TOKEN"
DESTROY_CONFIRMATION: Final = "DESTROY-T4K-VALIDATION-TOKEN"
TOKEN_PATTERN: Final = re.compile(r"^[A-Za-z0-9_-]{43,128}$")
SHA256_PATTERN: Final = re.compile(r"^[a-f0-9]{64}$")


class TokenProvisionError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class ContainerTokenPort(Protocol):
    def current_digest(self) -> str | None: ...

    def install_from_host_file(self, path: Path) -> None: ...

    def destroy(self) -> None: ...


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _validate_host_path(path: Path) -> Path:
    if not path.is_absolute():
        raise TokenProvisionError("HOST_TOKEN_PATH_INVALID")
    resolved_parent = path.parent.resolve(strict=True)
    resolved = resolved_parent / path.name
    if (
        resolved == PROJECT_ROOT
        or _is_within(resolved, PROJECT_ROOT.resolve())
        or path.name in {"", ".", ".."}
    ):
        raise TokenProvisionError("HOST_TOKEN_PATH_INVALID")
    try:
        parent = resolved_parent.lstat()
    except OSError as error:
        raise TokenProvisionError("HOST_TOKEN_DIRECTORY_INVALID") from error
    if (
        not stat.S_ISDIR(parent.st_mode)
        or stat.S_ISLNK(parent.st_mode)
        or parent.st_uid != os.getuid()
        or stat.S_IMODE(parent.st_mode) != 0o700
    ):
        raise TokenProvisionError("HOST_TOKEN_DIRECTORY_INVALID")
    return resolved


def read_private_host_token(path: Path) -> str:
    path = _validate_host_path(path)
    descriptor: int | None = None
    try:
        nofollow = getattr(os, "O_NOFOLLOW", None)
        if nofollow is None:
            raise TokenProvisionError("HOST_TOKEN_POLICY_UNAVAILABLE")
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | nofollow,
        )
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or metadata.st_uid != os.getuid()
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or not 43 <= metadata.st_size <= 128
        ):
            raise TokenProvisionError("HOST_TOKEN_FILE_INVALID")
        raw = os.read(descriptor, 129)
        try:
            token = raw.decode("ascii", errors="strict")
        except UnicodeDecodeError as error:
            raise TokenProvisionError("HOST_TOKEN_FILE_INVALID") from error
        if len(raw) != metadata.st_size or TOKEN_PATTERN.fullmatch(token) is None:
            raise TokenProvisionError("HOST_TOKEN_FILE_INVALID")
        return token
    except TokenProvisionError:
        raise
    except OSError as error:
        raise TokenProvisionError("HOST_TOKEN_FILE_INVALID") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _atomic_create_host_token(path: Path, token: str) -> None:
    path = _validate_host_path(path)
    if TOKEN_PATTERN.fullmatch(token) is None:
        raise TokenProvisionError("GENERATED_TOKEN_INVALID")
    descriptor: int | None = None
    temporary: Path | None = None
    try:
        descriptor, raw_path = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
        )
        temporary = Path(raw_path)
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = None
            stream.write(token.encode("ascii", errors="strict"))
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError as error:
            raise TokenProvisionError("HOST_TOKEN_ALREADY_EXISTS") from error
        temporary.unlink()
        temporary = None
        parent_descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(parent_descriptor)
        finally:
            os.close(parent_descriptor)
    except TokenProvisionError:
        raise
    except OSError as error:
        raise TokenProvisionError("HOST_TOKEN_WRITE_FAILED") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("ascii", errors="strict")).hexdigest()


def provision_token(
    host_path: Path,
    port: ContainerTokenPort,
    *,
    token_factory: Callable[[], str] = lambda: secrets.token_urlsafe(32),
) -> dict[str, object]:
    path = _validate_host_path(host_path)
    created = False
    if not path.exists():
        try:
            _atomic_create_host_token(path, token_factory())
            created = True
        except TokenProvisionError as error:
            if error.code != "HOST_TOKEN_ALREADY_EXISTS":
                raise
    token = read_private_host_token(path)
    expected_digest = _token_digest(token)
    observed = port.current_digest()
    if observed is None:
        port.install_from_host_file(path)
        observed = port.current_digest()
    if observed != expected_digest:
        raise TokenProvisionError("CONTAINER_TOKEN_MISMATCH")
    return {
        "schema_version": 1,
        "status": "READY",
        "host_token_created": created,
        "container_token_ready": True,
        "secret_values_emitted": False,
    }


def verify_token(host_path: Path, port: ContainerTokenPort) -> dict[str, object]:
    token = read_private_host_token(host_path)
    if port.current_digest() != _token_digest(token):
        raise TokenProvisionError("CONTAINER_TOKEN_MISMATCH")
    return {
        "schema_version": 1,
        "status": "READY",
        "host_token_created": False,
        "container_token_ready": True,
        "secret_values_emitted": False,
    }


def destroy_token(host_path: Path, port: ContainerTokenPort) -> dict[str, object]:
    """Remove only the two exact private token copies after validating identity."""

    path = _validate_host_path(host_path)
    host_present = path.exists() or path.is_symlink()
    container_digest = port.current_digest()
    if not host_present and container_digest is None:
        return {
            "schema_version": 1,
            "status": "DESTROYED",
            "host_token_present": False,
            "container_token_present": False,
            "secret_values_emitted": False,
        }
    if not host_present or container_digest is None:
        raise TokenProvisionError("TOKEN_COPIES_INCOMPLETE")
    token = read_private_host_token(path)
    if container_digest != _token_digest(token):
        raise TokenProvisionError("CONTAINER_TOKEN_MISMATCH")
    port.destroy()
    try:
        path.unlink()
    except OSError as error:
        raise TokenProvisionError("HOST_TOKEN_DESTROY_FAILED") from error
    parent_descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(parent_descriptor)
    finally:
        os.close(parent_descriptor)
    return {
        "schema_version": 1,
        "status": "DESTROYED",
        "host_token_present": False,
        "container_token_present": False,
        "secret_values_emitted": False,
    }


class DockerContainerTokenPort:
    """Fixed-container adapter; command output is bounded to safe status/digests."""

    def __init__(self) -> None:
        docker = shutil.which("docker")
        if docker is None:
            raise TokenProvisionError("DOCKER_UNAVAILABLE")
        self._docker = docker
        self._validate_container()

    def _run(self, *args: str, timeout: float = 30) -> str:
        environment = {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}
        docker_host = os.environ.get("DOCKER_HOST")
        if docker_host:
            environment["DOCKER_HOST"] = docker_host
        try:
            completed = subprocess.run(
                [self._docker, *args],
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=environment,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise TokenProvisionError("DOCKER_COMMAND_FAILED") from error
        if completed.returncode != 0:
            raise TokenProvisionError("DOCKER_COMMAND_FAILED")
        return completed.stdout.strip()

    def _run_input(
        self,
        payload: bytes,
        *args: str,
        timeout: float = 30,
    ) -> str:
        environment = {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}
        docker_host = os.environ.get("DOCKER_HOST")
        if docker_host:
            environment["DOCKER_HOST"] = docker_host
        try:
            completed = subprocess.run(
                [self._docker, *args],
                input=payload,
                check=False,
                capture_output=True,
                timeout=timeout,
                env=environment,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise TokenProvisionError("DOCKER_COMMAND_FAILED") from error
        if completed.returncode != 0:
            raise TokenProvisionError("DOCKER_COMMAND_FAILED")
        try:
            return completed.stdout.decode("ascii", errors="strict").strip()
        except UnicodeDecodeError as error:
            raise TokenProvisionError("DOCKER_COMMAND_FAILED") from error

    def _validate_container(self) -> None:
        value = self._run(
            "inspect",
            "--format",
            '{{ index .Config.Labels "com.docker.compose.service" }}|{{.State.Running}}',
            QWENPAW_CONTAINER,
        )
        if value != "qwenpaw|true":
            raise TokenProvisionError("QWENPAW_CONTAINER_INVALID")

    def _prepare_directory(self) -> None:
        code = (
            "import os,stat,sys; p=sys.argv[1]; "
            "os.makedirs(p,mode=0o700,exist_ok=True); s=os.lstat(p); "
            "ok=stat.S_ISDIR(s.st_mode) and not stat.S_ISLNK(s.st_mode) "
            "and s.st_uid==os.geteuid() and stat.S_IMODE(s.st_mode)==0o700; "
            "sys.exit(0 if ok else 64)"
        )
        self._run(
            "exec",
            QWENPAW_CONTAINER,
            "/app/venv/bin/python",
            "-c",
            code,
            CONTAINER_TOKEN_DIRECTORY,
        )

    def current_digest(self) -> str | None:
        self._prepare_directory()
        code = (
            "import hashlib,os,re,stat,sys; p=sys.argv[1]; "
            "exists=os.path.lexists(p); "
            "sys.stdout.write('MISSING') if not exists else None; "
            "sys.exit(0) if not exists else None; "
            "fd=os.open(p,os.O_RDONLY|os.O_CLOEXEC|os.O_NOFOLLOW); "
            "s=os.fstat(fd); b=os.read(fd,129); os.close(fd); "
            "ok=stat.S_ISREG(s.st_mode) and s.st_nlink==1 "
            "and s.st_uid==os.geteuid() and stat.S_IMODE(s.st_mode)==0o600 "
            "and len(b)==s.st_size and re.fullmatch(b'[A-Za-z0-9_-]{43,128}',b); "
            "sys.stdout.write(hashlib.sha256(b).hexdigest()) if ok else None; "
            "sys.exit(0 if ok else 64)"
        )
        value = self._run(
            "exec",
            QWENPAW_CONTAINER,
            "/app/venv/bin/python",
            "-c",
            code,
            CONTAINER_TOKEN_FILE,
        )
        if value == "MISSING":
            return None
        if SHA256_PATTERN.fullmatch(value) is None:
            raise TokenProvisionError("CONTAINER_TOKEN_INVALID")
        return value

    def install_from_host_file(self, path: Path) -> None:
        self._prepare_directory()
        token = read_private_host_token(path).encode("ascii", errors="strict")
        stage = f"{CONTAINER_TOKEN_DIRECTORY}/.staging-{uuid4().hex}"
        try:
            code = (
                "import os,re,sys; src,dst=sys.argv[1:3]; "
                "b=sys.stdin.buffer.read(129); "
                "ok=re.fullmatch(b'[A-Za-z0-9_-]{43,128}',b); "
                "sys.exit(64) if not ok else None; "
                "out=os.open(src,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_CLOEXEC,0o600); "
                "os.write(out,b); os.fsync(out); os.close(out); "
                "os.link(src,dst); os.unlink(src); "
                "d=os.open(os.path.dirname(dst),os.O_RDONLY|os.O_DIRECTORY); "
                "os.fsync(d); os.close(d)"
            )
            self._run_input(
                token,
                "exec",
                "-i",
                QWENPAW_CONTAINER,
                "/app/venv/bin/python",
                "-c",
                code,
                stage,
                CONTAINER_TOKEN_FILE,
            )
        finally:
            cleanup = (
                "import os,sys; p=sys.argv[1]; "
                "os.unlink(p) if os.path.isfile(p) and not os.path.islink(p) else None"
            )
            try:
                self._run(
                    "exec",
                    QWENPAW_CONTAINER,
                    "/app/venv/bin/python",
                    "-c",
                    cleanup,
                    stage,
                )
            except TokenProvisionError:
                pass

    def destroy(self) -> None:
        self._prepare_directory()
        code = (
            "import os,re,stat,sys; p=sys.argv[1]; "
            "exists=os.path.lexists(p); sys.exit(0) if not exists else None; "
            "fd=os.open(p,os.O_RDONLY|os.O_CLOEXEC|os.O_NOFOLLOW); "
            "s=os.fstat(fd); b=os.read(fd,129); os.close(fd); "
            "ok=stat.S_ISREG(s.st_mode) and s.st_nlink==1 "
            "and s.st_uid==os.geteuid() and stat.S_IMODE(s.st_mode)==0o600 "
            "and len(b)==s.st_size and re.fullmatch(b'[A-Za-z0-9_-]{43,128}',b); "
            "sys.exit(64) if not ok else None; os.unlink(p); "
            "d=os.open(os.path.dirname(p),os.O_RDONLY|os.O_DIRECTORY); "
            "os.fsync(d); os.close(d)"
        )
        self._run(
            "exec",
            QWENPAW_CONTAINER,
            "/app/venv/bin/python",
            "-c",
            code,
            CONTAINER_TOKEN_FILE,
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("provision", "verify", "destroy"),
        required=True,
    )
    parser.add_argument("--host-token-file", type=Path, required=True)
    parser.add_argument("--confirm", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        expected_confirmation = (
            DESTROY_CONFIRMATION if args.mode == "destroy" else CONFIRMATION
        )
        if args.confirm != expected_confirmation:
            raise TokenProvisionError("CONFIRMATION_REQUIRED")
        port = DockerContainerTokenPort()
        if args.mode == "provision":
            result = provision_token(args.host_token_file, port)
        elif args.mode == "verify":
            result = verify_token(args.host_token_file, port)
        else:
            result = destroy_token(args.host_token_file, port)
        sys.stdout.write(
            json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n"
        )
        return 0
    except TokenProvisionError as error:
        sys.stderr.write(
            json.dumps(
                {"status": "FAILED", "code": error.code},
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
