from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.mcp_server import server as mcp_server


class FakeDB:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.added = []

    def add(self, value):
        self.added.append(value)

    async def commit(self):
        return None

    async def refresh(self, value):
        if not getattr(value, "id", None):
            value.id = "project-test-id"
        if getattr(value, "created_at", None) is None:
            value.created_at = None
        if getattr(value, "updated_at", None) is None:
            value.updated_at = None

    async def execute(self, _query):
        return FakeResult(self.rows)


class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def scalar_one(self):
        return len(self.rows)

    def scalar_one_or_none(self):
        return self.rows[0] if self.rows else None

    def scalars(self):
        return self

    def all(self):
        return self.rows


class FakeRuntime(mcp_server.MCPRuntime):
    def __init__(self, db, user_id="agent-user"):
        super().__init__(mcp_server.MCPSettings(token="test-token", user_id=user_id))
        self.db = db

    async def session(self):
        yield self.db


EXPECTED_TOOLS = {
    "mumu_auth_status",
    "mumu_health",
    "list_projects",
    "create_project",
    "update_project",
    "list_categories",
    "create_category",
    "wizard_world_building",
    "wizard_world_regenerate",
    "wizard_career_system",
    "wizard_characters",
    "wizard_outline",
    "wizard_status",
    "list_chapters",
    "create_chapter",
    "generate_chapter",
    "continue_chapters",
    "task_status",
    "list_prompt_templates",
    "list_writing_styles",
    "video_capabilities",
    "create_video_export",
    "list_video_exports",
    "get_video_export",
    "video_export_action",
    "video_download_paths",
}


@pytest.mark.asyncio
async def test_tool_schemas_cover_pipeline():
    server = mcp_server.create_server(FakeRuntime(FakeDB()))
    tools = {tool.name: tool for tool in await server.list_tools()}
    assert EXPECTED_TOOLS <= tools.keys()
    assert len(tools) == 26
    assert "title" in tools["create_project"].inputSchema["properties"]
    assert "chapter_ids" in tools["create_video_export"].inputSchema["properties"]
    assert "project_id" in tools["wizard_world_regenerate"].inputSchema["properties"]


@pytest.mark.asyncio
async def test_create_project_uses_existing_project_model():
    runtime = FakeRuntime(FakeDB())
    server = mcp_server.create_server(runtime)
    result = await server._tool_manager.call_tool(
        "create_project",
        {"title": "Truyện MCP", "genre": "fantasy", "target_words": 10000},
    )
    assert result["title"] == "Truyện MCP"
    assert result["genre"] == "fantasy"
    assert runtime.db.added[0].user_id == "agent-user"


@pytest.mark.asyncio
async def test_create_video_export_calls_video_service(monkeypatch):
    runtime = FakeRuntime(FakeDB())
    server = mcp_server.create_server(runtime)
    calls = {}

    async def fake_create_job(**kwargs):
        calls.update(kwargs)
        return SimpleNamespace(id="job-1")

    async def fake_detail(**kwargs):
        return SimpleNamespace(id="job-1"), []

    monkeypatch.setattr(mcp_server.video_export_service, "create_job", fake_create_job)
    monkeypatch.setattr(mcp_server.video_export_service, "get_job_detail", fake_detail)
    monkeypatch.setattr(mcp_server, "serialize_job", lambda job, scenes=None: {"id": job.id, "scenes": scenes or []})

    result = await server._tool_manager.call_tool(
        "create_video_export",
        {"project_id": "project-1", "chapter_ids": ["chapter-1"], "options": {"motion_mode": "local"}},
    )
    assert result["id"] == "job-1"
    assert calls["user_id"] == "agent-user"
    assert calls["chapter_ids"] == ["chapter-1"]


@pytest.mark.asyncio
async def test_create_taxonomy_category_without_target_uses_existing_store():
    runtime = FakeRuntime(FakeDB())
    server = mcp_server.create_server(runtime)
    result = await server._tool_manager.call_tool(
        "create_category",
        {"kind": "genre", "name": "Solarpunk"},
    )
    assert result["created"] is True
    assert result["taxonomy_marker"].startswith("__mcp_genre__:")


@pytest.mark.asyncio
async def test_wizard_world_regenerate_hits_existing_sse_route(monkeypatch):
    runtime = FakeRuntime(FakeDB())
    server = mcp_server.create_server(runtime)
    calls = {}

    async def fake_sse(self, path, payload):
        calls["path"] = path
        calls["payload"] = payload
        return {"completed": True, "result": {"project_id": payload.get("project_id")}}

    monkeypatch.setattr(mcp_server._ApiClient, "sse", fake_sse)
    result = await server._tool_manager.call_tool(
        "wizard_world_regenerate",
        {"project_id": "project-1", "provider": "openai"},
    )
    assert result["completed"] is True
    assert calls["path"] == "/api/wizard-stream/world-building/project-1/regenerate"
    assert calls["payload"]["project_id"] == "project-1"
    assert calls["payload"]["user_id"] == "agent-user"


def test_api_client_sends_bearer_and_session_cookie():
    client = mcp_server._ApiClient(
        mcp_server.MCPSettings(token="shared-secret", user_id="agent-user")
    )
    headers = client.headers()
    assert headers["Authorization"] == "Bearer shared-secret"
    assert headers["Cookie"] == "session_token=shared-secret"
    assert headers["X-Mumu-User-ID"] == "agent-user"


@pytest.mark.asyncio
async def test_token_verifier_rejects_mismatch():
    verifier = mcp_server._TokenVerifier(
        mcp_server.MCPSettings(token="expected-token", user_id="agent-user")
    )
    ok = await verifier.verify_token("expected-token")
    bad = await verifier.verify_token("wrong-token")
    assert ok is not None
    assert ok.scopes == ["mumu"]
    assert bad is None
