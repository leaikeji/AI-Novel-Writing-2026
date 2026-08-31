from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile


ROOT = Path(__file__).resolve().parent


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


probe = load_module(ROOT / "t3_generate_probe.py", "vg40_t3_generate_probe")


def make_snapshot(root: Path) -> Path:
    model = root / "model"
    model.mkdir()
    (model / "config.json").write_text(
        json.dumps(
            {
                "model_type": "moss_tts_delay",
                "n_vq": 16,
                "audio_pad_code": 1024,
            }
        ),
        encoding="utf-8",
    )
    for name in ("model.safetensors", "processing_moss_tts.py"):
        (model / name).write_bytes(b"fixed")
    return model


def test_fixture_digest_and_parameters_are_stable():
    assert probe.fixture_sha256() == "155b477c14f6ddcbe54a91d8ff7354660a26e172feedcbfe087eede2689ac5f8"
    assert probe.FIXTURE["schema_version"] == "vg40-neutral-voice-input/1"
    assert probe.FIXTURE["tokens"] == 55
    assert probe.GENERATION_PARAMETERS["max_new_tokens"] == 256
    assert probe.GENERATION_PARAMETERS["text_temperature"] == 0.0
    assert probe.GENERATION_PARAMETERS["audio_temperature"] == 1.5
    assert probe.GENERATION_PARAMETERS["audio_top_p"] == 0.6


def test_request_requires_fixed_snapshot_and_empty_shared_run_directory():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary).resolve()
        model = make_snapshot(root)
        identity = probe.validate_probe_request(
            model_dir=model,
            revision="a" * 40,
            result_path=root / "result.json",
            artifact_path=root / "intermediate.safetensors",
            seed=104729,
        )
        assert identity["n_vq"] == 16
        assert identity["audio_pad_code"] == 1024
        (root / "result.json").write_text("occupied", encoding="utf-8")
        try:
            probe.validate_probe_request(
                model_dir=model,
                revision="a" * 40,
                result_path=root / "result.json",
                artifact_path=root / "intermediate.safetensors",
                seed=104729,
            )
        except probe.T3ProbeError:
            pass
        else:
            raise AssertionError("existing evidence must be rejected")


def test_request_rejects_floating_revision_and_contract_drift():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary).resolve()
        model = make_snapshot(root)
        for revision in ("main", "abc"):
            try:
                probe.validate_probe_request(
                    model_dir=model,
                    revision=revision,
                    result_path=root / "result.json",
                    artifact_path=root / "intermediate.safetensors",
                    seed=1,
                )
            except probe.T3ProbeError:
                pass
            else:
                raise AssertionError("floating revision must be rejected")
        config = json.loads((model / "config.json").read_text())
        config["n_vq"] = 32
        (model / "config.json").write_text(json.dumps(config), encoding="utf-8")
        try:
            probe.validate_probe_request(
                model_dir=model,
                revision="b" * 40,
                result_path=root / "result.json",
                artifact_path=root / "intermediate.safetensors",
                seed=1,
            )
        except probe.T3ProbeError:
            pass
        else:
            raise AssertionError("token contract drift must fail closed")


def test_error_evidence_contract_does_not_include_exception_message():
    source = (ROOT / "t3_generate_probe.py").read_text(encoding="utf-8")
    assert '"error_phase"' in source
    assert '"error_origin"' in source
    assert '"error_message"' not in source


def test_runtime_error_classifier_is_bounded_and_does_not_echo_text():
    cases = {
        "MPS backend out of memory": "memory_allocation",
        "operator has no MPS placeholder": "mps_placeholder_storage",
        "operation not implemented for MPS": "operator_not_implemented",
        "MPS does not support this operation": "operator_not_supported",
        "expected scalar type Float": "dtype_contract",
        "index 5 is out of bounds": "index_contract",
        "probability tensor contains inf": "non_finite_sampling",
        "Metal command failed": "mps_runtime",
        "private arbitrary detail": "unclassified",
    }
    for message, expected in cases.items():
        assert probe.classify_error(RuntimeError(message)) == expected
        assert message not in probe.classify_error(RuntimeError(message))
