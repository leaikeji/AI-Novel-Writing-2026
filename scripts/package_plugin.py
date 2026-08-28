"""Create and audit the minimal QwenPaw plugin directory under build/."""

import os
from pathlib import Path
import re
import shutil
import stat


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "build" / "ai-novel-world-2026"
PLUGIN_COPY_IGNORE = shutil.ignore_patterns(
    "__pycache__",
    "*.pyc",
    "*.pyo",
    "*.map",
)
_FORBIDDEN_SUFFIXES = frozenset(
    {
        ".aac",
        ".bin",
        ".data",
        ".db",
        ".dump",
        ".flac",
        ".gguf",
        ".key",
        ".lock",
        ".m4a",
        ".mp3",
        ".onnx",
        ".ogg",
        ".opus",
        ".p12",
        ".pem",
        ".pfx",
        ".pt",
        ".pth",
        ".safetensors",
        ".secret",
        ".sshsig",
        ".sqlite",
        ".sqlite3",
        ".token",
        ".wav",
    }
)
_SECRET_MARKERS = (
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(rb"(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{20,}"),
    re.compile(rb"AKIA[0-9A-Z]{16}"),
    # Prompt codes are model-derived voice material.  Metadata-only manifests
    # may retain hashes and frame counts, but never the codes themselves.
    re.compile(rb'(?i)["\']?(?:prompt_audio_codes|prompt_codes)["\']?\s*[:=]'),
)
_MAX_AUDIT_FILE_BYTES = 64 * 1024 * 1024
_HOST_ONLY_EXACT_PATHS = frozenset(
    {
        "scripts/tts/chapter_e2e_browser_observer.py",
        "scripts/tts/chapter_e2e_collector.py",
        "scripts/tts/chapter_e2e_controller_build.py",
        "scripts/tts/chapter_e2e_controller_evidence.py",
        "scripts/tts/chapter_e2e_controller_host.py",
        "scripts/tts/chapter_e2e_controller_lifecycle.py",
        "scripts/tts/chapter_e2e_controller_signer.py",
        "scripts/tts/chapter_e2e_controller_trust.py",
        "scripts/tts/chapter_e2e_executor.py",
        "scripts/tts/chapter_e2e_listening.py",
        "scripts/tts/chapter_e2e_metric_chain.py",
        "scripts/tts/chapter_e2e_operator_envelope.py",
        "scripts/tts/chapter_e2e_probe_request.py",
        "scripts/tts/chapter_e2e_probes.py",
        "scripts/tts/chapter_e2e_readiness.py",
        "scripts/tts/chapter_e2e_runtime_audit.py",
        "scripts/tts/chapter_e2e_runtime_observer.py",
        "scripts/tts/diagnose_nano_short_text.py",
        "scripts/tts/generate_nano_strategy_preview.py",
        "scripts/tts/nano_short_regression.py",
        "scripts/tts/run_nano_short_regression.py",
        "scripts/tts/controller_node_runtime.py",
        "scripts/tts/controller_ssh_askpass.sh",
        "scripts/tts/provision_validation_token.py",
        "scripts/tts/local_chapter_e2e_container.py",
        "scripts/tts/run_chapter_e2e_real.py",
        "scripts/tts/run_local_chapter_e2e.py",
        "scripts/tts/run_local_operator_report.py",
        "scripts/tts/validate_chapter_e2e.py",
        "scripts/tts/verify_chapter_e2e_teardown.py",
        "tests/fixtures/narration/chapter-e2e-v2.json",
        "tests/fixtures/narration/chapter-e2e-v3.json",
        "tests/fixtures/narration/short-attribution-regression-v1.json",
    }
)
_HOST_ONLY_PREFIXES = (
    "scripts/tts/controller-node/",
    "scripts/tts/trust/controller_",
)
_HOST_ONLY_BASENAMES = frozenset(
    {
        "agent.sock",
        "controller_ed25519",
        "controller_ed25519.pub",
    }
)


class UnsafePackageInput(RuntimeError):
    """Raised with a stable code when package input is not public source."""


def _forbidden_name(path: Path) -> bool:
    name = path.name.lower()
    return (
        name == ".env"
        or name.startswith(".env.")
        or path.suffix.lower() in _FORBIDDEN_SUFFIXES
    )


def _host_only_output_path(path: Path) -> bool:
    try:
        relative = path.relative_to(OUTPUT).as_posix()
    except ValueError:
        return True
    return (
        relative in _HOST_ONLY_EXACT_PATHS
        or path.name in _HOST_ONLY_BASENAMES
        or any(
            relative == prefix.removesuffix("/") or relative.startswith(prefix)
            for prefix in _HOST_ONLY_PREFIXES
        )
    )


def _assert_safe_regular_file(path: Path) -> None:
    try:
        metadata = path.lstat()
    except OSError as error:
        raise UnsafePackageInput("PACKAGE_INPUT_UNREADABLE") from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise UnsafePackageInput("PACKAGE_INPUT_NOT_REGULAR")
    if _forbidden_name(path):
        raise UnsafePackageInput("PACKAGE_INPUT_SENSITIVE_NAME")


def _assert_safe_source_tree(source: Path) -> None:
    for current_root, directory_names, file_names in os.walk(
        source,
        topdown=True,
        followlinks=False,
    ):
        current = Path(current_root)
        for directory_name in tuple(directory_names):
            directory = current / directory_name
            if directory.is_symlink():
                raise UnsafePackageInput("PACKAGE_INPUT_NOT_REGULAR")
        for file_name in file_names:
            path = current / file_name
            if path.suffix.lower() == ".map":
                continue
            _assert_safe_regular_file(path)


def _audit_output() -> None:
    for current_root, directory_names, file_names in os.walk(
        OUTPUT,
        topdown=True,
        followlinks=False,
    ):
        current = Path(current_root)
        for directory_name in tuple(directory_names):
            directory = current / directory_name
            if _host_only_output_path(directory):
                raise UnsafePackageInput("PACKAGE_OUTPUT_HOST_ONLY_FORBIDDEN")
            if directory.is_symlink():
                raise UnsafePackageInput("PACKAGE_OUTPUT_NOT_REGULAR")
        for file_name in file_names:
            path = current / file_name
            if _host_only_output_path(path):
                raise UnsafePackageInput("PACKAGE_OUTPUT_HOST_ONLY_FORBIDDEN")
            try:
                metadata = path.lstat()
            except OSError as error:
                raise UnsafePackageInput("PACKAGE_OUTPUT_UNREADABLE") from error
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                raise UnsafePackageInput("PACKAGE_OUTPUT_NOT_REGULAR")
            if _forbidden_name(path) or path.suffix.lower() == ".map":
                raise UnsafePackageInput("PACKAGE_OUTPUT_SENSITIVE_NAME")
            if metadata.st_size > _MAX_AUDIT_FILE_BYTES:
                raise UnsafePackageInput("PACKAGE_OUTPUT_FILE_TOO_LARGE")
            try:
                contents = path.read_bytes()
            except OSError as error:
                raise UnsafePackageInput("PACKAGE_OUTPUT_UNREADABLE") from error
            if any(pattern.search(contents) is not None for pattern in _SECRET_MARKERS):
                raise UnsafePackageInput("PACKAGE_OUTPUT_SECRET_MARKER")


def copy_file(relative_path: str) -> None:
    source = ROOT / relative_path
    target = OUTPUT / relative_path
    if not source.is_file():
        raise FileNotFoundError(f"Required plugin file is missing: {source}")
    _assert_safe_regular_file(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def copy_tree(relative_path: str) -> None:
    source = ROOT / relative_path
    target = OUTPUT / relative_path
    if not source.is_dir():
        raise FileNotFoundError(f"Required plugin directory is missing: {source}")
    _assert_safe_source_tree(source)
    shutil.copytree(source, target, symlinks=True, ignore=PLUGIN_COPY_IGNORE)


def main() -> None:
    if OUTPUT.exists():
        shutil.rmtree(OUTPUT)
    OUTPUT.mkdir(parents=True)

    try:
        copy_file("plugin.json")
        copy_file("plugin.py")
        copy_file("requirements.txt")
        copy_file("alembic.ini")
        copy_file("scripts/tts/manage_digest_keyring.py")
        copy_file("scripts/tts/bootstrap_digest_keyring.py")
        copy_tree("backend")
        copy_tree("skills")
        copy_tree("frontend/dist")
        _audit_output()
    except Exception:
        shutil.rmtree(OUTPUT, ignore_errors=True)
        raise

    print(OUTPUT)


if __name__ == "__main__":
    main()
