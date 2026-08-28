"""Verify the immutable T1-DEP Linux/arm64 dependency layer."""

from __future__ import annotations

import ctypes
import copy
import hashlib
from importlib import import_module, metadata
import json
from pathlib import Path, PurePosixPath
import platform
import re
import subprocess
from urllib.parse import urlsplit


EXPECTED_PACKAGES = {
    "fastapi": "0.141.1",
    "numpy": "2.3.3",
    "onnxruntime": "1.24.3",
    "soundfile": "0.14.0",
    "torch": "2.7.0",
    "torchaudio": "2.7.0",
    "transformers": "4.57.1",
    "uvicorn": "0.52.4",
}
IMPORT_NAMES = {
    "fastapi": "fastapi",
    "numpy": "numpy",
    "onnxruntime": "onnxruntime",
    "soundfile": "soundfile",
    "torch": "torch",
    "torchaudio": "torchaudio",
    "transformers": "transformers",
    "uvicorn": "uvicorn",
}
EXPECTED_FILES = {
    "/opt/ffmpeg/bin/ffmpeg": "13bf31d7ca85cc26ae5fd783183af3dfc7512fd60eb38326117b14cf03747ed3",
    "/opt/ffmpeg/bin/ffprobe": "3bb9de3597ee5bada04172e201b9df434be5d3c8076f20c0460867d07716b47d",
    "/opt/ffmpeg/licenses/COPYING.LGPLv2.1": "246041b6ecf9bc32d718a62c57877c78b5eb397b6467e74ed7ae2626ab189c30",
    "/opt/ffmpeg/licenses/LICENSE.md": "2e1d16c72fd74e12063776371da757322f8b77589386532f4fd8634bde7de1af",
    "/usr/lib/aarch64-linux-gnu/libgomp.so.1": "9d8c6a6175f6a7cda286c80f4de577edd58077ac3f4102356ec546869d170d30",
}
REQUIRED_FFMPEG_FLAGS = {
    "--disable-network",
    "--disable-autodetect",
    "--disable-gpl",
    "--disable-version3",
    "--disable-nonfree",
    "--enable-decoder=aac",
    "--enable-encoder=aac",
    "--enable-encoder=flac",
    "--enable-muxer=wav",
    "--enable-muxer=flac",
    "--enable-muxer=ipod",
}
FORBIDDEN_FFMPEG_FLAGS = {"--enable-gpl", "--enable-version3", "--enable-nonfree", "--enable-network"}
MODEL_SOURCE_LOCK = Path("/opt/ai-novel-world/tts-sidecar/model-source.lock.json")
EXPECTED_SOURCE_LOCK_SHA256 = "0485cdfb15eb01f7c4c0f65049f1c477fb6391ec523c5b7159ab25f763ab469d"
EXPECTED_INVENTORY_SHA256 = "d0f173dbc661d0352825dd28a5b35a1c65d60be540badacf7ef3b1a57b0b416d"
EXPECTED_SOURCE_TREE_SHA256 = "547f61c24427a59d802cc31dfe532e135303b6b9f71469be19a7f35acd5d4c94"
EXPECTED_MODEL_TREE_SHA256 = "92419b269673cd698afab06ef0e3f0b60673862c86190cc6c57ed010db9aca98"
EXPECTED_OFFICIAL_PRESET_MANIFEST_SHA256 = (
    "097d80e993dc29f0bae427590b4f77084a161cb578b50d82c29f455d5faa9eee"
)
EXPECTED_OFFICIAL_PRESET_COUNT = 18
EXPECTED_OFFICIAL_PRESET_QUANTIZER_COUNT = 16
EXPECTED_COMPONENTS = {
    "moss-tts-nano-source": {
        "provider": "github",
        "repository": "OpenMOSS/MOSS-TTS-Nano",
        "revision": "cc7bdf19c7639c0870dab22045a33b442760f6be",
        "artifact_count": 13,
    },
    "moss-tts-nano-100m-onnx": {
        "provider": "huggingface",
        "repository": "OpenMOSS-Team/MOSS-TTS-Nano-100M-ONNX",
        "revision": "f52645cb467506d8e18e746ddd59482685b74e58",
        "artifact_count": 10,
    },
    "moss-audio-tokenizer-nano-onnx": {
        "provider": "huggingface",
        "repository": "OpenMOSS-Team/MOSS-Audio-Tokenizer-Nano-ONNX",
        "revision": "ceff0d0749bfb3fa2d61149794ec6feef0d1e1ae",
        "artifact_count": 6,
    },
}
EXPECTED_COMPONENT_ORDER = list(EXPECTED_COMPONENTS)
HEX_PATTERN = re.compile(r"^[0-9a-f]+$")
OFFICIAL_PRESET_MANIFEST_KEYS = {
    "builtin_voices",
    "format_version",
    "generation_defaults",
    "model_files",
    "prompt_templates",
    "text_samples",
    "tts_config",
}
OFFICIAL_PRESET_ROW_KEYS = {
    "voice",
    "display_name",
    "group",
    "audio_file",
    "prompt_audio_codes",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_official_preset_manifest(path: Path) -> dict[str, object]:
    """Return only non-sensitive count/hash evidence for the fixed manifest."""

    try:
        raw = path.read_bytes()
    except OSError as error:
        raise SystemExit("official preset manifest is unavailable") from error
    if not (1 <= len(raw) <= 1024 * 1024):
        raise SystemExit("official preset manifest size mismatch")
    actual_sha256 = hashlib.sha256(raw).hexdigest()
    if actual_sha256 != EXPECTED_OFFICIAL_PRESET_MANIFEST_SHA256:
        raise SystemExit("official preset manifest raw hash mismatch")
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SystemExit("official preset manifest JSON mismatch") from error
    if (
        not isinstance(manifest, dict)
        or set(manifest) != OFFICIAL_PRESET_MANIFEST_KEYS
        or not isinstance(manifest.get("builtin_voices"), list)
        or isinstance(manifest.get("format_version"), bool)
        or not isinstance(manifest.get("format_version"), int)
        or not isinstance(manifest.get("generation_defaults"), dict)
        or not isinstance(manifest.get("model_files"), dict)
        or not isinstance(manifest.get("prompt_templates"), dict)
        or not isinstance(manifest.get("text_samples"), list)
        or not isinstance(manifest.get("tts_config"), dict)
    ):
        raise SystemExit("official preset manifest schema mismatch")
    rows = manifest["builtin_voices"]
    if len(rows) != EXPECTED_OFFICIAL_PRESET_COUNT:
        raise SystemExit("official preset manifest count mismatch")
    seen: set[str] = set()
    metadata_rows: list[dict[str, object]] = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != OFFICIAL_PRESET_ROW_KEYS:
            raise SystemExit("official preset row schema mismatch")
        voice = row["voice"]
        if not isinstance(voice, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,59}", voice):
            raise SystemExit("official preset voice mismatch")
        preset_id = f"onnx.{voice}"
        if preset_id in seen:
            raise SystemExit("official preset voice duplicate")
        seen.add(preset_id)
        if any(
            not isinstance(row[field], str) or not row[field]
            for field in ("display_name", "group", "audio_file")
        ) or Path(row["audio_file"]).name != row["audio_file"]:
            raise SystemExit("official preset metadata mismatch")
        codes = row["prompt_audio_codes"]
        if (
            not isinstance(codes, list)
            or not codes
            or any(
                not isinstance(frame, list)
                or len(frame) != EXPECTED_OFFICIAL_PRESET_QUANTIZER_COUNT
                or any(isinstance(code, bool) or not isinstance(code, int) for code in frame)
                for frame in codes
            )
        ):
            raise SystemExit("official preset prompt shape mismatch")
        metadata_rows.append(
            {
                "preset_id": preset_id,
                "prompt_frame_count": len(codes),
                "prompt_codes_sha256": canonical_sha256(codes),
            }
        )
    return {
        "preset_count": len(metadata_rows),
        "manifest_sha256": actual_sha256,
        "metadata_sha256": canonical_sha256(metadata_rows),
    }


def validate_model_source_lock(path: Path) -> dict[str, object]:
    lock = json.loads(path.read_text(encoding="utf-8"))
    if lock.get("schema_version") != "moss-tts-t1-dep-model-source-lock/1.1":
        raise SystemExit("model/source lock schema mismatch")
    if lock.get("source_lock_sha256") != EXPECTED_SOURCE_LOCK_SHA256:
        raise SystemExit("model/source T0 provenance mismatch")
    if lock.get("component_count") != 3 or lock.get("artifact_count") != 29:
        raise SystemExit("model/source lock count mismatch")
    if lock.get("allowed_component_ids") != EXPECTED_COMPONENT_ORDER:
        raise SystemExit("model/source component allowlist mismatch")

    components = lock.get("components")
    if not isinstance(components, list) or [row.get("component_id") for row in components] != EXPECTED_COMPONENT_ORDER:
        raise SystemExit("model/source components are missing, duplicated, reordered or unapproved")

    observed_artifacts = 0
    for component in components:
        component_id = component["component_id"]
        expected = EXPECTED_COMPONENTS[component_id]
        for field in ("provider", "repository", "revision"):
            if component.get(field) != expected[field]:
                raise SystemExit(f"{component_id} {field} mismatch")
        revision = component["revision"]
        if len(revision) != 40 or not HEX_PATTERN.fullmatch(revision):
            raise SystemExit(f"{component_id} revision is not a fixed lowercase git SHA")
        if component.get("download_allowed") is not True:
            raise SystemExit(f"{component_id} is not approved for controlled download")
        license_row = component.get("license")
        if not isinstance(license_row, dict) or not str(license_row.get("status", "")).startswith("verified"):
            raise SystemExit(f"{component_id} license metadata is not verified")
        artifacts = component.get("artifacts")
        if not isinstance(artifacts, list) or len(artifacts) != expected["artifact_count"]:
            raise SystemExit(f"{component_id} artifact count mismatch")
        observed_artifacts += len(artifacts)
        seen_paths: set[str] = set()
        selected_bytes = 0
        for artifact in artifacts:
            if not isinstance(artifact, dict) or set(artifact) != {"path", "url", "size", "hash", "hash_algorithm"}:
                raise SystemExit(f"{component_id} artifact fields mismatch")
            relative = artifact["path"]
            if not isinstance(relative, str) or not relative or "\0" in relative or "\\" in relative:
                raise SystemExit(f"{component_id} artifact path is invalid")
            posix = PurePosixPath(relative)
            if posix.is_absolute() or str(posix) != relative or any(part in {"", ".", ".."} for part in posix.parts):
                raise SystemExit(f"{component_id} artifact path is not canonical relative POSIX")
            if relative in seen_paths:
                raise SystemExit(f"{component_id} artifact path is duplicated")
            seen_paths.add(relative)

            url = artifact["url"]
            parsed = urlsplit(url) if isinstance(url, str) else None
            if parsed is None or parsed.scheme != "https" or not parsed.netloc or parsed.query or parsed.fragment:
                raise SystemExit(f"{component_id} artifact URL is not fixed HTTPS")
            if revision not in url:
                raise SystemExit(f"{component_id} artifact URL does not contain its frozen revision")

            size = artifact["size"]
            if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
                raise SystemExit(f"{component_id} artifact size is invalid")
            selected_bytes += size
            algorithm = artifact["hash_algorithm"]
            digest = artifact["hash"]
            expected_length = 64 if algorithm == "sha256" else 40 if algorithm == "git-blob-sha1" else 0
            if expected_length == 0 or not isinstance(digest, str) or len(digest) != expected_length or not HEX_PATTERN.fullmatch(digest):
                raise SystemExit(f"{component_id} artifact hash is invalid")
        if selected_bytes != component.get("selected_bytes"):
            raise SystemExit(f"{component_id} selected_bytes mismatch")

    if observed_artifacts != 29:
        raise SystemExit("model/source observed artifact count mismatch")
    canonical_components = []
    for component in sorted(components, key=lambda row: row["component_id"]):
        normalized = copy.deepcopy(component)
        normalized["artifacts"] = sorted(normalized["artifacts"], key=lambda row: row["path"])
        canonical_components.append(normalized)
    inventory_sha256 = canonical_sha256({"components": canonical_components})
    inventory = lock.get("inventory")
    if not isinstance(inventory, dict) or inventory.get("algorithm") != "sha256":
        raise SystemExit("model/source inventory algorithm mismatch")
    if inventory.get("sha256") != EXPECTED_INVENTORY_SHA256 or inventory_sha256 != EXPECTED_INVENTORY_SHA256:
        raise SystemExit("model/source canonical inventory mismatch")
    trees = lock.get("runtime_tree_canonicalization")
    if not isinstance(trees, dict):
        raise SystemExit("runtime tree canonicalization is missing")
    if trees.get("source_tree_sha256") != EXPECTED_SOURCE_TREE_SHA256:
        raise SystemExit("source runtime tree hash mismatch")
    if trees.get("model_tree_sha256") != EXPECTED_MODEL_TREE_SHA256:
        raise SystemExit("model runtime tree hash mismatch")
    return {
        "component_count": 3,
        "artifact_count": 29,
        "inventory_sha256": inventory_sha256,
        "source_tree_sha256": EXPECTED_SOURCE_TREE_SHA256,
        "model_tree_sha256": EXPECTED_MODEL_TREE_SHA256,
    }


def main() -> None:
    if platform.system() != "Linux" or platform.machine() != "aarch64":
        raise SystemExit("runtime must be Linux/aarch64")

    model_source_inventory = validate_model_source_lock(MODEL_SOURCE_LOCK)
    package_versions: dict[str, str] = {}
    for distribution, expected in EXPECTED_PACKAGES.items():
        actual = metadata.version(distribution)
        if actual != expected:
            raise SystemExit(f"{distribution} version mismatch: {actual}")
        import_module(IMPORT_NAMES[distribution])
        package_versions[distribution] = actual

    ctypes.CDLL("libgomp.so.1")
    file_hashes: dict[str, str] = {}
    for raw_path, expected in EXPECTED_FILES.items():
        path = Path(raw_path)
        actual = sha256(path)
        if actual != expected:
            raise SystemExit(f"runtime file hash mismatch: {path.name}")
        file_hashes[path.name] = actual

    version = subprocess.run(
        ["/opt/ffmpeg/bin/ffmpeg", "-version"], check=True, capture_output=True, text=True
    ).stdout.splitlines()[0]
    if not version.startswith("ffmpeg version 9.0.1"):
        raise SystemExit(f"FFmpeg version mismatch: {version}")
    probe_version = subprocess.run(
        ["/opt/ffmpeg/bin/ffprobe", "-version"], check=True, capture_output=True, text=True
    ).stdout.splitlines()[0]
    if not probe_version.startswith("ffprobe version 9.0.1"):
        raise SystemExit(f"FFprobe version mismatch: {probe_version}")
    buildconf = subprocess.run(
        ["/opt/ffmpeg/bin/ffmpeg", "-buildconf"], check=True, capture_output=True, text=True
    ).stdout
    missing = sorted(flag for flag in REQUIRED_FFMPEG_FLAGS if flag not in buildconf)
    forbidden = sorted(flag for flag in FORBIDDEN_FFMPEG_FLAGS if flag in buildconf)
    if missing or forbidden:
        raise SystemExit(f"FFmpeg buildconf mismatch: missing={missing}, forbidden={forbidden}")

    print(
        json.dumps(
            {
                "schema_version": "moss-tts-t1-dep-runtime-verification/1.0",
                "status": "passed",
                "platform": "linux/arm64",
                "packages": package_versions,
                "runtime_file_sha256": file_hashes,
                "ffmpeg_version": version,
                "ffprobe_version": probe_version,
                "ffmpeg_required_flags": sorted(REQUIRED_FFMPEG_FLAGS),
                "business_runtime_installed": False,
                "model_or_source_bytes_in_image": False,
                "model_source_inventory": model_source_inventory,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
