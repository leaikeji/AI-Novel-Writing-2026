"""Plan 76 V0.8.1 scoped frontend release using the audited V0.8 lifecycle."""
from __future__ import annotations

from pathlib import Path
import runpy


BASE_RELEASE = Path(__file__).resolve().parents[1] / "character-voice-v08" / "release.py"
release = runpy.run_path(str(BASE_RELEASE))
release_globals = release["main"].__globals__
release_globals["EXPECTED_JS"] = "4a8b436025732bd961670b3bc6e02405f36de250d071f54c0265d35fad91a930"
release_globals["SOURCE_FILES"] = (
    "frontend/src/narration/character-voice-panel.ts",
    "frontend/src/narration/character-voice-panel.test.ts",
    "frontend/src/narration/voice-source-workspace.ts",
    "frontend/src/narration/voice-source-workspace.test.ts",
)


if __name__ == "__main__":
    release["main"]()
