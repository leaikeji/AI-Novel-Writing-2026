"""Explicitly provision the embedding AES root and private record directory."""

from __future__ import annotations

import argparse
from pathlib import Path

from backend.embedding.secrets import EmbeddingSecretStore


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root-key", required=True, type=Path)
    parser.add_argument("--records-dir", required=True, type=Path)
    arguments = parser.parse_args()
    EmbeddingSecretStore.provision(
        root_key_path=arguments.root_key,
        records_dir=arguments.records_dir,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
