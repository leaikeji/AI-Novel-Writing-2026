from __future__ import annotations

import os
from pathlib import Path

import httpx
import pytest

from backend.embedding.adapter import (
    DashScopeEmbeddingAdapter,
    EmbeddingAdapterError,
    normalize_dashscope_base_url,
)
from backend.embedding.secrets import EmbeddingSecretError, EmbeddingSecretStore


async def _public_resolver(_hostname: str) -> list[str]:
    return ["8.8.8.8"]


def test_secret_store_encrypts_and_round_trips(tmp_path: Path) -> None:
    root = tmp_path / "root.key"
    records = tmp_path / "records"
    root.write_bytes(os.urandom(32))
    records.mkdir()
    root.chmod(0o600)
    records.chmod(0o700)
    store = EmbeddingSecretStore(root_key_path=root, records_dir=records)

    stored = store.put("sk-example-super-secret")
    record = next(records.iterdir())

    assert store.get(stored.credential_ref) == "sk-example-super-secret"
    assert stored.last4 == "cret"
    assert b"sk-example-super-secret" not in record.read_bytes()
    assert b"r-secret" not in record.read_bytes()
    store.delete(stored.credential_ref)
    assert not record.exists()


def test_secret_store_provision_is_private_and_idempotent(tmp_path: Path) -> None:
    root = tmp_path / "private" / "root.key"
    records = tmp_path / "private" / "records"

    assert EmbeddingSecretStore.provision(root_key_path=root, records_dir=records) is True
    assert EmbeddingSecretStore.provision(root_key_path=root, records_dir=records) is False
    assert root.stat().st_mode & 0o777 == 0o600
    assert root.parent.stat().st_mode & 0o777 == 0o700
    assert records.stat().st_mode & 0o777 == 0o700


def test_secret_store_refuses_new_root_over_orphaned_records(tmp_path: Path) -> None:
    root = tmp_path / "private" / "root.key"
    records = tmp_path / "private" / "records"
    records.mkdir(parents=True)
    records.chmod(0o700)
    (records / "orphan.json").write_text("{}", encoding="utf-8")

    with pytest.raises(EmbeddingSecretError, match="旧凭据记录"):
        EmbeddingSecretStore.provision(root_key_path=root, records_dir=records)


def test_secret_store_provision_rejects_symlinked_directory(tmp_path: Path) -> None:
    actual = tmp_path / "actual"
    actual.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(actual, target_is_directory=True)

    with pytest.raises(EmbeddingSecretError, match="符号链接"):
        EmbeddingSecretStore.provision(
            root_key_path=linked / "root.key",
            records_dir=linked / "records",
        )


def test_secret_store_rejects_weak_root_permissions(tmp_path: Path) -> None:
    root = tmp_path / "root.key"
    records = tmp_path / "records"
    root.write_bytes(os.urandom(32))
    records.mkdir()
    root.chmod(0o644)
    records.chmod(0o700)
    store = EmbeddingSecretStore(root_key_path=root, records_dir=records)
    with pytest.raises(EmbeddingSecretError, match="private regular file"):
        store.put("sk-secret-value-long-enough")


@pytest.mark.parametrize(
    "value",
    (
        "http://workspace.cn-beijing.maas.aliyuncs.com/api/v1",
        "https://user@example.com/api/v1",
        "https://127.0.0.1/api/v1",
        "https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
        "https://workspace.cn-beijing.maas.aliyuncs.com/api/v1?key=x",
    ),
)
def test_base_url_rejects_unsafe_or_wrong_protocol(value: str) -> None:
    with pytest.raises(EmbeddingAdapterError):
        normalize_dashscope_base_url(value)


@pytest.mark.asyncio
async def test_adapter_sends_native_roles_and_validates_response() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = request.read().decode("utf-8")
        return httpx.Response(
            200,
            json={
                "status_code": 200,
                "request_id": "req-safe",
                "output": {
                    "embeddings": [
                        {"text_index": 0, "embedding": [0.1, 0.2] + [0.0] * 254}
                    ]
                },
                "usage": {"total_tokens": 4, "input_tokens": 4},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await DashScopeEmbeddingAdapter(
            base_url="https://workspace.cn-beijing.maas.aliyuncs.com/api/v1"
        ).embed(
            api_key="sk-not-logged",
            texts=["查询"],
            text_type="query",
            dimension=256,
            instruct="Retrieve relevant novel evidence",
            client=client,
            resolver=_public_resolver,
        )
    assert result.request_id == "req-safe"
    assert len(result.vectors[0].values) == 256
    assert result.vectors[0].values[:2] == (0.1, 0.2)
    assert str(captured["url"]).endswith("/api/v1/services/embeddings/text-embedding/text-embedding")
    assert '"text_type":"query"' in str(captured["body"])
    assert "sk-not-logged" not in repr(result)


@pytest.mark.asyncio
async def test_adapter_rejects_an_unsupported_dimension_before_network() -> None:
    with pytest.raises(EmbeddingAdapterError, match="not supported"):
        await DashScopeEmbeddingAdapter(
            base_url="https://workspace.cn-beijing.maas.aliyuncs.com/api/v1"
        ).embed(
            api_key="sk-not-logged-long-enough",
            texts=["查询"],
            text_type="query",
            dimension=1234,
            resolver=_public_resolver,
        )


@pytest.mark.asyncio
async def test_adapter_rejects_private_dns_resolution() -> None:
    async def private_resolver(_hostname: str) -> list[str]:
        return ["127.0.0.1"]

    adapter = DashScopeEmbeddingAdapter(
        base_url="https://workspace.cn-beijing.maas.aliyuncs.com/api/v1"
    )
    with pytest.raises(EmbeddingAdapterError) as caught:
        await adapter.embed(
            api_key="sk-secret",
            texts=["text"],
            text_type="document",
            resolver=private_resolver,
        )
    assert caught.value.code == "EMBEDDING_SSRF_BLOCKED"
