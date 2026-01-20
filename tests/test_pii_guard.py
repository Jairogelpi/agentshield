# tests/test_pii_guard.py
"""Tests for the PII Guard service - testing actual exported functions."""
import pytest

from app.services.pii_guard import PIIEngine, fast_regex_scrub


class TestRegexScrubber:
    """Test the fast_regex_scrub function (Rust-powered)."""

    def test_email_redaction(self):
        """Test email addresses are redacted."""
        text = "Contact me at user@example.com"
        result = fast_regex_scrub(text)
        assert "user@example.com" not in result

    def test_credit_card_redaction(self):
        """Test credit card numbers are redacted."""
        text = "My card is 4111-1111-1111-1111"
        result = fast_regex_scrub(text)
        assert "4111-1111-1111-1111" not in result

    def test_normal_text_unchanged(self):
        """Test normal text without PII passes through."""
        text = "Hello world, this is a normal message."
        result = fast_regex_scrub(text)
        # Normal text should remain mostly unchanged
        assert "Hello" in result


class TestPIIEngine:
    """Test the PIIEngine class."""

    def test_singleton_pattern(self):
        """Test that get_instance returns same instance."""
        engine1 = PIIEngine.get_instance()
        engine2 = PIIEngine.get_instance()
        assert engine1 is engine2

    def test_engine_instantiation(self):
        """Test that PIIEngine can be instantiated."""
        engine = PIIEngine()
        assert engine is not None

    def test_predict_method_exists(self):
        """Test that predict method exists."""
        engine = PIIEngine()
        assert hasattr(engine, 'predict')
        assert callable(engine.predict)

    def test_predict_returns_text(self):
        """Test that predict returns text."""
        engine = PIIEngine()
        text = "Test input"
        result = engine.predict(text)
        assert isinstance(result, str)


class TestEntropyScanner:
    """Test the _entropy_scan method."""

    def test_method_exists(self):
        """Test that _entropy_scan method exists."""
        engine = PIIEngine()
        assert hasattr(engine, '_entropy_scan')
        assert callable(engine._entropy_scan)

    def test_normal_text_unchanged(self):
        """Test that normal text passes through."""
        engine = PIIEngine()
        text = "Hello world this is normal text"
        result = engine._entropy_scan(text)
        assert result == text

    def test_returns_string(self):
        """Test that _entropy_scan returns a string."""
        engine = PIIEngine()
        result = engine._entropy_scan("test text")
        assert isinstance(result, str)


class TestAsyncMethods:
    """Test async method signatures."""

    def test_scan_method_exists(self):
        """Test that scan is an async method on PIIEngine."""
        engine = PIIEngine()
        # The scan method is defined but may be a method of a different class structure
        # Check if the method exists
        assert hasattr(engine, 'scan') or hasattr(PIIEngine, 'scan')

    def test_apply_custom_rules_async_exists(self):
        """Test that apply_custom_rules_async method exists."""
        engine = PIIEngine()
        assert hasattr(engine, 'apply_custom_rules_async')
