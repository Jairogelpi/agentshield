# tests/test_entropy.py
"""Tests for the entropy scanning functionality in PII Guard."""
import pytest

from app.services.pii_guard import PIIEngine


class TestEntropyScanner:
    """Test the _entropy_scan method of PIIEngine."""

    def test_low_entropy_pass(self):
        """Test that normal text is NOT redacted."""
        engine = PIIEngine()
        text = "Hello world this is a normal sentence."
        result = engine._entropy_scan(text)
        assert result == text

    def test_high_entropy_detection(self):
        """Test that high entropy secrets are blocked."""
        engine = PIIEngine()
        # A high entropy string like an API key (long random characters)
        secret = "sk-proj-8Xk9LmN2pQwErTyUiOpAsdf1234567890qwertyuiopasdf"
        text = f"My secret key is {secret}"
        result = engine._entropy_scan(text)
        
        # Should contain redaction marker
        assert "<SECRET_REDACTED>" in result
        # Original secret should be removed
        assert secret not in result

    def test_short_tokens_pass(self):
        """Test that short tokens (< 8 chars) pass through."""
        engine = PIIEngine()
        text = "abc123 test OK"
        result = engine._entropy_scan(text)
        assert result == text

    def test_urls_pass_through(self):
        """Test that URLs are not flagged as high entropy."""
        engine = PIIEngine()
        text = "Visit https://example.com/page for more info"
        result = engine._entropy_scan(text)
        assert "https://example.com/page" in result
