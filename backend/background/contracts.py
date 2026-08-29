"""Cross-domain background execution contracts."""

from ..narration.contracts import NarrationRequestScope

# Compatibility alias to the already-frozen fixed local scope.  It is the same
# runtime class, so legacy exact-type guards remain safe during extraction.
LocalWorkspaceScope = NarrationRequestScope

__all__ = ["LocalWorkspaceScope"]
