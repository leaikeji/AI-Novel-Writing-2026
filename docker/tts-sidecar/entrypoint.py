"""Fail-closed T1-DEP entrypoint.

T1-DEP installs and verifies only the immutable dependency layer. It must not
expose a fake Sidecar server or health endpoint before T1-B owns that runtime.
"""

from __future__ import annotations

import json


def emit_and_exit(code: str, detail: str, exit_code: int = 78) -> None:
    print(
        json.dumps(
            {
                "schema_version": "moss-tts-t1-dep-entrypoint/1.0",
                "status": "inert",
                "error_code": code,
                "detail": detail,
                "health_endpoint_available": False,
                "business_runtime_available": False,
            },
            separators=(",", ":"),
        ),
        flush=True,
    )
    raise SystemExit(exit_code)


def main() -> None:
    emit_and_exit(
        "T1_B_RUNTIME_NOT_INSTALLED",
        "dependency image is verified; the approved Sidecar business runtime is intentionally absent until T1-B",
    )


if __name__ == "__main__":
    main()
