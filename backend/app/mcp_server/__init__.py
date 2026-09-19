"""MCP server first-party cho MuMuAINovel.

Chạy bằng ``python -m app.mcp_server``.  Biến môi trường chính:
``MUMU_API_BASE``, ``MUMU_MCP_TOKEN`` (hoặc ``MUMU_SESSION_TOKEN``), và
``MUMU_MCP_USER_ID`` (hoặc ``MUMU_USER_ID``).
"""

from .server import create_server, mcp

__all__ = ["create_server", "mcp"]
