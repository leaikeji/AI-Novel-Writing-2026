"""Strict DashScope Native text-embedding adapter."""

from __future__ import annotations

import asyncio
import ipaddress
import math
import socket
from dataclasses import dataclass
from typing import Awaitable, Callable, Literal, Sequence
from urllib.parse import urlsplit, urlunsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .contracts import SUPPORTED_EMBEDDING_DIMENSIONS, TARGET_CANDIDATE_DIMENSION


DASHSCOPE_EMBEDDING_PATH = "/api/v1/services/embeddings/text-embedding/text-embedding"
INTERNAL_MAX_BATCH_SIZE = 10


class EmbeddingAdapterError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class EmbeddingVector:
    text_index: int
    values: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class EmbeddingBatchResult:
    request_id: str
    vectors: tuple[EmbeddingVector, ...]
    total_tokens: int
    input_tokens: int | None


class _ResponseEmbedding(BaseModel):
    model_config = ConfigDict(extra="ignore")
    text_index: int = Field(ge=0)
    embedding: list[float]


class _ResponseOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    embeddings: list[_ResponseEmbedding]


class _ResponseUsage(BaseModel):
    model_config = ConfigDict(extra="ignore")
    total_tokens: int = Field(ge=0)
    input_tokens: int | None = Field(default=None, ge=0)


class _DashScopeResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    status_code: int
    request_id: str = Field(min_length=1, max_length=300)
    output: _ResponseOutput
    usage: _ResponseUsage


Resolver = Callable[[str], Awaitable[Sequence[str]]]


async def _system_resolver(hostname: str) -> Sequence[str]:
    loop = asyncio.get_running_loop()
    records = await loop.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
    return sorted({record[4][0] for record in records})


def normalize_dashscope_base_url(raw_url: str) -> str:
    parsed = urlsplit(raw_url.strip())
    hostname = (parsed.hostname or "").lower()
    if (
        parsed.scheme != "https"
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.port not in (None, 443)
    ):
        raise EmbeddingAdapterError("EMBEDDING_BASE_URL_INVALID", "Base URL is invalid")
    labels = hostname.split(".")
    if len(labels) < 5 or not hostname.endswith(".maas.aliyuncs.com"):
        raise EmbeddingAdapterError(
            "EMBEDDING_BASE_URL_INVALID", "Base URL must use an official Model Studio domain"
        )
    workspace_label = labels[0]
    if not workspace_label or any(character not in "abcdefghijklmnopqrstuvwxyz0123456789-" for character in workspace_label):
        raise EmbeddingAdapterError("EMBEDDING_BASE_URL_INVALID", "Workspace host label is invalid")
    path = parsed.path.rstrip("/")
    if path != "/api/v1":
        raise EmbeddingAdapterError(
            "EMBEDDING_BASE_URL_INVALID", "Base URL must end with /api/v1"
        )
    return urlunsplit(("https", hostname, "/api/v1", "", ""))


async def validate_public_resolution(base_url: str, resolver: Resolver = _system_resolver) -> None:
    hostname = urlsplit(base_url).hostname
    if hostname is None:
        raise EmbeddingAdapterError("EMBEDDING_BASE_URL_INVALID", "Base URL is invalid")
    try:
        addresses = await resolver(hostname)
    except Exception as error:
        raise EmbeddingAdapterError(
            "EMBEDDING_DNS_FAILED", "Model endpoint DNS resolution failed", retryable=True
        ) from error
    if not addresses:
        raise EmbeddingAdapterError("EMBEDDING_DNS_FAILED", "Model endpoint has no addresses")
    for raw_address in addresses:
        try:
            address = ipaddress.ip_address(raw_address.split("%", 1)[0])
        except ValueError as error:
            raise EmbeddingAdapterError("EMBEDDING_DNS_FAILED", "Model endpoint address is invalid") from error
        if not address.is_global:
            raise EmbeddingAdapterError(
                "EMBEDDING_SSRF_BLOCKED", "Model endpoint resolved to a non-public address"
            )


class DashScopeEmbeddingAdapter:
    def __init__(self, *, base_url: str, timeout_seconds: float = 30.0) -> None:
        self.base_url = normalize_dashscope_base_url(base_url)
        self.timeout_seconds = timeout_seconds

    async def embed(
        self,
        *,
        api_key: str,
        texts: Sequence[str],
        text_type: Literal["document", "query"],
        model_id: str = "qwen3.7-text-embedding",
        dimension: int = TARGET_CANDIDATE_DIMENSION,
        instruct: str | None = None,
        client: httpx.AsyncClient | None = None,
        resolver: Resolver = _system_resolver,
    ) -> EmbeddingBatchResult:
        if not 1 <= len(texts) <= INTERNAL_MAX_BATCH_SIZE:
            raise EmbeddingAdapterError("EMBEDDING_BATCH_INVALID", "Embedding batch size is invalid")
        cleaned = tuple(text.strip() for text in texts)
        if any(not text for text in cleaned):
            raise EmbeddingAdapterError("EMBEDDING_BATCH_INVALID", "Embedding text must not be blank")
        if instruct is not None and text_type != "query":
            raise EmbeddingAdapterError("EMBEDDING_REQUEST_INVALID", "instruct is valid only for query")
        if dimension not in SUPPORTED_EMBEDDING_DIMENSIONS:
            raise EmbeddingAdapterError(
                "EMBEDDING_REQUEST_INVALID",
                "Embedding dimension is not supported by qwen3.7-text-embedding",
            )
        if not api_key or "\x00" in api_key:
            raise EmbeddingAdapterError("EMBEDDING_AUTH_FAILED", "Embedding credential is unavailable")
        await validate_public_resolution(self.base_url, resolver)
        parameters: dict[str, object] = {
            "dimension": dimension,
            "output_type": "dense",
            "text_type": text_type,
        }
        if instruct:
            parameters["instruct"] = instruct
        payload = {"model": model_id, "input": {"texts": list(cleaned)}, "parameters": parameters}
        endpoint = f"{self.base_url}{DASHSCOPE_EMBEDDING_PATH.removeprefix('/api/v1')}"
        owns_client = client is None
        active_client = client or httpx.AsyncClient(
            timeout=self.timeout_seconds,
            follow_redirects=False,
            trust_env=False,
        )
        try:
            response = await active_client.post(
                endpoint,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
            )
        except (httpx.TimeoutException, httpx.NetworkError) as error:
            raise EmbeddingAdapterError(
                "EMBEDDING_UNAVAILABLE", "Embedding request failed", retryable=True
            ) from error
        finally:
            if owns_client:
                await active_client.aclose()
        if response.is_redirect:
            raise EmbeddingAdapterError("EMBEDDING_PROTOCOL_ERROR", "Embedding redirect is forbidden")
        if response.status_code in (401, 403):
            raise EmbeddingAdapterError("EMBEDDING_AUTH_FAILED", "Embedding authentication failed")
        if response.status_code == 429:
            raise EmbeddingAdapterError("EMBEDDING_RATE_LIMITED", "Embedding request was rate limited", retryable=True)
        if response.status_code >= 500:
            raise EmbeddingAdapterError("EMBEDDING_UNAVAILABLE", "Embedding service is unavailable", retryable=True)
        if response.status_code != 200:
            raise EmbeddingAdapterError("EMBEDDING_PROTOCOL_ERROR", "Embedding request was rejected")
        try:
            parsed = _DashScopeResponse.model_validate(response.json())
        except (ValueError, ValidationError) as error:
            raise EmbeddingAdapterError("EMBEDDING_PROTOCOL_ERROR", "Embedding response is invalid") from error
        if parsed.status_code != 200 or len(parsed.output.embeddings) != len(cleaned):
            raise EmbeddingAdapterError("EMBEDDING_PROTOCOL_ERROR", "Embedding response count is invalid")
        ordered = sorted(parsed.output.embeddings, key=lambda item: item.text_index)
        if [item.text_index for item in ordered] != list(range(len(cleaned))):
            raise EmbeddingAdapterError("EMBEDDING_PROTOCOL_ERROR", "Embedding response indexes are invalid")
        vectors: list[EmbeddingVector] = []
        for item in ordered:
            if len(item.embedding) != dimension or not all(math.isfinite(value) for value in item.embedding):
                raise EmbeddingAdapterError(
                    "EMBEDDING_DIMENSION_MISMATCH", "Embedding vector dimension is invalid"
                )
            vectors.append(EmbeddingVector(item.text_index, tuple(item.embedding)))
        return EmbeddingBatchResult(
            request_id=parsed.request_id,
            vectors=tuple(vectors),
            total_tokens=parsed.usage.total_tokens,
            input_tokens=parsed.usage.input_tokens,
        )
