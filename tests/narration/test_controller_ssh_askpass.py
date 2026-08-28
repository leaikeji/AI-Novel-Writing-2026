from __future__ import annotations

from pathlib import Path
import stat
import subprocess

import scripts.tts.chapter_e2e_controller_signer as signer_module


HELPER = Path(signer_module.PACKAGED_ASKPASS_PATH)


def _run_without_gui(*arguments: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [str(HELPER), *arguments],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={"LANG": "C", "LC_ALL": "C", "PATH": "/usr/bin:/bin"},
        timeout=5,
        check=False,
    )


def test_packaged_helper_is_fixed_owned_executable_and_first_candidate() -> None:
    details = HELPER.lstat()
    assert HELPER.is_absolute()
    assert stat.S_ISREG(details.st_mode)
    assert not stat.S_ISLNK(details.st_mode)
    assert stat.S_IMODE(details.st_mode) == 0o755
    assert signer_module.FIXED_ASKPASS_CANDIDATES[0] == HELPER


def test_unknown_missing_or_extra_prompt_fails_without_opening_gui() -> None:
    for arguments in (
        (),
        ("unknown prompt",),
        (
            "Enter passphrase for /tmp/arbitrary-key: ",
        ),
        (
            "Allow use of key attacker?\nKey fingerprint not-sha256.",
        ),
        ("one", "two"),
    ):
        completed = _run_without_gui(*arguments)
        assert completed.returncode != 0
        assert completed.stdout == b""
        assert completed.stderr == b""


def test_helper_has_fixed_hidden_passphrase_and_yes_no_confirmation_protocol() -> None:
    source = HELPER.read_text(encoding="utf-8")

    assert source.count("/usr/bin/osascript") == 2
    assert "with hidden answer" in source
    assert 'buttons {"拒绝", "允许"}' in source
    assert 'return "yes"' in source
    assert 'return "no"' in source
    assert 'cancel button "取消"' in source
    assert "SSH_AUTH_SOCK" not in source
    assert "logger" not in source
    assert "tee " not in source
    assert "eval " not in source
    assert "osascript -e" not in source


def test_helper_shell_syntax_is_valid() -> None:
    completed = subprocess.run(
        ["/bin/sh", "-n", str(HELPER)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=5,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr.decode(
        "utf-8", errors="replace"
    )
