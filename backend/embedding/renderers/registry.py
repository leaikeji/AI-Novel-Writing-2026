"""Independent corpus gates for structured renderers."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from ..contracts import EmbeddingCorpus

from .base import StructuredCorpusRenderer
from .character import CharacterRendererV1
from .contracts import (
    RenderScope,
    RenderedCorpusDocument,
    RendererError,
    RendererErrorCode,
    StructuredRenderSource,
)
from .foreshadow import ForeshadowRendererV1
from .relationship import RelationshipRendererV1
from .story_event import StoryEventRendererV1
from .storyline import StorylineRendererV1
from .timeline import TimelineRendererV1


STRUCTURED_CORPORA = frozenset(
    {
        EmbeddingCorpus.CHARACTER,
        EmbeddingCorpus.RELATIONSHIP,
        EmbeddingCorpus.STORY_EVENT,
        EmbeddingCorpus.STORYLINE,
        EmbeddingCorpus.FORESHADOW,
        EmbeddingCorpus.TIMELINE,
    }
)


def default_structured_renderers() -> dict[EmbeddingCorpus, StructuredCorpusRenderer]:
    renderers: tuple[StructuredCorpusRenderer, ...] = (
        CharacterRendererV1(),
        RelationshipRendererV1(),
        StoryEventRendererV1(),
        StorylineRendererV1(),
        ForeshadowRendererV1(),
        TimelineRendererV1(),
    )
    return {renderer.corpus: renderer for renderer in renderers}


class StructuredRendererRegistry:
    """Renderer dispatcher with fail-closed per-corpus release gates."""

    def __init__(
        self,
        *,
        enabled_corpora: Iterable[EmbeddingCorpus] = (),
        renderers: Mapping[EmbeddingCorpus, StructuredCorpusRenderer] | None = None,
    ) -> None:
        enabled = frozenset(enabled_corpora)
        unsupported = enabled - STRUCTURED_CORPORA
        if unsupported:
            raise RendererError(
                RendererErrorCode.UNSUPPORTED_SOURCE,
                "registry may enable only structured V2 corpora",
            )
        selected_renderers = (
            default_structured_renderers() if renderers is None else dict(renderers)
        )
        for corpus, renderer in selected_renderers.items():
            if corpus is not renderer.corpus:
                raise RendererError(
                    RendererErrorCode.INVALID_SOURCE_SCOPE,
                    "renderer registry key does not match renderer corpus",
                )
        self._enabled_corpora = enabled
        self._renderers = selected_renderers

    @property
    def enabled_corpora(self) -> frozenset[EmbeddingCorpus]:
        return self._enabled_corpora

    def render(
        self,
        source: StructuredRenderSource,
        scope: RenderScope,
    ) -> RenderedCorpusDocument | None:
        corpus = source.corpus
        if corpus not in self._enabled_corpora:
            raise RendererError(
                RendererErrorCode.CORPUS_DISABLED,
                f"structured corpus is disabled: {corpus.value}",
            )
        renderer = self._renderers.get(corpus)
        if renderer is None:
            raise RendererError(
                RendererErrorCode.UNSUPPORTED_SOURCE,
                f"no renderer registered for corpus: {corpus.value}",
            )
        return renderer.render(source, scope)
