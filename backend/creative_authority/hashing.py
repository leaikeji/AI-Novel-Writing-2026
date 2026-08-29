from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import UUID

from .errors import AuthorityValidationError


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise AuthorityValidationError("authority JSON object keys must be strings")
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    raise AuthorityValidationError(
        f"authority payload contains unsupported JSON value: {type(value).__name__}"
    )


def canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            _json_value(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise AuthorityValidationError("authority payload is not canonical JSON") from error


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
