"""
Tests for LLM Gateway - Circuit Breaker, Canary & Resilience.
"""

import pytest

from app.services.llm_gateway import CANARY_CONFIG, DEFAULT_CHAINS, CircuitBreaker

# Alias for backwards compatibility in tests
FALLBACK_CHAINS = DEFAULT_CHAINS


class TestFallbackChains:
    """Tests for fallback chain configuration."""

    def test_smart_chain_exists(self):
        """Smart tier should have fallback chain."""
        assert "agentshield-smart" in FALLBACK_CHAINS
        assert len(FALLBACK_CHAINS["agentshield-smart"]) >= 2

    def test_fast_chain_exists(self):
        """Fast tier should have fallback chain."""
        assert "agentshield-fast" in FALLBACK_CHAINS
        assert len(FALLBACK_CHAINS["agentshield-fast"]) >= 2

    def test_chain_has_required_fields(self):
        """Each fallback should have provider, model, timeout."""
        for tier, chain in FALLBACK_CHAINS.items():
            for fallback in chain:
                assert "provider" in fallback
                assert "model" in fallback
                assert "timeout" in fallback


class TestCircuitBreaker:
    """Tests for Circuit Breaker pattern."""

    def test_initialization(self):
        """Circuit breaker should initialize with default values."""
        cb = CircuitBreaker()
        assert hasattr(cb, "recovery_timeout")
        assert cb.recovery_timeout == 60

    def test_healthy_provider_allowed(self):
        """Healthy providers should be allowed."""
        cb = CircuitBreaker()
        # Fresh provider should be allowed
        assert cb.can_use_provider("test_provider") is True

    def test_success_reporting(self):
        """Successful calls should be tracked."""
        cb = CircuitBreaker()
        # Should not raise
        cb.report_success("openai")

    def test_failure_reporting(self):
        """Failed calls should be tracked."""
        cb = CircuitBreaker()
        # Should not raise
        cb.report_failure("openai")


class TestCanaryConfig:
    """Tests for Canary deployment configuration."""

    def test_canary_config_structure(self):
        """Canary config should have required fields."""
        assert "active" in CANARY_CONFIG
        assert "target_model" in CANARY_CONFIG
        assert "percentage" in CANARY_CONFIG
        assert "for_tiers" in CANARY_CONFIG

    def test_canary_percentage_valid(self):
        """Canary percentage should be between 0 and 1."""
        assert 0 <= CANARY_CONFIG["percentage"] <= 1

    def test_canary_tiers_is_list(self):
        """Canary tiers should be a list."""
        assert isinstance(CANARY_CONFIG["for_tiers"], list)
