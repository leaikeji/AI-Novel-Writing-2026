"""Fail-closed HTTP gate for T4 narration production surfaces.

The T2 reading-settings API is intentionally outside this gate.  Script
review, synthesis, Edition mutation, Manifest playback, range promotion, and
media streaming are released together only by an application-owned policy.
Importing this module installs no permissive default.
"""

from __future__ import annotations

from typing import Callable, Final

from fastapi import HTTPException, Request, status


VALIDATION_TOKEN_HEADER: Final = "X-AI-Novel-TTS-Validation"
NarrationT4HttpAccessPolicy = Callable[[Request], bool]

_access_policy: NarrationT4HttpAccessPolicy | None = None


def install_narration_t4_http_access_policy(
    policy: NarrationT4HttpAccessPolicy,
) -> None:
    global _access_policy
    if not callable(policy):
        raise TypeError("narration T4 HTTP access policy must be callable")
    if _access_policy is not None and _access_policy is not policy:
        raise RuntimeError("narration T4 HTTP access policy is already installed")
    _access_policy = policy


def uninstall_narration_t4_http_access_policy(
    policy: NarrationT4HttpAccessPolicy | None = None,
) -> None:
    global _access_policy
    if policy is not None and _access_policy is not None and _access_policy is not policy:
        raise RuntimeError("refusing to remove another narration T4 HTTP access policy")
    _access_policy = None


def require_narration_t4_http_access(request: Request) -> None:
    """Hide every T4 route unless the current application policy allows it."""

    policy = _access_policy
    allowed = False
    if policy is not None:
        try:
            allowed = policy(request) is True
        except Exception:
            allowed = False
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "RESOURCE_NOT_FOUND",
                "message": "找不到请求的朗读资源。",
            },
            headers={"Cache-Control": "no-store"},
        )


__all__ = [
    "NarrationT4HttpAccessPolicy",
    "VALIDATION_TOKEN_HEADER",
    "install_narration_t4_http_access_policy",
    "require_narration_t4_http_access",
    "uninstall_narration_t4_http_access_policy",
]
