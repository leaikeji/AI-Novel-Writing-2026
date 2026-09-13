from uuid import uuid4

import pytest
from pydantic import ValidationError

from backend.private_library.lexicon_contracts import (
    DEFAULT_WATCH_COUNT,
    LexiconAction,
    LexiconEntry,
    LexiconMatchMode,
    LexiconPack,
)
from backend.private_library.maintenance_contracts import (
    LibraryCaptureSource,
    LibraryChangeAction,
    LibraryChangeOperation,
    LibraryChangeProposal,
    LibraryCheckHit,
    LibraryScope,
    LibraryScopeKind,
    SelectionLibraryApplication,
)


def test_selection_application_is_bounded_and_never_accepts_authority_flags() -> None:
    payload = dict(
        application_id=uuid4(), job_id=uuid4(), attempt=1,
        base_draft_version=2, base_content_hash="a" * 64,
        replacement_sha256="b" * 64, library_check_report_id=uuid4(),
        library_check_version=1,
    )
    assert SelectionLibraryApplication(**payload).accepted_segment_ids is None
    for extra in (
        {"authorized": True},
        {"accepted_segment_ids": ["same", "same"]},
        {"accepted_segment_ids": [str(i) for i in range(201)]},
        {"library_check_version": 0},
    ):
        with pytest.raises(ValidationError):
            SelectionLibraryApplication.model_validate({**payload, **extra})


def _entry(**updates: object) -> LexiconEntry:
    values = {
        "entry_id": "entry_0001",
        "term": "眼底闪过",
        "action": "watch",
    }
    values.update(updates)
    return LexiconEntry.model_validate(values)


def test_watch_rule_receives_explicit_default_threshold() -> None:
    entry = _entry()
    assert entry.action is LexiconAction.WATCH
    assert entry.watch_threshold is not None
    assert entry.watch_threshold.count == DEFAULT_WATCH_COUNT


def test_non_watch_rule_rejects_watch_threshold() -> None:
    with pytest.raises(ValidationError):
        _entry(
            action="forbid",
            watch_threshold={"count": 3, "window_characters": 1_000},
        )


def test_ascii_word_requires_ascii_terms_and_variants() -> None:
    valid = _entry(
        term="basically",
        variants=["Basically"],
        action="forbid",
        match_mode=LexiconMatchMode.ASCII_WORD,
    )
    assert valid.match_mode is LexiconMatchMode.ASCII_WORD
    with pytest.raises(ValidationError):
        _entry(term="基本上", action="forbid", match_mode="ascii_word")


def test_lexicon_pack_rejects_duplicate_stable_entry_id() -> None:
    with pytest.raises(ValidationError):
        LexiconPack(entries=[_entry(), _entry(term="眸光微动")])


def test_library_and_novel_scopes_are_mutually_exclusive() -> None:
    assert LibraryScope(kind=LibraryScopeKind.LIBRARY).novel_id is None
    novel_id = uuid4()
    assert LibraryScope(kind=LibraryScopeKind.NOVEL, novel_id=novel_id).novel_id == novel_id
    with pytest.raises(ValidationError):
        LibraryScope(kind=LibraryScopeKind.LIBRARY, novel_id=novel_id)
    with pytest.raises(ValidationError):
        LibraryScope(kind=LibraryScopeKind.NOVEL)


def test_change_proposal_binds_author_scope_source_and_hashes() -> None:
    request_id = uuid4()
    novel_id = uuid4()
    document_id = uuid4()
    proposal = LibraryChangeProposal(
        request_id=request_id,
        session_id="session-1",
        author_text_sha256="a" * 64,
        scope={"kind": "novel", "novel_id": novel_id},
        source=LibraryCaptureSource(
            kind="unsynced_selection",
            text_sha256="b" * 64,
            selection_id=uuid4(),
            document_id=document_id,
            field_id="chapter.content",
        ),
        actions=[
            LibraryChangeAction(
                operation=LibraryChangeOperation.UPSERT_LEXICON_ENTRIES,
                asset_id=uuid4(),
                expected_root_version=2,
                payload={"entries": [_entry(action="forbid").model_dump(mode="json")]},
            )
        ],
        idempotency_key="request-0001",
        content_sha256="c" * 64,
        requires_review=False,
    )
    assert proposal.request_id == request_id
    assert proposal.scope.novel_id == novel_id
    assert proposal.source is not None
    assert proposal.source.kind == "unsynced_selection"


def test_check_hit_uses_non_empty_utf16_range() -> None:
    values = {
        "hit_id": uuid4(),
        "entry_id": "entry_0001",
        "asset_id": uuid4(),
        "asset_version_id": uuid4(),
        "action": "forbid",
        "matched_text": "仿佛",
        "start_utf16": 4,
        "end_utf16": 6,
        "reason": "作者明确禁用",
        "count": 1,
    }
    assert LibraryCheckHit.model_validate(values).end_utf16 == 6
    with pytest.raises(ValidationError):
        LibraryCheckHit.model_validate({**values, "end_utf16": 4})
