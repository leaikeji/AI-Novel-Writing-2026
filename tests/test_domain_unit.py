from backend.services import content_hash, markdown_to_text, visible_character_count


def test_markdown_snapshots_are_separate_and_deterministic() -> None:
    markdown = "# 标题\n\n**江述**走进雨夜。\n\n[线索](https://example.com)"

    assert markdown_to_text(markdown) == "标题\n\n江述走进雨夜。\n\n线索"
    assert visible_character_count(markdown) == 11
    assert len(content_hash(markdown)) == 64


def test_content_hash_changes_with_author_text() -> None:
    assert content_hash("第一稿") != content_hash("第二稿")
