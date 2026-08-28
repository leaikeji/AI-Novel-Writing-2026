#!/usr/bin/env python3
"""Install/verify the exact T1-B MOSS Nano production asset allowlist."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

try:
    from backend.narration.model_assets import (  # noqa: E402
        ModelAssetError,
        install_release,
        verify_release,
    )
except ModuleNotFoundError as error:  # Flat, minimal production Sidecar image.
    if error.name not in {"backend", "backend.narration"}:
        raise
    from model_assets import (  # type: ignore[no-redef]  # noqa: E402
        ModelAssetError,
        install_release,
        verify_release,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Install or verify the frozen 3-component/29-artifact MOSS Nano runtime",
    )
    parser.add_argument(
        "--lock",
        type=Path,
        default=REPOSITORY_ROOT / "docker/tts-sidecar/model-source.lock.json",
        help="exact production lock; any hash drift is rejected",
    )
    parser.add_argument("--assets-root", type=Path, required=True)
    parser.add_argument("--verify", action="store_true", help="verify an already published release")
    parser.add_argument("--dry-run", action="store_true", help="validate and print the immutable install plan")
    parser.add_argument("--offline", action="store_true", help="forbid network; verify existing release only")
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    parser.add_argument("--expected-uid", type=int, help="require every controlled asset to have this UID")
    parser.add_argument("--expected-gid", type=int, help="require every controlled asset to have this GID")
    parser.add_argument(
        "--max-parallel-downloads",
        type=int,
        default=4,
        help="bounded artifact download concurrency (1-4; publication remains serial)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.verify and args.dry_run:
        parser.error("--verify and --dry-run are mutually exclusive")
    try:
        result = (
            verify_release(
                args.lock,
                args.assets_root,
                expected_uid=args.expected_uid,
                expected_gid=args.expected_gid,
            )
            if args.verify
            else install_release(
                args.lock,
                args.assets_root,
                dry_run=args.dry_run,
                offline=args.offline,
                timeout_seconds=args.timeout_seconds,
                expected_uid=args.expected_uid,
                expected_gid=args.expected_gid,
                max_parallel_downloads=args.max_parallel_downloads,
            )
        )
    except ModelAssetError as error:
        print(json.dumps({"status": "failed", "error_code": error.code}, sort_keys=True))
        return 2
    print(json.dumps({"status": "passed", **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
