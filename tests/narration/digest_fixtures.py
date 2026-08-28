"""Deterministic test-only HMAC keys; never imported by production code."""

from backend.narration.digest_keyring import DigestKeyring, HmacDigestKey


TEST_DIGEST_KEY = HmacDigestKey(
    key_id="narration-test-active-v1",
    secret=b"narration-test-only-hmac-key-material-v1",
)
TEST_DIGEST_KEYRING = DigestKeyring(
    active_key_id=TEST_DIGEST_KEY.key_id,
    keys={TEST_DIGEST_KEY.key_id: TEST_DIGEST_KEY},
)


__all__ = ["TEST_DIGEST_KEY", "TEST_DIGEST_KEYRING"]
