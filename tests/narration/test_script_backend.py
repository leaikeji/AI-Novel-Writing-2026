from __future__ import annotations

import ast
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from backend.models import CharacterVoiceBinding, DocumentRevision
from backend.narration.script_api import (
    AnalyzeScriptRequest,
    ScriptApiCommand,
    ScriptApiErrorCode,
    ScriptApiFault,
    ScriptApiOperation,
    ScriptReviewAction,
    ScriptReviewResource,
    ScriptSourceStatus,
)
from backend.narration.script_backend import SqlAlchemyScriptApiBackend
from backend.narration.script_contracts import text_sha256
from tests.narration.test_script_analysis import _seed


def _memory_backend(store: object) -> tuple[SqlAlchemyScriptApiBackend, Session]:
    session = Session()
    backend = SqlAlchemyScriptApiBackend(session)
    backend.store = store  # type: ignore[assignment]
    return backend, session


def test_backend_analyzes_and_reads_the_same_typed_script_resource() -> None:
    store, _novel, _document, _revision, _character, request, command = _seed(
        "“没有任何说话提示。”"
    )
    backend, session = _memory_backend(store)
    try:
        analyzed = backend.dispatch(
            ScriptApiCommand(
                operation=ScriptApiOperation.ANALYZE_SCRIPT,
                document_id=command.document_id,
                idempotency_key=command.idempotency_key,
                payload=AnalyzeScriptRequest(
                    request_id=command.request_id,
                    source_revision_id=command.revision_id,
                    source_content_hash=command.content_hash,
                ),
            )
        )
        assert isinstance(analyzed, ScriptReviewResource)
        assert analyzed.blocker_count == 3
        assert analyzed.allowed_actions == []
        assert all(not segment.editable for segment in analyzed.segments)

        latest = backend.dispatch(
            ScriptApiCommand(
                operation=ScriptApiOperation.GET_SCRIPT,
                script_id=analyzed.script_id,
            )
        )
        exact = backend.dispatch(
            ScriptApiCommand(
                operation=ScriptApiOperation.GET_SCRIPT_VERSION,
                version_id=analyzed.script_version_id,
            )
        )
        assert latest == analyzed
        assert exact == analyzed
        assert request.state == "review_required"
    finally:
        session.close()


def test_backend_reads_approved_script_after_character_archive_and_voice_unset() -> None:
    store, _novel, _document, _revision, character, _request, command = _seed(
        "林晚说道：“历史版本仍可查看。”",
        intent="create",
    )
    backend, session = _memory_backend(store)
    try:
        approved = backend.dispatch(
            ScriptApiCommand(
                operation=ScriptApiOperation.ANALYZE_SCRIPT,
                document_id=command.document_id,
                idempotency_key=command.idempotency_key,
                payload=AnalyzeScriptRequest(
                    request_id=command.request_id,
                    source_revision_id=command.revision_id,
                    source_content_hash=command.content_hash,
                ),
            )
        )
        assert isinstance(approved, ScriptReviewResource)
        character.lifecycle_state = "archived"
        binding = store.find_one(
            CharacterVoiceBinding,
            character_id=character.id,
        )
        assert binding is not None
        store.rows[CharacterVoiceBinding].remove(binding)

        historical = backend.dispatch(
            ScriptApiCommand(
                operation=ScriptApiOperation.GET_SCRIPT_VERSION,
                version_id=approved.script_version_id,
            )
        )
        assert historical == approved
    finally:
        session.close()


def test_backend_derives_diverged_snapshot_choices_without_enabling_mutations() -> None:
    store, _novel, document, revision, _character, _request, command = _seed(
        "“无人答话。”"
    )
    backend, session = _memory_backend(store)
    try:
        analyzed = backend.dispatch(
            ScriptApiCommand(
                operation=ScriptApiOperation.ANALYZE_SCRIPT,
                document_id=command.document_id,
                idempotency_key=command.idempotency_key,
                payload=AnalyzeScriptRequest(
                    request_id=command.request_id,
                    source_revision_id=command.revision_id,
                    source_content_hash=command.content_hash,
                ),
            )
        )
        newer_text = "已修改的正文"
        store.add(
            DocumentRevision(
                id=uuid4(),
                document_id=document.id,
                revision_number=revision.revision_number + 1,
                parent_revision_id=revision.id,
                content_markdown=newer_text,
                content_text=newer_text,
                content_hash=text_sha256(newer_text),
                source="manual",
            )
        )
        diverged = backend.dispatch(
            ScriptApiCommand(
                operation=ScriptApiOperation.GET_SCRIPT_VERSION,
                version_id=analyzed.script_version_id,
            )
        )
        assert diverged.source_status is ScriptSourceStatus.WORKING_COPY_DIVERGED
        assert diverged.allowed_actions == [
            ScriptReviewAction.CONTINUE_SNAPSHOT,
            ScriptReviewAction.REANALYZE_LATEST,
        ]
        assert all(not segment.editable for segment in diverged.segments)
    finally:
        session.close()


def test_partial_reanalysis_hold_rejects_before_any_store_access() -> None:
    class ExplodingStore:
        def __getattribute__(self, name: str) -> object:
            raise AssertionError(f"unexpected store access: {name}")

    backend, session = _memory_backend(ExplodingStore())
    try:
        with pytest.raises(ScriptApiFault) as captured:
            backend.dispatch(
                ScriptApiCommand(
                    operation=ScriptApiOperation.REANALYZE_SEGMENTS,
                )
            )
        assert captured.value.code is ScriptApiErrorCode.INVALID_STATE
    finally:
        session.close()


def test_sqlalchemy_storage_failure_is_sanitized_and_retryable() -> None:
    class FailingStore:
        def get(self, *_args: object, **_kwargs: object) -> object:
            raise OperationalError("select hidden", {}, RuntimeError("private"))

    backend, session = _memory_backend(FailingStore())
    try:
        with pytest.raises(ScriptApiFault) as captured:
            backend.dispatch(
                ScriptApiCommand(
                    operation=ScriptApiOperation.GET_SCRIPT,
                    script_id=uuid4(),
                )
            )
        assert captured.value.code is ScriptApiErrorCode.STORAGE_UNAVAILABLE
        assert captured.value.retryable is True
        assert "private" not in captured.value.message
    finally:
        session.close()


def test_pawapp_lifecycle_installs_and_unwinds_both_narration_factories() -> None:
    source = Path("backend/app.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    functions = {
        node.name: ast.unparse(node)
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    assert "router.include_router(narration_script_router)" in source
    startup = functions["_launch_narration_runtime"]
    shutdown = functions["_stop_narration_runtime"]
    uninstall = functions["_uninstall_narration_runtime"]
    assert startup.index("install_narration_settings_backend_factory") < startup.index(
        "install_script_api_backend_factory"
    )
    assert startup.index("uninstall_script_api_backend_factory") < startup.index(
        "uninstall_narration_settings_backend_factory"
    )
    for lifecycle in (shutdown, uninstall):
        assert lifecycle.index("uninstall_script_api_backend_factory") < lifecycle.index(
            "uninstall_narration_settings_backend_factory"
        )
