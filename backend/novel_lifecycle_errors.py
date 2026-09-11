"""Stable domain errors for the recoverable novel lifecycle."""

from __future__ import annotations


class NovelLifecycleError(RuntimeError):
    code = "novel_lifecycle_error"
    http_status = 409


class NovelLifecycleNotFound(NovelLifecycleError):
    code = "novel_not_found"
    http_status = 404


class NovelRecycledError(NovelLifecycleError):
    code = "novel_recycled"
    http_status = 410


class NovelLifecycleStateConflict(NovelLifecycleError):
    code = "novel_lifecycle_state_conflict"


class NovelLifecycleVersionConflict(NovelLifecycleError):
    code = "novel_version_conflict"


class NovelLifecycleIdempotencyConflict(NovelLifecycleError):
    code = "idempotency_conflict"


class NovelLifecycleBusy(NovelLifecycleError):
    code = "novel_has_active_jobs"


class NovelCleanupInProgress(NovelLifecycleError):
    code = "novel_cleanup_in_progress"


class NovelRestoreIntegrityBlocked(NovelLifecycleError):
    code = "restore_integrity_blocked"


class NovelMaintenanceUnavailable(NovelLifecycleError):
    code = "novel_maintenance_unavailable"
    http_status = 503
