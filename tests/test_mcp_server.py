# tests/test_mcp_server.py
"""Tests for the MCP Server module."""

import pytest

from mcp_server import mcp


class TestMCPServer:
    """Test the main MCP server instance."""

    def test_mcp_instance_exists(self):
        """Test that the mcp instance is created."""
        assert mcp is not None

    def test_mcp_name(self):
        """Test that the MCP server has a name."""
        assert hasattr(mcp, "name")


class TestMCPServerConfiguration:
    """Test MCP server configuration."""

    def test_server_is_fastmcp_instance(self):
        """Test that mcp is a FastMCP instance."""
        from fastmcp import FastMCP

        assert isinstance(mcp, FastMCP)
