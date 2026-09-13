"""Execute the actual TypeScript suggestion and the production Pydantic boundary."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

from backend.narration.contracts import require_mandarin_voice_design
from backend.narration.schemas import CreateDesignedVoiceVersionRequest


def test_actual_frontend_suggestions_pass_mandarin_request_boundary() -> None:
    root = Path(__file__).resolve().parents[2]
    node = os.environ.get("CHARACTER_VOICE_NODE") or shutil.which("node")
    assert node, "Node is required for the real TypeScript-to-Pydantic handoff; set CHARACTER_VOICE_NODE"
    cases = json.loads((root / "tests/fixtures/character_voice_design_cases.json").read_text())
    script = """
import {readFileSync} from 'node:fs';
import {buildCharacterVoiceDesignSuggestion} from './frontend/src/narration/character-voice-design-suggestion.ts';
const cases = JSON.parse(readFileSync('tests/fixtures/character_voice_design_cases.json', 'utf8'));
process.stdout.write(JSON.stringify(cases.map(c => buildCharacterVoiceDesignSuggestion(c.evidence))));
"""
    result = subprocess.run([node, "--input-type=module", "-e", script], cwd=root,
                            check=True, text=True, capture_output=True, timeout=30)
    suggestions = json.loads(result.stdout)
    assert len(suggestions) == len(cases)
    for case, suggestion in zip(cases, suggestions, strict=True):
        assert suggestion["ageEvidence"] == case["age"], case["id"]
        assert suggestion["perceivedAgeEvidence"] == case["perceived"], case["id"]
        description = suggestion["description"]
        for phrase in case["includes"]:
            assert phrase in description, case["id"]
        for phrase in case["excludes"]:
            assert phrase not in description, case["id"]
        if not description:
            assert case["age"] is None and case["perceived"] is None
            continue
        request = CreateDesignedVoiceVersionRequest(
            expected_profile_version=1, description=description, language="zh-CN", seed=1234,
        )
        assert request.description == description
        assert require_mandarin_voice_design(request.description) == description
