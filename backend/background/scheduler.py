"""Cross-domain scheduler facade with explicit executor/resource contracts."""

from ..narration.scheduler import NarrationJobScheduler, SchedulerConfig

PersistentJobScheduler = NarrationJobScheduler

__all__ = ["PersistentJobScheduler", "SchedulerConfig"]
