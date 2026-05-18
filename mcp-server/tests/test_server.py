import json
import os
import sys
import pytest
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


@pytest.mark.asyncio
async def test_create_and_get_node_via_stdio(tmp_path):
    db_path = tmp_path / "graph.db"
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "agentic_mcp.server"],
        env={**os.environ, "AGENTIC_DB_PATH": str(db_path)},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            tool_names = {t.name for t in tools.tools}
            assert {"create_node", "get_node", "log_finding", "validate_spec"}.issubset(tool_names)

            r = await session.call_tool(
                "create_node",
                arguments={
                    "type": "Goal", "status": "active",
                    "owner": "test", "body": "ship Phase 0",
                },
            )
            payload = json.loads(r.content[0].text)
            nid = payload["id"]
            assert nid

            r2 = await session.call_tool("get_node", arguments={"id": nid})
            got = json.loads(r2.content[0].text)
            assert got["body"] == "ship Phase 0"


@pytest.mark.asyncio
async def test_validate_spec_via_stdio(tmp_path):
    db_path = tmp_path / "graph.db"
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "agentic_mcp.server"],
        env={**os.environ, "AGENTIC_DB_PATH": str(db_path)},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            r = await session.call_tool(
                "validate_spec",
                arguments={
                    "criteria_json": json.dumps([
                        {"text": "x", "verify": "tbd", "satisfied": False},
                    ]),
                    "feedback_loop": "tbd",
                },
            )
            payload = json.loads(r.content[0].text)
            assert payload["ok"] is False
            assert any("verify" in r.lower() for r in payload["reasons"])
