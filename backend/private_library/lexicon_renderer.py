"""Deterministic human-readable projections for structured lexicon packs.

The rendered Markdown is deliberately one-way.  Runtime rules must always be
loaded from :class:`LexiconPack` metadata and never reconstructed from this
display projection.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re

from .lexicon_contracts import (
    LEXICON_RENDERER_VERSION,
    LexiconAction,
    LexiconEntry,
    LexiconPack,
)


@dataclass(frozen=True, slots=True)
class RenderedLexicon:
    content: str
    content_sha256: str
    entry_count: int
    renderer_version: str


_ACTION_LABELS = {
    LexiconAction.RECOMMEND: "推荐",
    LexiconAction.WATCH: "慎用",
    LexiconAction.FORBID: "禁用",
}
_POSITION_LABELS = {
    "body": "正文",
    "dialogue": "对白",
    "title": "书名",
    "synopsis": "简介",
    "any": "不限",
}
_MARKDOWN_PUNCTUATION = re.compile(r"([\\`*{}\[\]()<>#+.!_|~-])")


def _inline(value: str) -> str:
    """Render arbitrary validated text as one safe Markdown line."""

    collapsed = " ".join(value.split())
    return _MARKDOWN_PUNCTUATION.sub(r"\\\1", collapsed)


def _append_details(lines: list[str], entry: LexiconEntry) -> None:
    if entry.variants:
        lines.append(f"  - 变体：{' / '.join(_inline(item) for item in entry.variants)}")
    filters: list[str] = []
    if entry.categories:
        filters.append("分类：" + " / ".join(_inline(item) for item in entry.categories))
    if entry.genres:
        filters.append("题材：" + " / ".join(_inline(item) for item in entry.genres))
    if entry.eras:
        filters.append("时代：" + " / ".join(_inline(item) for item in entry.eras))
    if entry.positions != ["any"]:
        filters.append("位置：" + " / ".join(
            _POSITION_LABELS[item] for item in entry.positions
        ))
    if filters:
        lines.append("  - " + "；".join(filters))
    matching = "ASCII 完整词" if entry.match_mode.value == "ascii_word" else "精确短语"
    case = "区分大小写" if entry.case_sensitive else "忽略大小写"
    lines.append(f"  - 匹配：{matching}，{case}")
    if entry.watch_threshold is not None:
        lines.append(
            "  - 提醒阈值："
            f"连续 {entry.watch_threshold.window_characters} 个可见字符内"
            f"至少 {entry.watch_threshold.count} 次"
        )
    for label, value in (
        ("说明", entry.note),
        ("例句", entry.example),
        ("反例", entry.counterexample),
        ("改写方向", entry.replacement_hint),
    ):
        if value:
            lines.append(f"  - {label}：{_inline(value)}")
    if entry.source_refs:
        rendered_sources = []
        for source in entry.source_refs:
            item = _inline(source.label)
            if source.locator:
                item += f"（{_inline(source.locator)}）"
            rendered_sources.append(item)
        lines.append("  - 来源：" + " / ".join(rendered_sources))


def render_lexicon_pack(pack: LexiconPack) -> RenderedLexicon:
    """Render one validated pack into stable Markdown and hash it."""

    if not isinstance(pack, LexiconPack):
        pack = LexiconPack.model_validate(pack)

    lines = ["# 用词包", ""]
    for action in (
        LexiconAction.RECOMMEND,
        LexiconAction.WATCH,
        LexiconAction.FORBID,
    ):
        entries = [entry for entry in pack.entries if entry.action is action]
        if not entries:
            continue
        lines.extend((f"## {_ACTION_LABELS[action]}", ""))
        for entry in entries:
            state = "（已停用）" if entry.state.value == "inactive" else ""
            lines.append(f"- **{_inline(entry.term)}**{state}")
            _append_details(lines, entry)
        lines.append("")

    if not pack.entries:
        lines.extend(("暂无词项。", ""))
    content = "\n".join(lines).rstrip() + "\n"
    return RenderedLexicon(
        content=content,
        content_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        entry_count=len(pack.entries),
        renderer_version=LEXICON_RENDERER_VERSION,
    )


__all__ = ["RenderedLexicon", "render_lexicon_pack"]
