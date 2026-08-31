from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile


MODULE_PATH = Path(__file__).with_name("t2_load_probe.py")
SPEC = importlib.util.spec_from_file_location("vg40_t2_load_probe", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def _snapshot(root: Path) -> Path:
    model = root / "model"
    model.mkdir()
    (model / "config.json").write_text(
        json.dumps({"model_type": "fixed", "auto_map": {"AutoModel": "model.Fixed"}}),
        encoding="utf-8",
    )
    (model / "model.safetensors").write_bytes(b"fixed")
    return model


def test_request_requires_fixed_local_snapshot_and_new_absolute_result():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary).resolve()
        model = _snapshot(root)
        result = root / "result.json"
        identity = MODULE.validate_probe_request(
            component="voice-generator",
            model_dir=model,
            revision="a" * 40,
            result_path=result,
        )
        assert identity["weight_file_count"] == 1
        result.write_text("occupied", encoding="utf-8")
        try:
            MODULE.validate_probe_request(
                component="voice-generator",
                model_dir=model,
                revision="a" * 40,
                result_path=result,
            )
        except MODULE.T2ProbeError:
            pass
        else:
            raise AssertionError("existing result must fail closed")


def test_symlinked_model_and_floating_revision_are_rejected():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary).resolve()
        model = _snapshot(root)
        linked = root / "linked"
        linked.symlink_to(model, target_is_directory=True)
        for candidate, revision in ((linked, "a" * 40), (model, "main")):
            try:
                MODULE.validate_probe_request(
                    component="voice-generator",
                    model_dir=candidate,
                    revision=revision,
                    result_path=root / "result.json",
                )
            except MODULE.T2ProbeError:
                pass
            else:
                raise AssertionError("unsafe probe request must fail closed")


def test_failure_result_keeps_only_error_type(monkeypatch):
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary).resolve()
        model = _snapshot(root)
        result = root / "result.json"
        monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
        code = MODULE.run_probe(
            component="voice-generator",
            model_dir=model,
            revision="a" * 40,
            result_path=result,
            mps_memory_fraction=0.55,
            stabilize_seconds=0,
        )
        payload = json.loads(result.read_text(encoding="utf-8"))
        assert code == 1
        assert payload["passed"] is False
        assert payload["error_type"] == "T2ProbeError"
        assert str(model) not in repr(payload)
