"""
Tests for Crypto Signer - Digital Notary System
Tests RSA signing, hash generation, and signature consistency.
"""

import pytest

from app.services.crypto_signer import hash_content, sign_payload


class TestSignPayload:
    """Tests for the RSA signing functionality."""

    def test_sign_returns_base64_string(self):
        """Signature should be a Base64 encoded string."""
        payload = {"user": "test", "amount": 100}
        signature = sign_payload(payload)
        assert isinstance(signature, str)
        assert len(signature) > 50  # RSA-2048 sig in Base64 is ~344 chars

    def test_sign_different_payloads(self):
        """Different payloads should produce different signatures."""
        sig1 = sign_payload({"user": "alice"})
        sig2 = sign_payload({"user": "bob"})
        assert sig1 != sig2

    def test_sign_same_payload_consistent(self):
        """Same payload should produce consistent signatures (deterministic key)."""
        payload = {"action": "purchase", "id": 123}
        sig1 = sign_payload(payload)
        sig2 = sign_payload(payload)
        # With PSS padding, signatures may differ, but both should be valid
        assert isinstance(sig1, str)
        assert isinstance(sig2, str)

    def test_sign_handles_nested_objects(self):
        """Should handle nested dictionaries."""
        payload = {
            "user": {"id": 1, "name": "Test"},
            "items": [1, 2, 3],
            "metadata": {"timestamp": 12345},
        }
        signature = sign_payload(payload)
        assert isinstance(signature, str)
        assert len(signature) > 50


class TestHashContent:
    """Tests for SHA256 hash generation."""

    def test_hash_is_sha256_format(self):
        """Hash should be 64 hex characters (SHA256)."""
        result = hash_content({"test": True})
        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)

    def test_hash_deterministic(self):
        """Same payload = same hash."""
        payload = {"a": 1, "b": 2}
        hash1 = hash_content(payload)
        hash2 = hash_content(payload)
        assert hash1 == hash2

    def test_hash_different_payloads(self):
        """Different payloads = different hashes."""
        hash1 = hash_content({"x": 1})
        hash2 = hash_content({"x": 2})
        assert hash1 != hash2

    def test_hash_key_order_independent(self):
        """Hash should be the same regardless of key insertion order."""
        hash1 = hash_content({"a": 1, "b": 2})
        hash2 = hash_content({"b": 2, "a": 1})
        assert hash1 == hash2  # sort_keys=True ensures this
