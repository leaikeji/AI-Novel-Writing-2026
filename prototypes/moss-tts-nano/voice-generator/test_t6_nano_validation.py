from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/tts/voice_generator/validate_with_nano.py"
DIRECT_SCRIPT = ROOT / "scripts/tts/voice_generator/validate_with_nano_direct.py"


def test_t6_script_is_database_free_and_does_not_publish_audio():
    source = SCRIPT.read_text(encoding="utf-8")
    assert "VoiceProfile" not in source
    assert "Session" not in source
    assert '"database_writes": 0' in source
    assert '"audio_published": False' in source
    assert "result.audio_bytes" in source
    assert "write_bytes(result.audio_bytes)" not in source


def test_t6_output_inspection_rejects_empty_audio():
    spec = importlib.util.spec_from_file_location("vg40_t6", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["vg40_t6"] = module
    spec.loader.exec_module(module)
    try:
        module.inspect_output(b"")
    except Exception:
        pass
    else:
        raise AssertionError("empty Nano output must fail")


def test_direct_t6_client_renews_lease_and_never_writes_audio():
    source = DIRECT_SCRIPT.read_text(encoding="utf-8")
    assert '"/v1/lease/acquire"' in source
    assert '"/v1/lease/renew"' in source
    assert '"/v1/lease/release"' in source
    assert '"database_writes": 0' in source
    assert '"audio_published": False' in source
    assert "write_bytes" not in source
