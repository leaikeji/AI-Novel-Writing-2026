import pytest

from backend.embedding.contracts import EmbeddingCorpus
from backend.embedding.renderers import (
    CharacterRendererV1,
    RelationshipRendererV1,
    RendererError,
    RendererErrorCode,
    StructuredRendererRegistry,
)

from .test_renderers import character_source, relationship_source, render_scope


def test_all_structured_corpora_are_disabled_by_default() -> None:
    registry = StructuredRendererRegistry()

    assert registry.enabled_corpora == frozenset()
    with pytest.raises(RendererError) as error:
        registry.render(character_source(), render_scope())
    assert error.value.code is RendererErrorCode.CORPUS_DISABLED


def test_each_corpus_gate_is_independent() -> None:
    registry = StructuredRendererRegistry(enabled_corpora=[EmbeddingCorpus.CHARACTER])

    assert registry.render(character_source(), render_scope()) is not None
    with pytest.raises(RendererError) as error:
        registry.render(relationship_source(), render_scope())
    assert error.value.code is RendererErrorCode.CORPUS_DISABLED


def test_v1_corpora_cannot_be_enabled_through_v2_registry() -> None:
    with pytest.raises(RendererError) as error:
        StructuredRendererRegistry(enabled_corpora=[EmbeddingCorpus.MANUSCRIPT])
    assert error.value.code is RendererErrorCode.UNSUPPORTED_SOURCE


def test_missing_renderer_fails_closed_even_when_corpus_gate_is_open() -> None:
    registry = StructuredRendererRegistry(
        enabled_corpora=[EmbeddingCorpus.CHARACTER],
        renderers={EmbeddingCorpus.RELATIONSHIP: RelationshipRendererV1()},
    )

    with pytest.raises(RendererError) as error:
        registry.render(character_source(), render_scope())
    assert error.value.code is RendererErrorCode.UNSUPPORTED_SOURCE


def test_registry_rejects_a_renderer_registered_under_the_wrong_corpus() -> None:
    with pytest.raises(RendererError) as error:
        StructuredRendererRegistry(
            renderers={EmbeddingCorpus.RELATIONSHIP: CharacterRendererV1()}
        )
    assert error.value.code is RendererErrorCode.INVALID_SOURCE_SCOPE
