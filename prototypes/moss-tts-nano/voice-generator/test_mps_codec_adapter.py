from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parent


def test_codec_adapter_freezes_only_the_quantizer_decoder_dtype_boundary():
    source = (ROOT / "mps_codec_adapter.py").read_text(encoding="utf-8")
    assert 'SCHEMA = "vg40-mps-codec-adapter/1"' in source
    assert "quantizer.float()" in source
    assert "decoder_parameter.dtype != torch.bfloat16" in source
    assert "quantized.to(dtype=decoder_parameter.dtype)" in source
    assert '.to("cpu")' not in source
    assert "PYTORCH_ENABLE_MPS_FALLBACK" not in source


def test_decode_probe_records_codec_adapter_identity():
    source = (ROOT / "t4_decode_probe.py").read_text(encoding="utf-8")
    assert '"codec_adapter_schema"' in source
    assert "decode_batch_one(" in source
    assert "codec.decode(" not in source
