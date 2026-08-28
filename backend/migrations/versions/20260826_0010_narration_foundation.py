"""Create the MOSS-TTS narration foundation schema.

Revision ID: 20260826_0010
Revises: 20260825_0009

This migration is a frozen PostgreSQL schema snapshot.  It never imports ORM
metadata and performs no model, media, network, or filesystem I/O.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260826_0010"
down_revision = "20260825_0009"
branch_labels = None
depends_on = None

LOCAL_OWNER = "29cf94d9-a5c9-54ec-912c-5dfff8738c4c"
LOCAL_WORKSPACE = "f0e2e632-bc99-52d2-9916-bb906aa4da6e"

CREATE_DDL = ("CREATE TABLE narration_requests (\n\tid UUID NOT NULL, \n\towner_id UUID NOT NULL, \n\tworkspace_id UUID NOT NULL, \n\tnovel_id UUID NOT NULL, \n\tdocument_id UUID, \n\tintent VARCHAR(20) NOT NULL, \n\trequest_hash VARCHAR(64) NOT NULL, \n\tidempotency_key VARCHAR(160) NOT NULL, \n\tsource_revision_id UUID, \n\tsource_content_hash VARCHAR(64), \n\tsettings_fingerprint VARCHAR(64) NOT NULL, \n\tforce_review BOOLEAN NOT NULL, \n\teffective_policy VARCHAR(24) NOT NULL, \n\tstate VARCHAR(24) NOT NULL, \n\tversion BIGINT NOT NULL, \n\tallows_edition BOOLEAN GENERATED ALWAYS AS (intent <> 'analyze_only') STORED NOT NULL, \n\tallows_render BOOLEAN GENERATED ALWAYS AS (intent <> 'analyze_only') STORED NOT NULL, \n\texplicit_generation_intent_at TIMESTAMP WITH TIME ZONE, \n\texplicit_generation_actor VARCHAR(120), \n\tcancel_requested_at TIMESTAMP WITH TIME ZONE, \n\tcancel_actor VARCHAR(120), \n\tcancel_reason_code VARCHAR(96), \n\tfailure_code VARCHAR(96), \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tcompleted_at TIMESTAMP WITH TIME ZONE, \n\tPRIMARY KEY (id), \n\tCONSTRAINT fk_narration_request_novel_scope FOREIGN KEY(novel_id, owner_id, workspace_id) REFERENCES novels (id, owner_id, workspace_id) ON DELETE CASCADE, \n\tCONSTRAINT fk_narration_request_document_scope FOREIGN KEY(document_id, novel_id) REFERENCES documents (id, novel_id), \n\tCONSTRAINT fk_narration_request_source_guard FOREIGN KEY(source_revision_id, document_id, source_content_hash) REFERENCES document_revisions (id, document_id, content_hash), \n\tCONSTRAINT uq_narration_request_idempotency UNIQUE (owner_id, workspace_id, idempotency_key), \n\tCONSTRAINT uq_narration_request_edition_guard UNIQUE (id, allows_edition), \n\tCONSTRAINT uq_narration_request_render_guard UNIQUE (id, allows_render), \n\tCONSTRAINT ck_narration_request_intent CHECK (intent IN ('analyze_only','create','update','batch')), \n\tCONSTRAINT ck_narration_request_state CHECK (state IN ('created','analyzing','analyzed','review_required','queued','rendering','partial_ready','ready','cancel_requested','cancelled','failed')), \n\tCONSTRAINT ck_narration_request_policy CHECK (effective_policy IN ('blockers_only','always_review')), \n\tCONSTRAINT ck_narration_request_generation_intent CHECK ((intent = 'analyze_only' AND explicit_generation_intent_at IS NULL AND explicit_generation_actor IS NULL) OR (intent IN ('create','update','batch') AND explicit_generation_intent_at IS NOT NULL AND explicit_generation_actor IS NOT NULL)), \n\tCONSTRAINT ck_narration_request_source_shape CHECK ((intent IN ('create','update') AND document_id IS NOT NULL AND source_revision_id IS NOT NULL AND source_content_hash IS NOT NULL) OR intent IN ('analyze_only','batch')), \n\tCONSTRAINT ck_narration_request_analyze_state CHECK (intent <> 'analyze_only' OR state NOT IN ('queued','rendering','partial_ready','ready'))\n)", 'CREATE INDEX ix_narration_requests_scope_state ON narration_requests (owner_id, workspace_id, novel_id, state)', "CREATE TABLE novel_narration_settings (\n\tid UUID NOT NULL, \n\tnovel_id UUID NOT NULL, \n\tnarrator_profile_id UUID, \n\tnarrator_version_id UUID, \n\tscript_review_policy VARCHAR(24) NOT NULL, \n\tanalysis_mode VARCHAR(24) NOT NULL, \n\tsettings_json JSONB NOT NULL, \n\tversion BIGINT NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_novel_narration_settings_novel UNIQUE (novel_id), \n\tCONSTRAINT ck_narration_settings_review_policy CHECK (script_review_policy IN ('blockers_only','always_review')), \n\tCONSTRAINT ck_narration_settings_analysis_mode CHECK (analysis_mode IN ('local_rules_only','cloud_assisted')), \n\tFOREIGN KEY(novel_id) REFERENCES novels (id) ON DELETE CASCADE\n)", 'CREATE TABLE narration_settings_snapshots (\n\tid UUID NOT NULL, \n\towner_id UUID NOT NULL, \n\tworkspace_id UUID NOT NULL, \n\tnovel_id UUID NOT NULL, \n\tschema_version VARCHAR(120) NOT NULL, \n\ttaxonomy_version VARCHAR(120) NOT NULL, \n\tfingerprint VARCHAR(64) NOT NULL, \n\tsnapshot_json JSONB NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_narration_settings_snapshot_fingerprint UNIQUE (owner_id, workspace_id, fingerprint), \n\tFOREIGN KEY(novel_id) REFERENCES novels (id) ON DELETE RESTRICT\n)', "CREATE TABLE narration_scope_overrides (\n\tid UUID NOT NULL, \n\tnovel_id UUID NOT NULL, \n\tscope_kind VARCHAR(16) NOT NULL, \n\tscope_id UUID NOT NULL, \n\tsettings_json JSONB NOT NULL, \n\tversion BIGINT NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_narration_scope_override UNIQUE (novel_id, scope_kind, scope_id), \n\tCONSTRAINT ck_narration_scope_override_kind CHECK (scope_kind IN ('volume','chapter')), \n\tFOREIGN KEY(novel_id) REFERENCES novels (id) ON DELETE CASCADE\n)", 'CREATE TABLE narration_cloud_consents (\n\tid UUID NOT NULL, \n\tnovel_id UUID NOT NULL, \n\tpurpose VARCHAR(80) NOT NULL, \n\tdata_scope VARCHAR(120) NOT NULL, \n\tnotice_version VARCHAR(120) NOT NULL, \n\tprovider_id VARCHAR(160), \n\tmodel_id VARCHAR(160), \n\tconfirmed_actor VARCHAR(120) NOT NULL, \n\tconfirmed_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\trevoked_at TIMESTAMP WITH TIME ZONE, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(novel_id) REFERENCES novels (id) ON DELETE RESTRICT\n)', 'CREATE TABLE voice_rights_records (\n\tid UUID NOT NULL, \n\towner_id UUID NOT NULL, \n\tworkspace_id UUID NOT NULL, \n\tnovel_id UUID, \n\tsource_kind VARCHAR(40) NOT NULL, \n\tsource_identifier VARCHAR(240) NOT NULL, \n\tnotice_version VARCHAR(120) NOT NULL, \n\tpurpose VARCHAR(120) NOT NULL, \n\tcommercial_use BOOLEAN NOT NULL, \n\tredistribution BOOLEAN NOT NULL, \n\tvoice_cloning BOOLEAN NOT NULL, \n\tsubject_consent_reference VARCHAR(240), \n\tconfirmed_actor VARCHAR(120) NOT NULL, \n\tconfirmed_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\texpires_at TIMESTAMP WITH TIME ZONE, \n\trisk_flags_json JSONB NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(novel_id) REFERENCES novels (id) ON DELETE RESTRICT\n)', "CREATE TABLE voice_profiles (\n\tid UUID NOT NULL, \n\towner_id UUID NOT NULL, \n\tworkspace_id UUID NOT NULL, \n\tnovel_id UUID, \n\tname VARCHAR(240) NOT NULL, \n\tcurrent_version_id UUID, \n\tstatus VARCHAR(24) NOT NULL, \n\tversion BIGINT NOT NULL, \n\tarchived_at TIMESTAMP WITH TIME ZONE, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_voice_profile_local_scope UNIQUE (id, owner_id, workspace_id), \n\tCONSTRAINT ck_voice_profile_status CHECK (status IN ('draft','active','archived','unavailable')), \n\tFOREIGN KEY(novel_id) REFERENCES novels (id) ON DELETE RESTRICT\n)", 'CREATE INDEX ix_voice_profiles_scope_novel ON voice_profiles (owner_id, workspace_id, novel_id, status)', "CREATE TABLE character_aliases (\n\tid UUID NOT NULL, \n\tnovel_id UUID NOT NULL, \n\tcharacter_id UUID NOT NULL, \n\talias VARCHAR(240) NOT NULL, \n\tnormalized_alias VARCHAR(240) NOT NULL, \n\tsource VARCHAR(40) NOT NULL, \n\tlifecycle_state VARCHAR(24) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT fk_character_alias_character_scope FOREIGN KEY(character_id, novel_id) REFERENCES novel_characters (id, novel_id) ON DELETE CASCADE, \n\tCONSTRAINT uq_character_alias_character_value UNIQUE (character_id, normalized_alias), \n\tCONSTRAINT ck_character_alias_lifecycle CHECK (lifecycle_state IN ('active','conflicted','archived'))\n)", 'CREATE INDEX ix_character_aliases_novel_normalized ON character_aliases (novel_id, normalized_alias, lifecycle_state)', 'CREATE TABLE generic_voice_pools (\n\tid UUID NOT NULL, \n\tnovel_id UUID NOT NULL, \n\tname VARCHAR(160) NOT NULL, \n\tversion_number INTEGER NOT NULL, \n\tstatus VARCHAR(24) NOT NULL, \n\tattributes_json JSONB NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_generic_voice_pool_version UNIQUE (novel_id, name, version_number), \n\tFOREIGN KEY(novel_id) REFERENCES novels (id) ON DELETE CASCADE\n)', 'CREATE TABLE pronunciation_profiles (\n\tid UUID NOT NULL, \n\tnovel_id UUID NOT NULL, \n\tversion_number INTEGER NOT NULL, \n\tfingerprint VARCHAR(64) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_pronunciation_profile_version UNIQUE (novel_id, version_number), \n\tCONSTRAINT uq_pronunciation_profile_fingerprint UNIQUE (novel_id, fingerprint), \n\tFOREIGN KEY(novel_id) REFERENCES novels (id) ON DELETE CASCADE\n)', 'CREATE TABLE narration_scripts (\n\tid UUID NOT NULL, \n\tnovel_id UUID NOT NULL, \n\tdocument_id UUID NOT NULL, \n\trevision_id UUID NOT NULL, \n\tcontent_hash VARCHAR(64) NOT NULL, \n\tversion BIGINT NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT fk_narration_script_document_scope FOREIGN KEY(document_id, novel_id) REFERENCES documents (id, novel_id), \n\tCONSTRAINT fk_narration_script_revision_guard FOREIGN KEY(revision_id, document_id, content_hash) REFERENCES document_revisions (id, document_id, content_hash), \n\tCONSTRAINT uq_narration_script_revision UNIQUE (document_id, revision_id), \n\tCONSTRAINT uq_narration_script_document_guard UNIQUE (id, document_id)\n)', 'CREATE TABLE background_resource_locks (\n\tresource_key VARCHAR(160) NOT NULL, \n\tlease_owner VARCHAR(160) NOT NULL, \n\tlease_token UUID NOT NULL, \n\tlease_generation BIGINT NOT NULL, \n\tlease_until TIMESTAMP WITH TIME ZONE NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tPRIMARY KEY (resource_key)\n)', 'CREATE TABLE narration_request_sources (\n\tid UUID NOT NULL, \n\trequest_id UUID NOT NULL, \n\tnovel_id UUID NOT NULL, \n\tdocument_id UUID NOT NULL, \n\trevision_id UUID NOT NULL, \n\tcontent_hash VARCHAR(64) NOT NULL, \n\tposition INTEGER NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT fk_narration_request_source_request FOREIGN KEY(request_id) REFERENCES narration_requests (id) ON DELETE CASCADE, \n\tCONSTRAINT fk_narration_request_source_document FOREIGN KEY(document_id, novel_id) REFERENCES documents (id, novel_id), \n\tCONSTRAINT fk_narration_request_source_revision FOREIGN KEY(revision_id, document_id, content_hash) REFERENCES document_revisions (id, document_id, content_hash), \n\tCONSTRAINT uq_narration_request_source_document UNIQUE (request_id, document_id), \n\tCONSTRAINT uq_narration_request_source_position UNIQUE (request_id, position)\n)', "CREATE TABLE voice_rights_events (\n\tid UUID NOT NULL, \n\trights_record_id UUID NOT NULL, \n\tevent_key VARCHAR(160) NOT NULL, \n\tevent_type VARCHAR(24) NOT NULL, \n\tactor VARCHAR(120) NOT NULL, \n\treason_code VARCHAR(96), \n\toccurred_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_voice_rights_event_key UNIQUE (rights_record_id, event_key), \n\tCONSTRAINT ck_voice_rights_event_type CHECK (event_type IN ('confirmed','revoked','expired','review_blocked')), \n\tFOREIGN KEY(rights_record_id) REFERENCES voice_rights_records (id) ON DELETE RESTRICT\n)", "CREATE TABLE voice_profile_versions (\n\tid UUID NOT NULL, \n\tprofile_id UUID NOT NULL, \n\towner_id UUID NOT NULL, \n\tworkspace_id UUID NOT NULL, \n\tversion_number INTEGER NOT NULL, \n\tsource_type VARCHAR(20) NOT NULL, \n\tstate VARCHAR(24) NOT NULL, \n\tprovider_id VARCHAR(160), \n\tmodel_id VARCHAR(160), \n\tmodel_revision VARCHAR(160), \n\tpreset_key VARCHAR(160), \n\treference_asset_id UUID, \n\tpreview_asset_id UUID, \n\trights_record_id UUID NOT NULL, \n\tdescription_digest_key_id VARCHAR(80), \n\tdescription_digest VARCHAR(64), \n\tlanguage VARCHAR(40) NOT NULL, \n\tseed BIGINT, \n\tparameters_json JSONB NOT NULL, \n\tfingerprint VARCHAR(64) NOT NULL, \n\tquality_state VARCHAR(24) NOT NULL, \n\tlocked_actor VARCHAR(120), \n\tlocked_at TIMESTAMP WITH TIME ZONE, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_voice_profile_version_number UNIQUE (profile_id, version_number), \n\tCONSTRAINT uq_voice_profile_version_profile_guard UNIQUE (id, profile_id), \n\tCONSTRAINT uq_voice_profile_version_fingerprint UNIQUE (owner_id, workspace_id, fingerprint), \n\tCONSTRAINT ck_voice_profile_version_source_type CHECK (source_type IN ('preset','uploaded','generated')), \n\tCONSTRAINT ck_voice_profile_version_state CHECK (state IN ('draft','preview_ready','locked','unavailable','deleted')), \n\tFOREIGN KEY(profile_id) REFERENCES voice_profiles (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(reference_asset_id) REFERENCES media_assets (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(preview_asset_id) REFERENCES media_assets (id) ON DELETE SET NULL, \n\tFOREIGN KEY(rights_record_id) REFERENCES voice_rights_records (id) ON DELETE RESTRICT\n)", "CREATE TABLE pronunciation_entries (\n\tid UUID NOT NULL, \n\tprofile_id UUID NOT NULL, \n\tscope_kind VARCHAR(16) NOT NULL, \n\tscope_id UUID NOT NULL, \n\tsource_text TEXT NOT NULL, \n\tnormalized_source TEXT NOT NULL, \n\tspoken_text TEXT NOT NULL, \n\tlanguage VARCHAR(40) NOT NULL, \n\tpriority INTEGER NOT NULL, \n\tsource_kind VARCHAR(24) NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_pronunciation_entry_match UNIQUE (profile_id, scope_kind, scope_id, normalized_source, priority), \n\tCONSTRAINT ck_pronunciation_entry_scope_kind CHECK (scope_kind IN ('novel','volume','chapter')), \n\tFOREIGN KEY(profile_id) REFERENCES pronunciation_profiles (id) ON DELETE CASCADE\n)", "CREATE TABLE narration_script_versions (\n\tid UUID NOT NULL, \n\tscript_id UUID NOT NULL, \n\tversion_number INTEGER NOT NULL, \n\tparent_version_id UUID, \n\tstate VARCHAR(24) NOT NULL, \n\tis_approved BOOLEAN GENERATED ALWAYS AS (state = 'approved') STORED NOT NULL, \n\tanalyzer_fingerprint VARCHAR(64) NOT NULL, \n\trules_fingerprint VARCHAR(64) NOT NULL, \n\tsettings_fingerprint VARCHAR(64) NOT NULL, \n\trequested_model_fingerprint VARCHAR(64), \n\tactual_model_fingerprint VARCHAR(64), \n\ttaxonomy_version VARCHAR(120) NOT NULL, \n\timmutable_hash VARCHAR(64) NOT NULL, \n\tidempotency_key VARCHAR(160) NOT NULL, \n\twarning_count INTEGER NOT NULL, \n\tblocker_count INTEGER NOT NULL, \n\tapproval_kind VARCHAR(32), \n\teffective_policy VARCHAR(24) NOT NULL, \n\tapproved_actor_type VARCHAR(24), \n\tapproved_actor_id VARCHAR(120), \n\tapproved_at TIMESTAMP WITH TIME ZONE, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_narration_script_version_number UNIQUE (script_id, version_number), \n\tCONSTRAINT uq_narration_script_version_script_guard UNIQUE (script_id, id), \n\tCONSTRAINT uq_narration_script_version_approved_guard UNIQUE (id, is_approved), \n\tCONSTRAINT uq_narration_script_version_idempotency UNIQUE (script_id, idempotency_key), \n\tCONSTRAINT ck_narration_script_version_state CHECK (state IN ('draft','review_required','approved','failed')), \n\tCONSTRAINT ck_narration_script_version_approval_kind CHECK (approval_kind IS NULL OR approval_kind IN ('auto_no_blockers','manual_after_review')), \n\tCONSTRAINT ck_narration_script_version_policy CHECK (effective_policy IN ('blockers_only','always_review')), \n\tCONSTRAINT ck_narration_script_version_counts CHECK (blocker_count >= 0 AND warning_count >= 0), \n\tCONSTRAINT ck_narration_script_version_approved_shape CHECK (state <> 'approved' OR (blocker_count = 0 AND approval_kind IS NOT NULL AND approved_at IS NOT NULL)), \n\tFOREIGN KEY(script_id) REFERENCES narration_scripts (id) ON DELETE CASCADE, \n\tFOREIGN KEY(parent_version_id) REFERENCES narration_script_versions (id) ON DELETE RESTRICT\n)", "CREATE TABLE background_jobs (\n\tid UUID NOT NULL, \n\towner_id UUID NOT NULL, \n\tworkspace_id UUID NOT NULL, \n\tnovel_id UUID, \n\trequest_id UUID, \n\trequest_allows_render BOOLEAN, \n\tjob_kind VARCHAR(80) NOT NULL, \n\tinput_hash VARCHAR(64) NOT NULL, \n\tidempotency_key VARCHAR(160) NOT NULL, \n\tresource_class VARCHAR(80) NOT NULL, \n\tbase_priority INTEGER NOT NULL, \n\tinteractive_priority INTEGER, \n\tinteractive_priority_expires_at TIMESTAMP WITH TIME ZONE, \n\tstate VARCHAR(24) NOT NULL, \n\tmax_attempts INTEGER NOT NULL, \n\tattempt_count INTEGER NOT NULL, \n\tnext_retry_at TIMESTAMP WITH TIME ZONE, \n\tcancel_requested_at TIMESTAMP WITH TIME ZONE, \n\tcancel_actor VARCHAR(120), \n\tcancel_reason_code VARCHAR(96), \n\tprogress_current INTEGER NOT NULL, \n\tprogress_total INTEGER, \n\terror_code VARCHAR(96), \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT fk_background_job_request_render_guard FOREIGN KEY(request_id, request_allows_render) REFERENCES narration_requests (id, allows_render), \n\tCONSTRAINT uq_background_job_idempotency UNIQUE (owner_id, workspace_id, idempotency_key), \n\tCONSTRAINT ck_background_job_state CHECK (state IN ('queued','running','retry_wait','succeeded','failed','dead_letter','cancel_requested','cancelled')), \n\tCONSTRAINT ck_background_job_render_guard CHECK (job_kind NOT IN ('narration.segment_render','narration.export') OR request_allows_render IS TRUE), \n\tCONSTRAINT ck_background_job_attempts CHECK (attempt_count >= 0 AND max_attempts > 0), \n\tFOREIGN KEY(novel_id) REFERENCES novels (id) ON DELETE CASCADE\n)", "CREATE TABLE voice_deletion_requests (\n\tid UUID NOT NULL, \n\towner_id UUID NOT NULL, \n\tworkspace_id UUID NOT NULL, \n\tvoice_profile_id UUID NOT NULL, \n\tcommand VARCHAR(48) NOT NULL, \n\tstate VARCHAR(40) NOT NULL, \n\timpact_digest_key_id VARCHAR(80) NOT NULL, \n\timpact_digest VARCHAR(64) NOT NULL, \n\trequested_actor VARCHAR(120) NOT NULL, \n\trequested_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tconfirmed_actor VARCHAR(120), \n\tconfirmed_at TIMESTAMP WITH TIME ZONE, \n\tfailure_code VARCHAR(96), \n\tPRIMARY KEY (id), \n\tCONSTRAINT ck_voice_deletion_request_state CHECK (state IN ('requested','live_deleting','live_deleted_backup_pending','completed','failed')), \n\tFOREIGN KEY(voice_profile_id) REFERENCES voice_profiles (id) ON DELETE RESTRICT\n)", "CREATE TABLE character_voice_bindings (\n\tid UUID NOT NULL, \n\tnovel_id UUID NOT NULL, \n\tcharacter_id UUID NOT NULL, \n\tprofile_id UUID, \n\tvoice_version_id UUID, \n\tbinding_policy VARCHAR(20) NOT NULL, \n\tlanguage VARCHAR(40) NOT NULL, \n\tparameters_json JSONB NOT NULL, \n\tversion BIGINT NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT fk_character_voice_binding_character FOREIGN KEY(character_id, novel_id) REFERENCES novel_characters (id, novel_id) ON DELETE CASCADE, \n\tCONSTRAINT fk_character_voice_binding_version FOREIGN KEY(voice_version_id, profile_id) REFERENCES voice_profile_versions (id, profile_id), \n\tCONSTRAINT uq_character_voice_binding_character UNIQUE (character_id), \n\tCONSTRAINT ck_character_voice_binding_policy CHECK (binding_policy IN ('dedicated','inherited','unset')), \n\tFOREIGN KEY(profile_id) REFERENCES voice_profiles (id) ON DELETE RESTRICT\n)", 'CREATE TABLE generic_voice_slots (\n\tid UUID NOT NULL, \n\tpool_id UUID NOT NULL, \n\tslot_key VARCHAR(80) NOT NULL, \n\tposition INTEGER NOT NULL, \n\tvoice_version_id UUID NOT NULL, \n\tlabels_json JSONB NOT NULL, \n\tenabled BOOLEAN NOT NULL, \n\tpriority INTEGER NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_generic_voice_slot_position UNIQUE (pool_id, position), \n\tCONSTRAINT uq_generic_voice_slot_key UNIQUE (pool_id, slot_key), \n\tFOREIGN KEY(pool_id) REFERENCES generic_voice_pools (id) ON DELETE CASCADE, \n\tFOREIGN KEY(voice_version_id) REFERENCES voice_profile_versions (id) ON DELETE RESTRICT\n)', 'CREATE TABLE narration_scenes (\n\tid UUID NOT NULL, \n\tscript_version_id UUID NOT NULL, \n\tordinal INTEGER NOT NULL, \n\tsource_start INTEGER, \n\tsource_end INTEGER, \n\tboundary_source VARCHAR(40) NOT NULL, \n\tlocal_hash VARCHAR(64) NOT NULL, \n\ttitle VARCHAR(240), \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_narration_scene_ordinal UNIQUE (script_version_id, ordinal), \n\tCONSTRAINT uq_narration_scene_version_guard UNIQUE (id, script_version_id), \n\tFOREIGN KEY(script_version_id) REFERENCES narration_script_versions (id) ON DELETE CASCADE\n)', "CREATE TABLE background_job_attempts (\n\tid UUID NOT NULL, \n\tjob_id UUID NOT NULL, \n\tattempt_number INTEGER NOT NULL, \n\tretry_kind VARCHAR(16) NOT NULL, \n\tmanual_actor VARCHAR(120), \n\tmanual_reason VARCHAR(240), \n\tlease_owner VARCHAR(160) NOT NULL, \n\tlease_token UUID NOT NULL, \n\tlease_generation BIGINT NOT NULL, \n\tlease_until TIMESTAMP WITH TIME ZONE NOT NULL, \n\theartbeat_at TIMESTAMP WITH TIME ZONE, \n\tstarted_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tcompleted_at TIMESTAMP WITH TIME ZONE, \n\terror_classification VARCHAR(24), \n\terror_code VARCHAR(96), \n\tactual_result_digest VARCHAR(64), \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_background_job_attempt_number UNIQUE (job_id, attempt_number), \n\tCONSTRAINT ck_background_job_attempt_retry_kind CHECK (retry_kind IN ('initial','automatic','manual')), \n\tCONSTRAINT ck_background_job_attempt_error_class CHECK (error_classification IS NULL OR error_classification IN ('retryable','non_retryable','cancelled','security_failure')), \n\tFOREIGN KEY(job_id) REFERENCES background_jobs (id) ON DELETE CASCADE\n)", "CREATE TABLE narration_editions (\n\tid UUID NOT NULL, \n\towner_id UUID NOT NULL, \n\tworkspace_id UUID NOT NULL, \n\tnovel_id UUID NOT NULL, \n\tdocument_id UUID NOT NULL, \n\trequest_id UUID NOT NULL, \n\trequest_allows_edition BOOLEAN NOT NULL, \n\tscript_version_id UUID NOT NULL, \n\tscript_is_approved BOOLEAN NOT NULL, \n\tsettings_snapshot_id UUID NOT NULL, \n\tpronunciation_profile_id UUID, \n\ttts_fingerprint VARCHAR(64) NOT NULL, \n\ttokenizer_fingerprint VARCHAR(64) NOT NULL, \n\tnormalizer_fingerprint VARCHAR(64) NOT NULL, \n\tpostprocess_fingerprint VARCHAR(64) NOT NULL, \n\tcontext_mode VARCHAR(32) NOT NULL, \n\tbuffer_policy_version VARCHAR(120) NOT NULL, \n\tedition_fingerprint VARCHAR(64) NOT NULL, \n\tstate VARCHAR(32) NOT NULL, \n\tunavailable_reason VARCHAR(96), \n\tcreated_actor VARCHAR(120) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT fk_narration_edition_request_guard FOREIGN KEY(request_id, request_allows_edition) REFERENCES narration_requests (id, allows_edition), \n\tCONSTRAINT fk_narration_edition_approved_guard FOREIGN KEY(script_version_id, script_is_approved) REFERENCES narration_script_versions (id, is_approved), \n\tCONSTRAINT uq_narration_edition_fingerprint UNIQUE (owner_id, workspace_id, edition_fingerprint), \n\tCONSTRAINT uq_narration_edition_script_guard UNIQUE (id, script_version_id), \n\tCONSTRAINT ck_narration_edition_guards CHECK (request_allows_edition IS TRUE AND script_is_approved IS TRUE), \n\tCONSTRAINT ck_narration_edition_context_mode CHECK (context_mode = 'independent_segment'), \n\tFOREIGN KEY(novel_id) REFERENCES novels (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(document_id) REFERENCES documents (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(settings_snapshot_id) REFERENCES narration_settings_snapshots (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(pronunciation_profile_id) REFERENCES pronunciation_profiles (id) ON DELETE RESTRICT\n)", "CREATE TABLE narration_segment_renders (\n\tid UUID NOT NULL, \n\towner_id UUID NOT NULL, \n\tworkspace_id UUID NOT NULL, \n\trequest_id UUID NOT NULL, \n\trequest_allows_render BOOLEAN NOT NULL, \n\trender_fingerprint VARCHAR(64) NOT NULL, \n\tcanonical_input_json JSONB NOT NULL, \n\tvoice_version_id UUID NOT NULL, \n\tmodel_fingerprint VARCHAR(64) NOT NULL, \n\tpostprocess_fingerprint VARCHAR(64) NOT NULL, \n\tstate VARCHAR(24) NOT NULL, \n\tsource_job_id UUID, \n\tduration_ms BIGINT, \n\taudio_validation_json JSONB NOT NULL, \n\tready_at TIMESTAMP WITH TIME ZONE, \n\tPRIMARY KEY (id), \n\tCONSTRAINT fk_narration_segment_render_request_guard FOREIGN KEY(request_id, request_allows_render) REFERENCES narration_requests (id, allows_render), \n\tCONSTRAINT uq_narration_segment_render_fingerprint UNIQUE (owner_id, workspace_id, render_fingerprint), \n\tCONSTRAINT ck_narration_segment_render_request_guard CHECK (request_allows_render IS TRUE), \n\tCONSTRAINT ck_narration_segment_render_state CHECK (state IN ('pending','rendering','ready','failed','cancelled','quarantined')), \n\tFOREIGN KEY(voice_version_id) REFERENCES voice_profile_versions (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(source_job_id) REFERENCES background_jobs (id) ON DELETE SET NULL\n)", 'CREATE TABLE asset_tombstones (\n\tid UUID NOT NULL, \n\towner_id UUID NOT NULL, \n\tworkspace_id UUID NOT NULL, \n\toriginal_asset_id UUID NOT NULL, \n\tdeletion_request_id UUID, \n\tdigest_key_id VARCHAR(80) NOT NULL, \n\tdigest VARCHAR(64) NOT NULL, \n\treason_code VARCHAR(96) NOT NULL, \n\tdeleted_actor VARCHAR(120) NOT NULL, \n\tdeleted_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(deletion_request_id) REFERENCES voice_deletion_requests (id) ON DELETE RESTRICT\n)', 'CREATE TABLE voice_casting_rules (\n\tid UUID NOT NULL, \n\tnovel_id UUID NOT NULL, \n\tpriority INTEGER NOT NULL, \n\tversion_number INTEGER NOT NULL, \n\tcondition_json JSONB NOT NULL, \n\ttarget_pool_id UUID, \n\ttarget_slot_id UUID, \n\taction VARCHAR(40) NOT NULL, \n\tarchived_at TIMESTAMP WITH TIME ZONE, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_voice_casting_rule_priority UNIQUE (novel_id, priority, version_number), \n\tFOREIGN KEY(novel_id) REFERENCES novels (id) ON DELETE CASCADE, \n\tFOREIGN KEY(target_pool_id) REFERENCES generic_voice_pools (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(target_slot_id) REFERENCES generic_voice_slots (id) ON DELETE RESTRICT\n)', "CREATE TABLE anonymous_speakers (\n\tid UUID NOT NULL, \n\tnovel_id UUID NOT NULL, \n\tstable_key_algorithm VARCHAR(120) NOT NULL, \n\tstable_key VARCHAR(160) NOT NULL, \n\tdisplay_name VARCHAR(160) NOT NULL, \n\tscope_kind VARCHAR(16) NOT NULL, \n\tscope_id UUID, \n\tinferred_json JSONB NOT NULL, \n\tconfidence VARCHAR(16) NOT NULL, \n\tslot_id UUID, \n\tvoice_version_id UUID, \n\tpromoted_character_id UUID, \n\tlifecycle_state VARCHAR(24) NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_anonymous_speaker_stable_key UNIQUE (novel_id, stable_key_algorithm, stable_key), \n\tCONSTRAINT ck_anonymous_speaker_scope_kind CHECK (scope_kind IN ('scene','chapter','novel')), \n\tCONSTRAINT ck_anonymous_speaker_confidence CHECK (confidence IN ('high','medium','low','unknown')), \n\tFOREIGN KEY(novel_id) REFERENCES novels (id) ON DELETE CASCADE, \n\tFOREIGN KEY(slot_id) REFERENCES generic_voice_slots (id) ON DELETE SET NULL, \n\tFOREIGN KEY(voice_version_id) REFERENCES voice_profile_versions (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(promoted_character_id) REFERENCES novel_characters (id) ON DELETE SET NULL\n)", 'CREATE TABLE model_run_records (\n\tid UUID NOT NULL, \n\tattempt_id UUID NOT NULL, \n\trequested_provider_id VARCHAR(160), \n\trequested_model_id VARCHAR(160) NOT NULL, \n\trequested_revision VARCHAR(160), \n\tactual_provider_id VARCHAR(160), \n\tactual_model_id VARCHAR(160), \n\tactual_revision VARCHAR(160), \n\tmodel_fingerprint VARCHAR(64), \n\tparameters_digest VARCHAR(64) NOT NULL, \n\tinput_digest_key_id VARCHAR(80) NOT NULL, \n\tinput_digest VARCHAR(64) NOT NULL, \n\toutput_digest VARCHAR(64), \n\tduration_ms BIGINT, \n\tprovider_request_id VARCHAR(240), \n\tresult_classification VARCHAR(40) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(attempt_id) REFERENCES background_job_attempts (id) ON DELETE RESTRICT\n)', "CREATE TABLE narration_render_assets (\n\tid UUID NOT NULL, \n\trender_id UUID NOT NULL, \n\tasset_id UUID NOT NULL, \n\trole VARCHAR(16) NOT NULL, \n\tactual_sha256 VARCHAR(64) NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_narration_render_asset_role UNIQUE (render_id, role), \n\tCONSTRAINT uq_narration_render_asset_asset UNIQUE (asset_id), \n\tCONSTRAINT ck_narration_render_asset_role CHECK (role IN ('master','playback')), \n\tFOREIGN KEY(render_id) REFERENCES narration_segment_renders (id) ON DELETE CASCADE, \n\tFOREIGN KEY(asset_id) REFERENCES media_assets (id) ON DELETE RESTRICT\n)", 'CREATE TABLE narration_exports (\n\tid UUID NOT NULL, \n\tedition_id UUID NOT NULL, \n\trequest_id UUID NOT NULL, \n\trequest_allows_render BOOLEAN NOT NULL, \n\texport_fingerprint VARCHAR(64) NOT NULL, \n\tasset_id UUID NOT NULL, \n\tstate VARCHAR(24) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT fk_narration_export_request_guard FOREIGN KEY(request_id, request_allows_render) REFERENCES narration_requests (id, allows_render), \n\tCONSTRAINT uq_narration_export_fingerprint UNIQUE (edition_id, export_fingerprint), \n\tCONSTRAINT uq_narration_export_asset UNIQUE (asset_id), \n\tCONSTRAINT ck_narration_export_request_guard CHECK (request_allows_render IS TRUE), \n\tFOREIGN KEY(edition_id) REFERENCES narration_editions (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(asset_id) REFERENCES media_assets (id) ON DELETE RESTRICT\n)', "CREATE TABLE narration_manifests (\n\tid UUID NOT NULL, \n\tedition_id UUID NOT NULL, \n\tmanifest_revision INTEGER NOT NULL, \n\tschema_version VARCHAR(120) NOT NULL, \n\tcanonical_json JSONB NOT NULL, \n\tetag_sha256 VARCHAR(64) NOT NULL, \n\tready_prefix_count INTEGER NOT NULL, \n\tready_ranges_json JSONB NOT NULL, \n\ttotal_duration_ms BIGINT NOT NULL, \n\tstatus VARCHAR(24) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_narration_manifest_revision UNIQUE (edition_id, manifest_revision), \n\tCONSTRAINT uq_narration_manifest_state_guard UNIQUE (id, edition_id, manifest_revision), \n\tCONSTRAINT ck_narration_manifest_revision CHECK (manifest_revision >= 1), \n\tCONSTRAINT ck_narration_manifest_schema CHECK (schema_version = 'narration-manifest/2.0'), \n\tFOREIGN KEY(edition_id) REFERENCES narration_editions (id) ON DELETE RESTRICT\n)", 'CREATE TABLE document_narration_state (\n\tid UUID NOT NULL, \n\towner_id UUID NOT NULL, \n\tworkspace_id UUID NOT NULL, \n\tdocument_id UUID NOT NULL, \n\tscript_id UUID, \n\tcurrent_script_version_id UUID, \n\tcurrent_edition_id UUID, \n\tversion BIGINT NOT NULL, \n\tswitched_actor VARCHAR(120) NOT NULL, \n\tswitched_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_document_narration_state_document UNIQUE (owner_id, workspace_id, document_id), \n\tCONSTRAINT fk_document_narration_state_script_version FOREIGN KEY(current_script_version_id, script_id) REFERENCES narration_script_versions (id, script_id), \n\tCONSTRAINT fk_document_narration_state_script FOREIGN KEY(script_id, document_id) REFERENCES narration_scripts (id, document_id), \n\tFOREIGN KEY(document_id) REFERENCES documents (id) ON DELETE CASCADE, \n\tFOREIGN KEY(current_edition_id) REFERENCES narration_editions (id) ON DELETE RESTRICT\n)', "CREATE TABLE narration_segments (\n\tid UUID NOT NULL, \n\tscript_version_id UUID NOT NULL, \n\tscene_id UUID, \n\tordinal INTEGER NOT NULL, \n\tsegment_kind VARCHAR(40) NOT NULL, \n\tparagraph_ordinal INTEGER, \n\tsource_block_key VARCHAR(160) NOT NULL, \n\tsource_start_utf16 INTEGER, \n\tsource_end_utf16 INTEGER, \n\tsource_text TEXT NOT NULL, \n\tspoken_text TEXT NOT NULL, \n\tlocal_hash VARCHAR(64) NOT NULL, \n\tanchor_before_hash VARCHAR(64), \n\tanchor_after_hash VARCHAR(64), \n\tspeaker_kind VARCHAR(16) NOT NULL, \n\tcharacter_id UUID, \n\tanonymous_speaker_id UUID, \n\tcasting_json JSONB NOT NULL, \n\tevidence_json JSONB NOT NULL, \n\tconfidence VARCHAR(16) NOT NULL, \n\temotion VARCHAR(24), \n\texpression VARCHAR(24), \n\tpause_before_ms INTEGER NOT NULL, \n\tpause_after_ms INTEGER NOT NULL, \n\tmanual_override BOOLEAN NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT fk_narration_segment_scene_guard FOREIGN KEY(scene_id, script_version_id) REFERENCES narration_scenes (id, script_version_id), \n\tCONSTRAINT uq_narration_segment_ordinal UNIQUE (script_version_id, ordinal), \n\tCONSTRAINT uq_narration_segment_version_guard UNIQUE (id, script_version_id), \n\tCONSTRAINT ck_narration_segment_speaker_kind CHECK (speaker_kind IN ('narrator','character','anonymous','group','unknown')), \n\tCONSTRAINT ck_narration_segment_confidence CHECK (confidence IN ('high','medium','low','unknown')), \n\tCONSTRAINT ck_narration_segment_source_range CHECK (source_start_utf16 IS NULL OR source_end_utf16 >= source_start_utf16), \n\tFOREIGN KEY(character_id) REFERENCES novel_characters (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(anonymous_speaker_id) REFERENCES anonymous_speakers (id) ON DELETE RESTRICT\n)", 'CREATE TABLE narration_edition_state (\n\tedition_id UUID NOT NULL, \n\tcurrent_manifest_id UUID, \n\tcurrent_manifest_revision INTEGER, \n\tversion BIGINT NOT NULL, \n\tupdated_actor VARCHAR(120) NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tPRIMARY KEY (edition_id), \n\tCONSTRAINT fk_narration_edition_state_manifest FOREIGN KEY(current_manifest_id, edition_id, current_manifest_revision) REFERENCES narration_manifests (id, edition_id, manifest_revision), \n\tCONSTRAINT uq_narration_edition_state_edition UNIQUE (edition_id), \n\tFOREIGN KEY(edition_id) REFERENCES narration_editions (id) ON DELETE CASCADE\n)', "CREATE TABLE narration_script_issues (\n\tid UUID NOT NULL, \n\tscript_version_id UUID NOT NULL, \n\tsegment_id UUID, \n\ttaxonomy_version VARCHAR(120) NOT NULL, \n\tcode VARCHAR(96) NOT NULL, \n\tseverity VARCHAR(16) NOT NULL, \n\tevidence_summary VARCHAR(500), \n\tevidence_digest VARCHAR(64), \n\tPRIMARY KEY (id), \n\tCONSTRAINT fk_narration_issue_segment_guard FOREIGN KEY(segment_id, script_version_id) REFERENCES narration_segments (id, script_version_id), \n\tCONSTRAINT ck_narration_issue_severity CHECK (severity IN ('warning','blocker')), \n\tCONSTRAINT ck_narration_issue_taxonomy_code CHECK ((severity='warning' AND code IN ('W_SPEAKER_MEDIUM_CONFIDENCE','W_NEW_ANONYMOUS_SPEAKER','W_GENERIC_VOICE_FALLBACK','W_MANUAL_OVERRIDE_INHERITED','W_PRONUNCIATION_SOFT_FALLBACK','W_CLOUD_ASSISTED_USED','W_SCENE_BOUNDARY_MEDIUM_CONFIDENCE')) OR (severity='blocker' AND code IN ('B_SPEAKER_UNKNOWN','B_SPEAKER_LOW_CONFIDENCE','B_CHARACTER_ALIAS_CONFLICT','B_CHARACTER_REFERENCE_INVALID','B_ANONYMOUS_IDENTITY_CONFLICT','B_CASTING_TARGET_UNRESOLVED','B_VOICE_MISSING','B_VOICE_VERSION_UNAVAILABLE','B_VOICE_RIGHTS_UNAVAILABLE','B_PRONUNCIATION_HARD_CONFLICT','B_CLOUD_DECISION_UNAVAILABLE'))), \n\tFOREIGN KEY(script_version_id) REFERENCES narration_script_versions (id) ON DELETE CASCADE\n)", 'CREATE TABLE narration_edition_segments (\n\tid UUID NOT NULL, \n\tedition_id UUID NOT NULL, \n\tscript_version_id UUID NOT NULL, \n\tsegment_id UUID NOT NULL, \n\tordinal INTEGER NOT NULL, \n\tslot_id UUID, \n\tprofile_id UUID NOT NULL, \n\tvoice_version_id UUID NOT NULL, \n\tresolution_json JSONB NOT NULL, \n\trender_fingerprint VARCHAR(64) NOT NULL, \n\trender_state VARCHAR(24) NOT NULL, \n\tgap_after_ms INTEGER NOT NULL, \n\tfailure_code VARCHAR(96), \n\tPRIMARY KEY (id), \n\tCONSTRAINT fk_narration_edition_segment_edition FOREIGN KEY(edition_id, script_version_id) REFERENCES narration_editions (id, script_version_id), \n\tCONSTRAINT fk_narration_edition_segment_script FOREIGN KEY(segment_id, script_version_id) REFERENCES narration_segments (id, script_version_id), \n\tCONSTRAINT uq_narration_edition_segment_ordinal UNIQUE (edition_id, ordinal), \n\tCONSTRAINT uq_narration_edition_segment_edition_guard UNIQUE (id, edition_id), \n\tFOREIGN KEY(slot_id) REFERENCES generic_voice_slots (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(profile_id) REFERENCES voice_profiles (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(voice_version_id) REFERENCES voice_profile_versions (id) ON DELETE RESTRICT\n)', 'CREATE TABLE narration_manifest_segments (\n\tid UUID NOT NULL, \n\tmanifest_id UUID NOT NULL, \n\tedition_id UUID NOT NULL, \n\tedition_segment_id UUID NOT NULL, \n\tordinal INTEGER NOT NULL, \n\trender_id UUID, \n\trender_state VARCHAR(24) NOT NULL, \n\tduration_ms BIGINT, \n\tgap_after_ms INTEGER NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_narration_manifest_segment_ordinal UNIQUE (manifest_id, ordinal), \n\tCONSTRAINT fk_narration_manifest_segment_edition FOREIGN KEY(edition_segment_id, edition_id) REFERENCES narration_edition_segments (id, edition_id), \n\tFOREIGN KEY(manifest_id) REFERENCES narration_manifests (id) ON DELETE CASCADE, \n\tFOREIGN KEY(render_id) REFERENCES narration_segment_renders (id) ON DELETE RESTRICT\n)', 'CREATE TABLE narration_playback_progress (\n\tid UUID NOT NULL, \n\towner_id UUID NOT NULL, \n\tworkspace_id UUID NOT NULL, \n\tprofile_id VARCHAR(160) NOT NULL, \n\tedition_id UUID NOT NULL, \n\tmanifest_revision INTEGER NOT NULL, \n\tedition_segment_id UUID NOT NULL, \n\toffset_ms BIGINT NOT NULL, \n\tlast_legal_start_ordinal INTEGER NOT NULL, \n\tplayback_rate_millis INTEGER NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_narration_playback_progress UNIQUE (owner_id, workspace_id, profile_id, edition_id), \n\tFOREIGN KEY(edition_id) REFERENCES narration_editions (id) ON DELETE CASCADE, \n\tFOREIGN KEY(edition_segment_id) REFERENCES narration_edition_segments (id) ON DELETE CASCADE\n)')

NEW_TABLES = ('narration_requests', 'novel_narration_settings', 'narration_settings_snapshots', 'narration_scope_overrides', 'narration_cloud_consents', 'voice_rights_records', 'voice_profiles', 'character_aliases', 'generic_voice_pools', 'pronunciation_profiles', 'narration_scripts', 'background_resource_locks', 'narration_request_sources', 'voice_rights_events', 'voice_profile_versions', 'pronunciation_entries', 'narration_script_versions', 'background_jobs', 'voice_deletion_requests', 'character_voice_bindings', 'generic_voice_slots', 'narration_scenes', 'background_job_attempts', 'narration_editions', 'narration_segment_renders', 'asset_tombstones', 'voice_casting_rules', 'anonymous_speakers', 'model_run_records', 'narration_render_assets', 'narration_exports', 'narration_manifests', 'document_narration_state', 'narration_segments', 'narration_edition_state', 'narration_script_issues', 'narration_edition_segments', 'narration_manifest_segments', 'narration_playback_progress')

IMMUTABLE_TABLES = (
    "narration_request_sources", "narration_settings_snapshots",
    "voice_rights_records", "voice_rights_events", "pronunciation_profiles",
    "pronunciation_entries", "narration_scripts", "model_run_records", "narration_render_assets",
    "narration_manifests", "narration_manifest_segments", "asset_tombstones",
)

def _preflight() -> None:
    op.execute(sa.text("""
    DO $$ BEGIN
      IF EXISTS (
        SELECT 1 FROM media_assets m JOIN document_revisions r ON r.id=m.source_revision_id
        JOIN documents d ON d.id=r.document_id WHERE d.novel_id<>m.novel_id
      ) THEN RAISE EXCEPTION 'T1-D preflight: media source revision scope mismatch'; END IF;
      IF EXISTS (
        SELECT 1 FROM novels n JOIN media_assets m ON m.id=n.cover_asset_id
        WHERE m.novel_id<>n.id
      ) THEN RAISE EXCEPTION 'T1-D preflight: cover asset scope mismatch'; END IF;
    END $$;
    """))

def _extend_existing() -> None:
    owner_default = sa.text(f"'{LOCAL_OWNER}'::uuid")
    workspace_default = sa.text(f"'{LOCAL_WORKSPACE}'::uuid")
    op.add_column("novels", sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False, server_default=owner_default))
    op.add_column("novels", sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False, server_default=workspace_default))
    op.create_unique_constraint("uq_novel_local_scope", "novels", ["id","owner_id","workspace_id"])
    op.create_index("ix_novels_local_scope", "novels", ["owner_id","workspace_id"])
    op.create_check_constraint("ck_novel_fixed_local_scope", "novels", f"owner_id='{LOCAL_OWNER}'::uuid AND workspace_id='{LOCAL_WORKSPACE}'::uuid")
    op.create_unique_constraint("uq_volume_novel_scope", "volumes", ["id","novel_id"])
    op.create_unique_constraint("uq_document_novel_scope", "documents", ["id","novel_id"])
    op.create_unique_constraint("uq_document_revision_document_scope", "document_revisions", ["id","document_id"])
    op.create_unique_constraint("uq_document_revision_source_guard", "document_revisions", ["id","document_id","content_hash"])
    op.create_index("uq_document_revision_tts_snapshot", "document_revisions", ["document_id","content_hash","source"], unique=True, postgresql_where=sa.text("source='tts_snapshot'"))
    op.create_unique_constraint("uq_novel_character_novel_scope", "novel_characters", ["id","novel_id"])
    op.add_column("media_assets", sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False, server_default=owner_default))
    op.add_column("media_assets", sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False, server_default=workspace_default))
    op.add_column("media_assets", sa.Column("asset_class", sa.String(32)))
    op.add_column("media_assets", sa.Column("mime_type", sa.String(120)))
    op.add_column("media_assets", sa.Column("byte_size", sa.BigInteger()))
    op.add_column("media_assets", sa.Column("duration_ms", sa.BigInteger()))
    op.add_column("media_assets", sa.Column("sample_rate", sa.Integer()))
    op.add_column("media_assets", sa.Column("channels", sa.Integer()))
    op.add_column("media_assets", sa.Column("storage_backend", sa.String(40), nullable=False, server_default="local"))
    op.add_column("media_assets", sa.Column("state", sa.String(24), nullable=False, server_default="ready"))
    op.add_column("media_assets", sa.Column("retention_policy", sa.String(40), nullable=False, server_default="legacy"))
    op.add_column("media_assets", sa.Column("checksum_algorithm", sa.String(20), nullable=False, server_default="sha256"))
    op.add_column("media_assets", sa.Column("validation_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")))
    for name, typ in (("verified_at",sa.DateTime(timezone=True)),("last_accessed_at",sa.DateTime(timezone=True)),("expires_at",sa.DateTime(timezone=True)),("deleted_at",sa.DateTime(timezone=True)),("gc_marked_at",sa.DateTime(timezone=True))):
        op.add_column("media_assets", sa.Column(name, typ))
    op.add_column("media_assets", sa.Column("gc_generation", sa.BigInteger(), nullable=False, server_default="0"))
    op.alter_column("media_assets", "novel_id", existing_type=postgresql.UUID(as_uuid=True), nullable=True)
    op.create_unique_constraint("uq_media_asset_local_scope", "media_assets", ["id","owner_id","workspace_id"])
    op.create_index("ix_media_assets_scope_class_state", "media_assets", ["owner_id","workspace_id","asset_class","state"])
    op.create_check_constraint("ck_media_asset_fixed_local_scope", "media_assets", f"owner_id='{LOCAL_OWNER}'::uuid AND workspace_id='{LOCAL_WORKSPACE}'::uuid")
    op.create_check_constraint("ck_media_asset_class", "media_assets", "asset_class IS NULL OR asset_class IN ('source','voice_reference','preview','segment_master','segment_playback','export')")
    op.create_check_constraint("ck_media_asset_tts_class_required", "media_assets", "(kind NOT LIKE 'narration_%' AND kind NOT LIKE 'tts_%') OR asset_class IS NOT NULL")
    op.create_check_constraint("ck_media_asset_state", "media_assets", "state IN ('staging','ready','quarantined','deleting','deleted')")
    op.create_check_constraint("ck_media_asset_byte_size", "media_assets", "byte_size IS NULL OR byte_size>=0")
    op.create_check_constraint("ck_media_asset_duration", "media_assets", "duration_ms IS NULL OR duration_ms>=0")

def _create_triggers() -> None:
    op.execute(sa.text("""
    CREATE FUNCTION narration_reject_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN RAISE EXCEPTION 'immutable narration row: %', TG_TABLE_NAME; END $$;
    CREATE FUNCTION narration_guard_approved_child() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE parent_id uuid; BEGIN
      parent_id := CASE WHEN TG_OP='DELETE' THEN OLD.script_version_id ELSE NEW.script_version_id END;
      IF EXISTS (SELECT 1 FROM narration_script_versions WHERE id=parent_id AND state='approved')
      THEN RAISE EXCEPTION 'approved narration script children are immutable'; END IF;
      IF TG_OP='UPDATE' AND EXISTS
        (SELECT 1 FROM narration_script_versions WHERE id=OLD.script_version_id AND state='approved')
      THEN RAISE EXCEPTION 'approved narration script children are immutable'; END IF;
      RETURN COALESCE(NEW,OLD);
    END $$;
    CREATE FUNCTION narration_guard_script_version() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF OLD.state='approved' THEN RAISE EXCEPTION 'approved narration script is immutable'; END IF;
      IF TG_OP='DELETE' THEN RETURN OLD; END IF;
      IF (to_jsonb(OLD)-ARRAY['state','is_approved','approval_kind','approval_request_id',
                              'approval_request_allows_edition','approved_actor_type',
                              'approved_actor_id','approved_at']) <>
         (to_jsonb(NEW)-ARRAY['state','is_approved','approval_kind','approval_request_id',
                              'approval_request_allows_edition','approved_actor_type',
                              'approved_actor_id','approved_at'])
      THEN RAISE EXCEPTION 'narration script version canonical identity is immutable'; END IF;
      RETURN NEW;
    END $$;
    CREATE FUNCTION narration_guard_voice_version() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF OLD.state='locked' THEN RAISE EXCEPTION 'locked voice version is immutable'; END IF;
      IF OLD.state='deleted' THEN RAISE EXCEPTION 'deleted voice version is immutable'; END IF;
      IF TG_OP='DELETE' THEN RETURN OLD; END IF;
      IF (to_jsonb(OLD)-ARRAY['state','quality_state','locked_actor','locked_at']) <>
         (to_jsonb(NEW)-ARRAY['state','quality_state','locked_actor','locked_at'])
      THEN RAISE EXCEPTION 'voice profile version canonical identity is immutable'; END IF;
      RETURN NEW;
    END $$;
    CREATE FUNCTION narration_guard_ready_render() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF OLD.state='ready' THEN RAISE EXCEPTION 'ready render is immutable'; END IF;
      IF OLD.state IN ('cancelled','quarantined')
      THEN RAISE EXCEPTION 'cancelled/quarantined render is immutable'; END IF;
      IF TG_OP='DELETE' THEN RETURN OLD; END IF;
      IF (to_jsonb(OLD)-ARRAY['state','duration_ms','audio_validation_json','ready_at']) <>
         (to_jsonb(NEW)-ARRAY['state','duration_ms','audio_validation_json','ready_at'])
      THEN RAISE EXCEPTION 'render canonical input and scope are immutable'; END IF;
      IF OLD.state<>NEW.state AND NOT (
        (OLD.state='pending' AND NEW.state IN ('rendering','ready','failed','cancelled','quarantined')) OR
        (OLD.state='rendering' AND NEW.state IN ('ready','failed','cancelled','quarantined')))
      THEN RAISE EXCEPTION 'invalid render state transition'; END IF;
      RETURN NEW;
    END $$;
    CREATE FUNCTION narration_guard_request() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP='INSERT' THEN
        IF NEW.state<>'created' THEN RAISE EXCEPTION 'narration request must be inserted in created state'; END IF;
        RETURN NEW;
      END IF;
      IF (to_jsonb(OLD)-ARRAY['state','version','allows_edition','allows_render',
                              'cancel_requested_at','cancel_actor','cancel_reason_code',
                              'failure_code','updated_at','completed_at']) <>
         (to_jsonb(NEW)-ARRAY['state','version','allows_edition','allows_render',
                              'cancel_requested_at','cancel_actor','cancel_reason_code',
                              'failure_code','updated_at','completed_at'])
      THEN RAISE EXCEPTION 'narration request canonical input is immutable'; END IF;
      IF OLD.intent='batch' AND OLD.state='created' AND NEW.state='analyzing' AND NOT EXISTS
        (SELECT 1 FROM narration_request_sources rs WHERE rs.request_id=OLD.id)
      THEN RAISE EXCEPTION 'batch request requires at least one frozen source before analysis'; END IF;
      IF OLD.state<>NEW.state AND NOT (
        (OLD.state='created' AND NEW.state IN ('analyzing','cancel_requested')) OR
        (OLD.state='analyzing' AND NEW.state IN ('analyzed','review_required','queued','cancel_requested','failed')) OR
        (OLD.state='review_required' AND NEW.state IN ('analyzing','queued','cancel_requested','failed')) OR
        (OLD.state='queued' AND NEW.state IN ('rendering','cancel_requested','failed')) OR
        (OLD.state='rendering' AND NEW.state IN ('partial_ready','ready','cancel_requested','failed')) OR
        (OLD.state='partial_ready' AND NEW.state IN ('ready','cancel_requested','failed')) OR
        (OLD.state='cancel_requested' AND NEW.state='cancelled'))
      THEN RAISE EXCEPTION 'invalid narration request state transition'; END IF; RETURN NEW; END $$;
    CREATE FUNCTION narration_guard_job() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP='INSERT' THEN
        IF NEW.state<>'queued' THEN RAISE EXCEPTION 'background job must be inserted queued'; END IF;
        RETURN NEW;
      END IF;
      IF (to_jsonb(OLD)-ARRAY['interactive_priority','interactive_priority_expires_at','state','attempt_count',
                                  'next_retry_at','cancel_requested_at','cancel_actor','cancel_reason_code',
                                  'progress_current','progress_total','error_code','updated_at']) <>
             (to_jsonb(NEW)-ARRAY['interactive_priority','interactive_priority_expires_at','state','attempt_count',
                                  'next_retry_at','cancel_requested_at','cancel_actor','cancel_reason_code',
                                  'progress_current','progress_total','error_code','updated_at'])
      THEN RAISE EXCEPTION 'background job canonical input is immutable'; END IF;
      IF OLD.state<>NEW.state AND NOT (
        (OLD.state='queued' AND NEW.state IN ('running','cancelled')) OR
        (OLD.state='running' AND NEW.state IN ('retry_wait','failed','dead_letter','cancel_requested','succeeded')) OR
        (OLD.state='retry_wait' AND NEW.state='queued') OR
        (OLD.state='cancel_requested' AND NEW.state='cancelled') OR
        (OLD.state IN ('failed','dead_letter') AND NEW.state='queued'))
      THEN RAISE EXCEPTION 'invalid background job state transition'; END IF; RETURN NEW; END $$;
    CREATE FUNCTION narration_guard_voice_deletion() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP='INSERT' THEN
        IF NEW.state<>'requested' OR NEW.confirmed_actor IS NOT NULL OR NEW.confirmed_at IS NOT NULL
        THEN RAISE EXCEPTION 'voice deletion must be inserted unconfirmed/requested'; END IF;
        RETURN NEW;
      END IF;
      IF TG_OP='DELETE' THEN RAISE EXCEPTION 'voice deletion request cannot be deleted'; END IF;
      IF OLD.state='completed' THEN RAISE EXCEPTION 'completed voice deletion is immutable'; END IF;
      IF OLD.confirmed_actor IS NOT NULL AND
         (OLD.confirmed_actor,OLD.confirmed_at) IS DISTINCT FROM (NEW.confirmed_actor,NEW.confirmed_at)
      THEN RAISE EXCEPTION 'voice deletion confirmation is write-once'; END IF;
      IF (NEW.confirmed_actor IS NULL)<>(NEW.confirmed_at IS NULL)
      THEN RAISE EXCEPTION 'voice deletion confirmation actor/time must be paired'; END IF;
      IF (to_jsonb(OLD)-ARRAY['state','confirmed_actor','confirmed_at','failure_code']) <>
             (to_jsonb(NEW)-ARRAY['state','confirmed_actor','confirmed_at','failure_code'])
      THEN RAISE EXCEPTION 'voice deletion canonical request is immutable'; END IF;
      IF OLD.state<>NEW.state AND NOT (
      (OLD.state='requested' AND NEW.state IN ('live_deleting','failed')) OR
      (OLD.state='live_deleting' AND NEW.state IN ('live_deleted_backup_pending','failed')) OR
      (OLD.state='live_deleted_backup_pending' AND NEW.state IN ('completed','failed')) OR
      (OLD.state='failed' AND NEW.state='live_deleting'))
      THEN RAISE EXCEPTION 'invalid voice deletion state transition'; END IF; RETURN NEW; END $$;
    CREATE FUNCTION narration_guard_cas() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE old_data jsonb := to_jsonb(OLD); new_data jsonb := to_jsonb(NEW); BEGIN
      IF NEW.version<>OLD.version+1 THEN RAISE EXCEPTION 'narration CAS version must increment by one'; END IF;
      IF TG_TABLE_NAME='novel_narration_settings' AND
         (old_data->'id',old_data->'novel_id') IS DISTINCT FROM (new_data->'id',new_data->'novel_id')
      THEN RAISE EXCEPTION 'narration settings identity is immutable'; END IF;
      IF TG_TABLE_NAME='narration_scope_overrides' AND
         (old_data->'id',old_data->'novel_id',old_data->'scope_kind',old_data->'scope_id') IS DISTINCT FROM
         (new_data->'id',new_data->'novel_id',new_data->'scope_kind',new_data->'scope_id')
      THEN RAISE EXCEPTION 'narration override identity is immutable'; END IF;
      IF TG_TABLE_NAME='voice_profiles' AND
         (old_data->'id',old_data->'owner_id',old_data->'workspace_id',old_data->'novel_id') IS DISTINCT FROM
         (new_data->'id',new_data->'owner_id',new_data->'workspace_id',new_data->'novel_id')
      THEN RAISE EXCEPTION 'voice profile scope identity is immutable'; END IF;
      IF TG_TABLE_NAME='character_voice_bindings' AND
         (old_data->'id',old_data->'novel_id',old_data->'character_id') IS DISTINCT FROM
         (new_data->'id',new_data->'novel_id',new_data->'character_id')
      THEN RAISE EXCEPTION 'character voice binding identity is immutable'; END IF;
      IF TG_TABLE_NAME='narration_edition_state' AND old_data->'edition_id' IS DISTINCT FROM new_data->'edition_id'
      THEN RAISE EXCEPTION 'edition state identity is immutable'; END IF;
      IF TG_TABLE_NAME='document_narration_state' AND
         (old_data->'id',old_data->'owner_id',old_data->'workspace_id',old_data->'document_id') IS DISTINCT FROM
         (new_data->'id',new_data->'owner_id',new_data->'workspace_id',new_data->'document_id')
      THEN RAISE EXCEPTION 'document narration state identity is immutable'; END IF;
      RETURN NEW;
    END $$;
    CREATE FUNCTION narration_guard_consent() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN IF (to_jsonb(OLD)-'revoked_at')<>(to_jsonb(NEW)-'revoked_at') OR OLD.revoked_at IS NOT NULL OR NEW.revoked_at IS NULL
      THEN RAISE EXCEPTION 'cloud consent only permits one revocation'; END IF; RETURN NEW; END $$;
    CREATE FUNCTION narration_guard_attempt() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP='DELETE' OR OLD.completed_at IS NOT NULL
      THEN RAISE EXCEPTION 'completed attempt is immutable'; END IF;
      IF (to_jsonb(OLD)-ARRAY['heartbeat_at','lease_until','completed_at','error_classification','error_code','actual_result_digest']) <>
         (to_jsonb(NEW)-ARRAY['heartbeat_at','lease_until','completed_at','error_classification','error_code','actual_result_digest'])
      THEN RAISE EXCEPTION 'attempt identity and fencing tuple are immutable'; END IF;
      RETURN NEW;
    END $$;
    CREATE FUNCTION narration_guard_edition() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN IF OLD.state='unavailable' THEN RAISE EXCEPTION 'unavailable edition is immutable'; END IF;
      IF (to_jsonb(OLD)-ARRAY['state','unavailable_reason'])<>(to_jsonb(NEW)-ARRAY['state','unavailable_reason'])
      THEN RAISE EXCEPTION 'edition production input is immutable'; END IF;
      IF OLD.state<>NEW.state AND NOT (
        (OLD.state='created' AND NEW.state IN ('rendering','partial_ready','ready','unavailable')) OR
        (OLD.state='rendering' AND NEW.state IN ('partial_ready','ready','unavailable')) OR
        (OLD.state='partial_ready' AND NEW.state IN ('ready','unavailable')) OR
        (OLD.state='ready' AND NEW.state='unavailable'))
      THEN RAISE EXCEPTION 'invalid edition state transition'; END IF;
      RETURN NEW; END $$;
    CREATE FUNCTION narration_guard_generated_media() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN IF NEW.state='ready' AND NEW.asset_class IN ('segment_master','segment_playback','export') AND NOT (
      (NEW.asset_class IN ('segment_master','segment_playback') AND EXISTS
        (SELECT 1 FROM narration_render_assets ra JOIN narration_segment_renders r ON r.id=ra.render_id
         WHERE ra.asset_id=NEW.id AND r.state='ready')) OR
      (NEW.asset_class='export' AND EXISTS
        (SELECT 1 FROM narration_exports e WHERE e.asset_id=NEW.id AND e.state='ready')))
      THEN RAISE EXCEPTION 'ready generated media requires a guarded render/export link'; END IF; RETURN NEW; END $$;
    CREATE FUNCTION narration_guard_ready_render_assets() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN IF NEW.state='ready' AND NOT EXISTS
      (SELECT 1 FROM narration_render_assets ra JOIN media_assets m ON m.id=ra.asset_id
       WHERE ra.render_id=NEW.id AND ra.role='master' AND m.state='ready'
         AND m.asset_class='segment_master' AND m.content_hash=ra.actual_sha256)
      THEN RAISE EXCEPTION 'ready render requires a verified master asset'; END IF; RETURN NEW; END $$;
    CREATE FUNCTION narration_guard_media_identity() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE row_data jsonb; BEGIN
      row_data := CASE WHEN TG_OP='DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END;
      IF TG_OP IN ('UPDATE','DELETE') AND OLD.state='deleted'
      THEN RAISE EXCEPTION 'deleted media asset is immutable'; END IF;
      IF (row_data->>'source_revision_id') IS NOT NULL AND NOT EXISTS
        (SELECT 1 FROM document_revisions r JOIN documents d ON d.id=r.document_id
         WHERE r.id=(row_data->>'source_revision_id')::uuid AND d.novel_id=(row_data->>'novel_id')::uuid)
      THEN RAISE EXCEPTION 'media source revision novel mismatch'; END IF;
      IF TG_OP IN ('UPDATE','DELETE') AND EXISTS
        (SELECT 1 FROM narration_render_assets ra WHERE ra.asset_id=OLD.id
         UNION ALL SELECT 1 FROM narration_exports ex WHERE ex.asset_id=OLD.id
         UNION ALL SELECT 1 FROM voice_profile_versions vv
           WHERE vv.state='locked' AND (vv.reference_asset_id=OLD.id OR vv.preview_asset_id=OLD.id)
         UNION ALL SELECT 1 FROM novels n WHERE n.cover_asset_id=OLD.id)
      THEN
        IF TG_OP='DELETE' OR
           (to_jsonb(OLD)-ARRAY['verified_at','last_accessed_at','validation_json']) <>
           (to_jsonb(NEW)-ARRAY['verified_at','last_accessed_at','validation_json'])
        THEN RAISE EXCEPTION 'referenced media identity is immutable'; END IF;
      END IF;
      RETURN COALESCE(NEW,OLD);
    END $$;
    CREATE FUNCTION narration_guard_novel_cover() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN IF NEW.cover_asset_id IS NOT NULL AND NOT EXISTS
      (SELECT 1 FROM media_assets m WHERE m.id=NEW.cover_asset_id AND m.novel_id=NEW.id)
      THEN RAISE EXCEPTION 'novel cover asset scope mismatch'; END IF; RETURN NEW; END $$;
    CREATE FUNCTION narration_guard_voice_pool() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN IF TG_OP='DELETE' THEN RAISE EXCEPTION 'versioned generic voice pool cannot be deleted'; END IF;
      IF (OLD.id,OLD.novel_id,OLD.name,OLD.version_number) IS DISTINCT FROM
         (NEW.id,NEW.novel_id,NEW.name,NEW.version_number)
      THEN RAISE EXCEPTION 'generic voice pool identity is immutable'; END IF; RETURN NEW; END $$;
    CREATE FUNCTION narration_guard_anonymous_identity() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN IF (OLD.novel_id,OLD.stable_key_algorithm,OLD.stable_key,OLD.scope_kind,OLD.scope_id) IS DISTINCT FROM
             (NEW.novel_id,NEW.stable_key_algorithm,NEW.stable_key,NEW.scope_kind,NEW.scope_id)
      THEN RAISE EXCEPTION 'anonymous speaker identity is immutable'; END IF; RETURN NEW; END $$;
    CREATE FUNCTION narration_guard_character_novel() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN IF OLD.novel_id IS DISTINCT FROM NEW.novel_id AND
      (EXISTS (SELECT 1 FROM narration_segments s WHERE s.character_id=OLD.id) OR
       EXISTS (SELECT 1 FROM anonymous_speakers a WHERE a.promoted_character_id=OLD.id))
      THEN RAISE EXCEPTION 'referenced character novel identity is immutable'; END IF; RETURN NEW; END $$;
    CREATE FUNCTION narration_guard_volume_scope_parent() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF (TG_OP='DELETE' OR OLD.novel_id IS DISTINCT FROM NEW.novel_id) AND
        (EXISTS (SELECT 1 FROM narration_scope_overrides o
                 WHERE o.scope_kind='volume' AND o.scope_id=OLD.id) OR
         EXISTS (SELECT 1 FROM pronunciation_entries p
                 WHERE p.scope_kind='volume' AND p.scope_id=OLD.id))
      THEN RAISE EXCEPTION 'referenced volume narration scope is immutable'; END IF;
      IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW;
    END $$;
    CREATE FUNCTION narration_guard_document_scope_parent() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF (TG_OP='DELETE' OR OLD.novel_id IS DISTINCT FROM NEW.novel_id) AND
        (EXISTS (SELECT 1 FROM narration_scope_overrides o
                 WHERE o.scope_kind='chapter' AND o.scope_id=OLD.id) OR
         EXISTS (SELECT 1 FROM pronunciation_entries p
                 WHERE p.scope_kind='chapter' AND p.scope_id=OLD.id) OR
         EXISTS (SELECT 1 FROM anonymous_speakers a
                 WHERE a.scope_kind='chapter' AND a.scope_id=OLD.id))
      THEN RAISE EXCEPTION 'referenced document narration scope is immutable'; END IF;
      IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW;
    END $$;
    CREATE FUNCTION narration_guard_scene_scope_parent() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF (TG_OP='DELETE' OR OLD.script_version_id IS DISTINCT FROM NEW.script_version_id) AND
         EXISTS (SELECT 1 FROM anonymous_speakers a
                 WHERE a.scope_kind='scene' AND a.scope_id=OLD.id)
      THEN RAISE EXCEPTION 'referenced scene narration scope is immutable'; END IF;
      IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW;
    END $$;
    CREATE FUNCTION narration_guard_revision_media_parent() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF EXISTS (SELECT 1 FROM media_assets m WHERE m.source_revision_id=OLD.id) AND
         (TG_OP='DELETE' OR (OLD.id,OLD.document_id,OLD.content_hash) IS DISTINCT FROM
                            (NEW.id,NEW.document_id,NEW.content_hash))
      THEN RAISE EXCEPTION 'media source revision identity is immutable'; END IF;
      IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW;
    END $$;
    CREATE FUNCTION narration_validate_scope() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE row_data jsonb := to_jsonb(NEW);
            expected_owner uuid := '29cf94d9-a5c9-54ec-912c-5dfff8738c4c'::uuid;
            expected_workspace uuid := 'f0e2e632-bc99-52d2-9916-bb906aa4da6e'::uuid;
    BEGIN
      IF row_data ? 'owner_id' AND
        ((row_data->>'owner_id')::uuid<>expected_owner OR (row_data->>'workspace_id')::uuid<>expected_workspace)
      THEN RAISE EXCEPTION 'narration fixed local scope mismatch'; END IF;
      IF TG_TABLE_NAME='narration_request_sources' AND NOT EXISTS
        (SELECT 1 FROM narration_requests r WHERE r.id=(row_data->>'request_id')::uuid
         AND r.novel_id=(row_data->>'novel_id')::uuid AND r.intent='batch'
         AND r.state='created')
      THEN RAISE EXCEPTION 'request source requires a created batch request in the same novel'; END IF;
      IF TG_TABLE_NAME='narration_scope_overrides' AND
        (((row_data->>'scope_kind')='volume' AND NOT EXISTS
            (SELECT 1 FROM volumes v WHERE v.id=(row_data->>'scope_id')::uuid AND v.novel_id=(row_data->>'novel_id')::uuid)) OR
         ((row_data->>'scope_kind')='chapter' AND NOT EXISTS
            (SELECT 1 FROM documents d WHERE d.id=(row_data->>'scope_id')::uuid AND d.novel_id=(row_data->>'novel_id')::uuid)))
      THEN RAISE EXCEPTION 'narration override scope mismatch'; END IF;
      IF TG_TABLE_NAME='voice_profile_versions' AND NOT EXISTS
        (SELECT 1 FROM voice_profiles p WHERE p.id=(row_data->>'profile_id')::uuid
         AND p.owner_id=(row_data->>'owner_id')::uuid AND p.workspace_id=(row_data->>'workspace_id')::uuid)
      THEN RAISE EXCEPTION 'voice version scope mismatch'; END IF;
      IF TG_TABLE_NAME='voice_profile_versions' AND NOT EXISTS
        (SELECT 1 FROM voice_rights_records rr JOIN voice_profiles p ON p.id=(row_data->>'profile_id')::uuid
         WHERE rr.id=(row_data->>'rights_record_id')::uuid AND rr.owner_id=(row_data->>'owner_id')::uuid
           AND rr.workspace_id=(row_data->>'workspace_id')::uuid AND rr.novel_id IS NOT DISTINCT FROM p.novel_id)
      THEN RAISE EXCEPTION 'voice rights scope mismatch'; END IF;
      IF TG_TABLE_NAME='voice_profile_versions' AND (row_data->>'source_type')='uploaded' AND NOT EXISTS
        (SELECT 1 FROM voice_rights_records rr WHERE rr.id=(row_data->>'rights_record_id')::uuid
         AND rr.voice_cloning IS TRUE)
      THEN RAISE EXCEPTION 'uploaded voice requires cloning rights'; END IF;
      IF TG_TABLE_NAME='voice_profile_versions' AND row_data->>'reference_asset_id' IS NOT NULL AND NOT EXISTS
        (SELECT 1 FROM media_assets m JOIN voice_profiles p ON p.id=(row_data->>'profile_id')::uuid
         WHERE m.id=(row_data->>'reference_asset_id')::uuid AND m.owner_id=(row_data->>'owner_id')::uuid
           AND m.workspace_id=(row_data->>'workspace_id')::uuid AND m.novel_id IS NOT DISTINCT FROM p.novel_id
           AND m.asset_class='voice_reference' AND m.state='ready')
      THEN RAISE EXCEPTION 'voice reference asset scope/class/state mismatch'; END IF;
      IF TG_TABLE_NAME='voice_profile_versions' AND row_data->>'preview_asset_id' IS NOT NULL AND NOT EXISTS
        (SELECT 1 FROM media_assets m JOIN voice_profiles p ON p.id=(row_data->>'profile_id')::uuid
         WHERE m.id=(row_data->>'preview_asset_id')::uuid AND m.owner_id=(row_data->>'owner_id')::uuid
           AND m.workspace_id=(row_data->>'workspace_id')::uuid AND m.novel_id IS NOT DISTINCT FROM p.novel_id
           AND m.asset_class='preview' AND m.state='ready')
      THEN RAISE EXCEPTION 'voice preview asset scope/class/state mismatch'; END IF;
      IF TG_TABLE_NAME='narration_script_versions' AND row_data->>'approval_request_id' IS NOT NULL AND NOT EXISTS
        (SELECT 1 FROM narration_requests r JOIN narration_scripts ns ON ns.id=(row_data->>'script_id')::uuid
         WHERE r.id=(row_data->>'approval_request_id')::uuid AND r.novel_id=ns.novel_id
           AND r.allows_edition IS TRUE AND r.effective_policy=(row_data->>'effective_policy'))
      THEN RAISE EXCEPTION 'script approval request scope mismatch'; END IF;
      IF TG_TABLE_NAME='character_voice_bindings' AND row_data->>'profile_id' IS NOT NULL AND NOT EXISTS
        (SELECT 1 FROM voice_profiles p WHERE p.id=(row_data->>'profile_id')::uuid
         AND (p.novel_id IS NULL OR p.novel_id=(row_data->>'novel_id')::uuid))
      THEN RAISE EXCEPTION 'character voice profile novel mismatch'; END IF;
      IF TG_TABLE_NAME='novel_narration_settings' AND row_data->>'narrator_profile_id' IS NOT NULL AND NOT EXISTS
        (SELECT 1 FROM voice_profiles p WHERE p.id=(row_data->>'narrator_profile_id')::uuid
         AND (p.novel_id IS NULL OR p.novel_id=(row_data->>'novel_id')::uuid))
      THEN RAISE EXCEPTION 'narrator profile novel mismatch'; END IF;
      IF TG_TABLE_NAME='generic_voice_slots' AND NOT EXISTS
        (SELECT 1 FROM generic_voice_pools gp JOIN voice_profile_versions vv ON vv.id=(row_data->>'voice_version_id')::uuid
         JOIN voice_profiles vp ON vp.id=vv.profile_id WHERE gp.id=(row_data->>'pool_id')::uuid
           AND (vp.novel_id IS NULL OR vp.novel_id=gp.novel_id))
      THEN RAISE EXCEPTION 'generic voice slot scope mismatch'; END IF;
      IF TG_TABLE_NAME='anonymous_speakers' AND
        (row_data->>'scope_id' IS NULL OR
         ((row_data->>'scope_kind')='novel' AND (row_data->>'scope_id')::uuid<>(row_data->>'novel_id')::uuid) OR
         ((row_data->>'scope_kind')='chapter' AND NOT EXISTS
           (SELECT 1 FROM documents d WHERE d.id=(row_data->>'scope_id')::uuid AND d.novel_id=(row_data->>'novel_id')::uuid)) OR
         ((row_data->>'scope_kind')='scene' AND NOT EXISTS
           (SELECT 1 FROM narration_scenes s JOIN narration_script_versions sv ON sv.id=s.script_version_id
            JOIN narration_scripts ns ON ns.id=sv.script_id WHERE s.id=(row_data->>'scope_id')::uuid
              AND ns.novel_id=(row_data->>'novel_id')::uuid)))
      THEN RAISE EXCEPTION 'anonymous speaker scope mismatch'; END IF;
      IF TG_TABLE_NAME='anonymous_speakers' AND row_data->>'promoted_character_id' IS NOT NULL AND NOT EXISTS
        (SELECT 1 FROM novel_characters c WHERE c.id=(row_data->>'promoted_character_id')::uuid
         AND c.novel_id=(row_data->>'novel_id')::uuid)
      THEN RAISE EXCEPTION 'anonymous promoted character novel mismatch'; END IF;
      IF TG_TABLE_NAME='anonymous_speakers' AND row_data->>'slot_id' IS NOT NULL AND NOT EXISTS
        (SELECT 1 FROM generic_voice_slots gs JOIN generic_voice_pools gp ON gp.id=gs.pool_id
         WHERE gs.id=(row_data->>'slot_id')::uuid AND gp.novel_id=(row_data->>'novel_id')::uuid)
      THEN RAISE EXCEPTION 'anonymous voice slot novel mismatch'; END IF;
      IF TG_TABLE_NAME='anonymous_speakers' AND row_data->>'voice_version_id' IS NOT NULL AND NOT EXISTS
        (SELECT 1 FROM voice_profile_versions vv JOIN voice_profiles p ON p.id=vv.profile_id
         WHERE vv.id=(row_data->>'voice_version_id')::uuid
           AND (p.novel_id IS NULL OR p.novel_id=(row_data->>'novel_id')::uuid))
      THEN RAISE EXCEPTION 'anonymous voice version novel mismatch'; END IF;
      IF TG_TABLE_NAME='anonymous_speakers' AND row_data->>'slot_id' IS NOT NULL
         AND row_data->>'voice_version_id' IS NOT NULL AND NOT EXISTS
        (SELECT 1 FROM generic_voice_slots gs WHERE gs.id=(row_data->>'slot_id')::uuid
         AND gs.voice_version_id=(row_data->>'voice_version_id')::uuid)
      THEN RAISE EXCEPTION 'anonymous slot and voice version mismatch'; END IF;
      IF TG_TABLE_NAME='voice_casting_rules' AND
        ((row_data->>'target_slot_id' IS NOT NULL AND row_data->>'target_pool_id' IS NULL) OR
         (row_data->>'target_pool_id' IS NOT NULL AND NOT EXISTS
           (SELECT 1 FROM generic_voice_pools gp WHERE gp.id=(row_data->>'target_pool_id')::uuid
            AND gp.novel_id=(row_data->>'novel_id')::uuid)) OR
         (row_data->>'target_slot_id' IS NOT NULL AND NOT EXISTS
           (SELECT 1 FROM generic_voice_slots gs JOIN generic_voice_pools gp ON gp.id=gs.pool_id
            WHERE gs.id=(row_data->>'target_slot_id')::uuid AND gs.pool_id=(row_data->>'target_pool_id')::uuid
              AND gp.novel_id=(row_data->>'novel_id')::uuid)))
      THEN RAISE EXCEPTION 'voice casting target scope mismatch'; END IF;
      IF TG_TABLE_NAME='pronunciation_entries' AND NOT EXISTS
        (SELECT 1 FROM pronunciation_profiles pp WHERE pp.id=(row_data->>'profile_id')::uuid AND
          (((row_data->>'scope_kind')='novel' AND (row_data->>'scope_id')::uuid=pp.novel_id) OR
           ((row_data->>'scope_kind')='volume' AND EXISTS
             (SELECT 1 FROM volumes v WHERE v.id=(row_data->>'scope_id')::uuid AND v.novel_id=pp.novel_id)) OR
           ((row_data->>'scope_kind')='chapter' AND EXISTS
             (SELECT 1 FROM documents d WHERE d.id=(row_data->>'scope_id')::uuid AND d.novel_id=pp.novel_id))))
      THEN RAISE EXCEPTION 'pronunciation entry scope mismatch'; END IF;
      IF TG_TABLE_NAME='background_jobs' AND row_data->>'request_id' IS NOT NULL AND NOT EXISTS
        (SELECT 1 FROM narration_requests r WHERE r.id=(row_data->>'request_id')::uuid
         AND r.owner_id=(row_data->>'owner_id')::uuid AND r.workspace_id=(row_data->>'workspace_id')::uuid
         AND r.novel_id=(row_data->>'novel_id')::uuid)
      THEN RAISE EXCEPTION 'background job request scope mismatch'; END IF;
      IF TG_TABLE_NAME='narration_editions' AND NOT EXISTS
        (SELECT 1 FROM narration_requests r JOIN narration_script_versions sv ON sv.id=(row_data->>'script_version_id')::uuid
         JOIN narration_scripts s ON s.id=sv.script_id
         JOIN narration_settings_snapshots ss ON ss.id=(row_data->>'settings_snapshot_id')::uuid
         WHERE r.id=(row_data->>'request_id')::uuid
           AND r.owner_id=(row_data->>'owner_id')::uuid AND r.workspace_id=(row_data->>'workspace_id')::uuid
           AND r.novel_id=(row_data->>'novel_id')::uuid AND s.document_id=(row_data->>'document_id')::uuid
           AND r.effective_policy=sv.effective_policy
           AND ss.owner_id=r.owner_id AND ss.workspace_id=r.workspace_id AND ss.novel_id=r.novel_id
           AND ss.fingerprint=r.settings_fingerprint AND sv.settings_fingerprint=ss.fingerprint AND
           ((r.intent IN ('create','update') AND r.document_id=s.document_id
             AND r.source_revision_id=s.revision_id AND r.source_content_hash=s.content_hash) OR
            (r.intent='batch' AND EXISTS
              (SELECT 1 FROM narration_request_sources rs WHERE rs.request_id=r.id AND rs.novel_id=r.novel_id
               AND rs.document_id=s.document_id AND rs.revision_id=s.revision_id AND rs.content_hash=s.content_hash))))
      THEN RAISE EXCEPTION 'edition provenance closure mismatch'; END IF;
      IF TG_TABLE_NAME='narration_segment_renders' AND NOT EXISTS
        (SELECT 1 FROM narration_requests r WHERE r.id=(row_data->>'request_id')::uuid
         AND r.owner_id=(row_data->>'owner_id')::uuid AND r.workspace_id=(row_data->>'workspace_id')::uuid
         AND r.novel_id=(row_data->>'novel_id')::uuid AND r.allows_render IS TRUE)
      THEN RAISE EXCEPTION 'render request scope mismatch'; END IF;
      IF TG_TABLE_NAME='narration_segment_renders' AND NOT EXISTS
        (SELECT 1 FROM voice_profile_versions vv JOIN voice_profiles p ON p.id=vv.profile_id
         JOIN voice_rights_records rr ON rr.id=vv.rights_record_id
         WHERE vv.id=(row_data->>'voice_version_id')::uuid AND vv.state='locked'
           AND p.owner_id=(row_data->>'owner_id')::uuid AND p.workspace_id=(row_data->>'workspace_id')::uuid
           AND (p.novel_id IS NULL OR p.novel_id=(row_data->>'novel_id')::uuid)
           AND (rr.expires_at IS NULL OR rr.expires_at>now())
           AND (vv.source_type<>'uploaded' OR rr.voice_cloning IS TRUE)
           AND NOT EXISTS (SELECT 1 FROM voice_rights_events re WHERE re.rights_record_id=rr.id
                           AND re.event_type IN ('revoked','expired','review_blocked')))
      THEN RAISE EXCEPTION 'render voice version is not locked/usable in scope'; END IF;
      IF TG_TABLE_NAME='narration_segment_renders' AND row_data->>'source_job_id' IS NOT NULL AND NOT EXISTS
        (SELECT 1 FROM background_jobs j WHERE j.id=(row_data->>'source_job_id')::uuid
         AND j.request_id=(row_data->>'request_id')::uuid AND j.novel_id=(row_data->>'novel_id')::uuid
         AND j.owner_id=(row_data->>'owner_id')::uuid AND j.workspace_id=(row_data->>'workspace_id')::uuid
         AND j.job_kind='narration.segment_render')
      THEN RAISE EXCEPTION 'render source job scope/kind mismatch'; END IF;
      IF TG_TABLE_NAME='narration_segments' AND NOT EXISTS
        (SELECT 1 FROM narration_script_versions sv JOIN narration_scripts ns ON ns.id=sv.script_id
         WHERE sv.id=(row_data->>'script_version_id')::uuid AND
           (((row_data->>'speaker_kind')='character' AND EXISTS
             (SELECT 1 FROM novel_characters c WHERE c.id=(row_data->>'character_id')::uuid AND c.novel_id=ns.novel_id)) OR
            ((row_data->>'speaker_kind')='anonymous' AND EXISTS
             (SELECT 1 FROM anonymous_speakers a WHERE a.id=(row_data->>'anonymous_speaker_id')::uuid AND a.novel_id=ns.novel_id)) OR
            (row_data->>'speaker_kind') IN ('narrator','group','unknown')))
      THEN RAISE EXCEPTION 'segment speaker target scope mismatch'; END IF;
      IF TG_TABLE_NAME='narration_edition_segments' AND NOT EXISTS
        (SELECT 1 FROM narration_editions e
         JOIN voice_profiles p ON p.id=(row_data->>'profile_id')::uuid
         JOIN voice_profile_versions vv ON vv.id=(row_data->>'voice_version_id')::uuid AND vv.profile_id=p.id
         JOIN voice_rights_records rr ON rr.id=vv.rights_record_id
         WHERE e.id=(row_data->>'edition_id')::uuid AND vv.state='locked'
           AND (p.novel_id IS NULL OR p.novel_id=e.novel_id)
           AND (rr.expires_at IS NULL OR rr.expires_at>now())
           AND (vv.source_type<>'uploaded' OR rr.voice_cloning IS TRUE)
           AND NOT EXISTS (SELECT 1 FROM voice_rights_events re WHERE re.rights_record_id=rr.id
                           AND re.event_type IN ('revoked','expired','review_blocked'))
           AND ((row_data->>'slot_id') IS NULL OR EXISTS
             (SELECT 1 FROM generic_voice_slots gs JOIN generic_voice_pools gp ON gp.id=gs.pool_id
              WHERE gs.id=(row_data->>'slot_id')::uuid AND gs.voice_version_id=vv.id AND gp.novel_id=e.novel_id)))
      THEN RAISE EXCEPTION 'edition segment voice scope/rights unavailable'; END IF;
      IF TG_TABLE_NAME='narration_render_assets' AND NOT EXISTS
        (SELECT 1 FROM narration_segment_renders r JOIN media_assets m ON m.id=(row_data->>'asset_id')::uuid
         WHERE r.id=(row_data->>'render_id')::uuid AND r.owner_id=m.owner_id AND r.workspace_id=m.workspace_id
           AND r.novel_id=m.novel_id AND m.state='ready' AND m.content_hash=(row_data->>'actual_sha256') AND
           (((row_data->>'role')='master' AND m.asset_class='segment_master') OR
            ((row_data->>'role')='playback' AND m.asset_class='segment_playback')))
      THEN RAISE EXCEPTION 'render asset scope/class mismatch'; END IF;
      IF TG_TABLE_NAME='narration_exports' AND NOT EXISTS
        (SELECT 1 FROM narration_editions e JOIN narration_requests r ON r.id=(row_data->>'request_id')::uuid
         JOIN media_assets m ON m.id=(row_data->>'asset_id')::uuid WHERE e.id=(row_data->>'edition_id')::uuid
           AND r.novel_id=e.novel_id AND r.owner_id=e.owner_id AND r.workspace_id=e.workspace_id
           AND r.id=e.request_id AND m.owner_id=e.owner_id AND m.workspace_id=e.workspace_id
           AND m.novel_id=e.novel_id AND m.asset_class='export'
           AND ((row_data->>'state')<>'ready' OR m.state='ready'))
      THEN RAISE EXCEPTION 'narration export scope/class mismatch'; END IF;
      IF TG_TABLE_NAME='narration_manifest_segments' AND
        (NOT EXISTS
          (SELECT 1 FROM narration_manifests mf JOIN narration_edition_segments es
             ON es.id=(row_data->>'edition_segment_id')::uuid
           WHERE mf.id=(row_data->>'manifest_id')::uuid AND mf.edition_id=(row_data->>'edition_id')::uuid
             AND es.edition_id=mf.edition_id AND es.ordinal=(row_data->>'ordinal')::integer
             AND es.gap_after_ms=(row_data->>'gap_after_ms')::integer) OR
         ((row_data->>'render_id') IS NULL AND
          ((row_data->>'render_state')='ready' OR (row_data->>'duration_ms') IS NOT NULL)) OR
         ((row_data->>'render_id') IS NOT NULL AND NOT EXISTS
          (SELECT 1 FROM narration_manifests mf
           JOIN narration_editions e ON e.id=mf.edition_id
           JOIN narration_edition_segments es ON es.id=(row_data->>'edition_segment_id')::uuid
           JOIN narration_segment_renders r ON r.id=(row_data->>'render_id')::uuid
           WHERE mf.id=(row_data->>'manifest_id')::uuid AND mf.edition_id=(row_data->>'edition_id')::uuid
             AND es.edition_id=mf.edition_id AND es.render_state='ready'
             AND es.render_fingerprint=r.render_fingerprint
             AND es.ordinal=(row_data->>'ordinal')::integer AND es.gap_after_ms=(row_data->>'gap_after_ms')::integer
             AND r.owner_id=e.owner_id AND r.workspace_id=e.workspace_id AND r.novel_id=e.novel_id
             AND r.state='ready' AND (row_data->>'render_state')='ready'
             AND r.duration_ms=(row_data->>'duration_ms')::bigint)))
      THEN RAISE EXCEPTION 'manifest segment render provenance mismatch'; END IF;
      IF TG_TABLE_NAME='document_narration_state' AND row_data->>'current_edition_id' IS NOT NULL AND NOT EXISTS
        (SELECT 1 FROM narration_editions e WHERE e.id=(row_data->>'current_edition_id')::uuid
         AND e.document_id=(row_data->>'document_id')::uuid AND e.owner_id=(row_data->>'owner_id')::uuid
         AND e.workspace_id=(row_data->>'workspace_id')::uuid)
      THEN RAISE EXCEPTION 'document current edition scope mismatch'; END IF;
      IF TG_TABLE_NAME='narration_playback_progress' AND NOT EXISTS
        (SELECT 1 FROM narration_editions e JOIN narration_edition_segments es ON es.id=(row_data->>'edition_segment_id')::uuid
         WHERE e.id=(row_data->>'edition_id')::uuid AND es.edition_id=e.id
           AND e.owner_id=(row_data->>'owner_id')::uuid AND e.workspace_id=(row_data->>'workspace_id')::uuid)
      THEN RAISE EXCEPTION 'playback progress scope mismatch'; END IF;
      IF TG_TABLE_NAME='voice_deletion_requests' AND NOT EXISTS
        (SELECT 1 FROM voice_profiles p WHERE p.id=(row_data->>'voice_profile_id')::uuid
         AND p.owner_id=(row_data->>'owner_id')::uuid AND p.workspace_id=(row_data->>'workspace_id')::uuid)
      THEN RAISE EXCEPTION 'voice deletion scope mismatch'; END IF;
      IF TG_TABLE_NAME='asset_tombstones' AND NOT EXISTS
        (SELECT 1 FROM media_assets m WHERE m.id=(row_data->>'original_asset_id')::uuid
         AND m.owner_id=(row_data->>'owner_id')::uuid AND m.workspace_id=(row_data->>'workspace_id')::uuid)
      THEN RAISE EXCEPTION 'asset tombstone scope mismatch'; END IF;
      IF TG_TABLE_NAME='asset_tombstones' AND row_data->>'deletion_request_id' IS NOT NULL AND NOT EXISTS
        (SELECT 1 FROM voice_deletion_requests d WHERE d.id=(row_data->>'deletion_request_id')::uuid
         AND d.owner_id=(row_data->>'owner_id')::uuid AND d.workspace_id=(row_data->>'workspace_id')::uuid)
      THEN RAISE EXCEPTION 'asset tombstone deletion scope mismatch'; END IF;
      RETURN NEW;
    END $$;
    CREATE FUNCTION narration_guard_edition_segment() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF OLD.render_state IN ('ready','cancelled','quarantined')
      THEN RAISE EXCEPTION 'ready/cancelled/quarantined edition segment is immutable'; END IF;
      IF (to_jsonb(OLD)-ARRAY['render_state','failure_code'])<>(to_jsonb(NEW)-ARRAY['render_state','failure_code'])
      THEN RAISE EXCEPTION 'edition segment production input is immutable'; END IF;
      IF OLD.render_state<>NEW.render_state AND NOT (
        (OLD.render_state='pending' AND NEW.render_state IN ('queued','rendering','ready','failed','cancelled','quarantined')) OR
        (OLD.render_state='queued' AND NEW.render_state IN ('rendering','ready','failed','cancelled','quarantined')) OR
        (OLD.render_state='rendering' AND NEW.render_state IN ('ready','failed','cancelled','quarantined')))
      THEN RAISE EXCEPTION 'invalid edition segment state transition'; END IF;
      RETURN NEW;
    END $$;
    CREATE FUNCTION narration_guard_export() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF OLD.state IN ('ready','cancelled','quarantined')
      THEN RAISE EXCEPTION 'ready/cancelled/quarantined export is immutable'; END IF;
      IF (to_jsonb(OLD)-'state')<>(to_jsonb(NEW)-'state')
      THEN RAISE EXCEPTION 'export input is immutable'; END IF;
      IF OLD.state<>NEW.state AND NOT
         (OLD.state='staging' AND NEW.state IN ('ready','failed','cancelled','quarantined'))
      THEN RAISE EXCEPTION 'invalid export state transition'; END IF;
      RETURN NEW;
    END $$;
    """))
    for table in IMMUTABLE_TABLES:
        op.execute(sa.text(f"CREATE TRIGGER trg_{table}_immutable BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION narration_reject_mutation()"))
    for table in ("narration_script_issues","narration_scenes","narration_segments"):
        op.execute(sa.text(f"CREATE TRIGGER trg_{table}_approved_guard BEFORE INSERT OR UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION narration_guard_approved_child()"))
    op.execute(sa.text("CREATE TRIGGER trg_narration_script_version_approved BEFORE UPDATE OR DELETE ON narration_script_versions FOR EACH ROW EXECUTE FUNCTION narration_guard_script_version()"))
    op.execute(sa.text("CREATE TRIGGER trg_voice_profile_version_locked BEFORE UPDATE OR DELETE ON voice_profile_versions FOR EACH ROW EXECUTE FUNCTION narration_guard_voice_version()"))
    op.execute(sa.text("CREATE TRIGGER trg_narration_ready_render BEFORE UPDATE OR DELETE ON narration_segment_renders FOR EACH ROW EXECUTE FUNCTION narration_guard_ready_render()"))
    op.execute(sa.text("CREATE TRIGGER trg_narration_request_immutable BEFORE INSERT OR UPDATE ON narration_requests FOR EACH ROW EXECUTE FUNCTION narration_guard_request()"))
    op.execute(sa.text("CREATE TRIGGER trg_narration_request_no_delete BEFORE DELETE ON narration_requests FOR EACH ROW EXECUTE FUNCTION narration_reject_mutation()"))
    op.execute(sa.text("CREATE TRIGGER trg_background_job_guard BEFORE INSERT OR UPDATE ON background_jobs FOR EACH ROW EXECUTE FUNCTION narration_guard_job()"))
    op.execute(sa.text("CREATE TRIGGER trg_voice_deletion_state BEFORE INSERT OR UPDATE OR DELETE ON voice_deletion_requests FOR EACH ROW EXECUTE FUNCTION narration_guard_voice_deletion()"))
    op.execute(sa.text("CREATE TRIGGER trg_narration_consent_revoke BEFORE UPDATE ON narration_cloud_consents FOR EACH ROW EXECUTE FUNCTION narration_guard_consent()"))
    op.execute(sa.text("CREATE TRIGGER trg_narration_consent_no_delete BEFORE DELETE ON narration_cloud_consents FOR EACH ROW EXECUTE FUNCTION narration_reject_mutation()"))
    op.execute(sa.text("CREATE TRIGGER trg_background_attempt_guard BEFORE UPDATE OR DELETE ON background_job_attempts FOR EACH ROW EXECUTE FUNCTION narration_guard_attempt()"))
    op.execute(sa.text("CREATE TRIGGER trg_narration_edition_guard BEFORE UPDATE ON narration_editions FOR EACH ROW EXECUTE FUNCTION narration_guard_edition()"))
    op.execute(sa.text("CREATE TRIGGER trg_narration_edition_no_delete BEFORE DELETE ON narration_editions FOR EACH ROW EXECUTE FUNCTION narration_reject_mutation()"))
    op.execute(sa.text("CREATE TRIGGER trg_narration_edition_segment_guard BEFORE UPDATE ON narration_edition_segments FOR EACH ROW EXECUTE FUNCTION narration_guard_edition_segment()"))
    op.execute(sa.text("CREATE TRIGGER trg_narration_edition_segment_no_delete BEFORE DELETE ON narration_edition_segments FOR EACH ROW EXECUTE FUNCTION narration_reject_mutation()"))
    op.execute(sa.text("CREATE TRIGGER trg_narration_export_guard BEFORE UPDATE ON narration_exports FOR EACH ROW EXECUTE FUNCTION narration_guard_export()"))
    op.execute(sa.text("CREATE TRIGGER trg_narration_export_no_delete BEFORE DELETE ON narration_exports FOR EACH ROW EXECUTE FUNCTION narration_reject_mutation()"))
    for table in ("narration_requests","novel_narration_settings","narration_scope_overrides","voice_profiles","character_voice_bindings","narration_edition_state","document_narration_state"):
        op.execute(sa.text(f"CREATE TRIGGER trg_{table}_cas BEFORE UPDATE ON {table} FOR EACH ROW EXECUTE FUNCTION narration_guard_cas()"))
    op.execute(sa.text("CREATE CONSTRAINT TRIGGER trg_media_generated_reachability AFTER INSERT OR UPDATE ON media_assets DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION narration_guard_generated_media()"))
    op.execute(sa.text("CREATE CONSTRAINT TRIGGER trg_render_ready_reachability AFTER INSERT OR UPDATE ON narration_segment_renders DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION narration_guard_ready_render_assets()"))
    op.execute(sa.text("CREATE TRIGGER trg_media_narration_identity BEFORE INSERT OR UPDATE OR DELETE ON media_assets FOR EACH ROW EXECUTE FUNCTION narration_guard_media_identity()"))
    op.execute(sa.text("CREATE TRIGGER trg_novel_cover_scope BEFORE INSERT OR UPDATE OF cover_asset_id ON novels FOR EACH ROW EXECUTE FUNCTION narration_guard_novel_cover()"))
    op.execute(sa.text("CREATE TRIGGER trg_generic_voice_pool_identity BEFORE UPDATE OR DELETE ON generic_voice_pools FOR EACH ROW EXECUTE FUNCTION narration_guard_voice_pool()"))
    op.execute(sa.text("CREATE TRIGGER trg_generic_voice_slot_immutable BEFORE UPDATE OR DELETE ON generic_voice_slots FOR EACH ROW EXECUTE FUNCTION narration_reject_mutation()"))
    op.execute(sa.text("CREATE TRIGGER trg_anonymous_speaker_identity BEFORE UPDATE ON anonymous_speakers FOR EACH ROW EXECUTE FUNCTION narration_guard_anonymous_identity()"))
    op.execute(sa.text("CREATE TRIGGER trg_novel_character_narration_scope BEFORE UPDATE OF novel_id ON novel_characters FOR EACH ROW EXECUTE FUNCTION narration_guard_character_novel()"))
    op.execute(sa.text("CREATE TRIGGER trg_volume_narration_scope_parent BEFORE UPDATE OF novel_id OR DELETE ON volumes FOR EACH ROW EXECUTE FUNCTION narration_guard_volume_scope_parent()"))
    op.execute(sa.text("CREATE TRIGGER trg_document_narration_scope_parent BEFORE UPDATE OF novel_id OR DELETE ON documents FOR EACH ROW EXECUTE FUNCTION narration_guard_document_scope_parent()"))
    op.execute(sa.text("CREATE TRIGGER trg_scene_narration_scope_parent BEFORE UPDATE OF script_version_id OR DELETE ON narration_scenes FOR EACH ROW EXECUTE FUNCTION narration_guard_scene_scope_parent()"))
    op.execute(sa.text("CREATE TRIGGER trg_revision_media_parent BEFORE UPDATE OF id, document_id, content_hash OR DELETE ON document_revisions FOR EACH ROW EXECUTE FUNCTION narration_guard_revision_media_parent()"))
    for table in ("narration_request_sources","narration_scope_overrides","voice_rights_records","voice_profiles","voice_profile_versions","character_voice_bindings","novel_narration_settings","generic_voice_slots","voice_casting_rules","anonymous_speakers","pronunciation_entries","narration_script_versions","narration_segments","background_jobs","narration_editions","narration_edition_segments","narration_segment_renders","narration_render_assets","narration_exports","narration_manifest_segments","document_narration_state","narration_playback_progress","voice_deletion_requests","asset_tombstones"):
        op.execute(sa.text(f"CREATE TRIGGER trg_{table}_scope BEFORE INSERT OR UPDATE ON {table} FOR EACH ROW EXECUTE FUNCTION narration_validate_scope()"))

def _harden_cross_scope() -> None:
    op.create_foreign_key("fk_media_asset_novel_scope", "media_assets", "novels", ["novel_id","owner_id","workspace_id"], ["id","owner_id","workspace_id"])
    op.create_unique_constraint("uq_narration_request_novel_guard", "narration_requests", ["id","novel_id"])
    op.create_unique_constraint("uq_narration_request_full_render_guard", "narration_requests", ["id","owner_id","workspace_id","novel_id","allows_render"])
    op.drop_constraint("fk_narration_request_source_request", "narration_request_sources", type_="foreignkey")
    op.create_foreign_key("fk_narration_request_source_request_scope", "narration_request_sources", "narration_requests", ["request_id","novel_id"], ["id","novel_id"], ondelete="CASCADE")
    op.create_foreign_key("fk_narration_settings_snapshot_novel_scope", "narration_settings_snapshots", "novels", ["novel_id","owner_id","workspace_id"], ["id","owner_id","workspace_id"], ondelete="RESTRICT")
    op.create_unique_constraint("uq_narration_settings_snapshot_edition_guard", "narration_settings_snapshots", ["id","owner_id","workspace_id","novel_id"])
    op.create_check_constraint("ck_narration_settings_snapshot_taxonomy_version", "narration_settings_snapshots", "taxonomy_version='narration-review-taxonomy/1'")
    op.create_foreign_key("fk_voice_rights_record_novel_scope", "voice_rights_records", "novels", ["novel_id","owner_id","workspace_id"], ["id","owner_id","workspace_id"], ondelete="RESTRICT")
    op.create_foreign_key("fk_voice_profile_novel_scope", "voice_profiles", "novels", ["novel_id","owner_id","workspace_id"], ["id","owner_id","workspace_id"], ondelete="RESTRICT")
    op.create_foreign_key("fk_background_job_novel_scope", "background_jobs", "novels", ["novel_id","owner_id","workspace_id"], ["id","owner_id","workspace_id"], ondelete="CASCADE")
    op.drop_constraint("fk_background_job_request_render_guard", "background_jobs", type_="foreignkey")
    op.create_foreign_key("fk_background_job_request_render_guard", "background_jobs", "narration_requests", ["request_id","owner_id","workspace_id","novel_id","request_allows_render"], ["id","owner_id","workspace_id","novel_id","allows_render"], ondelete="RESTRICT")
    op.drop_constraint("ck_background_job_render_guard", "background_jobs", type_="check")
    op.create_check_constraint("ck_background_job_render_guard", "background_jobs", "job_kind NOT IN ('narration.segment_render','narration.export') OR (request_id IS NOT NULL AND novel_id IS NOT NULL AND request_allows_render IS TRUE)")
    op.create_foreign_key("fk_narration_edition_novel_scope", "narration_editions", "novels", ["novel_id","owner_id","workspace_id"], ["id","owner_id","workspace_id"], ondelete="RESTRICT")
    op.create_unique_constraint("uq_pronunciation_profile_edition_guard", "pronunciation_profiles", ["id","novel_id"])
    op.create_foreign_key("fk_narration_edition_settings_scope", "narration_editions", "narration_settings_snapshots", ["settings_snapshot_id","owner_id","workspace_id","novel_id"], ["id","owner_id","workspace_id","novel_id"], ondelete="RESTRICT")
    op.create_foreign_key("fk_narration_edition_pronunciation_scope", "narration_editions", "pronunciation_profiles", ["pronunciation_profile_id","novel_id"], ["id","novel_id"], ondelete="RESTRICT")
    op.create_unique_constraint("uq_narration_edition_request_guard", "narration_editions", ["id","request_id"])
    op.create_foreign_key("fk_narration_export_edition_request_guard", "narration_exports", "narration_editions", ["edition_id","request_id"], ["id","request_id"], ondelete="RESTRICT")
    op.add_column("narration_segment_renders", sa.Column("novel_id", postgresql.UUID(as_uuid=True), nullable=False))
    op.drop_constraint("fk_narration_segment_render_request_guard", "narration_segment_renders", type_="foreignkey")
    op.create_foreign_key("fk_narration_segment_render_request_guard", "narration_segment_renders", "narration_requests", ["request_id","owner_id","workspace_id","novel_id","request_allows_render"], ["id","owner_id","workspace_id","novel_id","allows_render"], ondelete="RESTRICT")
    op.create_foreign_key("fk_narration_segment_render_novel_scope", "narration_segment_renders", "novels", ["novel_id","owner_id","workspace_id"], ["id","owner_id","workspace_id"], ondelete="RESTRICT")
    op.alter_column("anonymous_speakers", "scope_id", existing_type=postgresql.UUID(as_uuid=True), nullable=False)
    op.create_check_constraint("ck_narration_segment_speaker_shape", "narration_segments", "(speaker_kind='character' AND character_id IS NOT NULL AND anonymous_speaker_id IS NULL) OR (speaker_kind='anonymous' AND anonymous_speaker_id IS NOT NULL AND character_id IS NULL) OR (speaker_kind IN ('narrator','group','unknown') AND character_id IS NULL AND anonymous_speaker_id IS NULL)")
    op.create_foreign_key("fk_narration_edition_segment_voice_guard", "narration_edition_segments", "voice_profile_versions", ["voice_version_id","profile_id"], ["id","profile_id"], ondelete="RESTRICT")
    op.create_foreign_key("fk_narration_segment_script_version", "narration_segments", "narration_script_versions", ["script_version_id"], ["id"], ondelete="CASCADE")
    op.create_foreign_key("fk_narration_playback_manifest_revision", "narration_playback_progress", "narration_manifests", ["edition_id","manifest_revision"], ["edition_id","manifest_revision"], ondelete="CASCADE")
    op.create_foreign_key("fk_narration_playback_edition_segment", "narration_playback_progress", "narration_edition_segments", ["edition_segment_id","edition_id"], ["id","edition_id"], ondelete="CASCADE")
    op.create_foreign_key("fk_voice_profile_current_version", "voice_profiles", "voice_profile_versions", ["current_version_id","id"], ["id","profile_id"], ondelete="RESTRICT")
    op.create_foreign_key("fk_narration_settings_narrator_version", "novel_narration_settings", "voice_profile_versions", ["narrator_version_id","narrator_profile_id"], ["id","profile_id"], ondelete="RESTRICT")
    op.create_check_constraint("ck_narration_settings_narrator_shape", "novel_narration_settings", "(narrator_profile_id IS NULL AND narrator_version_id IS NULL) OR (narrator_profile_id IS NOT NULL AND narrator_version_id IS NOT NULL)")
    op.create_check_constraint("ck_character_voice_binding_shape", "character_voice_bindings", "(binding_policy='unset' AND profile_id IS NULL AND voice_version_id IS NULL) OR (binding_policy IN ('dedicated','inherited') AND profile_id IS NOT NULL AND voice_version_id IS NOT NULL)")
    op.create_check_constraint("ck_voice_profile_version_quality_state", "voice_profile_versions", "quality_state IN ('pending','accepted','rejected')")
    op.create_check_constraint("ck_voice_profile_version_locked_shape", "voice_profile_versions", "state <> 'locked' OR (quality_state='accepted' AND locked_actor IS NOT NULL AND locked_at IS NOT NULL)")
    op.drop_constraint("ck_narration_script_version_state", "narration_script_versions", type_="check")
    op.add_column("narration_script_versions", sa.Column("approval_request_id", postgresql.UUID(as_uuid=True)))
    op.add_column("narration_script_versions", sa.Column("approval_request_allows_edition", sa.Boolean()))
    op.create_foreign_key("fk_narration_script_version_approval_request", "narration_script_versions", "narration_requests", ["approval_request_id","approval_request_allows_edition"], ["id","allows_edition"], ondelete="RESTRICT")
    op.drop_constraint("narration_script_versions_parent_version_id_fkey", "narration_script_versions", type_="foreignkey")
    op.create_foreign_key("fk_narration_script_version_parent_same_script", "narration_script_versions", "narration_script_versions", ["script_id","parent_version_id"], ["script_id","id"], ondelete="RESTRICT")
    op.create_check_constraint("ck_narration_script_version_state", "narration_script_versions", "state IN ('draft','analyzing','analyzed','review_required','approved','failed')")
    op.create_check_constraint("ck_narration_request_force_review_policy", "narration_requests", "force_review IS FALSE OR effective_policy='always_review'")
    op.create_check_constraint("ck_narration_script_version_auto_policy", "narration_script_versions", "approval_kind <> 'auto_no_blockers' OR (effective_policy='blockers_only' AND approval_request_id IS NOT NULL AND approval_request_allows_edition IS TRUE)")
    op.create_check_constraint("ck_narration_script_version_manual_actor", "narration_script_versions", "approval_kind <> 'manual_after_review' OR (approved_actor_type='owner' AND approved_actor_id IS NOT NULL)")
    op.drop_constraint("ck_narration_script_version_approved_shape", "narration_script_versions", type_="check")
    op.create_check_constraint("ck_narration_script_version_approved_shape", "narration_script_versions", "state <> 'approved' OR (blocker_count=0 AND approval_kind IS NOT NULL AND approved_at IS NOT NULL AND approved_actor_type IS NOT NULL AND approved_actor_id IS NOT NULL AND approval_request_id IS NOT NULL AND approval_request_allows_edition IS TRUE)")
    op.create_check_constraint("ck_narration_script_version_taxonomy_version", "narration_script_versions", "taxonomy_version='narration-review-taxonomy/1'")
    op.create_check_constraint("ck_narration_issue_taxonomy_version", "narration_script_issues", "taxonomy_version='narration-review-taxonomy/1'")
    op.drop_constraint("ck_narration_segment_source_range", "narration_segments", type_="check")
    op.create_check_constraint("ck_narration_segment_source_range", "narration_segments", "(source_start_utf16 IS NULL AND source_end_utf16 IS NULL) OR (source_start_utf16 IS NOT NULL AND source_end_utf16 IS NOT NULL AND source_start_utf16>=0 AND source_end_utf16>=source_start_utf16)")
    op.create_check_constraint("ck_narration_segment_nonnegative", "narration_segments", "ordinal>=0 AND pause_before_ms>=0 AND pause_after_ms>=0")
    op.create_check_constraint("ck_narration_edition_state", "narration_editions", "state IN ('created','rendering','partial_ready','ready','unavailable')")
    op.create_check_constraint("ck_narration_edition_segment_state", "narration_edition_segments", "render_state IN ('pending','queued','rendering','ready','failed','cancelled','quarantined')")
    op.create_check_constraint("ck_narration_edition_segment_nonnegative", "narration_edition_segments", "ordinal>=0 AND gap_after_ms>=0")
    op.create_check_constraint("ck_narration_segment_render_duration", "narration_segment_renders", "duration_ms IS NULL OR duration_ms>=0")
    op.create_check_constraint("ck_narration_export_state", "narration_exports", "state IN ('staging','ready','failed','cancelled','quarantined')")
    op.create_check_constraint("ck_narration_manifest_status", "narration_manifests", "status IN ('partial_ready','ready','unavailable')")
    op.create_check_constraint("ck_narration_manifest_nonnegative", "narration_manifests", "ready_prefix_count>=0 AND total_duration_ms>=0")
    op.create_check_constraint("ck_narration_manifest_segment_state", "narration_manifest_segments", "render_state IN ('pending','rendering','ready','failed','unavailable')")
    op.create_check_constraint("ck_narration_manifest_segment_nonnegative", "narration_manifest_segments", "ordinal>=0 AND gap_after_ms>=0 AND (duration_ms IS NULL OR duration_ms>=0)")
    op.create_check_constraint("ck_narration_playback_nonnegative", "narration_playback_progress", "offset_ms>=0 AND last_legal_start_ordinal>=0 AND playback_rate_millis BETWEEN 250 AND 4000")
    op.create_check_constraint("ck_background_job_attempt_positive", "background_job_attempts", "attempt_number>0 AND lease_generation>0")
    op.create_check_constraint("ck_background_job_attempt_manual_shape", "background_job_attempts", "(retry_kind='manual' AND manual_actor IS NOT NULL AND manual_reason IS NOT NULL) OR (retry_kind IN ('initial','automatic') AND manual_actor IS NULL AND manual_reason IS NULL)")
    op.create_check_constraint("ck_voice_deletion_confirmation_shape", "voice_deletion_requests", "state NOT IN ('live_deleting','live_deleted_backup_pending','completed') OR (confirmed_actor IS NOT NULL AND confirmed_at IS NOT NULL)")
    op.create_check_constraint("ck_voice_deletion_request_command", "voice_deletion_requests", "command IN ('delete_uploaded_original_only','true_delete_private_voice')")
    op.create_check_constraint("ck_voice_profile_version_uploaded_reference", "voice_profile_versions", "source_type<>'uploaded' OR reference_asset_id IS NOT NULL")
    op.create_check_constraint("ck_narration_segment_render_ready_shape", "narration_segment_renders", "state<>'ready' OR (duration_ms IS NOT NULL AND ready_at IS NOT NULL)")
    op.create_unique_constraint("uq_narration_manifest_edition_guard", "narration_manifests", ["id","edition_id"])
    op.create_foreign_key("fk_narration_manifest_segment_manifest_edition", "narration_manifest_segments", "narration_manifests", ["manifest_id","edition_id"], ["id","edition_id"], ondelete="CASCADE")
    op.create_check_constraint("ck_narration_edition_state_manifest_shape", "narration_edition_state", "(current_manifest_id IS NULL AND current_manifest_revision IS NULL) OR (current_manifest_id IS NOT NULL AND current_manifest_revision IS NOT NULL)")
    op.create_check_constraint("ck_document_narration_state_script_shape", "document_narration_state", "(script_id IS NULL AND current_script_version_id IS NULL) OR (script_id IS NOT NULL AND current_script_version_id IS NOT NULL)")

def upgrade() -> None:
    _preflight()
    _extend_existing()
    for ddl in CREATE_DDL:
        op.execute(sa.text(ddl))
    _harden_cross_scope()
    _create_triggers()

def _assert_empty_for_downgrade() -> None:
    union = " UNION ALL ".join(f"SELECT 1 FROM {name}" for name in NEW_TABLES)
    op.execute(sa.text(f"""DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM ({union}) AS t)
        OR EXISTS (SELECT 1 FROM media_assets WHERE asset_class IS NOT NULL OR novel_id IS NULL)
      THEN RAISE EXCEPTION 'T1-D downgrade refused: narration/global media data exists; restore the pre-upgrade backup or fix forward'; END IF;
    END $$;"""))

def downgrade() -> None:
    _assert_empty_for_downgrade()
    op.execute(sa.text("DROP FUNCTION narration_guard_generated_media() CASCADE"))
    op.execute(sa.text("DROP FUNCTION narration_guard_ready_render_assets() CASCADE"))
    op.execute(sa.text("DROP FUNCTION narration_guard_media_identity() CASCADE"))
    op.execute(sa.text("DROP FUNCTION narration_guard_novel_cover() CASCADE"))
    op.execute(sa.text("DROP FUNCTION narration_guard_voice_pool() CASCADE"))
    op.execute(sa.text("DROP FUNCTION narration_guard_anonymous_identity() CASCADE"))
    op.execute(sa.text("DROP FUNCTION narration_guard_character_novel() CASCADE"))
    op.execute(sa.text("DROP FUNCTION narration_guard_revision_media_parent() CASCADE"))
    op.execute(sa.text("DROP FUNCTION narration_guard_scene_scope_parent() CASCADE"))
    op.execute(sa.text("DROP FUNCTION narration_guard_document_scope_parent() CASCADE"))
    op.execute(sa.text("DROP FUNCTION narration_guard_volume_scope_parent() CASCADE"))
    op.execute(sa.text("DROP FUNCTION narration_guard_export() CASCADE"))
    op.execute(sa.text("DROP FUNCTION narration_guard_edition_segment() CASCADE"))
    op.execute(sa.text("DROP FUNCTION narration_validate_scope() CASCADE"))
    op.execute(sa.text("DROP FUNCTION narration_guard_edition() CASCADE"))
    op.execute(sa.text("DROP FUNCTION narration_guard_attempt() CASCADE"))
    op.execute(sa.text("DROP FUNCTION narration_guard_consent() CASCADE"))
    op.execute(sa.text("DROP FUNCTION narration_guard_cas() CASCADE"))
    op.execute(sa.text("DROP FUNCTION narration_guard_request() CASCADE"))
    op.execute(sa.text("DROP FUNCTION narration_guard_voice_deletion() CASCADE"))
    op.execute(sa.text("DROP FUNCTION narration_guard_job() CASCADE"))
    op.execute(sa.text("DROP FUNCTION narration_guard_ready_render() CASCADE"))
    op.execute(sa.text("DROP FUNCTION narration_guard_voice_version() CASCADE"))
    op.execute(sa.text("DROP FUNCTION narration_guard_script_version() CASCADE"))
    op.execute(sa.text("DROP FUNCTION narration_guard_approved_child() CASCADE"))
    op.execute(sa.text("DROP FUNCTION narration_reject_mutation() CASCADE"))
    op.drop_constraint("fk_voice_profile_current_version", "voice_profiles", type_="foreignkey")
    op.drop_constraint("fk_narration_settings_narrator_version", "novel_narration_settings", type_="foreignkey")
    for table in reversed(NEW_TABLES):
        op.drop_table(table)
    op.drop_constraint("fk_media_asset_novel_scope", "media_assets", type_="foreignkey")
    op.drop_constraint("ck_media_asset_duration", "media_assets", type_="check")
    op.drop_constraint("ck_media_asset_byte_size", "media_assets", type_="check")
    op.drop_constraint("ck_media_asset_state", "media_assets", type_="check")
    op.drop_constraint("ck_media_asset_class", "media_assets", type_="check")
    op.drop_constraint("ck_media_asset_tts_class_required", "media_assets", type_="check")
    op.drop_constraint("ck_media_asset_fixed_local_scope", "media_assets", type_="check")
    op.drop_index("ix_media_assets_scope_class_state", table_name="media_assets")
    op.drop_constraint("uq_media_asset_local_scope", "media_assets", type_="unique")
    op.alter_column("media_assets", "novel_id", existing_type=postgresql.UUID(as_uuid=True), nullable=False)
    for column in ("gc_generation","gc_marked_at","deleted_at","expires_at","last_accessed_at","verified_at","validation_json","checksum_algorithm","retention_policy","state","storage_backend","channels","sample_rate","duration_ms","byte_size","mime_type","asset_class","workspace_id","owner_id"):
        op.drop_column("media_assets", column)
    op.drop_constraint("uq_novel_character_novel_scope", "novel_characters", type_="unique")
    op.drop_index("uq_document_revision_tts_snapshot", table_name="document_revisions")
    op.drop_constraint("uq_document_revision_source_guard", "document_revisions", type_="unique")
    op.drop_constraint("uq_document_revision_document_scope", "document_revisions", type_="unique")
    op.drop_constraint("uq_document_novel_scope", "documents", type_="unique")
    op.drop_constraint("uq_volume_novel_scope", "volumes", type_="unique")
    op.drop_constraint("ck_novel_fixed_local_scope", "novels", type_="check")
    op.drop_index("ix_novels_local_scope", table_name="novels")
    op.drop_constraint("uq_novel_local_scope", "novels", type_="unique")
    op.drop_column("novels", "workspace_id")
    op.drop_column("novels", "owner_id")
    # 20260825_0009 remains intentionally one-way; this function only returns to 0009.
