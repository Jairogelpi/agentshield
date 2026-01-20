"""
Tests for Policy Engine - Rule Evaluation System
Tests policy conditions, blocking logic, and shadow mode.
"""
import pytest
from app.services.policy_engine import evaluate_logic, PolicyContext


class TestEvaluateLogic:
    """Tests for individual rule evaluation."""
    
    def _make_context(self, **kwargs):
        """Helper to create PolicyContext with defaults."""
        defaults = {
            "user_id": "u1",
            "user_email": "test@company.com",
            "dept_id": "dept1",
            "role": "user",
            "model": "gpt-4",
            "estimated_cost": 5.0,
            "intent": "general",
            "trust_score": 100
        }
        defaults.update(kwargs)
        return PolicyContext(**defaults)
    
    def test_max_cost_block(self):
        """Should block when cost exceeds threshold."""
        rule = {"condition": "max_cost", "value": 5.0, "action": "BLOCK"}
        context = self._make_context(estimated_cost=10.0)
        result = evaluate_logic(rule, context)
        assert result.get("should_block") is True
    
    def test_max_cost_allow(self):
        """Should allow when cost is under threshold."""
        rule = {"condition": "max_cost", "value": 20.0, "action": "BLOCK"}
        context = self._make_context(estimated_cost=5.0)
        result = evaluate_logic(rule, context)
        assert result.get("should_block") is False
    
    def test_forbidden_model_block(self):
        """Should block forbidden models."""
        rule = {"condition": "forbidden_model", "value": "gpt-4", "action": "BLOCK"}
        context = self._make_context(model="gpt-4")
        result = evaluate_logic(rule, context)
        assert result.get("should_block") is True
    
    def test_forbidden_model_allow(self):
        """Should allow non-forbidden models."""
        rule = {"condition": "forbidden_model", "value": "gpt-4", "action": "BLOCK"}
        context = self._make_context(model="gpt-3.5-turbo")
        result = evaluate_logic(rule, context)
        assert result.get("should_block") is False
    
    def test_intent_match_block(self):
        """Should block matching intents."""
        rule = {"condition": "intent_match", "value": "code_generation", "action": "BLOCK"}
        context = self._make_context(intent="code_generation")
        result = evaluate_logic(rule, context)
        assert result.get("should_block") is True


class TestPolicyContext:
    """Tests for PolicyContext validation."""
    
    def test_context_creation(self):
        """Should create valid context."""
        context = PolicyContext(
            user_id="user123",
            user_email="user@example.com",
            dept_id="engineering",
            role="developer",
            model="gpt-4-turbo",
            estimated_cost=2.50
        )
        assert context.user_id == "user123"
        assert context.estimated_cost == 2.50
    
    def test_context_defaults(self):
        """Should have sensible defaults."""
        context = PolicyContext(
            user_id="u1",
            user_email="test@co.com",
            dept_id="d1",
            role="user",
            model="gpt-4",
            estimated_cost=1.0
        )
        assert context.intent == "general"
        assert context.trust_score == 100
