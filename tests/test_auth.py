"""
Tests for Authentication Logic - JWT & API Key validation.
"""

import pytest

from app.logic import ALGORITHM, create_aut_token, sign_receipt


class TestTokenCreation:
    """Tests for JWT token creation."""

    def test_token_is_string(self):
        """Token should be a string."""
        token = create_aut_token({"tenant_id": "test123"})
        assert isinstance(token, str)

    def test_token_is_jwt_format(self):
        """Token should have JWT format (3 parts separated by dots)."""
        token = create_aut_token({"user_id": "user456"})
        parts = token.split(".")
        assert len(parts) == 3

    def test_token_length(self):
        """Token should have reasonable length."""
        token = create_aut_token({"data": "test"})
        assert len(token) > 50

    def test_different_data_different_tokens(self):
        """Different payloads should produce different tokens."""
        token1 = create_aut_token({"id": "1"})
        token2 = create_aut_token({"id": "2"})
        assert token1 != token2


class TestReceiptSigning:
    """Tests for receipt signing."""

    def test_signed_receipt_is_string(self):
        """Signed receipt should be a string."""
        receipt = sign_receipt({"amount": 100, "model": "gpt-4"})
        assert isinstance(receipt, str)

    def test_signed_receipt_is_jwt(self):
        """Signed receipt should be JWT format."""
        receipt = sign_receipt({"cost": 0.05})
        parts = receipt.split(".")
        assert len(parts) == 3

    def test_complex_receipt(self):
        """Should handle complex receipt data."""
        receipt = sign_receipt(
            {
                "transaction_id": "tx_123",
                "amount": 0.0523,
                "tokens": {"input": 150, "output": 200},
                "model": "gpt-4-turbo",
                "timestamp": 1705789200,
            }
        )
        assert isinstance(receipt, str)
        assert len(receipt) > 50


class TestAlgorithm:
    """Tests for algorithm configuration."""

    def test_algorithm_is_hs256(self):
        """Algorithm should be HS256."""
        assert ALGORITHM == "HS256"
