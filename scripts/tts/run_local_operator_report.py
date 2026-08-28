#!/usr/bin/env python3
"""Run the fixed local T4-K browser/runtime evidence stage.

This repository-host-only command is the personal, single-user acceptance
entry point.  It deliberately exposes no URL, browser, selector, viewport,
import, database, signer, trust-root, or evidence-injection argument.  The
validation bearer is read from the existing owner-only host token file and is
never printed, hashed, or returned.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import Sequence, TextIO
from uuid import UUID


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.tts.chapter_e2e_collector import CollectorResult  # noqa: E402
from scripts.tts.chapter_e2e_controller_lifecycle import (  # noqa: E402
    ControllerLifecycleError,
    run_fixed_local_operator_report_stage,
)
from scripts.tts.chapter_e2e_probe_request import (  # noqa: E402
    PROBE_REQUEST_FILENAME,
)
from scripts.tts.provision_validation_token import (  # noqa: E402
    TokenProvisionError,
    read_private_host_token,
)


CONFIRMATION = "AUTHOR-OPERATOR-LOCAL-EVIDENCE"
REPORT_SCHEMA = "moss-tts-t4k-local-operator-cli/1.0"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class LocalOperatorCliError(RuntimeError):
    """Stable, redacted command-boundary failure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # pragma: no cover - argparse owns text
        del message
        raise LocalOperatorCliError("LOCAL_OPERATOR_ARGUMENTS_INVALID")


def build_parser() -> argparse.ArgumentParser:
    parser = _SafeArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--probe-request-file", type=Path, required=True)
    parser.add_argument("--host-token-file", type=Path, required=True)
    parser.add_argument("--novel-id", required=True)
    parser.add_argument("--document-id", required=True)
    parser.add_argument("--confirm", required=True)
    return parser


def _canonical_uuid(value: object) -> str:
    if type(value) is not str:
        raise LocalOperatorCliError("LOCAL_OPERATOR_SCOPE_INVALID")
    try:
        normalized = str(UUID(value))
    except (AttributeError, TypeError, ValueError):
        raise LocalOperatorCliError("LOCAL_OPERATOR_SCOPE_INVALID") from None
    if normalized != value:
        raise LocalOperatorCliError("LOCAL_OPERATOR_SCOPE_INVALID")
    return normalized


def _validate_paths(probe_request: Path, host_token: Path) -> None:
    if (
        not probe_request.is_absolute()
        or probe_request.name != PROBE_REQUEST_FILENAME
        or not host_token.is_absolute()
        or probe_request == host_token
    ):
        raise LocalOperatorCliError("LOCAL_OPERATOR_PATH_INVALID")


def _success(result: object) -> dict[str, object]:
    if (
        type(result) is not CollectorResult
        or result.status != "LOCAL_OPERATOR_OBSERVATION_COMMITTED"
        or _SHA256.fullmatch(result.collector_report_sha256) is None
        or _SHA256.fullmatch(result.probe_report_sha256) is None
    ):
        raise LocalOperatorCliError("LOCAL_OPERATOR_RESULT_INVALID")
    return {
        "schema_version": REPORT_SCHEMA,
        "status": result.status,
        "collector_report_sha256": result.collector_report_sha256,
        "probe_report_sha256": result.probe_report_sha256,
        "secret_values_emitted": False,
        "private_paths_emitted": False,
    }


def _write_json(stream: TextIO, payload: dict[str, object]) -> None:
    stream.write(
        json.dumps(
            payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    )


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        if args.confirm != CONFIRMATION:
            raise LocalOperatorCliError("LOCAL_OPERATOR_CONFIRMATION_REQUIRED")
        _validate_paths(args.probe_request_file, args.host_token_file)
        novel_id = _canonical_uuid(args.novel_id)
        document_id = _canonical_uuid(args.document_id)
        validation_token = read_private_host_token(args.host_token_file)
        result = run_fixed_local_operator_report_stage(
            args.probe_request_file,
            novel_id,
            document_id,
            validation_token,
        )
        _write_json(sys.stdout, _success(result))
        return 0
    except (LocalOperatorCliError, ControllerLifecycleError, TokenProvisionError) as error:
        _write_json(
            sys.stderr,
            {
                "schema_version": REPORT_SCHEMA,
                "status": "HOLD",
                "code": error.code,
                "secret_values_emitted": False,
                "private_paths_emitted": False,
            },
        )
        return 2
    except KeyboardInterrupt:
        _write_json(
            sys.stderr,
            {
                "schema_version": REPORT_SCHEMA,
                "status": "HOLD",
                "code": "LOCAL_OPERATOR_INTERRUPTED",
                "secret_values_emitted": False,
                "private_paths_emitted": False,
            },
        )
        return 130
    except SystemExit as error:
        return error.code if type(error.code) is int else 0
    except BaseException:
        _write_json(
            sys.stderr,
            {
                "schema_version": REPORT_SCHEMA,
                "status": "HOLD",
                "code": "LOCAL_OPERATOR_INTERNAL_ERROR",
                "secret_values_emitted": False,
                "private_paths_emitted": False,
            },
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["CONFIRMATION", "REPORT_SCHEMA", "build_parser", "main"]
