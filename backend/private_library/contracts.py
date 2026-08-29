from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any
from uuid import UUID


PRIVATE_ASSET_SNAPSHOT_VERSION = "private-asset-snapshot/2"


class UsagePolicy(str, Enum):
    REQUIRED = "required"
    PREFERRED = "preferred"
    CONTEXT_ONLY = "context_only"
    PROHIBITED = "prohibited"


@dataclass(frozen=True, slots=True)
class VersionSelection:
    asset_id: UUID
    asset_version_id: UUID
    usage_policy: UsagePolicy = UsagePolicy.PREFERRED
    position: int = 0


@dataclass(frozen=True, slots=True)
class DirectAssetSelection:
    asset_id: UUID
    asset_version_id: UUID | None = None
    usage_policy: UsagePolicy = UsagePolicy.PREFERRED
    selection_key: str | None = None


@dataclass(frozen=True, slots=True)
class AssetWriteResult:
    asset: Any
    asset_version: Any
    replayed: bool
    restored_from_version_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class BindingView:
    binding: Any
    asset: Any
    asset_version: Any
    update_available: bool


@dataclass(frozen=True, slots=True)
class BindingSetResult:
    bindings: tuple[BindingView, ...]
    changed: bool
