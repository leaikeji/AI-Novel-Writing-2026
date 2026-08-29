"""Explicitly provision the embedding AES root and private record directory."""

from __future__ import annotations

import argparse
import os
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root-key", required=True, type=Path)
    parser.add_argument("--records-dir", required=True, type=Path)
    arguments = parser.parse_args()
    root_key = arguments.root_key.resolve()
    records_dir = arguments.records_dir.resolve()
    if root_key.exists():
        raise SystemExit("root key already exists; refusing to rotate implicitly")
    records_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    records_dir.chmod(0o700)
    descriptor = os.open(root_key, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(descriptor, os.urandom(32))
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    root_key.chmod(0o600)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
