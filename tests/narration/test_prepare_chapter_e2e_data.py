from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Mapping
from urllib.parse import parse_qs, urlsplit
from uuid import NAMESPACE_URL, UUID, uuid5

import pytest

from backend.narration.official_presets import (
    OFFICIAL_PRESETS,
    official_preset_validation_tier,
    official_preset_version_fingerprint,
)
from scripts.tts import prepare_chapter_e2e_data as target


NOVEL_ID = uuid5(NAMESPACE_URL, "t4kd-test-novel")
DOCUMENT_ID = uuid5(NAMESPACE_URL, "t4kd-test-document")
LIN_WAN_ID = uuid5(NAMESPACE_URL, "t4kd-test-lin-wan")
SHEN_CHUAN_ID = uuid5(NAMESPACE_URL, "t4kd-test-shen-chuan")
EDITION_ID = uuid5(NAMESPACE_URL, "t4kd-test-edition")
OLD_EDITION_ID = uuid5(NAMESPACE_URL, "t4kd-test-old-edition")
REQUEST_ID = uuid5(NAMESPACE_URL, "t4kd-test-request")


def _identifier(label: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"t4kd-test:{label}"))


class FakeTransport:
    def __init__(self) -> None:
        self.calls: list[
            tuple[str, str, dict[str, str], bytes | None, int]
        ] = []
        self.profiles: dict[str, dict[str, object]] = {}
        self.profile_names: dict[str, str] = {}
        self.bindings: dict[str, dict[str, object]] = {}
        self.settings: dict[str, object] = {
            "contract_version": "narration-settings-api/1",
            "schema_version": "narration-settings/1",
            "novel_id": str(NOVEL_ID),
            "settings_id": None,
            "exists": False,
            "version": 0,
            "values": {
                "narrator": None,
                "language": "zh-CN",
                "output_format": "m4a_aac_lc",
                "script_review_policy": "blockers_only",
                "analysis_mode": "local_rules_only",
                "text_rules": {
                    "read_chapter_title": True,
                    "read_author_notes": False,
                    "read_section_breaks": True,
                    "first_person_mode": "narrator",
                    "first_person_character_id": None,
                    "inner_monologue_mode": "character",
                },
                "timing": {
                    "sentence_gap_ms": 250,
                    "paragraph_gap_ms": 600,
                    "section_gap_ms": 1000,
                },
                "casting": {
                    "anonymous_reuse_scope": "chapter",
                    "same_scene_voice_deduplication": True,
                    "unknown_speaker_action": "require_review",
                },
                "playback": {"playback_rate": 1.0, "volume": 1.0},
            },
            "updated_at": None,
        }
        self.current_edition_id = str(OLD_EDITION_ID)
        self.pointer_version = 4
        self.switch_response_overrides: dict[str, object] = {}

    @staticmethod
    def _json(payload: Mapping[str, object], status: int = 200) -> target.HttpResult:
        return target.HttpResult(
            status=status,
            headers={"content-type": "application/json"},
            body=json.dumps(payload, separators=(",", ":")).encode(),
        )

    def request(
        self,
        method: str,
        path: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None,
        maximum_bytes: int,
    ) -> target.HttpResult:
        copied = dict(headers)
        self.calls.append((method, path, copied, body, maximum_bytes))
        split = urlsplit(path)
        parts = split.path.strip("/").split("/")
        payload = json.loads(body) if body is not None else None

        if split.path == "/voice-presets":
            return self._json(
                {
                    "schema_version": "moss-tts-official-preset-catalog/2.0",
                    "items": [
                        {
                            "preset_id": preset.preset_id,
                            "display_name": preset.display_name,
                            "group": preset.group,
                            "language": preset.language,
                            "local_use_status": "available",
                            "commercial_distribution_status": "not_evaluated",
                            "validation_tier": official_preset_validation_tier(
                                preset.preset_id
                            ),
                            "language_scope": preset.language,
                            "selectable_now": True,
                            "previewable_now": True,
                            "renderable_existing": True,
                            "usage_notice": "private_local_writing_tool",
                            "provenance": preset.provenance(),
                        }
                        for preset in OFFICIAL_PRESETS
                    ],
                }
            )
        if split.path == "/voice-profiles" and method == "GET":
            return self._json({"items": list(self.profiles.values())})
        if split.path == "/voice-profiles" and method == "POST":
            assert isinstance(payload, dict)
            name = payload["name"]
            profile_id = _identifier(f"profile:{name}")
            profile = {
                "profile_id": profile_id,
                "novel_id": str(NOVEL_ID),
                "name": name,
                "status": "active",
                "version": 1,
                "current_version_id": None,
                "versions": [],
            }
            self.profiles[profile_id] = profile
            self.profile_names[str(name)] = profile_id
            return self._json(profile, 201)
        if len(parts) >= 2 and parts[0] == "voice-profiles":
            profile_id = parts[1]
            profile = self.profiles[profile_id]
            if len(parts) == 2 and method == "GET":
                return self._json(profile)
            if parts[2:] == ["versions", "preset"]:
                assert isinstance(payload, dict)
                version_number = len(profile["versions"]) + 1
                version_id = _identifier(
                    f"version:{profile_id}:{payload['preset_id']}:{version_number}"
                )
                preset = next(
                    item
                    for item in OFFICIAL_PRESETS
                    if item.preset_id == payload["preset_id"]
                )
                version = {
                    "version_id": version_id,
                    "profile_id": profile_id,
                    "version_number": version_number,
                    "source_type": "preset",
                    "preset_key": preset.preset_id,
                    "official_preset": preset.provenance(),
                    "fingerprint": official_preset_version_fingerprint(
                        profile_id=profile_id,
                        version_id=version_id,
                        preset_id=preset.preset_id,
                    ),
                    "state": "draft",
                }
                profile["versions"].append(version)
                profile["version"] = int(profile["version"]) + 1
                return self._json(version, 201)
            if parts[2:] == ["previews"]:
                assert isinstance(payload, dict)
                preview_id = _identifier(f"preview:{payload['version_id']}")
                asset_id = _identifier(f"asset:{payload['version_id']}")
                return self._json(
                    {
                        "preview_id": preview_id,
                        "profile_id": profile_id,
                        "version_id": payload["version_id"],
                        "status": "ready",
                        "asset": {
                            "asset_id": asset_id,
                            "content_path": f"/media-assets/{asset_id}/content",
                        },
                    },
                    202,
                )
            if parts[2:] == ["lock"]:
                assert isinstance(payload, dict)
                profile["version"] = int(profile["version"]) + 1
                profile["current_version_id"] = payload["version_id"]
                for item in profile["versions"]:
                    if item["version_id"] == payload["version_id"]:
                        item["state"] = "locked"
                return self._json(profile)
        if parts[0] == "media-assets":
            if copied.get("Range") == "bytes=0-0":
                return target.HttpResult(206, {"content-range": "bytes 0-0/12"}, b"R")
            sample = b"RIFF\x04\x00\x00\x00WAVE"
            digest = hashlib.sha256(sample).hexdigest()
            return target.HttpResult(
                200,
                {
                    "content-type": "audio/wav",
                    "content-length": str(len(sample)),
                    "accept-ranges": "bytes",
                    "etag": f'"{digest}"',
                },
                sample,
            )
        if parts[0] == "voice-previews":
            raise AssertionError("fake previews are immediately ready")
        if split.path.endswith("/voice-binding"):
            character_id = parts[3]
            current = self.bindings.get(
                character_id,
                {
                    "novel_id": str(NOVEL_ID),
                    "character_id": character_id,
                    "binding_policy": "unset",
                    "profile_id": None,
                    "version_id": None,
                    "language": "zh-CN",
                    "version": 0,
                },
            )
            if method == "GET":
                return self._json(current)
            assert isinstance(payload, dict)
            updated = {
                **current,
                **payload,
                "version": int(current["version"]) + 1,
            }
            updated.pop("expected_version")
            self.bindings[character_id] = updated
            return self._json(updated)
        if split.path.endswith("/narration-settings"):
            if method == "GET":
                return self._json(self.settings)
            assert isinstance(payload, dict)
            self.settings = {
                **self.settings,
                "settings_id": _identifier("settings"),
                "exists": True,
                "version": int(self.settings["version"]) + 1,
                "values": payload["values"],
            }
            return self._json(self.settings)
        if split.path.endswith("/narration-playback-context"):
            return self._json(
                {
                    "document_id": str(DOCUMENT_ID),
                    "novel_id": str(NOVEL_ID),
                    "working_copy_draft_version": 7,
                    "working_copy_content_hash": "a" * 64,
                    "current_edition_id": self.current_edition_id,
                    "pointer_version": self.pointer_version,
                }
            )
        if split.path.endswith("/current-narration-edition"):
            assert method == "PUT"
            assert payload == {
                "target_edition_id": str(EDITION_ID),
                "expected_version": self.pointer_version,
                "switch_mode": "next_playback",
                "start_segment_id": None,
                "playback_rate_millis": 1000,
                "confirmed": True,
            }
            self.current_edition_id = str(EDITION_ID)
            self.pointer_version += 1
            return self._json(
                {
                    "contract_version": "document-narration-context/1",
                    "document_id": str(DOCUMENT_ID),
                    "current_edition_id": self.current_edition_id,
                    "pointer_version": self.pointer_version,
                    "switch_mode": "next_playback",
                    "start_segment_id": None,
                    "manifest_revision": 1,
                    "playback_progress_id": None,
                    **self.switch_response_overrides,
                }
            )
        if split.path.endswith("/narration-requests") and method == "POST":
            return self._json(
                {
                    "request_id": str(REQUEST_ID),
                    "workflow_state": "ready",
                    "edition_id": str(EDITION_ID),
                    "current_manifest_revision": 1,
                },
                202,
            )
        if parts[0] == "narration-requests":
            raise AssertionError("fake baseline is immediately ready")
        if parts[0] == "narration-editions" and parts[-1] == "manifest":
            return self._json(
                {
                    "edition_id": str(EDITION_ID),
                    "manifest_revision": 1,
                    "segments": [{"render_status": "ready"}],
                }
            )
        raise AssertionError(f"unexpected request {method} {path}")


def _scope() -> target.T4KScope:
    return target.T4KScope(
        novel_id=NOVEL_ID,
        document_id=DOCUMENT_ID,
        lin_wan_character_id=LIN_WAN_ID,
        shen_chuan_character_id=SHEN_CHUAN_ID,
    )


def test_preview_stage_scopes_every_voice_route_and_never_commits() -> None:
    transport = FakeTransport()
    result = target.T4KDataClient(
        _scope(), "A" * 43, transport=transport, sleep=lambda _seconds: None
    ).prepare(timeout_seconds=30)

    assert result["status"] == "QUALITY_CONFIRMATION_REQUIRED"
    assert set(result["voices"]) == {"narrator", "lin_wan", "shen_chuan"}
    expected = {
        "narrator": {
            "name": "T4-K 专用旁白（official_preset）",
            "preset_id": "onnx.Zhiming",
            "sentinels": ("夜色从城西", "林晚推开旧书店", "沈川已经站在雨幕之外"),
        },
        "lin_wan": {
            "name": "T4-K 专用林晚（official_preset）",
            "preset_id": "onnx.Xiaoyu",
            "sentinels": ("沈川，我不是不相信你", "我要亲眼看见答案", "我都不会再逃"),
        },
        "shen_chuan": {
            "name": "T4-K 专用沈川（official_preset）",
            "preset_id": "onnx.Junhao",
            "sentinels": ("林晚，你先别急着回答我", "把手交给我", "陪你走到最后"),
        },
    }
    preview_texts: dict[str, str] = {}
    for role, contract in expected.items():
        voice = result["voices"][role]
        assert voice["preset_id"] == contract["preset_id"]
        profile = transport.profiles[voice["profile_id"]]
        assert profile["name"] == contract["name"]
        version = next(
            item
            for item in profile["versions"]
            if item["version_id"] == voice["version_id"]
        )
        assert version["preset_key"] == contract["preset_id"]
        preview_call = next(
            call
            for call in transport.calls
            if call[0] == "POST"
            and urlsplit(call[1]).path
            == f"/voice-profiles/{voice['profile_id']}/previews"
        )
        preview_payload = json.loads(preview_call[3])
        assert preview_payload["version_id"] == voice["version_id"]
        preview_text = preview_payload["preview_text"]
        assert len(preview_text) >= 100
        assert all(marker in preview_text for marker in contract["sentinels"])
        preview_texts[role] = preview_text
    assert len(set(preview_texts.values())) == 3
    assert not any(
        path.endswith("/lock?novel_id=" + str(NOVEL_ID))
        for _, path, *_ in transport.calls
    )
    assert not any(method == "PUT" for method, *_ in transport.calls)
    assert not any("narration-requests" in path for _, path, *_ in transport.calls)
    assert transport.bindings == {}
    assert transport.settings["values"]["narrator"] is None
    assert transport.current_edition_id == str(OLD_EDITION_ID)
    assert transport.pointer_version == 4
    assert all(
        profile["current_version_id"] is None
        and all(version["state"] == "draft" for version in profile["versions"])
        for profile in transport.profiles.values()
    )
    for _method, path, headers, body, _maximum in transport.calls:
        assert sum(key.lower() == target.VALIDATION_HEADER.lower() for key in headers) == 1
        assert headers[target.VALIDATION_HEADER] == "A" * 43
        assert "A" * 43 not in path
        assert body is None or b"A" * 43 not in body
        split = urlsplit(path)
        if split.path.startswith("/voice-"):
            assert parse_qs(split.query) == {"novel_id": [str(NOVEL_ID)]}
        if split.path.startswith("/media-assets/"):
            assert split.query == ""


def test_nondefault_same_preset_is_preserved_while_default_is_appended_and_reused() -> None:
    transport = FakeTransport()
    roles = (
        ("T4-K 专用旁白（official_preset）", "onnx.Zhiming"),
        ("T4-K 专用林晚（official_preset）", "onnx.Xiaoyu"),
        ("T4-K 专用沈川（official_preset）", "onnx.Junhao"),
    )
    legacy: dict[str, dict[str, object]] = {}
    for name, preset_id in roles:
        profile_id = _identifier(f"profile:{name}")
        version_id = _identifier(f"legacy-seed-zero:{profile_id}:{preset_id}")
        preset = next(
            item for item in OFFICIAL_PRESETS if item.preset_id == preset_id
        )
        old = {
            "version_id": version_id,
            "profile_id": profile_id,
            "version_number": 1,
            "source_type": "preset",
            "preset_key": preset_id,
            "official_preset": preset.provenance(),
            "fingerprint": "0" * 64,
            "state": "locked",
        }
        profile = {
            "profile_id": profile_id,
            "novel_id": str(NOVEL_ID),
            "name": name,
            "status": "active",
            "version": 2,
            "current_version_id": version_id,
            "versions": [old],
        }
        transport.profiles[profile_id] = profile
        transport.profile_names[name] = profile_id
        legacy[profile_id] = dict(old)

    client = target.T4KDataClient(
        _scope(), "D" * 43, transport=transport, sleep=lambda _seconds: None
    )
    first = client.prepare(timeout_seconds=30)

    assert first["status"] == "QUALITY_CONFIRMATION_REQUIRED"
    for voice in first["voices"].values():
        profile_id = str(voice["profile_id"])
        profile = transport.profiles[profile_id]
        assert len(profile["versions"]) == 2
        assert profile["versions"][0] == legacy[profile_id]
        appended = profile["versions"][1]
        assert appended["version_number"] == 2
        assert appended["version_id"] == voice["version_id"]
        assert appended["version_id"] != legacy[profile_id]["version_id"]
        assert appended["fingerprint"] == official_preset_version_fingerprint(
            profile_id=profile_id,
            version_id=str(appended["version_id"]),
            preset_id=str(voice["preset_id"]),
        )
        assert profile["current_version_id"] == legacy[profile_id]["version_id"]

    create_calls_after_first = [
        call
        for call in transport.calls
        if call[0] == "POST"
        and urlsplit(call[1]).path.endswith("/versions/preset")
    ]
    assert len(create_calls_after_first) == 3

    second = client.prepare(timeout_seconds=30)

    assert {
        role: values["version_id"] for role, values in second["voices"].items()
    } == {
        role: values["version_id"] for role, values in first["voices"].items()
    }
    assert len(
        [
            call
            for call in transport.calls
            if call[0] == "POST"
            and urlsplit(call[1]).path.endswith("/versions/preset")
        ]
    ) == 3
    for profile_id, old in legacy.items():
        assert transport.profiles[profile_id]["versions"][0] == old


def test_explicit_quality_confirmation_commits_two_bindings_and_baseline() -> None:
    transport = FakeTransport()
    client = target.T4KDataClient(
        _scope(), "B" * 43, transport=transport, sleep=lambda _seconds: None
    )
    result = client.prepare(
        quality_confirmation=target.QUALITY_CONFIRMATION,
        timeout_seconds=30,
    )

    assert result["status"] == "BASELINE_READY"
    assert result["baseline"] == {
        "request_id": str(REQUEST_ID),
        "edition_id": str(EDITION_ID),
        "manifest_revision": 1,
    }
    expected_presets = {
        "narrator": "onnx.Zhiming",
        "lin_wan": "onnx.Xiaoyu",
        "shen_chuan": "onnx.Junhao",
    }
    for role, preset_id in expected_presets.items():
        voice = result["voices"][role]
        assert voice["preset_id"] == preset_id
        profile = transport.profiles[voice["profile_id"]]
        assert profile["current_version_id"] == voice["version_id"]
        version = next(
            item
            for item in profile["versions"]
            if item["version_id"] == voice["version_id"]
        )
        assert version["preset_key"] == preset_id
        assert version["state"] == "locked"

    lin_wan_voice = result["voices"]["lin_wan"]
    lin_wan_binding = transport.bindings[str(LIN_WAN_ID)]
    assert lin_wan_binding["binding_policy"] == "dedicated"
    assert lin_wan_binding["profile_id"] == lin_wan_voice["profile_id"]
    assert lin_wan_binding["version_id"] == lin_wan_voice["version_id"]
    assert lin_wan_binding["language"] == "zh-CN"

    shen_chuan_voice = result["voices"]["shen_chuan"]
    shen_chuan_binding = transport.bindings[str(SHEN_CHUAN_ID)]
    assert shen_chuan_binding["binding_policy"] == "dedicated"
    assert shen_chuan_binding["profile_id"] == shen_chuan_voice["profile_id"]
    assert shen_chuan_binding["version_id"] == shen_chuan_voice["version_id"]
    assert shen_chuan_binding["language"] == "zh-CN"

    narrator_voice = result["voices"]["narrator"]
    assert transport.settings["values"]["narrator"] == {
        "profile_id": narrator_voice["profile_id"],
        "version_id": narrator_voice["version_id"],
    }
    calls = [(method, urlsplit(path).path) for method, path, *_ in transport.calls]
    assert sum(method == "POST" and path.endswith("/lock") for method, path in calls) == 3
    assert sum(method == "PUT" and path.endswith("/voice-binding") for method, path in calls) == 2
    assert ("PUT", f"/novels/{NOVEL_ID}/narration-settings") in calls
    assert ("POST", f"/documents/{DOCUMENT_ID}/narration-requests") in calls
    switch_path = f"/documents/{DOCUMENT_ID}/current-narration-edition"
    assert calls.count(("PUT", switch_path)) == 1
    context_path = f"/documents/{DOCUMENT_ID}/narration-playback-context"
    assert calls.count(("GET", context_path)) == 3
    assert ("GET", f"/narration-editions/{EDITION_ID}/manifest") in calls
    assert transport.current_edition_id == str(EDITION_ID)
    assert transport.pointer_version == 5

    second = client.prepare(
        quality_confirmation=target.QUALITY_CONFIRMATION,
        timeout_seconds=30,
    )

    assert second["baseline"] == result["baseline"]
    calls = [(method, urlsplit(path).path) for method, path, *_ in transport.calls]
    assert calls.count(("PUT", switch_path)) == 1
    assert calls.count(("GET", context_path)) == 5
    assert transport.current_edition_id == str(EDITION_ID)
    assert transport.pointer_version == 5


def test_baseline_rejects_a_noncanonical_edition_switch_response() -> None:
    transport = FakeTransport()
    transport.switch_response_overrides["pointer_version"] = 99

    with pytest.raises(
        target.T4KDataError, match="DOCUMENT_EDITION_SWITCH_INVALID"
    ):
        target.T4KDataClient(
            _scope(), "E" * 43, transport=transport, sleep=lambda _seconds: None
        ).prepare(
            quality_confirmation=target.QUALITY_CONFIRMATION,
            timeout_seconds=30,
        )


def test_listening_samples_are_private_exact_wav_files(tmp_path: Path) -> None:
    destination = tmp_path / "samples"
    transport = FakeTransport()
    client = target.T4KDataClient(
        _scope(), "S" * 43, transport=transport, sleep=lambda _seconds: None
    )
    result = client.prepare(timeout_seconds=30)

    names = client.write_listening_samples(result["voices"], destination)

    assert names == ("narrator.wav", "lin_wan.wav", "shen_chuan.wav")
    assert destination.stat().st_mode & 0o777 == 0o700
    for name in names:
        sample = destination / name
        assert sample.stat().st_mode & 0o777 == 0o600
        assert sample.read_bytes() == b"RIFF\x04\x00\x00\x00WAVE"
    full_media_calls = [
        (path, headers)
        for method, path, headers, _body, maximum in transport.calls
        if method == "GET"
        and path.startswith("/media-assets/")
        and maximum == target.MAX_LISTENING_SAMPLE_BYTES
    ]
    assert len(full_media_calls) == 3
    assert all("?" not in path for path, _headers in full_media_calls)


def test_client_rejects_unscoped_voice_routes_and_arbitrary_targets() -> None:
    client = target.T4KDataClient(_scope(), "C" * 43, transport=FakeTransport())
    with pytest.raises(target.T4KDataError, match="VOICE_ROUTE_SCOPE_REQUIRED"):
        client._request("GET", "/voice-presets")
    with pytest.raises(target.T4KDataError, match="HTTP_ROUTE_NOT_ALLOWED"):
        client._request("GET", "http://example.com/voice-presets")
    with pytest.raises(target.T4KDataError, match="HTTP_METHOD_NOT_ALLOWED"):
        client._request("DELETE", "/voice-presets")
    with pytest.raises(target.T4KDataError, match="HTTP_ROUTE_NOT_ALLOWED"):
        client._request(
            "PUT",
            f"/documents/{_identifier('other-document')}/current-narration-edition",
            payload={},
        )


def test_cli_has_no_url_import_or_database_escape_hatches() -> None:
    destinations = {action.dest for action in target.build_parser()._actions}
    assert {
        "base_url",
        "url",
        "host",
        "port",
        "import_path",
        "executor_import",
        "database_url",
        "db_url",
    }.isdisjoint(destinations)


def test_main_reuses_private_token_reader_and_emits_no_secret_or_path(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    with tempfile.TemporaryDirectory(prefix="t4kd-token-") as raw_directory:
        directory = Path(raw_directory)
        directory.chmod(0o700)
        token_file = directory / "token"
        token = "D" * 43
        token_file.write_text(token, encoding="ascii")
        token_file.chmod(0o600)
        assert os.stat(token_file).st_nlink == 1

        def fake_prepare(
            self: target.T4KDataClient, **_values: object
        ) -> dict[str, object]:
            assert self._token == token
            return {
                "schema_version": "t4-k-data-preparation/1.0",
                "status": "QUALITY_CONFIRMATION_REQUIRED",
                "secret_values_emitted": False,
                "request_bodies_emitted": False,
            }

        monkeypatch.setattr(target.T4KDataClient, "prepare", fake_prepare)
        exit_code = target.main(
            [
                "--token-file",
                str(token_file),
                "--novel-id",
                str(NOVEL_ID),
                "--document-id",
                str(DOCUMENT_ID),
                "--lin-wan-character-id",
                str(LIN_WAN_ID),
                "--shen-chuan-character-id",
                str(SHEN_CHUAN_ID),
            ]
        )

    output = capsys.readouterr()
    assert exit_code == 2
    assert token not in output.out + output.err
    assert str(token_file) not in output.out + output.err
    assert "QUALITY_CONFIRMATION_REQUIRED" in output.out
