"""Two-process staged-loading proof for VoiceGenerator then codec decode.

Stage B is not started until Stage A has exited, passed watchdog recovery, and
produced a bounded regular-file artifact whose digest has been recorded.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import hashlib
from pathlib import Path
import threading
from typing import Callable, Mapping, Sequence

from macos_memory_watchdog import OneShotProcessWatchdog, ProcessOutcome, WatchdogResult


class StagedOutcome(str, Enum):
    COMPLETED = "completed"
    STAGE_A_FAILED = "stage_a_failed"
    ARTIFACT_INVALID = "artifact_invalid"
    STAGE_A_NOT_RECOVERED = "stage_a_not_recovered"
    STAGE_B_FAILED = "stage_b_failed"


@dataclass(frozen=True)
class IntermediateArtifact:
    path: str
    byte_size: int
    sha256: str


@dataclass(frozen=True)
class StagedResult:
    outcome: StagedOutcome
    stage_a: WatchdogResult
    artifact: IntermediateArtifact | None
    stage_b: WatchdogResult | None
    stage_pid_overlap: bool
    reason: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "outcome": self.outcome.value,
            "stage_a": self.stage_a.to_dict(),
            "artifact": asdict(self.artifact) if self.artifact else None,
            "stage_b": self.stage_b.to_dict() if self.stage_b else None,
            "stage_pid_overlap": self.stage_pid_overlap,
            "reason": self.reason,
        }


WatchdogFactory = Callable[[str], OneShotProcessWatchdog]


class StagedRuntime:
    def __init__(self, watchdog_factory: WatchdogFactory) -> None:
        self._watchdog_factory = watchdog_factory

    def run(
        self,
        *,
        stage_a_command: Sequence[str],
        stage_b_command: Sequence[str],
        working_directory: Path,
        intermediate_path: Path,
        maximum_intermediate_bytes: int,
        cancel_event: threading.Event | None = None,
        environment: Mapping[str, str] | None = None,
    ) -> StagedResult:
        root = working_directory.resolve()
        artifact_path = (
            intermediate_path
            if intermediate_path.is_absolute()
            else working_directory / intermediate_path
        )
        resolved_parent = artifact_path.parent.resolve()
        if resolved_parent != root and root not in resolved_parent.parents:
            raise ValueError("intermediate artifact must remain in the working directory")
        if maximum_intermediate_bytes <= 0:
            raise ValueError("maximum_intermediate_bytes must be positive")
        if artifact_path.exists():
            raise FileExistsError("intermediate artifact already exists")

        stage_a = self._watchdog_factory("voice_generator").run(
            stage_a_command,
            cwd=working_directory,
            cancel_event=cancel_event,
            environment=environment,
        )
        if stage_a.outcome is not ProcessOutcome.COMPLETED:
            return StagedResult(
                StagedOutcome.STAGE_A_FAILED,
                stage_a,
                None,
                None,
                False,
                stage_a.outcome.value,
            )
        if stage_a.recovery is None or not stage_a.recovery.recovered:
            return StagedResult(
                StagedOutcome.STAGE_A_NOT_RECOVERED,
                stage_a,
                None,
                None,
                False,
                stage_a.recovery.reason if stage_a.recovery else "recovery_missing",
            )

        try:
            artifact = _validate_artifact(
                artifact_path, root, maximum_intermediate_bytes
            )
        except (OSError, ValueError) as error:
            return StagedResult(
                StagedOutcome.ARTIFACT_INVALID,
                stage_a,
                None,
                None,
                False,
                type(error).__name__,
            )

        if cancel_event is not None and cancel_event.is_set():
            return StagedResult(
                StagedOutcome.STAGE_B_FAILED,
                stage_a,
                artifact,
                None,
                False,
                "cancelled_before_codec",
            )

        stage_b = self._watchdog_factory("audio_tokenizer").run(
            stage_b_command,
            cwd=working_directory,
            cancel_event=cancel_event,
            environment=environment,
        )
        stage_a_exit = _event_time(stage_a, "child_exited")
        stage_b_start = _event_time(stage_b, "child_started")
        # Compare lifecycle timestamps instead of PID values: an OS may reuse a
        # PID after Stage A exits without the processes ever overlapping.
        overlap = (
            stage_a_exit is None
            or stage_b_start is None
            or stage_b_start < stage_a_exit
        )
        if stage_b.outcome is not ProcessOutcome.COMPLETED or overlap:
            return StagedResult(
                StagedOutcome.STAGE_B_FAILED,
                stage_a,
                artifact,
                stage_b,
                overlap,
                "pid_overlap" if overlap else stage_b.outcome.value,
            )
        return StagedResult(
            StagedOutcome.COMPLETED,
            stage_a,
            artifact,
            stage_b,
            False,
            None,
        )


def _validate_artifact(path: Path, root: Path, maximum_bytes: int) -> IntermediateArtifact:
    if path.is_symlink() or not path.is_file():
        raise ValueError("intermediate artifact must be a regular non-symlink file")
    resolved = path.resolve(strict=True)
    if resolved.parent != root and root not in resolved.parent.parents:
        raise ValueError("intermediate artifact escaped the working directory")
    size = resolved.stat().st_size
    if size <= 0 or size > maximum_bytes:
        raise ValueError("intermediate artifact size is outside the frozen bound")
    digest = hashlib.sha256()
    with resolved.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return IntermediateArtifact(str(resolved), size, digest.hexdigest())


def _event_time(result: WatchdogResult, kind: str) -> float | None:
    return next(
        (event.monotonic_seconds for event in result.events if event.kind == kind),
        None,
    )
