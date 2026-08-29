"""Application policy for persisting and adopting public model evidence."""

from __future__ import annotations

from collections.abc import Mapping


ALLOWED_CANDIDATE_STATUSES = frozenset(
    {"verified_from_provider_usage", "not_exposed"}
)


class ModelEvidencePolicyError(ValueError):
    pass


def candidate_actual_identity(
    evidence: Mapping[str, object],
    *,
    requested_provider_id: str,
    requested_model_id: str,
) -> tuple[str | None, str | None]:
    """Validate V2 evidence and return a truthful optional actual identity."""

    if evidence.get("schema_version") != "model-execution-evidence/2":
        raise ModelEvidencePolicyError("模型证据版本无效")
    status = evidence.get("status")
    if status not in ALLOWED_CANDIDATE_STATUSES:
        raise ModelEvidencePolicyError("模型证据已拒绝，不能形成候选")
    preflight = evidence.get("preflight_effective")
    postflight = evidence.get("postflight_effective")
    expected = {
        "provider_id": requested_provider_id,
        "model_id": requested_model_id,
    }
    if not isinstance(preflight, Mapping) or not isinstance(postflight, Mapping):
        raise ModelEvidencePolicyError("模型证据缺少调用前后有效模型")
    if (
        preflight.get("provider_id") != expected["provider_id"]
        or preflight.get("model_id") != expected["model_id"]
        or postflight.get("provider_id") != expected["provider_id"]
        or postflight.get("model_id") != expected["model_id"]
    ):
        raise ModelEvidencePolicyError("模型证据与任务启动模型不一致")
    actual = evidence.get("reported_actual")
    usage = evidence.get("usage")
    if not isinstance(usage, Mapping):
        raise ModelEvidencePolicyError("模型证据缺少公开用量状态")
    if status == "not_exposed":
        if actual is not None or usage.get("status") != "not_exposed":
            raise ModelEvidencePolicyError("未公开模型证据不能携带实际模型或用量")
        return None, None
    if actual != expected or usage.get("status") != "exposed":
        raise ModelEvidencePolicyError("公开用量中的实际模型与任务启动模型不一致")
    return requested_provider_id, requested_model_id


def evidence_allows_candidate(evidence: object) -> bool:
    return (
        isinstance(evidence, Mapping)
        and evidence.get("schema_version") == "model-execution-evidence/2"
        and evidence.get("status") in ALLOWED_CANDIDATE_STATUSES
    )
