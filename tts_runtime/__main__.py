"""Run the native runtime with ``python -m tts_runtime``."""

from __future__ import annotations

import os

from backend.narration.providers.local import local_auth_token_from_env

from .server import create_app


def main() -> None:
    bind = os.getenv("QWEN_TTS_LOCAL_BIND", "127.0.0.1")
    token = local_auth_token_from_env()
    if bind not in {"127.0.0.1", "::1", "localhost"} and not token:
        raise RuntimeError(
            "QWEN_TTS_LOCAL_TOKEN or QWEN_TTS_LOCAL_TOKEN_FILE is required "
            "for a non-loopback bind"
        )
    import uvicorn

    uvicorn.run(
        create_app(),
        host=bind,
        port=int(os.getenv("QWEN_TTS_LOCAL_PORT", "8766")),
        access_log=False,
    )


if __name__ == "__main__":
    main()
