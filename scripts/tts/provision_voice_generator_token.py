#!/usr/bin/env python3
"""Provision the shared private token for the native VoiceGenerator host."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
import sys
from typing import Final, Sequence

PROJECT_ROOT: Final = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.tts.provision_validation_token import (
    DockerContainerTokenPort,
    TokenProvisionError,
    destroy_token,
    provision_token,
    verify_token,
)


APP_ROOT: Final = (
    Path.home()
    / "Library"
    / "Application Support"
    / "AI小说世界2026"
    / "voice-generator-vg40"
)
HOST_TOKEN_FILE: Final = APP_ROOT / "secrets" / "host-token"
CONTAINER_TOKEN_DIRECTORY: Final = (
    "/app/working.secret/ai-novel-world-2026/voice-generator"
)
CONTAINER_TOKEN_FILE: Final = f"{CONTAINER_TOKEN_DIRECTORY}/token"
CONFIRMATION: Final = "PROVISION-VOICE-GENERATOR-TOKEN"
DESTROY_CONFIRMATION: Final = "DESTROY-VOICE-GENERATOR-TOKEN"


def _prepare_private_parent(path: Path) -> None:
    if path != HOST_TOKEN_FILE:
        raise TokenProvisionError("HOST_TOKEN_PATH_INVALID")
    parent = path.parent
    if not parent.exists():
        parent.mkdir(mode=0o700, parents=False)
    details = parent.lstat()
    if (
        not stat.S_ISDIR(details.st_mode)
        or stat.S_ISLNK(details.st_mode)
        or details.st_uid != os.getuid()
        or stat.S_IMODE(details.st_mode) != 0o700
    ):
        raise TokenProvisionError("HOST_TOKEN_DIRECTORY_INVALID")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("provision", "verify", "destroy"), required=True)
    parser.add_argument("--confirm", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        arguments = build_parser().parse_args(argv)
        expected = (
            DESTROY_CONFIRMATION
            if arguments.mode == "destroy"
            else CONFIRMATION
        )
        if arguments.confirm != expected:
            raise TokenProvisionError("CONFIRMATION_REQUIRED")
        _prepare_private_parent(HOST_TOKEN_FILE)
        port = DockerContainerTokenPort(
            token_directory=CONTAINER_TOKEN_DIRECTORY,
            token_file=CONTAINER_TOKEN_FILE,
        )
        if arguments.mode == "provision":
            result = provision_token(HOST_TOKEN_FILE, port)
        elif arguments.mode == "verify":
            result = verify_token(HOST_TOKEN_FILE, port)
        else:
            result = destroy_token(HOST_TOKEN_FILE, port)
        sys.stdout.write(json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n")
        return 0
    except TokenProvisionError as error:
        sys.stderr.write(
            json.dumps(
                {"status": "FAILED", "code": error.code},
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
