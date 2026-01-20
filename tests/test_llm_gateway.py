# tests/test_llm_gateway.py
"""Tests for the LLM Gateway service."""
import pytest

from app.services.llm_gateway import CANARY_CONFIG, DEFAULT_CHAINS, CircuitBreaker


class TestFallbackChains:
    """Test the DEFAULT_CHAINS configuration."""

    def test_smart_chain_exists(self):
        """Test that agentshield-smart chain is defined."""
        assert "agentshield-smart" in DEFAULT_CHAINS

    def test_fast_chain_exists(self):
        """Test that agentshield-fast chain is defined."""
        assert "agentshield-fast" in DEFAULT_CHAINS

    def test_chain_has_required_fields(self):
        """Each fallback should have provider, model, timeout."""
        for tier, chain in DEFAULT_CHAINS.items():
            for fallback in chain:
                assert "provider" in fallback
                assert "model" in fallback
                assert "timeout" in fallback

    def test_chain_is_list(self):
        """Test that each chain is a list of providers."""
        for tier, chain in DEFAULT_CHAINS.items():
            assert isinstance(chain, list)
            assert len(chain) > 0


class TestCircuitBreaker:
    """Test the CircuitBreaker class."""

    def test_initialization(self):
        """Test CircuitBreaker can be instantiated."""
        cb = CircuitBreaker()
        assert cb is not None
        assert cb.recovery_timeout == 60

    @pytest.mark.asyncio
    async def test_healthy_provider_allowed(self):
        """Test that a healthy provider is allowed (async)."""
        cb = CircuitBreaker()
        # By default, all providers should be allowed
        result = await cb.can_use_provider("test_provider")
        assert result is True

    @pytest.mark.asyncio
    async def test_success_reporting(self):
        """Test that report_success is callable and async."""
        cb = CircuitBreaker()
        # Should not raise
        await cb.report_success("openai")

    @pytest.mark.asyncio
    async def test_failure_reporting(self):
        """Test that report_failure is callable and async."""
        cb = CircuitBreaker()
        # Should not raise
        await cb.report_failure("openai")


class TestCanaryConfig:
    """Test the CANARY_CONFIG structure."""

    def test_canary_config_structure(self):
        """Test that CANARY_CONFIG has required keys."""
        assert "active" in CANARY_CONFIG
        assert "target_model" in CANARY_CONFIG
        assert "percentage" in CANARY_CONFIG
        assert "for_tiers" in CANARY_CONFIG

    def test_canary_percentage_valid(self):
        """Test that canary percentage is a valid fraction."""
        pct = CANARY_CONFIG["percentage"]
        assert 0 <= pct <= 1

    def test_canary_tiers_is_list(self):
        """Test that for_tiers is a list."""
        assert isinstance(CANARY_CONFIG["for_tiers"], list)
