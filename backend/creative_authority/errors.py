from __future__ import annotations

from typing import Any


class CreativeAuthorityError(RuntimeError):
    """Base error for formal creative-authority operations."""


class AuthorityValidationError(CreativeAuthorityError):
    pass


class AuthorityNotFoundError(CreativeAuthorityError):
    pass


class AuthorityConflictError(CreativeAuthorityError):
    def __init__(self, code: str, *, current: dict[str, Any]) -> None:
        self.code = code
        self.current = current
        super().__init__(code)


class AuthorityIdempotencyConflict(CreativeAuthorityError):
    def __init__(self, key: str) -> None:
        self.key = key
        super().__init__("idempotency key was already used with another payload")
