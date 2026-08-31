"""Narrow dtype-boundary adapter for MOSS Audio Tokenizer on MPS/BF16."""

from __future__ import annotations


SCHEMA = "vg40-mps-codec-adapter/1"


class MPSCodecAdapterError(RuntimeError):
    pass


def decode_batch_one(codec: object, audio_codes: object, codes_lengths: object):
    """Decode one short code tensor without changing the official snapshot.

    The fixed codec remote code intentionally accumulates quantizer embeddings
    in float32.  Loading every parameter as BF16 therefore makes the small
    quantizer output projection reject its float32 input.  Keep that small
    submodule in float32, then cast once to the large decoder's BF16 dtype.
    """

    import torch

    if audio_codes.device.type != "mps" or codes_lengths.device.type != "mps":
        raise MPSCodecAdapterError("codec inputs must be on MPS")
    if audio_codes.ndim != 3 or tuple(audio_codes.shape[:2]) != (16, 1):
        raise MPSCodecAdapterError("adapter supports exactly 16 codebooks and batch=1")
    if codes_lengths.shape != (1,):
        raise MPSCodecAdapterError("codec length tensor shape is invalid")
    quantizer = getattr(codec, "quantizer", None)
    decoder = getattr(codec, "decoder", None)
    if quantizer is None or decoder is None or len(decoder) == 0:
        raise MPSCodecAdapterError("codec modules are unavailable")
    quantizer.float()
    quantized = quantizer.decode_codes(audio_codes)
    decoder_parameter = next(decoder.parameters(), None)
    if decoder_parameter is None or decoder_parameter.device.type != "mps":
        raise MPSCodecAdapterError("decoder parameter identity is invalid")
    if decoder_parameter.dtype != torch.bfloat16:
        raise MPSCodecAdapterError("decoder must remain BF16")
    decoded = quantized.to(dtype=decoder_parameter.dtype)
    decoded_lengths = codes_lengths
    for decoder_module in decoder:
        decoded, decoded_lengths = decoder_module(decoded, decoded_lengths)
    return decoded, decoded_lengths


__all__ = ["MPSCodecAdapterError", "SCHEMA", "decode_batch_one"]
