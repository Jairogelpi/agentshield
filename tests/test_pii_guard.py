"""
Tests for PII Guard - Core Security Layer
Tests regex patterns, entropy scanner, and custom rules.
"""

import pytest

from app.services.pii_guard import fast_regex_scrub, pii_guard


class TestRegexScrubber:
    """Tests for the Rust-powered regex scrubber."""

    def test_email_redaction(self):
        """Emails should be redacted."""
        text = "Contact me at john@example.com please"
        result = fast_regex_scrub(text)
        assert "john@example.com" not in result

    def test_credit_card_redaction(self):
        """Credit card numbers should be redacted."""
        text = "My card is 4111-1111-1111-1111"
        result = fast_regex_scrub(text)
        assert "4111-1111-1111-1111" not in result

    def test_phone_number_redaction(self):
        """Phone numbers should be redacted."""
        text = "Call me at +1-555-123-4567"
        result = fast_regex_scrub(text)
        assert "555-123-4567" not in result

    def test_normal_text_unchanged(self):
        """Normal text without PII should pass through."""
        text = "Hello world, this is a normal sentence."
        result = fast_regex_scrub(text)
        # Should be mostly unchanged (no PII to remove)
        assert "Hello" in result
        assert "normal" in result


class TestEntropyScanner:
    """Tests for the entropy-based secret detection."""

    def test_low_entropy_pass(self):
        """Normal text has low entropy and should NOT be redacted."""
        text = "Hello world this is a normal sentence."
        result = pii_guard._entropy_scan(text)
        assert text == result

    def test_high_entropy_detection(self):
        """High entropy strings (API keys) should be blocked."""
        secret = "sk-proj-89823982398293d9823_ABS"
        text = f"My secret key is {secret}"
        result = pii_guard._entropy_scan(text)
        assert "<SECRET_REDACTED>" in result
        assert secret not in result

    def test_mixed_content(self):
        """Mix of normal text and secrets."""
        text = "Here is a password: 7F9a#99!xL and here is a dog."
        result = pii_guard._entropy_scan(text)
        assert "Here is a password:" in result
        assert "and here is a dog." in result
        assert "<SECRET_REDACTED>" in result


class TestPIIGuardScan:
    """Tests for the full scan pipeline."""

    def test_scan_clean_message(self):
        """Clean messages should pass unchanged."""
        messages = [{"role": "user", "content": "What is the weather today?"}]
        result = pii_guard.scan(messages)
        assert result["blocked"] is False
        assert result["changed"] is False
        assert result["findings_count"] == 0

    def test_scan_pii_message(self):
        """Messages with PII should be flagged and cleaned."""
        messages = [{"role": "user", "content": "My email is test@example.com"}]
        result = pii_guard.scan(messages)
        assert result["changed"] is True
        assert result["findings_count"] > 0
        assert "test@example.com" not in str(result["cleaned_messages"])
