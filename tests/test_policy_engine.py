# tests/test_policy_engine.py
"""Tests for the Policy Engine service."""
import pytest

from app.services.policy_engine import PolicyContext, PolicyResult, evaluate_logic


class TestPolicyContext:
    """Test PolicyContext model."""

    def test_context_creation(self):
        """Test that PolicyContext can be created with required fields."""
        ctx = PolicyContext(
            user_id="user123",
            user_email="user@test.com",
            dept_id="dept1",
            role="user",
            model="gpt-4",
            estimated_cost=5.0,
        )
        assert ctx.user_id == "user123"
        assert ctx.estimated_cost == 5.0

    def test_context_defaults(self):
        """Test that PolicyContext has sensible defaults."""
        ctx = PolicyContext(
            user_id="user123",
            user_email="user@test.com",
            dept_id=None,
            role="user",
            model="gpt-4",
            estimated_cost=1.0,
        )
        assert ctx.intent == "general"
        assert ctx.trust_score == 100


class TestPolicyResult:
    """Test PolicyResult model."""

    def test_result_creation(self):
        """Test that PolicyResult can be created."""
        result = PolicyResult()
        assert result.should_block is False
        assert result.action == "ALLOW"

    def test_result_defaults(self):
        """Test PolicyResult default values."""
        result = PolicyResult()
        assert result.modified_model is None
        assert result.violation_msg is None
        assert result.shadow_hits == []


class TestEvaluateLogic:
    """Test the evaluate_logic function - returns bool."""

    def test_empty_rule_returns_false(self):
        """Test that empty rule returns False."""
        ctx = PolicyContext(
            user_id="u1",
            user_email="u@t.com",
            dept_id=None,
            role="user",
            model="gpt-4",
            estimated_cost=10.0,
        )
        result = evaluate_logic({}, ctx)
        assert result is False

    def test_max_cost_exceeds_blocks(self):
        """Test that exceeding max_cost triggers the rule (returns True)."""
        ctx = PolicyContext(
            user_id="u1",
            user_email="u@t.com",
            dept_id=None,
            role="user",
            model="gpt-4",
            estimated_cost=10.0,
        )
        rule = {"max_cost": 5.0}
        result = evaluate_logic(rule, ctx)
        assert result is True  # Rule triggered

    def test_max_cost_under_limit_allows(self):
        """Test that being under max_cost does not trigger (returns False)."""
        ctx = PolicyContext(
            user_id="u1",
            user_email="u@t.com",
            dept_id=None,
            role="user",
            model="gpt-4",
            estimated_cost=3.0,
        )
        rule = {"max_cost": 5.0}
        result = evaluate_logic(rule, ctx)
        assert result is False  # Rule not triggered

    def test_forbidden_model_blocks(self):
        """Test that forbidden_model triggers when model contains substring."""
        ctx = PolicyContext(
            user_id="u1",
            user_email="u@t.com",
            dept_id=None,
            role="user",
            model="gpt-4-turbo",
            estimated_cost=1.0,
        )
        rule = {"forbidden_model": "gpt-4"}
        result = evaluate_logic(rule, ctx)
        assert result is True  # Rule triggered

    def test_forbidden_model_allows_different_model(self):
        """Test that forbidden_model does not trigger for different model."""
        ctx = PolicyContext(
            user_id="u1",
            user_email="u@t.com",
            dept_id=None,
            role="user",
            model="claude-3",
            estimated_cost=1.0,
        )
        rule = {"forbidden_model": "gpt-4"}
        result = evaluate_logic(rule, ctx)
        assert result is False  # Rule not triggered

    def test_forbidden_intent_blocks(self):
        """Test that forbidden_intent triggers on matching intent."""
        ctx = PolicyContext(
            user_id="u1",
            user_email="u@t.com",
            dept_id=None,
            role="user",
            model="gpt-4",
            estimated_cost=1.0,
            intent="coding",
        )
        rule = {"forbidden_intent": "coding"}
        result = evaluate_logic(rule, ctx)
        assert result is True  # Rule triggered

    def test_json_logic_greater_than(self):
        """Test JSON Logic style rule with > operator."""
        ctx = PolicyContext(
            user_id="u1",
            user_email="u@t.com",
            dept_id=None,
            role="user",
            model="gpt-4",
            estimated_cost=10.0,
        )
        rule = {"var": "cost_usd", "op": ">", "val": 5}
        result = evaluate_logic(rule, ctx)
        assert result is True

    def test_json_logic_less_than(self):
        """Test JSON Logic style rule with < operator."""
        ctx = PolicyContext(
            user_id="u1",
            user_email="u@t.com",
            dept_id=None,
            role="user",
            model="gpt-4",
            estimated_cost=3.0,
        )
        rule = {"var": "cost_usd", "op": "<", "val": 5}
        result = evaluate_logic(rule, ctx)
        assert result is True
