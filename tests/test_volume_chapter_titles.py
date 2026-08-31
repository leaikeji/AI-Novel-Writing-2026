from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.volume_chapter_titles import (
    bound_contract_title,
    canonical_tree,
    context_chapter_title,
    display_chapter_title,
    display_volume_title,
    embedding_chapter_title,
    next_chapter_ordinal,
    semantic_title,
)


@pytest.mark.parametrize(
    ("raw", "kind", "expected"),
    [
        ("第十二章 · 海边来信", "chapter", "海边来信"),
        ("第 12 章：海边来信", "chapter", "海边来信"),
        ("第2章: 重逢", "chapter", "重逢"),
        ("第一章", "chapter", ""),
        ("第一章里的秘密", "chapter", "第一章里的秘密"),
        ("第三卷轴之谜", "volume", "第三卷轴之谜"),
        ("第五卷：潮汐旧声", "volume", "潮汐旧声"),
        ("第 1 卷 - 潮汐旧声", "volume", "潮汐旧声"),
        ("  纯名称  ", "chapter", "纯名称"),
        ("", "volume", ""),
    ],
)
def test_semantic_title_only_strips_legacy_prefix_at_boundary(raw, kind, expected):
    assert semantic_title(raw, kind) == expected


def test_display_titles_derive_ordinals_without_persisting_them():
    assert display_volume_title("第五卷：潮汐旧声", 1) == "第1卷 潮汐旧声"
    assert display_chapter_title("第十二章 · 海边来信", 1) == "第1章 海边来信"
    assert display_chapter_title("", 28) == "第28章"


def test_runtime_title_adapters_keep_context_non_empty_and_embedding_stable():
    assert context_chapter_title("", 28) == "第28章"
    assert context_chapter_title("海边来信", 28, suffix=" · 片段 2").endswith(
        " · 片段 2"
    )
    assert embedding_chapter_title("") == "章节正文"
    assert embedding_chapter_title("第9章：海边来信") == "海边来信"


def test_bound_contract_title_reserves_final_suffix_space():
    title = "第123章 " + "潮" * 240
    bounded = bound_contract_title(title, suffix=" · 片段 12", max_length=240)
    assert len(bounded) == 240
    assert bounded.startswith("第123章 ")
    assert bounded.endswith(" · 片段 12")


def test_bound_contract_title_never_silently_drops_the_ordinal():
    with pytest.raises(ValueError, match="preserve both ordinal"):
        bound_contract_title("第123章 潮汐", suffix="x" * 238, max_length=240)


def test_canonical_tree_groups_real_volumes_then_unassigned():
    volume_one = SimpleNamespace(id=uuid4(), position=1000, title="一")
    volume_two = SimpleNamespace(id=uuid4(), position=2000, title="二")
    chapter_one = SimpleNamespace(
        id=uuid4(), volume_id=volume_one.id, position=3000, kind="chapter"
    )
    chapter_two = SimpleNamespace(
        id=uuid4(), volume_id=volume_two.id, position=1000, kind="chapter"
    )
    unassigned = SimpleNamespace(
        id=uuid4(), volume_id=None, position=2000, kind="chapter"
    )
    outline = SimpleNamespace(
        id=uuid4(), volume_id=None, position=1, kind="outline"
    )

    tree = canonical_tree(
        [volume_two, volume_one],
        [chapter_two, unassigned, outline, chapter_one],
    )

    assert tree.volumes == (volume_one, volume_two)
    assert tree.chapters == (chapter_one, chapter_two, unassigned)
    assert tree.chapter_ordinals == {
        chapter_one.id: 1,
        chapter_two.id: 2,
        unassigned.id: 3,
    }
    assert next_chapter_ordinal(tree, volume_one.id) == 2
    assert next_chapter_ordinal(tree, volume_two.id) == 3


def test_canonical_tree_keeps_unknown_volume_chapter_visible_as_unassigned():
    volume = SimpleNamespace(id=uuid4(), position=1000, title="")
    valid = SimpleNamespace(
        id=uuid4(), volume_id=volume.id, position=2000, kind="chapter"
    )
    historical_cross_book = SimpleNamespace(
        id=uuid4(), volume_id=uuid4(), position=1000, kind="chapter"
    )

    tree = canonical_tree([volume], [historical_cross_book, valid])

    assert tree.chapters == (valid, historical_cross_book)
    assert tree.chapter_ordinals == {
        valid.id: 1,
        historical_cross_book.id: 2,
    }
