"""Allow pinned official-preset previews without uploaded reference media.

Revision ID: 20260827_0022
Revises: 20260827_0021

The migration changes no existing voice evidence.  Uploaded previews retain
their exact reference-link/media closure; official presets instead close over
the pinned ONNX manifest identity stored on the immutable voice version.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260827_0022"
down_revision = "20260827_0021"
branch_labels = None
depends_on = None


def _install_scope_guard() -> None:
    op.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION narration_guard_voice_preview_scope_v1()
            RETURNS trigger LANGUAGE plpgsql AS $$
            DECLARE preview_row voice_previews%ROWTYPE;
            BEGIN
              SELECT * INTO preview_row FROM voice_previews WHERE id=NEW.id;
              IF NOT FOUND THEN RETURN NULL; END IF;
              IF NOT EXISTS (
                SELECT 1
                FROM voice_profiles p
                JOIN voice_profile_versions v
                  ON v.id=preview_row.version_id AND v.profile_id=p.id
                JOIN voice_rights_records r ON r.id=preview_row.rights_record_id
                JOIN background_jobs j ON j.id=preview_row.job_id
                LEFT JOIN voice_reference_asset_links l
                  ON l.voice_version_id=v.id AND l.profile_id=p.id
                LEFT JOIN media_assets reference
                  ON reference.id=preview_row.reference_asset_id
                LEFT JOIN media_assets result
                  ON result.id=preview_row.result_asset_id
                WHERE p.id=preview_row.profile_id
                  AND (p.owner_id,p.workspace_id,p.novel_id) IS NOT DISTINCT FROM
                      (preview_row.owner_id,preview_row.workspace_id,preview_row.novel_id)
                  AND p.status IN ('draft','active')
                  AND (v.owner_id,v.workspace_id)=
                      (preview_row.owner_id,preview_row.workspace_id)
                  AND v.state IN ('draft','preview_ready','locked')
                  AND v.rights_record_id=r.id
                  AND (r.owner_id,r.workspace_id,r.novel_id) IS NOT DISTINCT FROM
                      (preview_row.owner_id,preview_row.workspace_id,preview_row.novel_id)
                  AND r.purpose='private_novel_narration'
                  AND (r.expires_at IS NULL OR r.expires_at>CURRENT_TIMESTAMP)
                  AND EXISTS (
                    SELECT 1 FROM voice_rights_events confirmed
                    WHERE confirmed.rights_record_id=r.id
                      AND confirmed.event_type='confirmed'
                  )
                  AND NOT EXISTS (
                    SELECT 1 FROM voice_rights_events e
                    WHERE e.rights_record_id=r.id
                      AND e.event_type IN ('revoked','expired','review_blocked')
                  )
                  AND (
                    (
                      v.source_type='uploaded'
                      AND r.source_kind='user_upload'
                      AND r.voice_cloning IS TRUE
                      AND preview_row.reference_asset_id IS NOT NULL
                      AND v.reference_asset_id=preview_row.reference_asset_id
                      AND l.rights_record_id=r.id
                      AND l.reference_asset_id=reference.id
                      AND (l.owner_id,l.workspace_id,l.novel_id) IS NOT DISTINCT FROM
                          (preview_row.owner_id,preview_row.workspace_id,preview_row.novel_id)
                      AND (reference.owner_id,reference.workspace_id,reference.novel_id)
                          IS NOT DISTINCT FROM
                          (preview_row.owner_id,preview_row.workspace_id,preview_row.novel_id)
                      AND reference.kind='narration_voice_reference'
                      AND reference.asset_class='voice_reference'
                      AND reference.state='ready'
                      AND reference.retention_policy='locked_voice'
                    ) OR (
                      v.source_type='preset'
                      AND r.source_kind='official_preset'
                      AND r.commercial_use IS FALSE
                      AND r.redistribution IS FALSE
                      AND preview_row.reference_asset_id IS NULL
                      AND v.reference_asset_id IS NULL
                      AND l.id IS NULL
                      AND reference.id IS NULL
                      AND v.provider_id='local-sidecar'
                      AND v.model_id='OpenMOSS-Team/MOSS-TTS-Nano-100M-ONNX'
                      AND v.model_revision='f52645cb467506d8e18e746ddd59482685b74e58'
                      AND v.preset_key=v.parameters_json#>>'{official_preset,preset_id}'
                      AND v.preset_key='onnx.' ||
                          (v.parameters_json#>>'{official_preset,manifest_voice}')
                      AND v.parameters_json->>'schema_version'=
                          'narration-official-preset-version/1.0'
                      AND v.parameters_json#>>'{official_preset,schema_version}'=
                          'moss-tts-official-preset-provenance/1.0'
                      AND v.parameters_json#>>'{official_preset,repository}'=
                          'OpenMOSS-Team/MOSS-TTS-Nano-100M-ONNX'
                      AND v.parameters_json#>>'{official_preset,revision}'=
                          'f52645cb467506d8e18e746ddd59482685b74e58'
                      AND v.parameters_json#>>'{official_preset,manifest_path}'=
                          'browser_poc_manifest.json'
                      AND v.parameters_json#>>'{official_preset,manifest_sha256}'=
                          '097d80e993dc29f0bae427590b4f77084a161cb578b50d82c29f455d5faa9eee'
                      AND v.parameters_json#>>'{official_preset,model_fingerprint_sha256}'=
                          '3c76f3e9e1381699c5555287cf66eeb023632d0c3ee94adc6d8ae1b1d455fd7d'
                      AND v.parameters_json#>>'{official_preset,prompt_codes_sha256}'
                          ~ '^[0-9a-f]{64}$'
                      AND (v.parameters_json#>>'{official_preset,prompt_frame_count}')
                          ~ '^[1-9][0-9]*$'
                      AND (
                        v.preset_key,
                        v.parameters_json#>>'{official_preset,prompt_codes_sha256}',
                        (v.parameters_json#>>'{official_preset,prompt_frame_count}')::integer
                      ) IN (VALUES
                        ('onnx.Junhao','395976042d458c44977c43b9b20a9945100cbf0302381e5d25e46b43304aa6d4',98),
                        ('onnx.Zhiming','6574897aab814be3b155f073683e4f19a3e5f1ab92ddfa66bec5b7911cf4099e',98),
                        ('onnx.Weiguo','cbfa9212b4f8ec64172f7057c92dc8ec9a1731530b012bd9dfb3b1e297624ee6',140),
                        ('onnx.Xiaoyu','847277bcef201396ef1aa6adbc8e55a25c9b0b8e3cfa3c72ac306053224022be',180),
                        ('onnx.Yuewen','bed66ac01188f639b18f1a8cfd1520d6fbf0c319d27c282b1dc1cd3e9a8a888f',102),
                        ('onnx.Lingyu','761b4a0b0c3e0cec067c76b9a21560d8c8b0e302f67e16f0bf090e288c6fb3b0',218),
                        ('onnx.Trump','3055948dd0646a7d1a72de824d33ab069ca3a2a5489a78f22818314a3d2e9d27',97),
                        ('onnx.Ava','892a532b562d79fe683640e98f2e061683e4ea7bc93929d0866a1f5dae30ba48',98),
                        ('onnx.Bella','d4def268888ebb0575d3bb8b1428bdea252af26e68281c43218432ddc9b0cda4',59),
                        ('onnx.Adam','14ffba3b57fdd50e16f431ba6631bf9b26d4c8ae1ec671ab73c1dea61e2835b7',59),
                        ('onnx.Nathan','3e4bdb8ba9884ebf028efafb1535af784bb792a2695a25e571abc0a9cd18072e',168),
                        ('onnx.Soyo','d2079895cc7f2ec931a983e8f16150cc322c37bf0b62135507126736ee70e4e1',125),
                        ('onnx.Saki','85f916c338c1a26f5e91b90b71f7942bfb3c465e999d97a12b24644258de18bd',32),
                        ('onnx.Mortis','9976030044c8746d488fa1cdf470e43760429bf73113819f9da15784bf4d4449',60),
                        ('onnx.Umiri','72bdf9fb4dfcd4405ec216030a73bf004856b6cf66b100c040fe36bea6165d43',77),
                        ('onnx.Mei','2068325ad43d3589bcffcb2f8a969eb7ff6570de4736aa3221553537c6232b1a',49),
                        ('onnx.Anon','566b5098c19390f178cba0e1d16961ff45a225677adbb6f0bc2315c20954a5ee',47),
                        ('onnx.Arisa','2cf65c28e3bb62c93195a1d0778578d10c0ef71a42a66dcbe613592efb17dd5f',85)
                      )
                      AND (v.parameters_json#>>'{official_preset,prompt_quantizer_count}')
                          = '16'
                      AND v.parameters_json#>>'{official_preset,provenance_fingerprint_sha256}'
                          ~ '^[0-9a-f]{64}$'
                    )
                  )
                  AND (j.owner_id,j.workspace_id,j.novel_id) IS NOT DISTINCT FROM
                      (preview_row.owner_id,preview_row.workspace_id,preview_row.novel_id)
                  AND j.job_kind='narration.voice_preview'
                  AND j.resource_class='moss-nano'
                  AND j.request_id IS NULL
                  AND (
                    (preview_row.status='queued' AND j.state IN
                      ('queued','running','retry_wait','cancel_requested')) OR
                    (preview_row.status='running' AND j.state IN
                      ('running','retry_wait','cancel_requested')) OR
                    (preview_row.status='ready' AND j.state='succeeded') OR
                    (preview_row.status='failed' AND j.state IN
                      ('failed','dead_letter')) OR
                    (preview_row.status='cancelled' AND j.state='cancelled')
                  )
                  AND (
                    (preview_row.status<>'ready' AND result.id IS NULL) OR
                    (preview_row.status='ready'
                     AND (result.owner_id,result.workspace_id,result.novel_id)
                         IS NOT DISTINCT FROM
                         (preview_row.owner_id,preview_row.workspace_id,preview_row.novel_id)
                     AND result.kind='narration_voice_preview'
                     AND result.asset_class='preview'
                     AND result.state='ready'
                     AND result.retention_policy='temporary_preview'
                     AND result.expires_at IS NOT DISTINCT FROM preview_row.expires_at
                     AND result.duration_ms>0)
                  )
              ) THEN
                RAISE EXCEPTION
                  'voice preview profile/version/rights/job/media closure mismatch';
              END IF;
              RETURN NULL;
            END $$;
            """
        )
    )


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
              IF EXISTS (
                SELECT 1 FROM voice_previews p
                JOIN voice_profile_versions v ON v.id=p.version_id
                WHERE v.source_type<>'uploaded' OR p.reference_asset_id IS NULL
              ) THEN
                RAISE EXCEPTION
                  'T4 official preset preflight: legacy preview source is ambiguous';
              END IF;
            END $$;
            """
        )
    )
    op.alter_column(
        "voice_previews",
        "reference_asset_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=True,
    )
    _install_scope_guard()


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
              IF EXISTS (
                SELECT 1 FROM voice_previews WHERE reference_asset_id IS NULL
              ) OR EXISTS (
                SELECT 1 FROM voice_profile_versions v
                JOIN voice_rights_records r ON r.id=v.rights_record_id
                WHERE v.source_type='preset' AND r.source_kind='official_preset'
              ) THEN
                RAISE EXCEPTION
                  'T4 official preset downgrade refused: durable official preset evidence exists';
              END IF;
            END $$;
            """
        )
    )
    op.alter_column(
        "voice_previews",
        "reference_asset_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
    )
    # The 0021 function remains conservative for every surviving uploaded row.
    op.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION narration_guard_voice_preview_scope_v1()
            RETURNS trigger LANGUAGE plpgsql AS $$
            DECLARE preview_row voice_previews%ROWTYPE;
            BEGIN
              SELECT * INTO preview_row FROM voice_previews WHERE id=NEW.id;
              IF NOT FOUND THEN RETURN NULL; END IF;
              IF NOT EXISTS (
                SELECT 1
                FROM voice_profiles p
                JOIN voice_profile_versions v
                  ON v.id=preview_row.version_id AND v.profile_id=p.id
                JOIN voice_rights_records r ON r.id=preview_row.rights_record_id
                JOIN voice_reference_asset_links l
                  ON l.voice_version_id=v.id AND l.profile_id=p.id
                JOIN media_assets reference
                  ON reference.id=preview_row.reference_asset_id
                JOIN background_jobs j ON j.id=preview_row.job_id
                LEFT JOIN media_assets result
                  ON result.id=preview_row.result_asset_id
                WHERE p.id=preview_row.profile_id
                  AND (p.owner_id,p.workspace_id,p.novel_id) IS NOT DISTINCT FROM
                      (preview_row.owner_id,preview_row.workspace_id,preview_row.novel_id)
                  AND p.status IN ('draft','active')
                  AND (v.owner_id,v.workspace_id)=
                      (preview_row.owner_id,preview_row.workspace_id)
                  AND v.state IN ('draft','preview_ready','locked')
                  AND v.rights_record_id=r.id
                  AND v.reference_asset_id=preview_row.reference_asset_id
                  AND (r.owner_id,r.workspace_id,r.novel_id) IS NOT DISTINCT FROM
                      (preview_row.owner_id,preview_row.workspace_id,preview_row.novel_id)
                  AND (r.expires_at IS NULL OR r.expires_at>CURRENT_TIMESTAMP)
                  AND (v.source_type<>'uploaded' OR r.voice_cloning IS TRUE)
                  AND EXISTS (
                    SELECT 1 FROM voice_rights_events confirmed
                    WHERE confirmed.rights_record_id=r.id
                      AND confirmed.event_type='confirmed'
                  )
                  AND NOT EXISTS (
                    SELECT 1 FROM voice_rights_events e
                    WHERE e.rights_record_id=r.id
                      AND e.event_type IN ('revoked','expired','review_blocked')
                  )
                  AND l.rights_record_id=r.id
                  AND l.reference_asset_id=reference.id
                  AND (l.owner_id,l.workspace_id,l.novel_id) IS NOT DISTINCT FROM
                      (preview_row.owner_id,preview_row.workspace_id,preview_row.novel_id)
                  AND (reference.owner_id,reference.workspace_id,reference.novel_id)
                      IS NOT DISTINCT FROM
                      (preview_row.owner_id,preview_row.workspace_id,preview_row.novel_id)
                  AND reference.kind='narration_voice_reference'
                  AND reference.asset_class='voice_reference'
                  AND reference.state='ready'
                  AND reference.retention_policy='locked_voice'
                  AND (j.owner_id,j.workspace_id,j.novel_id) IS NOT DISTINCT FROM
                      (preview_row.owner_id,preview_row.workspace_id,preview_row.novel_id)
                  AND j.job_kind='narration.voice_preview'
                  AND j.resource_class='moss-nano'
                  AND j.request_id IS NULL
                  AND (
                    (preview_row.status='queued' AND j.state IN
                      ('queued','running','retry_wait','cancel_requested')) OR
                    (preview_row.status='running' AND j.state IN
                      ('running','retry_wait','cancel_requested')) OR
                    (preview_row.status='ready' AND j.state='succeeded') OR
                    (preview_row.status='failed' AND j.state IN
                      ('failed','dead_letter')) OR
                    (preview_row.status='cancelled' AND j.state='cancelled')
                  )
                  AND (
                    (preview_row.status<>'ready' AND result.id IS NULL) OR
                    (preview_row.status='ready'
                     AND (result.owner_id,result.workspace_id,result.novel_id)
                         IS NOT DISTINCT FROM
                         (preview_row.owner_id,preview_row.workspace_id,preview_row.novel_id)
                     AND result.kind='narration_voice_preview'
                     AND result.asset_class='preview'
                     AND result.state='ready'
                     AND result.retention_policy='temporary_preview'
                     AND result.expires_at IS NOT DISTINCT FROM preview_row.expires_at
                     AND result.duration_ms>0)
                  )
              ) THEN
                RAISE EXCEPTION
                  'voice preview profile/version/rights/job/media closure mismatch';
              END IF;
              RETURN NULL;
            END $$;
            """
        )
    )
