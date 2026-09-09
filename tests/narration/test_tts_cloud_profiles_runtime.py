from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import SecretStr

from backend.embedding.api import SECRET_DIR_ENV, SECRET_ROOT_ENV
from backend.embedding.secrets import EmbeddingSecretStore
from backend.models import TTSCloudProfile
from backend.narration.cloud_profiles_runtime import (
    build_cloud_provider_resolver,
    cloud_secret_store_from_environment,
)
from backend.narration.providers.base import TTSProviderError


class _Session:
    def __init__(self, profile: TTSCloudProfile) -> None:
        self.profile = profile

    def __enter__(self) -> "_Session":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def scalar(self, _statement: object) -> TTSCloudProfile:
        return self.profile


def _vault(tmp_path):  # type: ignore[no-untyped-def]
    root = (tmp_path / "vault" / "root.key").resolve()
    records = (tmp_path / "vault" / "records").resolve()
    EmbeddingSecretStore.provision(root_key_path=root, records_dir=records)
    return cloud_secret_store_from_environment(
        {SECRET_ROOT_ENV: str(root), SECRET_DIR_ENV: str(records)}
    )


def test_cloud_vault_uses_separate_namespace_and_never_returns_plaintext_metadata(
    tmp_path,
) -> None:  # type: ignore[no-untyped-def]
    vault = _vault(tmp_path)
    stored = vault.put(SecretStr("sk-private-value-1234"))

    assert stored.credential_ref.startswith("tts-cloud/")
    assert stored.last4 == "1234"
    assert vault.get(stored.credential_ref).get_secret_value() == "sk-private-value-1234"


def test_dynamic_resolver_requires_the_frozen_verified_profile(tmp_path) -> None:  # type: ignore[no-untyped-def]
    vault = _vault(tmp_path)
    stored = vault.put(SecretStr("sk-private-value-1234"))
    profile_id = uuid4()
    now = datetime.now(UTC)
    base_url = "https://member.example.com/qwen"
    profile = TTSCloudProfile(
        id=profile_id,
        owner_id=uuid4(),
        workspace_id=uuid4(),
        name="会员渠道",
        protocol="qwen_audio_native_http/1",
        base_url=base_url,
        credential_ref=stored.credential_ref,
        api_key_last4=stored.last4,
        quality_model_id="member-qwen-quality",
        speed_model_id=None,
        quality_test_state="passed",
        speed_test_state="untested",
        lifecycle_state="active",
        verification_fingerprint="d" * 64,
        version=8,
        created_at=now,
        updated_at=now,
    )
    resolver = build_cloud_provider_resolver(lambda: _Session(profile), vault)  # type: ignore[arg-type]
    provider = resolver(
        profile_id,
        7,
        "qwen_audio_native_http/1",
        "member-qwen-quality",
        hashlib.sha256(base_url.encode()).hexdigest(),
        "d" * 64,
    )

    identity = asyncio.run(provider.model_identity())
    assert identity.model_id == "member-qwen-quality"
    assert "private-value" not in repr(provider)

    with pytest.raises(TTSProviderError) as mismatch:
        resolver(
            profile_id,
            7,
            "qwen_audio_native_http/1",
            "member-qwen-quality",
            hashlib.sha256(base_url.encode()).hexdigest(),
            "e" * 64,
        )
    assert mismatch.value.code == "TTS_PROVIDER_DISABLED"
