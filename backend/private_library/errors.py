from __future__ import annotations

from typing import Any


class PrivateLibraryError(RuntimeError):
    """Base error for private-library domain operations."""


class PrivateLibraryValidationError(PrivateLibraryError):
    pass


class PrivateLibraryNotFoundError(PrivateLibraryError):
    pass


class PrivateLibraryConflictError(PrivateLibraryError):
    def __init__(self, code: str, *, current: dict[str, Any]) -> None:
        self.code = code
        self.current = current
        super().__init__(code)


class PrivateLibraryIdempotencyConflict(PrivateLibraryError):
    def __init__(self, operation_key: str) -> None:
        self.operation_key = operation_key
        super().__init__("operation key was already used with another payload")
