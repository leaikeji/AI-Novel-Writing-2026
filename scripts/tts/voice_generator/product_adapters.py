"""Audited MPS/BF16 compatibility adapters for the product host workers."""

from __future__ import annotations

from dataclasses import dataclass
import sys


GENERATION_ADAPTER_SCHEMA = "vg40-mps-generation-adapter/2"
CODEC_ADAPTER_SCHEMA = "vg40-mps-codec-adapter/1"


class ProductAdapterError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class GenerationResult:
    output: object
    completed: bool
    assistant_completed: bool
    generation_steps: int


def generate_batch_one(
    model: object,
    *,
    input_ids: object,
    attention_mask: object,
    max_new_tokens: int,
    text_temperature: float,
    text_top_p: float,
    text_top_k: int,
    audio_temperature: float,
    audio_top_p: float,
    audio_top_k: int,
    audio_repetition_penalty: float,
) -> GenerationResult:
    """Preserve the official loop while avoiding the MPS chained-mask bug."""

    import torch

    if input_ids.device.type != "mps" or attention_mask.device.type != "mps":
        raise ProductAdapterError("generation inputs must be on MPS")
    batch_size, sequence_length, channels = input_ids.shape
    if batch_size != 1 or channels != 17 or not 1 <= max_new_tokens <= 256:
        raise ProductAdapterError("generation shape is outside the product bound")
    model_module = sys.modules.get(model.__class__.__module__)
    sample_token = getattr(model_module, "sample_token", None)
    find_last_equal = getattr(model_module, "find_last_equal_C", None)
    if not callable(sample_token) or not callable(find_last_equal):
        raise ProductAdapterError("official generation helpers are unavailable")

    text_do_sample = text_temperature > 0
    audio_do_sample = audio_temperature > 0
    text_temperature = text_temperature if text_do_sample else 1
    audio_temperature = audio_temperature if audio_do_sample else 1
    n_vq = channels - 1
    past_key_values = None
    current_input_ids = input_ids
    current_attention_mask = attention_mask
    generation_ids = input_ids[:]
    is_stopping = torch.zeros(batch_size, dtype=torch.bool, device=input_ids.device)
    audio_completed = torch.zeros(batch_size, dtype=torch.bool, device=input_ids.device)
    audio_lengths = torch.zeros(batch_size, dtype=torch.int64, device=input_ids.device)
    int64_max = torch.iinfo(torch.int64).max
    delayed_lengths = torch.full(
        (batch_size,), int64_max, dtype=torch.int64, device=input_ids.device
    )
    is_continuation = (
        (input_ids[:, -1, 0] == model.config.audio_start_token_id)
        | (input_ids[:, -1, 0] == model.config.audio_assistant_gen_slot_token_id)
    )
    audio_start_indices = find_last_equal(
        input_ids[..., 0], model.config.audio_start_token_id
    )
    audio_start_mask = is_continuation & (audio_start_indices != -1)
    audio_lengths[audio_start_mask] = sequence_length - audio_start_indices[audio_start_mask]
    is_audio = audio_start_mask.clone()
    excluded_text_ids = torch.tensor(
        [
            model.config.pad_token_id,
            model.config.audio_assistant_gen_slot_token_id,
            model.config.audio_assistant_delay_slot_token_id,
            model.config.audio_end_token_id,
        ],
        device=input_ids.device,
        dtype=torch.long,
    )
    audio_text_mask = torch.ones(
        model.config.language_config.vocab_size,
        device=input_ids.device,
        dtype=torch.bool,
    )
    audio_text_mask[
        [
            model.config.audio_assistant_gen_slot_token_id,
            model.config.audio_assistant_delay_slot_token_id,
        ]
    ] = False

    generation_steps = 0
    for time_step in range(max_new_tokens):
        generation_steps = time_step + 1
        outputs = model(
            input_ids=current_input_ids,
            attention_mask=current_attention_mask,
            past_key_values=past_key_values,
            use_cache=True,
        )
        past_key_values = outputs.past_key_values
        next_token_logits = [
            logit[:, -1, :] / (text_temperature if index == 0 else audio_temperature)
            for index, logit in enumerate(outputs.logits)
        ]
        text_logits = next_token_logits[0].clone()
        next_text_token = torch.full(
            (batch_size,),
            model.config.pad_token_id,
            device=input_ids.device,
            dtype=torch.long,
        )
        next_text_token[~is_stopping & (delayed_lengths < n_vq)] = (
            model.config.audio_assistant_delay_slot_token_id
        )
        is_audio_eos = ~is_stopping & (delayed_lengths == n_vq)
        next_text_token[is_audio_eos] = model.config.audio_end_token_id
        audio_completed[is_audio_eos] = True
        is_audio[is_audio_eos] = False
        sampling_text_mask = ~is_stopping & (delayed_lengths > n_vq)
        if bool(is_audio[0].item()):
            text_logits.masked_fill_(audio_text_mask.unsqueeze(0), float("-inf"))
        else:
            text_logits.index_fill_(-1, excluded_text_ids, float("-inf"))
        if time_step == 0:
            text_logits[..., model.config.audio_assistant_delay_slot_token_id] = float("-inf")
        if time_step <= n_vq:
            text_logits[..., model.config.im_end_token_id] = float("-inf")
        if bool(sampling_text_mask[0].item()):
            next_text_token[0] = sample_token(
                logits=text_logits,
                top_p=text_top_p,
                top_k=text_top_k,
                do_sample=text_do_sample,
            )[0]
        is_audio[next_text_token == model.config.audio_start_token_id] = True
        is_stopping[next_text_token == model.config.im_end_token_id] = True

        next_audio_tokens = torch.full(
            (batch_size, n_vq),
            model.config.audio_pad_code,
            device=input_ids.device,
            dtype=torch.long,
        )
        channel_indices = torch.arange(n_vq, dtype=torch.long, device=input_ids.device)
        pre_audio_mask = audio_lengths.unsqueeze(1) > channel_indices.unsqueeze(0)
        post_audio_mask = channel_indices.unsqueeze(0) > delayed_lengths.unsqueeze(1) - 1
        post_audio_mask[delayed_lengths == int64_max] = True
        sampling_audio_mask = pre_audio_mask & post_audio_mask
        if bool(sampling_audio_mask.any().item()):
            if bool(sampling_audio_mask[0, 0].item()):
                logits = next_token_logits[1]
                logits[..., model.config.audio_pad_code] = float("-inf")
                next_audio_tokens[0, 0] = sample_token(
                    logits=logits,
                    prev_tokens=generation_ids[:, :, 1],
                    repetition_penalty=audio_repetition_penalty,
                    top_p=audio_top_p,
                    top_k=audio_top_k,
                    do_sample=audio_do_sample,
                )[0]
            for channel in range(1, n_vq):
                if not bool(sampling_audio_mask[0, channel].item()):
                    continue
                logits = next_token_logits[channel + 1]
                logits[..., model.config.audio_pad_code] = float("-inf")
                next_audio_tokens[0, channel] = sample_token(
                    logits=logits,
                    prev_tokens=generation_ids[:, :, channel + 1],
                    repetition_penalty=audio_repetition_penalty,
                    top_p=audio_top_p,
                    top_k=audio_top_k,
                    do_sample=audio_do_sample,
                )[0]

        audio_lengths[
            (next_text_token == model.config.audio_start_token_id)
            | (next_text_token == model.config.audio_assistant_gen_slot_token_id)
            | (next_text_token == model.config.audio_assistant_delay_slot_token_id)
        ] += 1
        audio_lengths[next_text_token == model.config.audio_end_token_id] = 0
        delayed_lengths[
            (delayed_lengths == int64_max)
            & (next_text_token == model.config.audio_assistant_delay_slot_token_id)
        ] = 0
        delayed_lengths[delayed_lengths != int64_max] += 1
        delayed_lengths[delayed_lengths > n_vq] = int64_max
        current_input_ids = torch.cat(
            [next_text_token[:, None, None], next_audio_tokens[:, None, :]], dim=2
        )
        current_attention_mask = torch.cat(
            [current_attention_mask, (~is_stopping).unsqueeze(-1)], dim=-1
        )
        generation_ids = torch.cat([generation_ids, current_input_ids], dim=1)
        if bool(audio_completed[0].item()) or bool(is_stopping[0].item()):
            break

    start_indices = find_last_equal(input_ids[..., 0], model.config.im_start_token_id) + 3
    start_index = int(start_indices[0].item())
    start_length = int(sequence_length - start_indices[0].item())
    return GenerationResult(
        output=[(start_length, generation_ids[0, start_index:])],
        completed=bool(audio_completed[0].item()),
        assistant_completed=bool(is_stopping[0].item()),
        generation_steps=generation_steps,
    )


def decode_batch_one(codec: object, audio_codes: object, code_lengths: object):
    import torch

    if audio_codes.device.type != "mps" or code_lengths.device.type != "mps":
        raise ProductAdapterError("codec inputs must be on MPS")
    if audio_codes.ndim != 3 or tuple(audio_codes.shape[:2]) != (16, 1):
        raise ProductAdapterError("codec supports exactly 16 codebooks and batch one")
    if code_lengths.shape != (1,):
        raise ProductAdapterError("codec length shape is invalid")
    quantizer = getattr(codec, "quantizer", None)
    decoder = getattr(codec, "decoder", None)
    if quantizer is None or decoder is None or len(decoder) == 0:
        raise ProductAdapterError("codec modules are unavailable")
    quantizer.float()
    quantized = quantizer.decode_codes(audio_codes)
    parameter = next(decoder.parameters(), None)
    if parameter is None or parameter.device.type != "mps" or parameter.dtype != torch.bfloat16:
        raise ProductAdapterError("codec decoder is not MPS/BF16")
    decoded = quantized.to(dtype=parameter.dtype)
    decoded_lengths = code_lengths
    for module in decoder:
        decoded, decoded_lengths = module(decoded, decoded_lengths)
    return decoded, decoded_lengths
