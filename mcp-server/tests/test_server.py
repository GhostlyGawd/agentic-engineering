import asyncio
import json
import os
import sys
import pytest
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from agentic_mcp import server


def test_phase2_tools_listed():
    tools = asyncio.run(server.list_tools())
    names = {t.name for t in tools}
    assert {"claim_scope", "release_claim", "detect_overlap", "flag_stale",
            "record_outcome", "get_calibration", "adjust_trust",
            "triage_pattern"} <= names
    assert len(names) == 26


def test_claim_scope_and_overlap_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTIC_DB_PATH", str(tmp_path / "graph.db"))
    out = asyncio.run(server.call_tool("claim_scope", {"task_id": "t1", "scope_paths": ["src/a/*"]}))
    assert "id" in json.loads(out[0].text)
    out2 = asyncio.run(server.call_tool("claim_scope", {"task_id": "t2", "scope_paths": ["src/a/b.py"]}))
    assert "error" in json.loads(out2[0].text)


def test_calibration_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTIC_DB_PATH", str(tmp_path / "graph.db"))
    asyncio.run(server.call_tool("record_outcome", {"role": "code-reviewer", "hit": False}))
    out = asyncio.run(server.call_tool("get_calibration", {"role": "code-reviewer"}))
    assert json.loads(out[0].text)["observations"] == 1


def test_release_claim_unknown_id_errors(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTIC_DB_PATH", str(tmp_path / "graph.db"))
    out = asyncio.run(server.call_tool("release_claim", {"claim_id": "does-not-exist"}))
    assert "error" in json.loads(out[0].text)


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


@pytest.mark.asyncio
async def test_phase1_tools_via_stdio(tmp_path):
    db_path = tmp_path / "graph.db"
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "agentic_mcp.server"],
        env={**os.environ, "AGENTIC_DB_PATH": str(db_path)},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            names = {t.name for t in (await session.list_tools()).tools}
            assert {
                "dispatch_spec", "start_critical_loop", "advance_critical_loop",
                "resolve_critical_loop", "get_open_loops", "record_triage", "log_retro",
            }.issubset(names)

            # Spec -> dispatch.
            spec = await session.call_tool("create_node", arguments={
                "type": "Spec", "status": "open", "owner": "t", "body": "s",
                "criteria_json": json.dumps([{"text": "c", "verify": "pytest x.py::t -q"}]),
                "feedback_loop": "if a user reports a bug we open a PR and write a retro",
            })
            sid = json.loads(spec.content[0].text)["id"]
            disp = await session.call_tool("dispatch_spec", arguments={"spec_id": sid})
            assert json.loads(disp.content[0].text)["dispatched_at"]

            # Finding -> critical loop -> advance -> resolve.
            find = await session.call_tool("log_finding", arguments={
                "parent_id": sid, "severity": "Critical", "body": "boom",
            })
            fid = json.loads(find.content[0].text)["id"]
            loop = await session.call_tool("start_critical_loop", arguments={"finding_id": fid})
            lid = json.loads(loop.content[0].text)["id"]
            adv = await session.call_tool("advance_critical_loop", arguments={"loop_id": lid})
            assert json.loads(adv.content[0].text)["iteration_count"] == 2
            res = await session.call_tool("resolve_critical_loop", arguments={"loop_id": lid})
            assert json.loads(res.content[0].text)["ok"] is True

            # Important -> triage. Retro -> failed_layer.
            imp = await session.call_tool("log_finding", arguments={
                "parent_id": sid, "severity": "Important", "body": "n+1",
            })
            ifid = json.loads(imp.content[0].text)["id"]
            tri = await session.call_tool("record_triage", arguments={
                "finding_id": ifid, "decision": "backlog",
            })
            assert json.loads(tri.content[0].text)["ok"] is True
            retro = await session.call_tool("log_retro", arguments={
                "body": "root cause", "failed_layer": "implementation",
                "caused_by_finding_id": fid,
            })
            assert json.loads(retro.content[0].text)["id"]


def test_triage_pattern_tool_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTIC_DB_PATH", str(tmp_path / "graph.db"))
    created = asyncio.run(server.call_tool(
        "create_node", {"type": "Pattern", "status": "open", "owner": "t", "body": "p"}))
    pid = json.loads(created[0].text)["id"]
    out = asyncio.run(server.call_tool(
        "triage_pattern", {"pattern_id": pid, "disposition": "confirmed"}))
    assert json.loads(out[0].text) == {"ok": True}
    got = asyncio.run(server.call_tool("get_node", {"id": pid}))
    assert json.loads(got[0].text)["status"] == "confirmed"


def test_triage_pattern_tool_bad_disposition_errors(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTIC_DB_PATH", str(tmp_path / "graph.db"))
    created = asyncio.run(server.call_tool(
        "create_node", {"type": "Pattern", "status": "open", "owner": "t", "body": "p"}))
    pid = json.loads(created[0].text)["id"]
    out = asyncio.run(server.call_tool(
        "triage_pattern", {"pattern_id": pid, "disposition": "nope"}))
    assert "error" in json.loads(out[0].text)
