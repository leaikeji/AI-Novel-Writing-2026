"""Plan 76 final closeout frontend release using the audited V0.8 lifecycle."""
from __future__ import annotations

from pathlib import Path
import runpy


BASE_RELEASE = Path(__file__).resolve().parents[1] / "character-voice-v08" / "release.py"
release = runpy.run_path(str(BASE_RELEASE))
release_globals = release["main"].__globals__
release_globals["EXPECTED_JS"] = "6bfb413400c722dc63a4a7f405343ddcd8fb58ee743bdf1a42ab47b4144b1a05"
release_globals["SOURCE_FILES"] = (
    "frontend/src/workbench-v2.ts",
    "frontend/src/narration/chapter-narration-workflow.ts",
    "frontend/src/narration/chapter-narration-workflow.test.ts",
    "frontend/src/narration/contracts.ts",
)


if __name__ == "__main__":
    release["main"]()
