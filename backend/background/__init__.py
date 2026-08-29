"""Shared persistent background execution facade.

Narration keeps its compatibility imports; new domains must import through
this package so executor/resource ownership stays explicit.
"""

from .contracts import LocalWorkspaceScope
from .scheduler import PersistentJobScheduler, SchedulerConfig

__all__ = ["LocalWorkspaceScope", "PersistentJobScheduler", "SchedulerConfig"]
