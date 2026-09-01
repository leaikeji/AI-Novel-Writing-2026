"""Request-scoped SQLAlchemy adapter for the frozen T3 script API facade."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from datetime import datetime
from typing import Final
from uuid import UUID, uuid5

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from ..models import (
    AnonymousSpeaker,
    CharacterVoiceBinding,
    DocumentRevision,
    DocumentWorkingCopy,
    NarrationEdition,
    NarrationRequest,
    NarrationScopeOverride,
    NarrationScript,
    NarrationScriptReviewActionRecord,
    NarrationScriptVersion,
    NarrationSettingsSnapshot,
    NovelCharacter,
    NovelNarrationSettings,
)

from .contracts import (
    LOCAL_OWNER_ACTOR_ID,
    LOCAL_OWNER_ID,
    LOCAL_WORKSPACE_ID,
    NARRATION_REVIEW_TAXONOMY_VERSION,
)
from .authority_locks import (
    RequestDocumentMutex,
    VoiceAuthorityLock,
    lock_request_document_mutex,
    lock_voice_authorities,
    require_voice_authority_lock,
)
from .edition_service import (
    NarrationProductionPolicy,
    produce_approved_request,
)
from .render_cache import RenderJobQueue, SqlAlchemyRenderJobQueue
from .review_actions import (
    REVIEW_ACTION_REQUEST_VERSION,
    CorrectReviewSegment,
    correct_review_segment,
    load_review_script_contract,
)
from .script_analysis import AnalyzeNarrationScript, analyze_narration_script
from .script_api import (
    AnalyzeScriptRequest,
    ApproveScriptRequest,
    SegmentReviewPatch,
    ScriptApiCommand,
    ScriptApiErrorCode,
    ScriptApiFault,
    ScriptApiOperation,
    ScriptApprovalResource,
    ScriptCastingState,
    ScriptReviewAction,
    ScriptReviewIssueResource,
    ScriptReviewResource,
    ScriptReviewSegmentResource,
    ScriptSpeakerKind,
    ScriptSourceStatus,
)
from .script_contracts import (
    SOURCE_BOUND_SEGMENT_KINDS,
    CastingDecision,
    CastingDecisionOrigin,
    CastingTargetKind,
    CastingTargetRef,
    NarrationScriptContract,
    ScriptVersionState,
    SpeakerKind,
    SpeakerRef,
)
from .script_versions import (
    LegacyScriptVersionRead,
    freeze_script_version,
    load_script_contract,
    load_script_version_for_read,
)
from .services import (
    IdempotencyConflict,
    InvalidNarrationState,
    NarrationCasConflict,
    NarrationNotFound,
    NarrationScopeMismatch,
    NarrationServiceError,
    SqlAlchemyNarrationStore,
    canonical_payload,
    canonical_sha256,
    require_local_novel,
    require_nonempty,
    require_row,
    require_usable_voice,
    utc_now,
)
from .snapshots import (
    SETTINGS_SNAPSHOT_SCHEMA_VERSION,
    CreateSettingsSnapshot,
    snapshot_payload,
)


_HOLD_OPERATIONS = frozenset(
    {
        ScriptApiOperation.REANALYZE_SEGMENTS,
    }
)

_REVIEW_ACTION_UNIQUE_CONSTRAINTS: Final = frozenset(
    {
        "narration_script_review_actions_pkey",
        "uq_narration_review_action_idempotency",
        "uq_narration_review_action_request_version",
        "uq_narration_review_action_approve_request",
    }
)

ProductionPolicyProvider = Callable[[], NarrationProductionPolicy | None]
RenderQueueFactory = Callable[[Session], RenderJobQueue]


class SqlAlchemyScriptApiBackend:
    """Thin API adapter; domain rules remain in the frozen T3 services."""

    def __init__(
        self,
        session: Session,
        *,
        production_policy_provider: ProductionPolicyProvider | None = None,
        queue_factory: RenderQueueFactory = SqlAlchemyRenderJobQueue,
    ) -> None:
        if not isinstance(session, Session):
            raise TypeError("script backend requires a SQLAlchemy Session")
        if production_policy_provider is not None and not callable(
            production_policy_provider
        ):
            raise TypeError("production_policy_provider must be callable")
        if not callable(queue_factory):
            raise TypeError("queue_factory must be callable")
        self.session = session
        self.store = SqlAlchemyNarrationStore(session)
        self._production_policy_provider = production_policy_provider
        self._queue_factory = queue_factory

    def dispatch(self, command: ScriptApiCommand) -> object:
        if type(command) is not ScriptApiCommand:
            raise NarrationServiceError("command must be ScriptApiCommand")
        if command.operation in _HOLD_OPERATIONS:
            raise ScriptApiFault(
                ScriptApiErrorCode.INVALID_STATE,
                "该脚本修改动作尚无持久幂等证据，当前继续保持禁用。",
            )
        try:
            if command.operation is ScriptApiOperation.ANALYZE_SCRIPT:
                return self._analyze(command)
            if command.operation is ScriptApiOperation.GET_SCRIPT:
                return self._get_script(command)
            if command.operation is ScriptApiOperation.GET_SCRIPT_VERSION:
                return self._get_version(command)
            if command.operation is ScriptApiOperation.PATCH_SEGMENT:
                return self._patch(command)
            if command.operation is ScriptApiOperation.APPROVE_SCRIPT_VERSION:
                return self._approve(command)
            raise InvalidNarrationState("unsupported script API operation")
        except IntegrityError as error:
            self.session.rollback()
            if self._is_review_action_unique_collision(error):
                try:
                    return self._replay_unique_winner(command)
                except SQLAlchemyError as replay_error:
                    self.session.rollback()
                    raise self._storage_unavailable() from replay_error
            raise self._storage_unavailable() from error
        except SQLAlchemyError as error:
            self.session.rollback()
            raise self._storage_unavailable() from error
        except (ScriptApiFault, NarrationServiceError):
            raise
        except Exception as error:
            # Queue/runtime adapters execute inside the caller-owned
            # Session.begin block.  Unknown dependency failures must trigger
            # rollback and cross the HTTP boundary only as the frozen,
            # retryable storage-unavailable contract.
            self.session.rollback()
            raise self._storage_unavailable() from error

    @staticmethod
    def _storage_unavailable() -> ScriptApiFault:
        return ScriptApiFault(
            ScriptApiErrorCode.STORAGE_UNAVAILABLE,
            "朗读脚本数据库当前不可用。",
            retryable=True,
        )

    @staticmethod
    def _is_review_action_unique_collision(error: IntegrityError) -> bool:
        original = error.orig
        diagnostic = getattr(original, "diag", None)
        constraint_name = getattr(diagnostic, "constraint_name", None)
        if constraint_name is None:
            constraint_name = getattr(original, "constraint_name", None)
        if constraint_name in _REVIEW_ACTION_UNIQUE_CONSTRAINTS:
            return True
        # Some DBAPI test doubles and non-psycopg drivers omit ``diag``.  The
        # fallback stays narrow to the exact frozen ledger/index identities.
        message = str(original)
        return any(name in message for name in _REVIEW_ACTION_UNIQUE_CONSTRAINTS)

    def _replay_unique_winner(
        self,
        command: ScriptApiCommand,
    ) -> ScriptReviewResource:
        """Rollback first, then safely re-read the committed ledger winner.

        This path never retries a write.  A same-key canonical winner replays;
        a different-key request winner conflicts; an unexplained collision is
        reported as unavailable instead of being turned into synthetic success.
        """

        if self.session.in_transaction():
            self.session.rollback()
        with self.session.begin():
            if command.operation is ScriptApiOperation.PATCH_SEGMENT:
                return self._patch_in_transaction(
                    command,
                    require_existing_action=True,
                )
            if command.operation is ScriptApiOperation.APPROVE_SCRIPT_VERSION:
                return self._approve_in_transaction(
                    command,
                    require_existing_action=True,
                )
        raise self._storage_unavailable()

    def _analyze(self, command: ScriptApiCommand) -> ScriptReviewResource:
        if type(command.payload) is not AnalyzeScriptRequest:
            raise NarrationServiceError("analyze command payload is invalid")
        if command.document_id is None or command.idempotency_key is None:
            raise NarrationServiceError("analyze command is incomplete")
        if self.session.in_transaction():
            raise RuntimeError("script command received a pre-opened transaction")
        with self.session.begin():
            contract = analyze_narration_script(
                self.store,
                AnalyzeNarrationScript(
                    request_id=command.payload.request_id,
                    document_id=command.document_id,
                    revision_id=command.payload.source_revision_id,
                    content_hash=command.payload.source_content_hash,
                    idempotency_key=command.idempotency_key,
                ),
            )
            return self._resource(contract)

    def _patch(self, command: ScriptApiCommand) -> ScriptReviewResource:
        if self.session.in_transaction():
            raise RuntimeError("script command received a pre-opened transaction")
        with self.session.begin():
            return self._patch_in_transaction(
                command,
                require_existing_action=False,
            )

    def _patch_in_transaction(
        self,
        command: ScriptApiCommand,
        *,
        require_existing_action: bool,
    ) -> ScriptReviewResource:
        if type(command.payload) is not SegmentReviewPatch:
            raise NarrationServiceError("segment patch payload is invalid")
        if (
            command.version_id is None
            or command.segment_id is None
            or command.idempotency_key is None
        ):
            raise NarrationServiceError("segment patch command is incomplete")
        payload = command.payload
        speaker, casting = self._patch_authority(
            command,
            payload,
            require_existing_action=require_existing_action,
        )
        result = correct_review_segment(
            self.store,
            CorrectReviewSegment(
                request_id=payload.request_id,
                script_version_id=command.version_id,
                segment_id=command.segment_id,
                expected_request_version=payload.expected_request_version,
                expected_version_number=payload.expected_version_number,
                expected_immutable_hash=payload.expected_immutable_hash,
                expected_local_hash=payload.expected_local_hash,
                idempotency_key=command.idempotency_key,
                actor_id=LOCAL_OWNER_ACTOR_ID,
                speaker=speaker,
                casting=casting,
                spoken_text=payload.spoken_text,
                reason=payload.reason,
            ),
        )
        if require_existing_action and not result.replayed:
            raise InvalidNarrationState(
                "review action unique winner was not replayed"
            )
        return self._resource(result.contract)

    def _patch_authority(
        self,
        command: ScriptApiCommand,
        payload: SegmentReviewPatch,
        *,
        require_existing_action: bool,
    ) -> tuple[SpeakerRef, CastingDecision]:
        assert command.version_id is not None
        assert command.idempotency_key is not None
        existing = self.store.find_one(
            NarrationScriptReviewActionRecord,
            owner_id=LOCAL_OWNER_ID,
            workspace_id=LOCAL_WORKSPACE_ID,
            idempotency_key=command.idempotency_key,
            for_update=True,
        )
        if existing is not None:
            return self._stored_patch_authority(existing, payload)
        if require_existing_action:
            contender = self.store.find_one(
                NarrationScriptReviewActionRecord,
                request_id=payload.request_id,
                request_version_after=payload.expected_request_version + 1,
                for_update=True,
            )
            if contender is not None:
                raise NarrationCasConflict(
                    "another review action advanced the request version"
                )
            raise self._storage_unavailable()

        request = require_row(
            self.store.get(NarrationRequest, payload.request_id, for_update=True),
            label="narration request",
        )
        # A same-key contender can become visible only after this request-row
        # lock waits for the first transaction to commit.  Re-read before any
        # state/pointer CAS so an exact loser replays instead of seeing queued
        # state or the winner's child pointer as a false conflict.
        existing = self.store.find_one(
            NarrationScriptReviewActionRecord,
            owner_id=LOCAL_OWNER_ID,
            workspace_id=LOCAL_WORKSPACE_ID,
            idempotency_key=command.idempotency_key,
            for_update=True,
        )
        if existing is not None:
            return self._stored_patch_authority(existing, payload)
        request, _document, mutex = lock_request_document_mutex(
            self.store,
            request.id,
            expected_document_id=request.document_id,
            expected_novel_id=request.novel_id,
        )
        self._require_patch_request(request, command.version_id)
        contract = load_review_script_contract(
            self.store,
            command.version_id,
            for_update=True,
        )
        if (
            contract.script_id != request.review_script_id
            or contract.novel_id != request.novel_id
            or contract.document_id != request.document_id
            or contract.revision_id != request.source_revision_id
            or contract.source_content_hash != request.source_content_hash
            or contract.settings_fingerprint != request.settings_fingerprint
        ):
            raise NarrationScopeMismatch(
                "current review candidate is outside request provenance"
            )
        if self._source_status(contract) is not ScriptSourceStatus.CURRENT:
            raise InvalidNarrationState(
                "only the current source and settings candidate is editable"
            )
        # A new correction is part of the production workflow.  Runtime
        # absence must fail before correct_review_segment can materialize a
        # child/action; an already-ledgered replay returned above stays readable.
        self._require_production_policy()
        settings_snapshot, resolved_settings = self._settings_snapshot_for_request(
            request
        )
        authority_lock = lock_voice_authorities(
            self.store,
            mutex=mutex,
            contract=contract,
            settings_snapshot=settings_snapshot,
            extra_character_ids=(
                frozenset({payload.character_id})
                if payload.character_id is not None
                else frozenset()
            ),
            extra_anonymous_ids=(
                frozenset({payload.anonymous_speaker_id})
                if payload.anonymous_speaker_id is not None
                else frozenset()
            ),
            include_narrator=(
                payload.speaker_kind is ScriptSpeakerKind.NARRATOR
            ),
        )
        return self._resolve_current_speaker_casting(
            request,
            contract,
            payload,
            resolved_settings=resolved_settings,
            authority_lock=authority_lock,
        )

    @staticmethod
    def _require_patch_request(
        request: NarrationRequest,
        version_id: UUID,
    ) -> None:
        if (
            request.owner_id != LOCAL_OWNER_ID
            or request.workspace_id != LOCAL_WORKSPACE_ID
        ):
            raise NarrationScopeMismatch(
                "narration request is outside the fixed local scope"
            )
        if (
            request.intent == "analyze_only"
            or request.explicit_generation_intent_at is None
            or not request.explicit_generation_actor
            or request.allows_render is not True
        ):
            raise InvalidNarrationState(
                "manual correction requires an explicit generation request"
            )
        if request.state != "review_required":
            raise InvalidNarrationState(
                "manual correction requires request state review_required"
            )
        if (
            request.review_script_id is None
            or request.current_review_version_id is None
        ):
            raise InvalidNarrationState(
                "review_required request has no complete current script pointer"
            )
        if request.current_review_version_id != version_id:
            raise NarrationCasConflict(
                "narration request current review version changed"
            )

    def _stored_patch_authority(
        self,
        action: NarrationScriptReviewActionRecord,
        payload: SegmentReviewPatch,
    ) -> tuple[SpeakerRef, CastingDecision]:
        if action.action_kind != "patch_segment":
            raise IdempotencyConflict(
                "review action idempotency key belongs to another action"
            )
        contract = load_review_script_contract(
            self.store,
            action.result_version_id,
            for_update=True,
        )
        corrected = [
            segment
            for segment in contract.segments
            if segment.attribution.override_provenance is not None
            and segment.attribution.override_provenance.action_id == action.id
        ]
        if len(corrected) != 1:
            raise InvalidNarrationState(
                "review action result lacks one exact manual correction"
            )
        speaker = corrected[0].speaker
        if not self._payload_selects_speaker(payload, speaker):
            raise IdempotencyConflict(
                "review action idempotency key has another speaker target"
            )
        return speaker, corrected[0].casting

    @staticmethod
    def _payload_selects_speaker(
        payload: SegmentReviewPatch,
        speaker: SpeakerRef,
    ) -> bool:
        return (
            payload.speaker_kind.value == speaker.kind.value
            and payload.character_id == speaker.character_id
            and payload.anonymous_speaker_id == speaker.anonymous_speaker_id
            and payload.group_key == speaker.group_key
        )

    def _settings_snapshot_for_request(
        self,
        request: NarrationRequest,
    ) -> tuple[NarrationSettingsSnapshot, dict[str, object]]:
        snapshot = require_row(
            self.store.find_one(
                NarrationSettingsSnapshot,
                owner_id=LOCAL_OWNER_ID,
                workspace_id=LOCAL_WORKSPACE_ID,
                fingerprint=request.settings_fingerprint,
            ),
            label="narration settings snapshot",
        )
        if (
            snapshot.novel_id != request.novel_id
            or snapshot.schema_version != SETTINGS_SNAPSHOT_SCHEMA_VERSION
            or snapshot.taxonomy_version != NARRATION_REVIEW_TAXONOMY_VERSION
            or canonical_sha256(snapshot.snapshot_json) != snapshot.fingerprint
        ):
            raise NarrationScopeMismatch(
                "request settings snapshot provenance is inconsistent"
            )
        payload = snapshot.snapshot_json
        if type(payload) is not dict or set(payload) != {
            "schema_version",
            "taxonomy_version",
            "novel_id",
            "settings_version",
            "resolved_settings",
        }:
            raise InvalidNarrationState(
                "request settings snapshot has an unknown shape"
            )
        if (
            payload["schema_version"] != snapshot.schema_version
            or payload["taxonomy_version"] != snapshot.taxonomy_version
            or payload["novel_id"] != str(request.novel_id)
        ):
            raise NarrationScopeMismatch(
                "request settings snapshot root metadata changed"
            )
        resolved = payload["resolved_settings"]
        if type(resolved) is not dict or set(resolved) != {
            "script_review_policy",
            "analysis_mode",
            "narrator_profile_id",
            "narrator_version_id",
            "settings",
            "scope_overrides",
        }:
            raise InvalidNarrationState(
                "request resolved settings have an unknown shape"
            )
        if resolved["script_review_policy"] != request.effective_policy:
            raise NarrationScopeMismatch(
                "request review policy differs from its settings snapshot"
            )
        return snapshot, resolved

    def _resolve_current_speaker_casting(
        self,
        request: NarrationRequest,
        contract: NarrationScriptContract,
        payload: SegmentReviewPatch,
        *,
        resolved_settings: dict[str, object],
        authority_lock: VoiceAuthorityLock,
    ) -> tuple[SpeakerRef, CastingDecision]:
        require_voice_authority_lock(
            authority_lock,
            request_id=request.id,
            contract_version_id=contract.script_version_id,
        )
        require_local_novel(self.store, contract.novel_id)
        if payload.speaker_kind is ScriptSpeakerKind.NARRATOR:
            raw_profile_id = resolved_settings["narrator_profile_id"]
            raw_version_id = resolved_settings["narrator_version_id"]
            if raw_profile_id is None or raw_version_id is None:
                raise InvalidNarrationState(
                    "request settings snapshot has no narrator voice"
                )
            try:
                profile_id = UUID(str(raw_profile_id))
                version_id = UUID(str(raw_version_id))
            except (TypeError, ValueError) as error:
                raise InvalidNarrationState(
                    "request narrator profile/version identity is invalid"
                ) from error
            profile, version, _rights = require_usable_voice(
                self.store,
                version_id,
                novel_id=contract.novel_id,
            )
            if (
                profile.id != profile_id
                or version.profile_id != profile_id
            ):
                raise NarrationScopeMismatch(
                    "request narrator profile/version relation changed"
                )
            target = CastingTargetRef(
                kind=CastingTargetKind.PROFILE,
                profile_id=profile.id,
            )
            return (
                SpeakerRef(SpeakerKind.NARRATOR),
                CastingDecision(
                    candidate_targets=(target,),
                    final_target=target,
                    origin=CastingDecisionOrigin.NARRATOR_SETTING,
                ),
            )

        if payload.speaker_kind is ScriptSpeakerKind.CHARACTER:
            assert payload.character_id is not None
            character = require_row(
                self.store.get(
                    NovelCharacter,
                    payload.character_id,
                ),
                label="character",
            )
            if (
                character.novel_id != contract.novel_id
                or character.lifecycle_state != "active"
            ):
                raise NarrationScopeMismatch(
                    "character is outside the active novel scope"
                )
            binding = require_row(
                self.store.find_one(
                    CharacterVoiceBinding,
                    character_id=character.id,
                ),
                label="character voice binding",
            )
            if (
                binding.novel_id != contract.novel_id
                or binding.binding_policy not in {"dedicated", "inherited"}
                or binding.profile_id is None
                or binding.voice_version_id is None
            ):
                raise InvalidNarrationState(
                    "current character voice binding is incomplete"
                )
            profile, version, _rights = require_usable_voice(
                self.store,
                binding.voice_version_id,
                novel_id=contract.novel_id,
            )
            if profile.id != binding.profile_id or version.profile_id != profile.id:
                raise NarrationScopeMismatch(
                    "character binding profile/version relation changed"
                )
            target = CastingTargetRef(
                kind=CastingTargetKind.CHARACTER_BINDING,
                binding_id=binding.id,
                character_id=character.id,
            )
            return (
                SpeakerRef(
                    SpeakerKind.CHARACTER,
                    character_id=character.id,
                ),
                CastingDecision(
                    candidate_targets=(target,),
                    final_target=target,
                    origin=CastingDecisionOrigin.CHARACTER_BINDING,
                ),
            )

        if payload.speaker_kind is ScriptSpeakerKind.ANONYMOUS:
            assert payload.anonymous_speaker_id is not None
            anonymous = require_row(
                self.store.get(
                    AnonymousSpeaker,
                    payload.anonymous_speaker_id,
                ),
                label="anonymous speaker",
            )
            known_ids = {
                item.anonymous_speaker_id
                for item in contract.anonymous_speakers
            }
            if (
                anonymous.novel_id != contract.novel_id
                or anonymous.lifecycle_state != "active"
                or anonymous.id not in known_ids
            ):
                raise NarrationScopeMismatch(
                    "anonymous speaker is outside the current script authority"
                )
            if anonymous.voice_version_id is None:
                raise InvalidNarrationState(
                    "current anonymous speaker has no resolved voice"
                )
            require_usable_voice(
                self.store,
                anonymous.voice_version_id,
                novel_id=contract.novel_id,
            )
            target = CastingTargetRef(
                kind=CastingTargetKind.ANONYMOUS_BINDING,
                anonymous_speaker_id=anonymous.id,
            )
            return (
                SpeakerRef(
                    SpeakerKind.ANONYMOUS,
                    anonymous_speaker_id=anonymous.id,
                ),
                CastingDecision(
                    candidate_targets=(target,),
                    final_target=target,
                    origin=CastingDecisionOrigin.ANONYMOUS_BINDING,
                ),
            )

        raise InvalidNarrationState(
            "group speaker correction has no frozen server-side casting authority"
        )

    def _approve(self, command: ScriptApiCommand) -> ScriptReviewResource:
        if self.session.in_transaction():
            raise RuntimeError("script command received a pre-opened transaction")
        with self.session.begin():
            return self._approve_in_transaction(
                command,
                require_existing_action=False,
            )

    def _approve_in_transaction(
        self,
        command: ScriptApiCommand,
        *,
        require_existing_action: bool,
    ) -> ScriptReviewResource:
        if type(command.payload) is not ApproveScriptRequest:
            raise NarrationServiceError("script approval payload is invalid")
        if command.version_id is None or command.idempotency_key is None:
            raise NarrationServiceError("script approval command is incomplete")
        payload = command.payload
        key = require_nonempty(
            command.idempotency_key,
            field="idempotency_key",
        )
        if len(key) > 128:
            raise NarrationServiceError("idempotency_key exceeds 128 characters")
        request_hash = self._approval_request_hash(
            command.version_id,
            payload,
        )
        existing = self.store.find_one(
            NarrationScriptReviewActionRecord,
            owner_id=LOCAL_OWNER_ID,
            workspace_id=LOCAL_WORKSPACE_ID,
            idempotency_key=key,
            for_update=True,
        )
        if existing is not None:
            return self._replay_approval(
                command.version_id,
                payload,
                key=key,
                request_hash=request_hash,
                action=existing,
            )

        prior_approval = self.store.find_one(
            NarrationScriptReviewActionRecord,
            request_id=payload.request_id,
            action_kind="approve",
            for_update=True,
        )
        if prior_approval is not None:
            raise IdempotencyConflict(
                "narration request was approved under another idempotency key"
            )

        request = require_row(
            self.store.get(NarrationRequest, payload.request_id, for_update=True),
            label="narration request",
        )
        # As with PATCH, the request lock is the visibility fence for a
        # same-key concurrent approval.  Re-read both the scoped key and the
        # per-request approval winner before interpreting queued/current state.
        existing = self.store.find_one(
            NarrationScriptReviewActionRecord,
            owner_id=LOCAL_OWNER_ID,
            workspace_id=LOCAL_WORKSPACE_ID,
            idempotency_key=key,
            for_update=True,
        )
        if existing is not None:
            return self._replay_approval(
                command.version_id,
                payload,
                key=key,
                request_hash=request_hash,
                action=existing,
            )
        prior_approval = self.store.find_one(
            NarrationScriptReviewActionRecord,
            request_id=payload.request_id,
            action_kind="approve",
            for_update=True,
        )
        if prior_approval is not None:
            raise IdempotencyConflict(
                "narration request was approved under another idempotency key"
            )
        if require_existing_action:
            raise self._storage_unavailable()
        request, _document, mutex = lock_request_document_mutex(
            self.store,
            request.id,
            expected_document_id=request.document_id,
            expected_novel_id=request.novel_id,
        )
        self._require_approval_request(
            request,
            version_id=command.version_id,
            payload=payload,
        )
        contract = load_script_contract(
            self.store,
            command.version_id,
            for_update=True,
        )
        self._require_approval_contract(
            contract,
            request=request,
            payload=payload,
        )
        if self._source_status(contract) is not ScriptSourceStatus.CURRENT:
            raise InvalidNarrationState(
                "only the current source and settings candidate can be approved"
            )

        policy = self._require_production_policy()
        try:
            queue = self._queue_factory(self.session)
            enqueue_segment_render = getattr(
                queue,
                "enqueue_segment_render",
                None,
            )
        except Exception as error:
            raise self._storage_unavailable() from error
        if not callable(enqueue_segment_render):
            raise self._storage_unavailable()
        settings_snapshot, _resolved_settings = (
            self._settings_snapshot_for_request(request)
        )
        lock_voice_authorities(
            self.store,
            mutex=mutex,
            contract=contract,
            settings_snapshot=settings_snapshot,
            include_narrator=any(
                segment.casting.final_target is not None
                and segment.casting.final_target.kind
                is CastingTargetKind.PROFILE
                for segment in contract.segments
            ),
        )

        approved_at = utc_now()
        self._freeze_current_review_version(
            request=request,
            mutex=mutex,
            version_id=command.version_id,
            approved_at=approved_at,
        )
        approved = load_script_contract(
            self.store,
            command.version_id,
            for_update=True,
        )
        if (
            approved.state is not ScriptVersionState.APPROVED
            or approved.approval is None
            or approved.approval.kind.value != "manual_after_review"
            or approved.approval.request_id != request.id
            or approved.approval.actor_type.value != "owner"
            or approved.approval.actor_id != LOCAL_OWNER_ACTOR_ID
            or approved.approval.approved_at != approved_at
        ):
            raise InvalidNarrationState(
                "manual script freeze did not produce exact owner approval evidence"
            )

        projection = produce_approved_request(
            self.store,
            queue,
            request=request,
            contract=approved,
            settings_snapshot=settings_snapshot,
            policy=policy,
            replayed=False,
        )
        if (
            projection.edition_id is None
            or projection.script_version_id != command.version_id
        ):
            raise InvalidNarrationState(
                "approved request did not create its exact Edition"
            )
        edition = require_row(
            self.store.get(
                NarrationEdition,
                projection.edition_id,
                for_update=True,
            ),
            label="narration Edition",
        )
        if (
            edition.owner_id != LOCAL_OWNER_ID
            or edition.workspace_id != LOCAL_WORKSPACE_ID
            or edition.novel_id != request.novel_id
            or edition.document_id != approved.document_id
            or edition.request_id != request.id
            or edition.script_version_id != approved.script_version_id
        ):
            raise NarrationScopeMismatch(
                "approved Edition provenance differs from the request"
            )

        action = NarrationScriptReviewActionRecord(
            id=self._review_action_id(key),
            owner_id=LOCAL_OWNER_ID,
            workspace_id=LOCAL_WORKSPACE_ID,
            novel_id=request.novel_id,
            request_id=request.id,
            request_allows_render=True,
            script_id=approved.script_id,
            parent_version_id=approved.script_version_id,
            result_version_id=approved.script_version_id,
            result_edition_id=edition.id,
            action_kind="approve",
            request_hash=request_hash,
            idempotency_key=key,
            request_version_before=payload.expected_request_version,
            request_version_after=payload.expected_request_version + 1,
            actor_type="owner",
            actor_id=LOCAL_OWNER_ACTOR_ID,
            created_at=approved_at,
        )
        self.store.add(action)
        self.store.flush()
        if request.version < action.request_version_after:
            raise NarrationCasConflict(
                "approved request did not advance its exact queued version"
            )
        return self._resource(approved)

    def _freeze_current_review_version(
        self,
        *,
        request: NarrationRequest,
        mutex: RequestDocumentMutex,
        version_id: UUID,
        approved_at: datetime,
    ) -> None:
        """Enforce request/document mutex -> current version before freeze."""

        if (
            mutex.request_id != request.id
            or mutex.request_version != request.version
            or mutex.current_review_version_id != version_id
            or request.current_review_version_id != version_id
        ):
            raise NarrationCasConflict(
                "manual freeze lost the request current-version contract"
            )
        freeze_script_version(
            self.store,
            version_id,
            request_id=request.id,
            actor_type="owner",
            actor_id=LOCAL_OWNER_ACTOR_ID,
            approved_at=approved_at,
        )

    @staticmethod
    def _review_action_id(idempotency_key: str) -> UUID:
        return uuid5(
            LOCAL_WORKSPACE_ID,
            f"narration-review-action:{LOCAL_OWNER_ID}:{idempotency_key}",
        )

    @staticmethod
    def _approval_request_hash(
        version_id: UUID,
        payload: ApproveScriptRequest,
    ) -> str:
        return canonical_sha256(
            {
                "contract_version": REVIEW_ACTION_REQUEST_VERSION,
                "action_kind": "approve",
                "request_id": str(payload.request_id),
                "script_version_id": str(version_id),
                "expected_request_version": payload.expected_request_version,
                "expected_version_number": payload.expected_version_number,
                "expected_immutable_hash": payload.expected_immutable_hash,
                "source_revision_id": str(payload.source_revision_id),
                "confirmed": payload.confirmed,
                "actor_id": LOCAL_OWNER_ACTOR_ID,
            }
        )

    @staticmethod
    def _require_approval_request(
        request: NarrationRequest,
        *,
        version_id: UUID,
        payload: ApproveScriptRequest,
    ) -> None:
        if (
            request.owner_id != LOCAL_OWNER_ID
            or request.workspace_id != LOCAL_WORKSPACE_ID
        ):
            raise NarrationScopeMismatch(
                "narration request is outside the fixed local scope"
            )
        if (
            request.intent == "analyze_only"
            or request.explicit_generation_intent_at is None
            or not request.explicit_generation_actor
            or request.allows_render is not True
        ):
            raise InvalidNarrationState(
                "manual approval requires an explicit generation request"
            )
        if request.state != "review_required":
            raise InvalidNarrationState(
                "manual approval requires request state review_required"
            )
        if request.version != payload.expected_request_version:
            raise NarrationCasConflict("narration request version changed")
        if (
            request.review_script_id is None
            or request.current_review_version_id is None
        ):
            raise InvalidNarrationState(
                "review_required request has no complete current script pointer"
            )
        if request.current_review_version_id != version_id:
            raise NarrationCasConflict(
                "narration request current review version changed"
            )
        if request.source_revision_id != payload.source_revision_id:
            raise NarrationCasConflict(
                "narration request source revision changed"
            )

    @staticmethod
    def _require_approval_contract(
        contract: NarrationScriptContract,
        *,
        request: NarrationRequest,
        payload: ApproveScriptRequest,
    ) -> None:
        if (
            contract.script_id != request.review_script_id
            or contract.script_version_id != request.current_review_version_id
            or contract.novel_id != request.novel_id
            or contract.document_id != request.document_id
            or contract.revision_id != request.source_revision_id
            or contract.source_content_hash != request.source_content_hash
            or contract.settings_fingerprint != request.settings_fingerprint
        ):
            raise NarrationScopeMismatch(
                "approval candidate is outside request provenance"
            )
        if contract.state is not ScriptVersionState.REVIEW_REQUIRED:
            raise InvalidNarrationState(
                "script version is not awaiting manual approval"
            )
        if contract.blocker_count:
            raise InvalidNarrationState(
                "script version still contains blocking review issues"
            )
        if contract.version_number != payload.expected_version_number:
            raise NarrationCasConflict("script version number changed")
        if contract.immutable_hash != payload.expected_immutable_hash:
            raise NarrationCasConflict("script immutable hash changed")
        if contract.revision_id != payload.source_revision_id:
            raise NarrationCasConflict("script source revision changed")

    def _replay_approval(
        self,
        version_id: UUID,
        payload: ApproveScriptRequest,
        *,
        key: str,
        request_hash: str,
        action: NarrationScriptReviewActionRecord,
    ) -> ScriptReviewResource:
        if (
            action.id != self._review_action_id(key)
            or action.owner_id != LOCAL_OWNER_ID
            or action.workspace_id != LOCAL_WORKSPACE_ID
            or action.request_id != payload.request_id
            or action.request_allows_render is not True
            or action.action_kind != "approve"
            or action.idempotency_key != key
            or action.request_hash != request_hash
            or action.parent_version_id != version_id
            or action.result_version_id != version_id
            or action.result_edition_id is None
            or action.request_version_before != payload.expected_request_version
            or action.request_version_after != payload.expected_request_version + 1
            or action.actor_type != "owner"
            or action.actor_id != LOCAL_OWNER_ACTOR_ID
        ):
            raise IdempotencyConflict(
                "review action idempotency key has another canonical input"
            )
        request = require_row(
            self.store.get(NarrationRequest, action.request_id, for_update=True),
            label="narration request",
        )
        contract = load_script_contract(
            self.store,
            version_id,
            for_update=True,
        )
        edition = require_row(
            self.store.get(
                NarrationEdition,
                action.result_edition_id,
                for_update=True,
            ),
            label="narration Edition",
        )
        if (
            request.owner_id != action.owner_id
            or request.workspace_id != action.workspace_id
            or request.novel_id != action.novel_id
            or request.intent == "analyze_only"
            or request.allows_render is not True
            or request.review_script_id != action.script_id
            or request.current_review_version_id != version_id
            or request.version < action.request_version_after
            or contract.state is not ScriptVersionState.APPROVED
            or contract.approval is None
            or contract.approval.kind.value != "manual_after_review"
            or contract.approval.request_id != request.id
            or contract.approval.actor_type.value != "owner"
            or contract.approval.actor_id != LOCAL_OWNER_ACTOR_ID
            or contract.approval.approved_at != action.created_at
            or contract.script_id != action.script_id
            or contract.novel_id != request.novel_id
            or contract.document_id != request.document_id
            or contract.revision_id != payload.source_revision_id
            or contract.immutable_hash != payload.expected_immutable_hash
            or contract.version_number != payload.expected_version_number
            or edition.owner_id != action.owner_id
            or edition.workspace_id != action.workspace_id
            or edition.novel_id != action.novel_id
            or edition.request_id != request.id
            or edition.script_version_id != version_id
        ):
            raise InvalidNarrationState(
                "approval replay differs from its immutable ledger"
            )
        return self._resource(contract)

    def _require_production_policy(self) -> NarrationProductionPolicy:
        provider = self._production_policy_provider
        if provider is None:
            raise self._storage_unavailable()
        try:
            policy = provider()
        except Exception as error:
            raise self._storage_unavailable() from error
        if type(policy) is not NarrationProductionPolicy:
            raise self._storage_unavailable()
        return policy

    def _get_script(self, command: ScriptApiCommand) -> ScriptReviewResource:
        if command.script_id is None:
            raise NarrationServiceError("script identity is missing")
        script = require_row(
            self.store.get(NarrationScript, command.script_id), label="script"
        )
        versions = self.store.find_all(
            NarrationScriptVersion,
            script_id=script.id,
            order_by=("version_number",),
        )
        if not versions:
            raise NarrationNotFound("script has no materialized version")
        return self._read_resource(versions[-1].id)

    def _get_version(self, command: ScriptApiCommand) -> ScriptReviewResource:
        if command.version_id is None:
            raise NarrationServiceError("script version identity is missing")
        return self._read_resource(command.version_id)

    def _read_resource(self, version_id: UUID) -> ScriptReviewResource:
        version = load_script_version_for_read(self.store, version_id)
        if isinstance(version, LegacyScriptVersionRead):
            raise ScriptApiFault(
                ScriptApiErrorCode.INVALID_STATE,
                "此脚本使用旧版存储结构，请重新分析后查看。",
            )
        return self._resource(version)

    def _current_settings_fingerprints(
        self,
        contract: NarrationScriptContract,
    ) -> frozenset[str]:
        """Return live settings plus its authorized force-review tightening.

        T4 may freeze a request-local snapshot by changing only
        ``blockers_only`` to ``always_review``.  That stricter immutable view
        remains current while every underlying live setting is unchanged.
        """

        settings = self.store.find_one(
            NovelNarrationSettings,
            novel_id=contract.novel_id,
        )
        if settings is None:
            return frozenset()
        overrides = self.store.find_all(
            NarrationScopeOverride,
            novel_id=contract.novel_id,
            order_by=("scope_kind", "scope_id"),
        )
        payload = snapshot_payload(
            CreateSettingsSnapshot(
                novel_id=contract.novel_id,
                settings_version=settings.version,
            ),
            settings,
            overrides,
        )
        fingerprints = {canonical_sha256(payload)}
        resolved = payload.get("resolved_settings")
        if (
            type(resolved) is dict
            and resolved.get("script_review_policy") == "blockers_only"
        ):
            tightened = canonical_payload(payload)
            tightened_resolved = tightened.get("resolved_settings")
            if type(tightened_resolved) is not dict:
                raise InvalidNarrationState(
                    "current narration settings payload is malformed"
                )
            tightened_resolved["script_review_policy"] = "always_review"
            fingerprints.add(canonical_sha256(tightened))
        return frozenset(fingerprints)

    def _source_status(
        self,
        contract: NarrationScriptContract,
    ) -> ScriptSourceStatus:
        working = self.store.find_one(
            DocumentWorkingCopy,
            document_id=contract.document_id,
        )
        if working is not None:
            source_current = working.content_hash == contract.source_content_hash
        else:
            revisions = self.store.find_all(
                DocumentRevision,
                document_id=contract.document_id,
                order_by=("revision_number",),
            )
            source_current = bool(
                revisions
                and revisions[-1].content_hash == contract.source_content_hash
            )
        if not source_current:
            return ScriptSourceStatus.WORKING_COPY_DIVERGED
        if (
            contract.settings_fingerprint
            not in self._current_settings_fingerprints(contract)
        ):
            return ScriptSourceStatus.SUPERSEDED
        return ScriptSourceStatus.CURRENT

    def _speaker_labels(
        self,
        contract: NarrationScriptContract,
    ) -> dict[UUID, str]:
        labels: dict[UUID, str] = {}
        character_ids = {
            segment.speaker.character_id
            for segment in contract.segments
            if segment.speaker.character_id is not None
        }
        anonymous_ids = {
            segment.speaker.anonymous_speaker_id
            for segment in contract.segments
            if segment.speaker.anonymous_speaker_id is not None
        }
        for character_id in character_ids:
            character = self.store.get(NovelCharacter, character_id)
            if (
                character is None
                or character.novel_id != contract.novel_id
            ):
                raise InvalidNarrationState(
                    "script character label is outside current authority"
                )
            labels[character_id] = character.name
        for anonymous_id in anonymous_ids:
            anonymous = self.store.get(AnonymousSpeaker, anonymous_id)
            if anonymous is None or anonymous.novel_id != contract.novel_id:
                raise InvalidNarrationState(
                    "script anonymous label is outside current authority"
                )
            labels[anonymous_id] = anonymous.display_name
        return labels

    def _production_policy_available(self) -> bool:
        provider = self._production_policy_provider
        if provider is None:
            return False
        try:
            return type(provider()) is NarrationProductionPolicy
        except Exception:
            return False

    def _mutable_request_for_contract(
        self,
        contract: NarrationScriptContract,
        *,
        source_status: ScriptSourceStatus,
    ) -> NarrationRequest | None:
        if (
            contract.state is not ScriptVersionState.REVIEW_REQUIRED
            or source_status is not ScriptSourceStatus.CURRENT
            or not self._production_policy_available()
        ):
            return None
        candidates = self.store.find_all(
            NarrationRequest,
            review_script_id=contract.script_id,
            current_review_version_id=contract.script_version_id,
        )
        eligible = [
            request
            for request in candidates
            if request.owner_id == LOCAL_OWNER_ID
            and request.workspace_id == LOCAL_WORKSPACE_ID
            and request.novel_id == contract.novel_id
            and request.document_id == contract.document_id
            and request.source_revision_id == contract.revision_id
            and request.source_content_hash == contract.source_content_hash
            and request.settings_fingerprint == contract.settings_fingerprint
            and request.effective_policy == contract.effective_policy.value
            and request.state == "review_required"
            and request.intent != "analyze_only"
            and request.explicit_generation_intent_at is not None
            and bool(request.explicit_generation_actor)
            and request.allows_render is True
        ]
        if len(eligible) != 1:
            # GET_SCRIPT has no request identity.  Ambiguous, historical, and
            # orphan candidates stay readable but never become mutable.
            return None
        return eligible[0]

    def _resource(
        self,
        contract: NarrationScriptContract,
    ) -> ScriptReviewResource:
        source_status = self._source_status(contract)
        mutable_request = self._mutable_request_for_contract(
            contract,
            source_status=source_status,
        )
        labels = self._speaker_labels(contract)
        issues_by_segment: dict[UUID, list[str]] = defaultdict(list)
        for issue in contract.issues:
            if issue.segment_id is not None:
                issues_by_segment[issue.segment_id].append(issue.code)
        segments: list[ScriptReviewSegmentResource] = []
        for segment in contract.segments:
            speaker = segment.speaker
            if speaker.kind is SpeakerKind.NARRATOR:
                speaker_label = "旁白"
            elif speaker.kind is SpeakerKind.CHARACTER:
                assert speaker.character_id is not None
                speaker_label = labels[speaker.character_id]
            elif speaker.kind is SpeakerKind.ANONYMOUS:
                assert speaker.anonymous_speaker_id is not None
                speaker_label = labels[speaker.anonymous_speaker_id]
            elif speaker.kind is SpeakerKind.GROUP:
                speaker_label = speaker.group_key or "群体声音"
            else:
                speaker_label = "待确认说话人"
            source_range = segment.source_range_utf16
            segments.append(
                ScriptReviewSegmentResource(
                    segment_id=segment.segment_id,
                    ordinal=segment.ordinal,
                    segment_kind=segment.segment_kind,
                    source_block_key=segment.source_block_key,
                    source_start_utf16=(source_range.start if source_range else None),
                    source_end_utf16=(
                        source_range.end_exclusive if source_range else None
                    ),
                    source_text=segment.source_text,
                    spoken_text=segment.spoken_text,
                    local_hash=segment.local_hash,
                    speaker_kind=speaker.kind.value,
                    speaker_label=speaker_label,
                    character_id=speaker.character_id,
                    anonymous_speaker_id=speaker.anonymous_speaker_id,
                    confidence=segment.confidence.value,
                    casting_state=(
                        ScriptCastingState.RESOLVED
                        if segment.casting.final_target is not None
                        or segment.casting.origin
                        is CastingDecisionOrigin.NOT_APPLICABLE
                        else ScriptCastingState.UNRESOLVED
                    ),
                    issue_codes=sorted(issues_by_segment[segment.segment_id]),
                    editable=(
                        mutable_request is not None
                        and segment.segment_kind in SOURCE_BOUND_SEGMENT_KINDS
                    ),
                )
            )
        allowed_actions: list[ScriptReviewAction] = []
        if mutable_request is not None:
            if any(segment.editable for segment in segments):
                allowed_actions.append(ScriptReviewAction.EDIT_SEGMENT)
            if contract.blocker_count == 0:
                allowed_actions.append(ScriptReviewAction.APPROVE)
        elif (
            contract.state.value == "review_required"
            and source_status is ScriptSourceStatus.WORKING_COPY_DIVERGED
        ):
            # continue_snapshot is a local UI acknowledgement.  The companion
            # action remains declarative until T4 installs the latest-source
            # orchestration callback; no T3 HTTP mutation claims success.
            allowed_actions = [
                ScriptReviewAction.CONTINUE_SNAPSHOT,
                ScriptReviewAction.REANALYZE_LATEST,
            ]
        approval = None
        if contract.approval is not None:
            approval = ScriptApprovalResource(
                kind=contract.approval.kind.value,
                request_id=contract.approval.request_id,
                actor_type=contract.approval.actor_type.value,
                actor_id=contract.approval.actor_id,
                approved_at=contract.approval.approved_at,
            )
        return ScriptReviewResource(
            script_id=contract.script_id,
            script_version_id=contract.script_version_id,
            novel_id=contract.novel_id,
            document_id=contract.document_id,
            revision_id=contract.revision_id,
            source_content_hash=contract.source_content_hash,
            immutable_hash=contract.immutable_hash,
            version_number=contract.version_number,
            state=contract.state.value,
            effective_policy=contract.effective_policy.value,
            source_status=source_status,
            warning_count=contract.warning_count,
            blocker_count=contract.blocker_count,
            allowed_actions=allowed_actions,
            segments=segments,
            issues=[
                ScriptReviewIssueResource(
                    code=issue.code,
                    severity=issue.severity.value,
                    segment_id=issue.segment_id,
                    evidence_summary=issue.evidence_summary,
                    evidence_digest=issue.evidence_digest,
                )
                for issue in contract.issues
            ],
            approval=approval,
        )


def build_script_api_backend(
    session: Session,
    *,
    production_policy_provider: ProductionPolicyProvider | None = None,
    queue_factory: RenderQueueFactory = SqlAlchemyRenderJobQueue,
) -> SqlAlchemyScriptApiBackend:
    return SqlAlchemyScriptApiBackend(
        session,
        production_policy_provider=production_policy_provider,
        queue_factory=queue_factory,
    )


__all__ = [
    "ProductionPolicyProvider",
    "RenderQueueFactory",
    "SqlAlchemyScriptApiBackend",
    "build_script_api_backend",
]
