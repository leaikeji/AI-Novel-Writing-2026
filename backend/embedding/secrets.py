"""Encrypted, project-scoped credential storage for embedding providers."""

from __future__ import annotations

import base64
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


SECRET_SCHEMA = "embedding-secret-record/1"
SECRET_ALGORITHM = "AES-256-GCM"


class EmbeddingSecretError(RuntimeError):
    """A stable, secret-free credential storage failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class StoredCredential:
    credential_ref: str
    last4: str


def _read_private_file(path: Path, *, expected_size: int | None = None) -> bytes:
    if not path.is_absolute():
        raise EmbeddingSecretError("SECRET_PATH_INVALID", "secret path must be absolute")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise EmbeddingSecretError("SECRET_UNAVAILABLE", "secret file is unavailable") from error
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_mode & 0o077:
            raise EmbeddingSecretError(
                "SECRET_PERMISSIONS_INVALID", "secret file must be a private regular file"
            )
        data = b""
        while True:
            chunk = os.read(descriptor, 65536)
            if not chunk:
                break
            data += chunk
            if len(data) > 65536:
                raise EmbeddingSecretError("SECRET_RECORD_INVALID", "secret record is too large")
        after = os.fstat(descriptor)
        if (before.st_dev, before.st_ino, before.st_size) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
        ):
            raise EmbeddingSecretError("SECRET_CHANGED", "secret file changed while being read")
    finally:
        os.close(descriptor)
    if expected_size is not None and len(data) != expected_size:
        raise EmbeddingSecretError("SECRET_KEY_INVALID", "secret root key has an invalid size")
    return data


class EmbeddingSecretStore:
    """AES-GCM records with a separate 32-byte root-key file.

    The root key and record directory must be supplied from the project secret
    mount.  This service never creates or rotates the root key implicitly.
    """

    def __init__(self, *, root_key_path: Path, records_dir: Path) -> None:
        if not root_key_path.is_absolute() or not records_dir.is_absolute():
            raise EmbeddingSecretError("SECRET_PATH_INVALID", "secret paths must be absolute")
        self._root_key_path = root_key_path
        self._records_dir = records_dir

    def _key(self) -> bytes:
        return _read_private_file(self._root_key_path, expected_size=32)

    def _validated_records_dir(self) -> Path:
        try:
            metadata = self._records_dir.lstat()
        except OSError as error:
            raise EmbeddingSecretError(
                "SECRET_UNAVAILABLE", "credential record directory is unavailable"
            ) from error
        if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
            raise EmbeddingSecretError(
                "SECRET_PATH_INVALID", "credential record directory must not be a symlink"
            )
        if metadata.st_mode & 0o077:
            raise EmbeddingSecretError(
                "SECRET_PERMISSIONS_INVALID", "credential record directory must be private"
            )
        return self._records_dir

    def put(self, api_key: str) -> StoredCredential:
        value = api_key.strip()
        if not value or len(value) > 4096 or "\x00" in value:
            raise EmbeddingSecretError("SECRET_VALUE_INVALID", "API credential is invalid")
        credential_ref = f"embedding/{uuid4()}"
        nonce = os.urandom(12)
        ciphertext = AESGCM(self._key()).encrypt(
            nonce, value.encode("utf-8"), credential_ref.encode("utf-8")
        )
        payload = {
            "schema_version": SECRET_SCHEMA,
            "algorithm": SECRET_ALGORITHM,
            "credential_ref": credential_ref,
            "nonce_base64": base64.b64encode(nonce).decode("ascii"),
            "ciphertext_base64": base64.b64encode(ciphertext).decode("ascii"),
        }
        directory = self._validated_records_dir()
        final_path = directory / f"{credential_ref.split('/', 1)[1]}.json"
        temporary_path = directory / f".{final_path.name}.{uuid4().hex}.tmp"
        descriptor = os.open(
            temporary_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            encoded = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
            os.write(descriptor, encoded)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        try:
            os.replace(temporary_path, final_path)
            directory_fd = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError as error:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise EmbeddingSecretError("SECRET_WRITE_FAILED", "credential record write failed") from error
        return StoredCredential(credential_ref=credential_ref, last4=value[-4:])

    def get(self, credential_ref: str) -> str:
        record_id = self._record_id(credential_ref)
        raw = _read_private_file(self._validated_records_dir() / f"{record_id}.json")
        try:
            payload = json.loads(raw)
            if (
                payload.get("schema_version") != SECRET_SCHEMA
                or payload.get("algorithm") != SECRET_ALGORITHM
                or payload.get("credential_ref") != credential_ref
            ):
                raise ValueError
            nonce = base64.b64decode(payload["nonce_base64"], validate=True)
            ciphertext = base64.b64decode(payload["ciphertext_base64"], validate=True)
            plaintext = AESGCM(self._key()).decrypt(
                nonce, ciphertext, credential_ref.encode("utf-8")
            )
            value = plaintext.decode("utf-8")
        except Exception as error:
            raise EmbeddingSecretError("SECRET_RECORD_INVALID", "credential record is invalid") from error
        if not value or len(value) > 4096 or "\x00" in value:
            raise EmbeddingSecretError("SECRET_RECORD_INVALID", "credential record is invalid")
        return value

    def delete(self, credential_ref: str) -> None:
        record_id = self._record_id(credential_ref)
        path = self._validated_records_dir() / f"{record_id}.json"
        if path.is_symlink():
            raise EmbeddingSecretError("SECRET_PATH_INVALID", "credential record is a symlink")
        try:
            path.unlink(missing_ok=True)
        except OSError as error:
            raise EmbeddingSecretError("SECRET_DELETE_FAILED", "credential record delete failed") from error

    @staticmethod
    def _record_id(credential_ref: str) -> str:
        prefix = "embedding/"
        if not credential_ref.startswith(prefix):
            raise EmbeddingSecretError("SECRET_REFERENCE_INVALID", "credential reference is invalid")
        record_id = credential_ref[len(prefix) :]
        try:
            parsed = uuid4().__class__(record_id)
        except ValueError as error:
            raise EmbeddingSecretError("SECRET_REFERENCE_INVALID", "credential reference is invalid") from error
        return str(parsed)
