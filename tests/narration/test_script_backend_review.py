from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from copy import deepcopy
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.models import (
    BackgroundJob,
    AnonymousSpeaker,
    CharacterVoiceBinding,
    Document,
    GenericVoicePool,
    GenericVoiceSlot,
    NarrationEdition,
    NarrationRequest,
    NarrationScriptReviewActionRecord,
    NarrationScriptVersion,
    NarrationSettingsSnapshot,
    Novel,
    NovelCharacter,
    NovelNarrationSettings,
    VoiceProfile,
    VoiceProfileVersion,
    VoiceRightsEvent,
    VoiceRightsRecord,
)
from backend.narration.script_api import (
    AnalyzeScriptRequest,
    ApproveScriptRequest,
    SegmentReviewPatch,
    ScriptApiCommand,
    ScriptApiErrorCode,
    ScriptApiFault,
    ScriptApiOperation,
    ScriptReviewAction,
    ScriptReviewResource,
    ScriptSpeakerKind,
)
from backend.narration.script_backend import SqlAlchemyScriptApiBackend
from backend.narration.authority_locks import (
    lock_request_document_mutex,
    lock_voice_authorities,
)
from backend.narration.script_contracts import (
    CastingDecisionOrigin,
    CastingTargetKind,
    SpeakerKind,
)
from backend.narration.script_versions import load_script_contract
from backend.narration.edition_service import orchestrate_narration_request
from backend.narration.services import (
    IdempotencyConflict,
    InvalidNarrationState,
)
from tests.narration.test_edition_service import (
    MemoryRenderQueue,
    POLICY,
    _workflow_seed,
)
from tests.narration.test_script_analysis import _seed


def _backend(
    store: object,
    *,
    with_policy: bool = True,
) -> tuple[SqlAlchemyScriptApiBackend, Session, MemoryRenderQueue]:
    session = Session()
    queue = MemoryRenderQueue(store)  # type: ignore[arg-type]
    backend = SqlAlchemyScriptApiBackend(
        session,
        production_policy_provider=(lambda: POLICY) if with_policy else None,
        queue_factory=lambda _session: queue,
    )
    backend.store = store  # type: ignore[assignment]
    return backend, session, queue


def _backend_with_dependencies(
    store: object,
    *,
    policy_provider: Callable[[], object],
    queue_factory: Callable[[Session], object],
) -> tuple[SqlAlchemyScriptApiBackend, Session]:
    session = Session()
    backend = SqlAlchemyScriptApiBackend(
        session,
        production_policy_provider=policy_provider,  # type: ignore[arg-type]
        queue_factory=queue_factory,  # type: ignore[arg-type]
    )
    backend.store = store  # type: ignore[assignment]
    return backend, session


def _raise_dependency_error() -> object:
    raise RuntimeError("secret dependency detail must not escape")


class _LockRecordingStore:
    def __init__(self, wrapped: object) -> None:
        self.wrapped = wrapped
        self.locks: list[tuple[type[object], UUID]] = []

    def __getattr__(self, name: str) -> object:
        return getattr(self.wrapped, name)

    def get(
        self,
        model: type[object],
        row_id: object,
        *,
        for_update: bool = False,
    ) -> object | None:
        if for_update:
            assert isinstance(row_id, UUID)
            self.locks.append((model, row_id))
        return self.wrapped.get(model, row_id, for_update=for_update)  # type: ignore[attr-defined]

    def find_one(
        self,
        model: type[object],
        *,
        for_update: bool = False,
        **filters: object,
    ) -> object | None:
        return self.wrapped.find_one(  # type: ignore[attr-defined]
            model,
            for_update=for_update,
            **filters,
        )

    def find_all(
        self,
        model: type[object],
        *,
        order_by: tuple[str, ...] = (),
        for_update: bool = False,
        **filters: object,
    ) -> list[object]:
        return self.wrapped.find_all(  # type: ignore[attr-defined]
            model,
            order_by=order_by,
            for_update=for_update,
            **filters,
        )


def _analyze_review_candidate(
    backend: SqlAlchemyScriptApiBackend,
    *,
    document_id: UUID,
    request_id: UUID,
    revision_id: UUID,
    content_hash: str,
    idempotency_key: str,
) -> ScriptReviewResource:
    result = backend.dispatch(
        ScriptApiCommand(
            operation=ScriptApiOperation.ANALYZE_SCRIPT,
            document_id=document_id,
            idempotency_key=idempotency_key,
            payload=AnalyzeScriptRequest(
                request_id=request_id,
                source_revision_id=revision_id,
                source_content_hash=content_hash,
            ),
        )
    )
    assert isinstance(result, ScriptReviewResource)
    return result


def _patch_command(
    resource: ScriptReviewResource,
    *,
    request_id: UUID,
    request_version: int,
    key: str = "script-review-http-patch-0001",
    speaker_kind: ScriptSpeakerKind = ScriptSpeakerKind.NARRATOR,
    character_id: UUID | None = None,
    spoken_text: str = "作者修正后的朗读文本。",
) -> ScriptApiCommand:
    segment = resource.segments[0]
    return ScriptApiCommand(
        operation=ScriptApiOperation.PATCH_SEGMENT,
        version_id=resource.script_version_id,
        segment_id=segment.segment_id,
        idempotency_key=key,
        payload=SegmentReviewPatch(
            request_id=request_id,
            expected_request_version=request_version,
            expected_version_number=resource.version_number,
            expected_immutable_hash=resource.immutable_hash,
            expected_local_hash=segment.local_hash,
            speaker_kind=speaker_kind,
            speaker_label="客户端伪造的显示名称",
            character_id=character_id,
            spoken_text=spoken_text,
            reason="作者确认该句说话人与朗读文本",
        ),
    )


def _approve_command(
    resource: ScriptReviewResource,
    *,
    request_id: UUID,
    request_version: int,
    revision_id: UUID,
    key: str = "script-review-http-approve-0001",
) -> ScriptApiCommand:
    return ScriptApiCommand(
        operation=ScriptApiOperation.APPROVE_SCRIPT_VERSION,
        version_id=resource.script_version_id,
        idempotency_key=key,
        payload=ApproveScriptRequest(
            request_id=request_id,
            expected_request_version=request_version,
            expected_version_number=resource.version_number,
            expected_immutable_hash=resource.immutable_hash,
            source_revision_id=revision_id,
            confirmed=True,
        ),
    )


def _review_flow():
    store, novel, document, revision, character, request, analyze = _seed(
        "“没有任何说话提示。”",
        intent="create",
    )
    backend, session, queue = _backend(store)
    resource = _analyze_review_candidate(
        backend,
        document_id=document.id,
        request_id=request.id,
        revision_id=revision.id,
        content_hash=revision.content_hash,
        idempotency_key=analyze.idempotency_key,
    )
    return (
        store,
        novel,
        document,
        revision,
        character,
        request,
        backend,
        session,
        queue,
        resource,
    )


def test_actions_require_current_generation_pointer_and_runtime_policy() -> None:
    (
        store,
        _novel,
        _document,
        _revision,
        _character,
        request,
        backend,
        session,
        _queue,
        parent,
    ) = _review_flow()
    try:
        assert parent.allowed_actions == [ScriptReviewAction.EDIT_SEGMENT]
        assert all(segment.editable for segment in parent.segments)

        child = backend.dispatch(
            _patch_command(
                parent,
                request_id=request.id,
                request_version=request.version,
            )
        )
        assert isinstance(child, ScriptReviewResource)
        assert child.allowed_actions == [
            ScriptReviewAction.EDIT_SEGMENT,
            ScriptReviewAction.APPROVE,
        ]

        historical = backend.dispatch(
            ScriptApiCommand(
                operation=ScriptApiOperation.GET_SCRIPT_VERSION,
                version_id=parent.script_version_id,
            )
        )
        assert isinstance(historical, ScriptReviewResource)
        assert historical.allowed_actions == []
        assert all(not segment.editable for segment in historical.segments)

        no_runtime, no_runtime_session, _ = _backend(
            store,
            with_policy=False,
        )
        try:
            current_without_runtime = no_runtime.dispatch(
                ScriptApiCommand(
                    operation=ScriptApiOperation.GET_SCRIPT_VERSION,
                    version_id=child.script_version_id,
                )
            )
            assert isinstance(current_without_runtime, ScriptReviewResource)
            assert current_without_runtime.allowed_actions == []
            assert all(
                not segment.editable
                for segment in current_without_runtime.segments
            )
        finally:
            no_runtime_session.close()

        # GET_SCRIPT has no request id.  A newer typed child not referenced by
        # the request remains readable, but is never advertised as mutable.
        request.current_review_version_id = parent.script_version_id
        request.version += 1
        orphan_latest = backend.dispatch(
            ScriptApiCommand(
                operation=ScriptApiOperation.GET_SCRIPT,
                script_id=child.script_id,
            )
        )
        assert isinstance(orphan_latest, ScriptReviewResource)
        assert orphan_latest.script_version_id == child.script_version_id
        assert orphan_latest.allowed_actions == []
        assert all(not segment.editable for segment in orphan_latest.segments)
    finally:
        session.close()


def test_force_review_tightened_snapshot_remains_current_and_actionable() -> None:
    store, _novel, _document, _revision, _seed_request, command = _workflow_seed()
    queue = MemoryRenderQueue(store)
    projection = orchestrate_narration_request(
        store,
        queue,
        replace(
            command,
            force_review=True,
            idempotency_key="production-force-review-backend-0001",
        ),
        POLICY,
    )
    request = store.get(NarrationRequest, projection.request_id)
    assert request is not None
    assert request.state == "review_required"
    assert projection.script_version_id is not None
    backend, session, _ = _backend(store)
    try:
        resource = backend.dispatch(
            ScriptApiCommand(
                operation=ScriptApiOperation.GET_SCRIPT_VERSION,
                version_id=projection.script_version_id,
            )
        )
        assert isinstance(resource, ScriptReviewResource)
        assert resource.source_status.value == "current"
        assert resource.blocker_count == 0
        assert resource.allowed_actions == [
            ScriptReviewAction.EDIT_SEGMENT,
            ScriptReviewAction.APPROVE,
        ]
        approved = backend.dispatch(
            _approve_command(
                resource,
                request_id=request.id,
                request_version=request.version,
                revision_id=resource.revision_id,
                key="script-review-force-approve-0001",
            )
        )
        assert isinstance(approved, ScriptReviewResource)
        assert approved.state.value == "approved"
        assert len(store.find_all(NarrationEdition, request_id=request.id)) == 1
    finally:
        session.close()


def test_patch_uses_server_snapshot_and_current_character_binding_not_label() -> None:
    (
        store,
        _novel,
        _document,
        _revision,
        character,
        request,
        backend,
        session,
        _queue,
        parent,
    ) = _review_flow()
    try:
        command = _patch_command(
            parent,
            request_id=request.id,
            request_version=request.version,
            speaker_kind=ScriptSpeakerKind.CHARACTER,
            character_id=character.id,
        )
        child = backend.dispatch(command)
        assert isinstance(child, ScriptReviewResource)
        corrected_resource = child.segments[0]
        assert corrected_resource.speaker_kind is ScriptSpeakerKind.CHARACTER
        assert corrected_resource.speaker_label == character.name
        assert corrected_resource.speaker_label != command.payload.speaker_label  # type: ignore[union-attr]

        contract = load_script_contract(store, child.script_version_id)
        corrected = contract.segments[0]
        binding = store.find_one(
            CharacterVoiceBinding,
            character_id=character.id,
        )
        assert binding is not None
        assert corrected.speaker.kind is SpeakerKind.CHARACTER
        assert corrected.speaker.character_id == character.id
        assert corrected.casting.origin is CastingDecisionOrigin.CHARACTER_BINDING
        assert corrected.casting.final_target is not None
        assert corrected.casting.final_target.kind is CastingTargetKind.CHARACTER_BINDING
        assert corrected.casting.final_target.binding_id == binding.id
    finally:
        session.close()


def test_narrator_patch_authority_comes_from_request_snapshot_not_live_settings() -> None:
    (
        store,
        _novel,
        _document,
        _revision,
        character,
        request,
        backend,
        session,
        _queue,
        parent,
    ) = _review_flow()
    try:
        snapshot = store.find_one(
            NarrationSettingsSnapshot,
            fingerprint=request.settings_fingerprint,
        )
        settings = store.find_one(
            NovelNarrationSettings,
            novel_id=request.novel_id,
        )
        binding = store.find_one(
            CharacterVoiceBinding,
            character_id=character.id,
        )
        assert snapshot is not None and settings is not None and binding is not None
        resolved = snapshot.snapshot_json["resolved_settings"]
        assert isinstance(resolved, dict)
        snapshot_profile_id = UUID(str(resolved["narrator_profile_id"]))
        assert binding.profile_id is not None and binding.voice_version_id is not None
        assert binding.profile_id != snapshot_profile_id

        contract = load_script_contract(store, parent.script_version_id)
        request, _document, mutex = lock_request_document_mutex(
            store,
            request.id,
            expected_document_id=request.document_id,
            expected_novel_id=request.novel_id,
        )
        authority_lock = lock_voice_authorities(
            store,
            mutex=mutex,
            contract=contract,
            settings_snapshot=snapshot,
            include_narrator=True,
        )

        # Simulate mutable settings moving after the request snapshot.  The
        # narrow resolver must still use the immutable request authority.
        settings.narrator_profile_id = binding.profile_id
        settings.narrator_version_id = binding.voice_version_id
        command = _patch_command(
            parent,
            request_id=request.id,
            request_version=request.version,
        )
        payload = command.payload
        assert isinstance(payload, SegmentReviewPatch)
        speaker, casting = backend._resolve_current_speaker_casting(
            request,
            contract,
            payload,
            resolved_settings=resolved,
            authority_lock=authority_lock,
        )

        assert speaker.kind is SpeakerKind.NARRATOR
        assert casting.origin is CastingDecisionOrigin.NARRATOR_SETTING
        assert casting.final_target is not None
        assert casting.final_target.profile_id == snapshot_profile_id
        assert casting.final_target.profile_id != settings.narrator_profile_id
    finally:
        session.close()


def test_character_patch_lock_plan_includes_drifted_exact_narrator_version() -> None:
    store, _novel, document, revision, character, request, analyze = _seed(
        "夜色沉沉。\n\n“没有任何说话提示。”",
        intent="create",
    )
    backend, session, _queue = _backend(store)
    try:
        parent = _analyze_review_candidate(
            backend,
            document_id=document.id,
            request_id=request.id,
            revision_id=revision.id,
            content_hash=revision.content_hash,
            idempotency_key=analyze.idempotency_key,
        )
        contract = load_script_contract(store, parent.script_version_id)
        assert any(
            segment.casting.origin is CastingDecisionOrigin.NARRATOR_SETTING
            for segment in contract.segments
        )
        snapshot = store.find_one(
            NarrationSettingsSnapshot,
            fingerprint=request.settings_fingerprint,
        )
        assert snapshot is not None
        resolved = snapshot.snapshot_json["resolved_settings"]
        assert isinstance(resolved, dict)
        exact_version_id = UUID(str(resolved["narrator_version_id"]))
        exact_version = store.get(VoiceProfileVersion, exact_version_id)
        narrator_profile = store.get(
            VoiceProfile,
            UUID(str(resolved["narrator_profile_id"])),
        )
        assert exact_version is not None and narrator_profile is not None
        drift_values = {
            column.name: deepcopy(getattr(exact_version, column.name))
            for column in VoiceProfileVersion.__table__.columns
        }
        drift_values.update(
            id=uuid4(),
            version_number=exact_version.version_number + 100,
            fingerprint="e" * 64,
        )
        drifted_version = VoiceProfileVersion(**drift_values)
        store.add(drifted_version)
        narrator_profile.current_version_id = drifted_version.id

        recording = _LockRecordingStore(store)
        _locked_request, _document, mutex = lock_request_document_mutex(
            recording,  # type: ignore[arg-type]
            request.id,
            expected_document_id=request.document_id,
            expected_novel_id=request.novel_id,
        )
        assert [model for model, _identifier in recording.locks[:3]] == [
            NarrationRequest,
            Document,
            Novel,
        ]
        recording.locks.clear()
        lock_voice_authorities(
            recording,  # type: ignore[arg-type]
            mutex=mutex,
            contract=contract,
            settings_snapshot=snapshot,
            extra_character_ids=frozenset({character.id}),
        )

        resource_order = (
            NovelCharacter,
            CharacterVoiceBinding,
            AnonymousSpeaker,
            GenericVoicePool,
            GenericVoiceSlot,
            VoiceProfileVersion,
            VoiceProfile,
            VoiceRightsRecord,
            VoiceRightsEvent,
        )
        rank = {model: position for position, model in enumerate(resource_order)}
        assert [rank[model] for model, _identifier in recording.locks] == sorted(
            rank[model] for model, _identifier in recording.locks
        )
        for model in resource_order:
            identifiers = [
                identifier
                for locked_model, identifier in recording.locks
                if locked_model is model
            ]
            assert identifiers == sorted(identifiers, key=str)
        locked_voice_versions = {
            identifier
            for model, identifier in recording.locks
            if model is VoiceProfileVersion
        }
        assert exact_version_id in locked_voice_versions
        assert drifted_version.id in locked_voice_versions
    finally:
        session.close()


def test_patch_novel_mutex_observes_settings_commit_before_source_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        store,
        _novel,
        _document,
        _revision,
        _character,
        request,
        backend,
        session,
        _queue,
        parent,
    ) = _review_flow()
    settings = store.find_one(NovelNarrationSettings, novel_id=request.novel_id)
    assert settings is not None
    original_get = store.get
    injected = False

    def commit_settings_before_novel_lock(
        model: type[object],
        row_id: object,
        *,
        for_update: bool = False,
    ) -> object | None:
        nonlocal injected
        if model is Novel and for_update and not injected:
            injected = True
            settings.version += 1
        return original_get(model, row_id, for_update=for_update)

    monkeypatch.setattr(store, "get", commit_settings_before_novel_lock)
    counts = (
        len(store.rows[NarrationScriptVersion]),
        len(store.rows[NarrationScriptReviewActionRecord]),
        request.version,
    )
    try:
        with pytest.raises(InvalidNarrationState, match="current source and settings"):
            backend.dispatch(
                _patch_command(
                    parent,
                    request_id=request.id,
                    request_version=request.version,
                )
            )
        assert injected is True
        assert (
            len(store.rows[NarrationScriptVersion]),
            len(store.rows[NarrationScriptReviewActionRecord]),
            request.version,
        ) == counts
    finally:
        session.close()


def test_approval_novel_mutex_rejects_snapshot_superseded_before_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        store,
        _novel,
        _document,
        revision,
        _character,
        request,
        backend,
        session,
        _queue,
        parent,
    ) = _review_flow()
    child = backend.dispatch(
        _patch_command(
            parent,
            request_id=request.id,
            request_version=request.version,
        )
    )
    assert isinstance(child, ScriptReviewResource)
    settings = store.find_one(NovelNarrationSettings, novel_id=request.novel_id)
    assert settings is not None
    original_get = store.get
    injected = False

    def commit_settings_before_novel_lock(
        model: type[object],
        row_id: object,
        *,
        for_update: bool = False,
    ) -> object | None:
        nonlocal injected
        if model is Novel and for_update and not injected:
            injected = True
            settings.version += 1
        return original_get(model, row_id, for_update=for_update)

    monkeypatch.setattr(store, "get", commit_settings_before_novel_lock)
    request_version = request.version
    try:
        with pytest.raises(InvalidNarrationState, match="current source and settings"):
            backend.dispatch(
                _approve_command(
                    child,
                    request_id=request.id,
                    request_version=request_version,
                    revision_id=revision.id,
                )
            )
        assert injected is True
        version = store.get(NarrationScriptVersion, child.script_version_id)
        assert version is not None and version.state == "review_required"
        assert request.state == "review_required"
        assert request.version == request_version
        assert store.find_all(NarrationEdition, request_id=request.id) == []
        assert store.find_all(
            NarrationScriptReviewActionRecord,
            request_id=request.id,
            action_kind="approve",
        ) == []
    finally:
        session.close()


def test_patch_exact_replay_is_zero_write_and_changed_input_conflicts() -> None:
    (
        store,
        _novel,
        _document,
        _revision,
        _character,
        request,
        backend,
        session,
        _queue,
        parent,
    ) = _review_flow()
    try:
        command = _patch_command(
            parent,
            request_id=request.id,
            request_version=request.version,
        )
        first = backend.dispatch(command)
        assert isinstance(first, ScriptReviewResource)
        assert first.segments[0].speaker_label == "旁白"
        counts = (
            len(store.rows[NarrationScriptVersion]),
            len(store.rows[NarrationScriptReviewActionRecord]),
        )
        request_version = request.version

        replay = backend.dispatch(command)
        assert replay == first
        assert request.version == request_version
        assert (
            len(store.rows[NarrationScriptVersion]),
            len(store.rows[NarrationScriptReviewActionRecord]),
        ) == counts

        payload = command.payload
        assert isinstance(payload, SegmentReviewPatch)
        with pytest.raises(IdempotencyConflict, match="canonical input"):
            backend.dispatch(
                ScriptApiCommand(
                    operation=command.operation,
                    version_id=command.version_id,
                    segment_id=command.segment_id,
                    idempotency_key=command.idempotency_key,
                    payload=payload.model_copy(
                        update={"spoken_text": "同键不同朗读文本"}
                    ),
                )
            )
    finally:
        session.close()


def test_patch_rechecks_same_key_after_request_lock_visibility_fence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        store,
        _novel,
        _document,
        _revision,
        _character,
        request,
        backend,
        session,
        _queue,
        parent,
    ) = _review_flow()
    try:
        command = _patch_command(
            parent,
            request_id=request.id,
            request_version=request.version,
        )
        first = backend.dispatch(command)
        assert isinstance(first, ScriptReviewResource)

        original_find_one = store.find_one
        hidden_first_lookup = False

        def hide_winner_before_request_lock(
            model: type[object],
            *,
            for_update: bool = False,
            **filters: object,
        ) -> object | None:
            nonlocal hidden_first_lookup
            if (
                model is NarrationScriptReviewActionRecord
                and filters.get("idempotency_key") == command.idempotency_key
                and not hidden_first_lookup
            ):
                hidden_first_lookup = True
                return None
            return original_find_one(
                model,
                for_update=for_update,
                **filters,
            )

        monkeypatch.setattr(store, "find_one", hide_winner_before_request_lock)
        replay = backend.dispatch(command)

        assert hidden_first_lookup is True
        assert replay == first
        assert len(store.rows[NarrationScriptReviewActionRecord]) == 1
    finally:
        session.close()


def test_new_patch_fails_closed_without_runtime_policy_and_writes_nothing() -> None:
    (
        store,
        _novel,
        _document,
        _revision,
        _character,
        request,
        _backend_with_policy,
        session,
        _queue,
        parent,
    ) = _review_flow()
    session.close()
    unavailable, unavailable_session, _ = _backend(store, with_policy=False)
    try:
        counts = (
            len(store.rows[NarrationScriptVersion]),
            len(store.rows[NarrationScriptReviewActionRecord]),
        )
        request_version = request.version
        with pytest.raises(ScriptApiFault) as captured:
            unavailable.dispatch(
                _patch_command(
                    parent,
                    request_id=request.id,
                    request_version=request.version,
                )
            )
        assert captured.value.code is ScriptApiErrorCode.STORAGE_UNAVAILABLE
        assert captured.value.retryable is True
        assert request.version == request_version
        assert (
            len(store.rows[NarrationScriptVersion]),
            len(store.rows[NarrationScriptReviewActionRecord]),
        ) == counts
    finally:
        unavailable_session.close()


@pytest.mark.parametrize(
    "policy_provider",
    [
        _raise_dependency_error,
        lambda: object(),
    ],
    ids=["provider-raises", "provider-wrong-type"],
)
def test_new_patch_sanitizes_invalid_policy_provider_with_zero_writes(
    policy_provider: Callable[[], object],
) -> None:
    (
        store,
        _novel,
        _document,
        _revision,
        _character,
        request,
        _backend_with_policy,
        session,
        _queue,
        parent,
    ) = _review_flow()
    session.close()
    backend, dependency_session = _backend_with_dependencies(
        store,
        policy_provider=policy_provider,
        queue_factory=lambda _session: MemoryRenderQueue(store),
    )
    try:
        counts = (
            len(store.rows[NarrationScriptVersion]),
            len(store.rows[NarrationScriptReviewActionRecord]),
            request.version,
        )
        with pytest.raises(ScriptApiFault) as captured:
            backend.dispatch(
                _patch_command(
                    parent,
                    request_id=request.id,
                    request_version=request.version,
                )
            )
        assert captured.value.code is ScriptApiErrorCode.STORAGE_UNAVAILABLE
        assert captured.value.message == "朗读脚本数据库当前不可用。"
        assert captured.value.retryable is True
        assert (
            len(store.rows[NarrationScriptVersion]),
            len(store.rows[NarrationScriptReviewActionRecord]),
            request.version,
        ) == counts
    finally:
        dependency_session.close()


def test_approval_freezes_produces_and_ledgers_in_one_backend_transaction() -> None:
    (
        store,
        _novel,
        _document,
        revision,
        _character,
        request,
        backend,
        session,
        queue,
        parent,
    ) = _review_flow()
    try:
        child = backend.dispatch(
            _patch_command(
                parent,
                request_id=request.id,
                request_version=request.version,
            )
        )
        assert isinstance(child, ScriptReviewResource)
        expected_request_version = request.version
        command = _approve_command(
            child,
            request_id=request.id,
            request_version=expected_request_version,
            revision_id=revision.id,
        )

        approved = backend.dispatch(command)
        assert isinstance(approved, ScriptReviewResource)
        assert approved.state.value == "approved"
        assert approved.allowed_actions == []
        assert all(not segment.editable for segment in approved.segments)
        assert request.state in {"queued", "rendering", "partial_ready", "ready"}
        assert request.version >= expected_request_version + 1

        editions = store.find_all(NarrationEdition, request_id=request.id)
        assert len(editions) == 1
        approval_actions = store.find_all(
            NarrationScriptReviewActionRecord,
            request_id=request.id,
            action_kind="approve",
        )
        assert len(approval_actions) == 1
        action = approval_actions[0]
        assert action.parent_version_id == child.script_version_id
        assert action.result_version_id == child.script_version_id
        assert action.result_edition_id == editions[0].id
        assert action.request_version_before == expected_request_version
        assert action.request_version_after == expected_request_version + 1
        assert len(queue.calls) == len(
            store.find_all(BackgroundJob, request_id=request.id)
        )

        counts = (
            len(store.rows[NarrationEdition]),
            len(store.rows[BackgroundJob]),
            len(store.rows[NarrationScriptReviewActionRecord]),
        )
        replay = backend.dispatch(command)
        assert replay == approved
        assert (
            len(store.rows[NarrationEdition]),
            len(store.rows[BackgroundJob]),
            len(store.rows[NarrationScriptReviewActionRecord]),
        ) == counts

        with pytest.raises(IdempotencyConflict, match="another idempotency key"):
            backend.dispatch(
                _approve_command(
                    child,
                    request_id=request.id,
                    request_version=expected_request_version,
                    revision_id=revision.id,
                    key="script-review-http-approve-other",
                )
            )
    finally:
        session.close()


def test_new_approval_fails_closed_when_runtime_policy_is_missing() -> None:
    (
        store,
        _novel,
        _document,
        revision,
        _character,
        request,
        backend,
        session,
        _queue,
        parent,
    ) = _review_flow()
    child = backend.dispatch(
        _patch_command(
            parent,
            request_id=request.id,
            request_version=request.version,
        )
    )
    assert isinstance(child, ScriptReviewResource)
    expected_request_version = request.version
    session.close()

    unavailable, unavailable_session, _ = _backend(store, with_policy=False)
    try:
        with pytest.raises(ScriptApiFault) as captured:
            unavailable.dispatch(
                _approve_command(
                    child,
                    request_id=request.id,
                    request_version=expected_request_version,
                    revision_id=revision.id,
                )
            )
        assert captured.value.code is ScriptApiErrorCode.STORAGE_UNAVAILABLE
        assert captured.value.retryable is True
        version = store.get(NarrationScriptVersion, child.script_version_id)
        assert version is not None and version.state == "review_required"
        assert request.state == "review_required"
        assert request.version == expected_request_version
        assert store.find_all(NarrationEdition, request_id=request.id) == []
        assert store.find_all(
            NarrationScriptReviewActionRecord,
            request_id=request.id,
            action_kind="approve",
        ) == []
    finally:
        unavailable_session.close()


@pytest.mark.parametrize(
    "queue_factory",
    [
        lambda _session: _raise_dependency_error(),
        lambda _session: object(),
    ],
    ids=["factory-raises", "malformed-queue"],
)
def test_new_approval_sanitizes_invalid_queue_with_zero_writes(
    queue_factory: Callable[[Session], object],
) -> None:
    (
        store,
        _novel,
        _document,
        revision,
        _character,
        request,
        backend,
        session,
        _queue,
        parent,
    ) = _review_flow()
    child = backend.dispatch(
        _patch_command(
            parent,
            request_id=request.id,
            request_version=request.version,
        )
    )
    assert isinstance(child, ScriptReviewResource)
    expected_request_version = request.version
    session.close()
    unavailable, unavailable_session = _backend_with_dependencies(
        store,
        policy_provider=lambda: POLICY,
        queue_factory=queue_factory,
    )
    try:
        counts = (
            len(store.rows[NarrationScriptVersion]),
            len(store.rows[NarrationEdition]),
            len(store.rows[NarrationScriptReviewActionRecord]),
            request.version,
        )
        with pytest.raises(ScriptApiFault) as captured:
            unavailable.dispatch(
                _approve_command(
                    child,
                    request_id=request.id,
                    request_version=expected_request_version,
                    revision_id=revision.id,
                )
            )
        assert captured.value.code is ScriptApiErrorCode.STORAGE_UNAVAILABLE
        assert captured.value.message == "朗读脚本数据库当前不可用。"
        assert captured.value.retryable is True
        version = store.get(NarrationScriptVersion, child.script_version_id)
        assert version is not None and version.state == "review_required"
        assert request.state == "review_required"
        assert (
            len(store.rows[NarrationScriptVersion]),
            len(store.rows[NarrationEdition]),
            len(store.rows[NarrationScriptReviewActionRecord]),
            request.version,
        ) == counts
    finally:
        unavailable_session.close()


def test_approval_sanitizes_queue_execution_failure() -> None:
    (
        store,
        _novel,
        _document,
        revision,
        _character,
        request,
        backend,
        session,
        _queue,
        parent,
    ) = _review_flow()
    child = backend.dispatch(
        _patch_command(
            parent,
            request_id=request.id,
            request_version=request.version,
        )
    )
    assert isinstance(child, ScriptReviewResource)
    expected_request_version = request.version
    session.close()
    failing_queue = MemoryRenderQueue(store, fail=True)
    unavailable, unavailable_session = _backend_with_dependencies(
        store,
        policy_provider=lambda: POLICY,
        queue_factory=lambda _session: failing_queue,
    )
    try:
        with pytest.raises(ScriptApiFault) as captured:
            unavailable.dispatch(
                _approve_command(
                    child,
                    request_id=request.id,
                    request_version=expected_request_version,
                    revision_id=revision.id,
                )
            )
        assert failing_queue.calls
        assert captured.value.code is ScriptApiErrorCode.STORAGE_UNAVAILABLE
        assert captured.value.message == "朗读脚本数据库当前不可用。"
        assert captured.value.retryable is True
        assert "injected queue failure" not in captured.value.message
    finally:
        unavailable_session.close()


def test_legal_review_action_replays_ignore_broken_runtime_dependencies() -> None:
    (
        store,
        _novel,
        _document,
        revision,
        _character,
        request,
        backend,
        session,
        _queue,
        parent,
    ) = _review_flow()
    patch_command = _patch_command(
        parent,
        request_id=request.id,
        request_version=request.version,
    )
    child = backend.dispatch(patch_command)
    assert isinstance(child, ScriptReviewResource)
    approve_command = _approve_command(
        child,
        request_id=request.id,
        request_version=request.version,
        revision_id=revision.id,
    )
    approved = backend.dispatch(approve_command)
    assert isinstance(approved, ScriptReviewResource)
    counts = (
        len(store.rows[NarrationScriptVersion]),
        len(store.rows[NarrationEdition]),
        len(store.rows[NarrationScriptReviewActionRecord]),
    )
    session.close()

    replay_backend, replay_session = _backend_with_dependencies(
        store,
        policy_provider=_raise_dependency_error,
        queue_factory=lambda _session: _raise_dependency_error(),
    )
    try:
        patch_replay = replay_backend.dispatch(patch_command)
        assert isinstance(patch_replay, ScriptReviewResource)
        assert patch_replay.script_version_id == child.script_version_id
        assert patch_replay.state.value == "approved"
        assert replay_backend.dispatch(approve_command) == approved
        assert (
            len(store.rows[NarrationScriptVersion]),
            len(store.rows[NarrationEdition]),
            len(store.rows[NarrationScriptReviewActionRecord]),
        ) == counts
    finally:
        replay_session.close()


def test_approval_rechecks_same_key_after_request_lock_visibility_fence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        store,
        _novel,
        _document,
        revision,
        _character,
        request,
        backend,
        session,
        _queue,
        parent,
    ) = _review_flow()
    try:
        child = backend.dispatch(
            _patch_command(
                parent,
                request_id=request.id,
                request_version=request.version,
            )
        )
        assert isinstance(child, ScriptReviewResource)
        command = _approve_command(
            child,
            request_id=request.id,
            request_version=request.version,
            revision_id=revision.id,
        )
        first = backend.dispatch(command)
        assert isinstance(first, ScriptReviewResource)

        original_find_one = store.find_one
        hidden_key_lookup = False
        hidden_request_lookup = False

        def hide_winner_until_request_lock(
            model: type[object],
            *,
            for_update: bool = False,
            **filters: object,
        ) -> object | None:
            nonlocal hidden_key_lookup, hidden_request_lookup
            if model is NarrationScriptReviewActionRecord:
                if (
                    filters.get("idempotency_key") == command.idempotency_key
                    and not hidden_key_lookup
                ):
                    hidden_key_lookup = True
                    return None
                if (
                    filters.get("request_id") == request.id
                    and filters.get("action_kind") == "approve"
                    and not hidden_request_lookup
                ):
                    hidden_request_lookup = True
                    return None
            return original_find_one(
                model,
                for_update=for_update,
                **filters,
            )

        monkeypatch.setattr(store, "find_one", hide_winner_until_request_lock)
        replay = backend.dispatch(command)

        assert hidden_key_lookup is True
        assert hidden_request_lookup is True
        assert replay == first
        assert len(
            store.find_all(
                NarrationScriptReviewActionRecord,
                request_id=request.id,
                action_kind="approve",
            )
        ) == 1
    finally:
        session.close()


def test_approval_unique_collision_rolls_back_then_replays_visible_winner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        store,
        _novel,
        _document,
        revision,
        _character,
        request,
        backend,
        session,
        _queue,
        parent,
    ) = _review_flow()
    try:
        child = backend.dispatch(
            _patch_command(
                parent,
                request_id=request.id,
                request_version=request.version,
            )
        )
        assert isinstance(child, ScriptReviewResource)
        command = _approve_command(
            child,
            request_id=request.id,
            request_version=request.version,
            revision_id=revision.id,
        )

        original_flush: Callable[[], None] = store.flush
        raised = False

        class _Diagnostic:
            constraint_name = "uq_narration_review_action_idempotency"

        class _UniqueViolation(Exception):
            diag = _Diagnostic()

        def collide_after_visible_winner() -> None:
            nonlocal raised
            original_flush()
            if not raised and store.find_all(
                NarrationScriptReviewActionRecord,
                request_id=request.id,
                action_kind="approve",
            ):
                raised = True
                raise IntegrityError(
                    "insert narration_script_review_actions",
                    {},
                    _UniqueViolation("duplicate key"),
                )

        monkeypatch.setattr(store, "flush", collide_after_visible_winner)
        approved = backend.dispatch(command)

        assert isinstance(approved, ScriptReviewResource)
        assert approved.state.value == "approved"
        assert raised is True
        assert len(store.find_all(NarrationEdition, request_id=request.id)) == 1
        assert len(
            store.find_all(
                NarrationScriptReviewActionRecord,
                request_id=request.id,
                action_kind="approve",
            )
        ) == 1
    finally:
        session.close()


def test_group_patch_remains_fail_closed_without_server_casting_authority() -> None:
    (
        _store,
        _novel,
        _document,
        _revision,
        _character,
        request,
        backend,
        session,
        _queue,
        parent,
    ) = _review_flow()
    try:
        segment = parent.segments[0]
        with pytest.raises(InvalidNarrationState, match="group speaker"):
            backend.dispatch(
                ScriptApiCommand(
                    operation=ScriptApiOperation.PATCH_SEGMENT,
                    version_id=parent.script_version_id,
                    segment_id=segment.segment_id,
                    idempotency_key="script-review-http-group-0001",
                    payload=SegmentReviewPatch(
                        request_id=request.id,
                        expected_request_version=request.version,
                        expected_version_number=parent.version_number,
                        expected_immutable_hash=parent.immutable_hash,
                        expected_local_hash=segment.local_hash,
                        speaker_kind=ScriptSpeakerKind.GROUP,
                        speaker_label="群体声音",
                        group_key="grp1_" + "a" * 64,
                        spoken_text=segment.spoken_text,
                        reason="作者尝试选择群体说话人",
                    ),
                )
            )
    finally:
        session.close()
