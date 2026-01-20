"""
Tests for MCP Server - Model Context Protocol Tools.
Tests the AgentShield Enterprise Protocol tools.
"""
import pytest
from mcp_server import mcp


class TestMCPServer:
    """Tests for MCP server configuration."""
    
    def test_mcp_instance_exists(self):
        """MCP server instance should exist."""
        assert mcp is not None
    
    def test_mcp_name(self):
        """MCP server should have correct name."""
        assert mcp.name == "AgentShield Enterprise Protocol"


class TestMCPTools:
    """Tests for MCP tool availability."""
    
    def test_tools_module_imports(self):
        """All MCP tools should be importable."""
        from mcp_server import (
            get_user_trust_profile,
            search_knowledge_vault,
            get_wallet_balance,
            create_dynamic_policy,
            get_forensic_timeline,
            check_financial_compliance,
            list_knowledge_royalties
        )
        
        # All should be callable
        assert callable(get_user_trust_profile)
        assert callable(search_knowledge_vault)
        assert callable(get_wallet_balance)
        assert callable(create_dynamic_policy)
        assert callable(get_forensic_timeline)
        assert callable(check_financial_compliance)
        assert callable(list_knowledge_royalties)


class TestFinancialCompliance:
    """Tests for financial compliance tool."""
    
    @pytest.mark.asyncio
    async def test_compliance_function_exists(self):
        """check_financial_compliance should be async."""
        from mcp_server import check_financial_compliance
        import asyncio
        assert asyncio.iscoroutinefunction(check_financial_compliance)
    
    @pytest.mark.asyncio
    async def test_budget_check_returns_result(self):
        """Budget check should return a result."""
        from mcp_server import check_financial_compliance
        result = await check_financial_compliance(
            project_budget=1000.0,
            estimated_cost=500.0
        )
        # Should return some result (string or dict)
        assert result is not None
