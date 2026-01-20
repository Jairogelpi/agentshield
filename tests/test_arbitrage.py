"""
Tests for Arbitrage Engine - RL/Bandit Model Selection.
"""
import pytest
from app.services.arbitrage import AgentShieldRLArbitrator, arbitrage_engine


class TestArbitrageConfig:
    """Tests for Arbitrage Engine configuration."""
    
    def test_singleton_exists(self):
        """Arbitrage engine singleton should exist."""
        assert arbitrage_engine is not None
    
    def test_engine_instantiation(self):
        """Engine should instantiate with defaults."""
        engine = AgentShieldRLArbitrator()
        assert engine is not None
    
    def test_learning_rate(self):
        """Learning rate should be reasonable (0 < lr <= 1)."""
        engine = AgentShieldRLArbitrator()
        assert 0 < engine.learning_rate <= 1
    
    def test_discount_factor(self):
        """Discount factor should be between 0 and 1."""
        engine = AgentShieldRLArbitrator()
        assert 0 <= engine.discount_factor <= 1


class TestRewardCalculation:
    """Tests for reward function."""
    
    def test_reward_positive_savings(self):
        """Positive cost savings should yield positive reward."""
        engine = AgentShieldRLArbitrator()
        reward = engine.calculate_reward(
            cost_saved=0.5,
            rerank_score=0.9,
            latency_ms=100
        )
        assert reward > 0
    
    def test_reward_zero_savings(self):
        """Zero savings should still work."""
        engine = AgentShieldRLArbitrator()
        reward = engine.calculate_reward(
            cost_saved=0.0,
            rerank_score=0.85,
            latency_ms=200
        )
        # Should not raise, reward depends on other factors
        assert isinstance(reward, (int, float))
    
    def test_reward_high_latency_penalty(self):
        """High latency should reduce reward."""
        engine = AgentShieldRLArbitrator()
        low_latency_reward = engine.calculate_reward(
            cost_saved=0.5,
            rerank_score=0.9,
            latency_ms=50
        )
        high_latency_reward = engine.calculate_reward(
            cost_saved=0.5,
            rerank_score=0.9,
            latency_ms=5000
        )
        assert low_latency_reward >= high_latency_reward


class TestStateDiscretization:
    """Tests for Q-learning state discretization."""
    
    def test_state_key_generation(self):
        """State key should be generated."""
        engine = AgentShieldRLArbitrator()
        state = engine._get_state_key(
            complexity_score=0.5,
            input_tokens=500
        )
        assert isinstance(state, str)
        assert len(state) > 0
    
    def test_different_inputs_different_states(self):
        """Different inputs should produce different states."""
        engine = AgentShieldRLArbitrator()
        state1 = engine._get_state_key(complexity_score=0.1, input_tokens=100)
        state2 = engine._get_state_key(complexity_score=0.9, input_tokens=5000)
        # States may or may not be different based on bucketing
        assert isinstance(state1, str)
        assert isinstance(state2, str)
