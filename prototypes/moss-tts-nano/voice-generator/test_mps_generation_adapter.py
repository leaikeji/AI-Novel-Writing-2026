from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parent


def test_adapter_is_batch_one_and_does_not_enable_cpu_fallback():
    source = (ROOT / "mps_generation_adapter.py").read_text(encoding="utf-8")
    assert 'SCHEMA = "vg40-mps-generation-adapter/2"' in source
    assert "batch_size != 1" in source
    assert "AdapterGenerationResult" in source
    assert "completed=bool(audio_completed[0].item())" in source
    assert "assistant_completed=bool(is_stopping[0].item())" in source
    assert "index_fill_" in source
    assert "x[mask] = x[mask].index_fill" in source
    assert "PYTORCH_ENABLE_MPS_FALLBACK" not in source
    assert '.to("cpu")' not in source


def test_probe_records_adapter_identity():
    source = (ROOT / "t3_generate_probe.py").read_text(encoding="utf-8")
    assert '"generation_adapter_schema"' in source
    assert "generate_batch_one(model" in source
    assert "model.generate(" not in source
