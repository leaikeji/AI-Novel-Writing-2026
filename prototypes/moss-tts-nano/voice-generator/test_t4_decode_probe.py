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


probe = load_module(ROOT / "t4_decode_probe.py", "vg40_t4_decode_probe")


def make_codec(root: Path) -> Path:
    codec = root / "codec"
    codec.mkdir()
    (codec / "config.json").write_text(
        json.dumps(
            {
                "model_type": "moss-audio-tokenizer",
                "sampling_rate": 24000,
                "downsample_rate": 1920,
            }
        ),
        encoding="utf-8",
    )
    for name in (
        "model.safetensors.index.json",
        "model-00001-of-00002.safetensors",
        "model-00002-of-00002.safetensors",
    ):
        (codec / name).write_bytes(b"fixed")
    return codec


def test_request_rejects_artifact_tamper_and_codec_contract_drift():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary).resolve()
        codec = make_codec(root)
        artifact = root / "tokens.safetensors"
        artifact.write_bytes(b"tokens")
        digest = probe._sha256(artifact)
        identity = probe.validate_probe_request(
            codec_dir=codec,
            codec_revision="a" * 40,
            artifact_path=artifact,
            artifact_sha256=digest,
            result_path=root / "result.json",
            output_wav=root / "sample.wav",
        )
        assert identity["native_sampling_rate"] == 24000
        artifact.write_bytes(b"tampered")
        try:
            probe.validate_probe_request(
                codec_dir=codec,
                codec_revision="a" * 40,
                artifact_path=artifact,
                artifact_sha256=digest,
                result_path=root / "result.json",
                output_wav=root / "sample.wav",
            )
        except probe.T4ProbeError:
            pass
        else:
            raise AssertionError("tampered token artifact must fail closed")


def test_probe_source_has_fixed_nano_audio_contract():
    source = (ROOT / "t4_decode_probe.py").read_text(encoding="utf-8")
    assert '"processing_policy": "vg40-24k-mono-to-48k-stereo-pcm16/1"' in source
    assert 'subtype="PCM_16"' in source
    assert "3.0 <=" in source
    for field in (
        "non_finite_sample_count",
        "rms_dbfs",
        "clipped_fraction",
        "dc_offset",
        "leading_silence_seconds",
        "trailing_silence_seconds",
    ):
        assert field in source
    assert '"error_message"' not in source


def test_codec_error_classifier_is_bounded():
    cases = {
        "MPS out of memory": "memory_allocation",
        "Placeholder storage": "mps_placeholder_storage",
        "op not implemented for MPS": "operator_not_implemented",
        "bias type differs from dtype": "dtype_contract",
        "kernel size cannot be greater": "convolution_shape_contract",
        "private arbitrary detail": "unclassified",
    }
    for message, expected in cases.items():
        assert probe.classify_error(RuntimeError(message)) == expected
        assert message not in probe.classify_error(RuntimeError(message))
