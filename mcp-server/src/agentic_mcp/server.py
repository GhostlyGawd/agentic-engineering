"""Agentic graph MCP server (stdio)."""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from . import db as db_mod
from . import nodes as nodes_mod
from . import relations as rel_mod
from . import queries as q_mod
from . import findings as f_mod
from . import scope as scope_mod
from . import validators as v_mod


def _db_path() -> Path:
    raw = os.environ.get("AGENTIC_DB_PATH", "./.agentic/graph.db")
    p = Path(raw).resolve()
    if not p.exists():
        db_mod.init_db(p)
    return p


def _ok(data) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps(data, default=str))]


def _err(msg: str) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps({"error": msg}))]


app = Server("agentic-graph")


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="create_node",
            description="Create a graph node of the given entity type.",
            inputSchema={
                "type": "object",
                "properties": {
                    "type": {"type": "string"},
                    "status": {"type": "string"},
                    "owner": {"type": "string"},
                    "body": {"type": "string"},
                    "id": {"type": "string"},
                    "severity": {"type": "string"},
                    "summary": {"type": "string"},
                    "tags": {"type": "string"},
                    "scope": {"type": "string"},
                    "criteria_json": {"type": "string"},
                    "feedback_loop": {"type": "string"},
                    "required_reads": {"type": "string"},
                    "parent_id": {"type": "string"},
                    "path": {"type": "string"},
                    "failed_layer": {"type": "string"},
                    "verdict": {"type": "string"},
                    "subtype": {"type": "string"},
                },
                "required": ["type", "status", "owner", "body"],
            },
        ),
        Tool(
            name="update_node",
            description="Update fields on an existing node.",
            inputSchema={
                "type": "object",
                "properties": {"id": {"type": "string"}},
                "required": ["id"],
                "additionalProperties": True,
            },
        ),
        Tool(
            name="get_node",
            description="Fetch a single node by id.",
            inputSchema={
                "type": "object",
                "properties": {"id": {"type": "string"}},
                "required": ["id"],
            },
        ),
        Tool(
            name="link_nodes",
            description="Create a typed relation between two nodes.",
            inputSchema={
                "type": "object",
                "properties": {
                    "from_id": {"type": "string"},
                    "to_id": {"type": "string"},
                    "relation_type": {"type": "string"},
                },
                "required": ["from_id", "to_id", "relation_type"],
            },
        ),
        Tool(
            name="query_graph",
            description="Filtered query over node tables.",
            inputSchema={
                "type": "object",
                "properties": {
                    "type": {"type": "string"},
                    "status": {"type": "string"},
                    "severity": {"type": "string"},
                    "scope": {"type": "string"},
                    "limit": {"type": "integer", "default": 100},
                },
            },
        ),
        Tool(
            name="get_required_reads",
            description="Fetch all nodes listed in a spec's required_reads.",
            inputSchema={
                "type": "object",
                "properties": {"spec_id": {"type": "string"}},
                "required": ["spec_id"],
            },
        ),
        Tool(
            name="log_finding",
            description="Create a Finding attached to a parent node.",
            inputSchema={
                "type": "object",
                "properties": {
                    "parent_id": {"type": "string"},
                    "severity": {"type": "string"},
                    "body": {"type": "string"},
                    "subtype": {"type": "string"},
                    "scope": {"type": "string"},
                    "owner": {"type": "string"},
                },
                "required": ["parent_id", "severity", "body"],
            },
        ),
        Tool(
            name="mark_criterion_satisfied",
            description="Mark a Spec criterion as satisfied with evidence.",
            inputSchema={
                "type": "object",
                "properties": {
                    "spec_id": {"type": "string"},
                    "criterion_index": {"type": "integer"},
                    "evidence": {"type": "string"},
                },
                "required": ["spec_id", "criterion_index", "evidence"],
            },
        ),
        Tool(
            name="validate_spec",
            description="Run falsifiability + feedback-loop gates on a Spec.",
            inputSchema={
                "type": "object",
                "properties": {
                    "criteria_json": {"type": "string"},
                    "feedback_loop": {"type": "string"},
                },
                "required": ["criteria_json", "feedback_loop"],
            },
        ),
        Tool(
            name="infer_scope",
            description="Heuristically infer a scope tag for a new node.",
            inputSchema={
                "type": "object",
                "properties": {
                    "body": {"type": "string"},
                    "explicit": {"type": "string"},
                    "parent_scope": {"type": "string"},
                    "cwd": {"type": "string"},
                    "recent_files": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["body"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    conn = db_mod.connect(_db_path())
    try:
        if name == "create_node":
            ntype = arguments.pop("type")
            nid = nodes_mod.create_node(conn, ntype, **arguments)
            return _ok({"id": nid})
        if name == "update_node":
            nid = arguments.pop("id")
            nodes_mod.update_node(conn, nid, **arguments)
            return _ok({"id": nid})
        if name == "get_node":
            return _ok(nodes_mod.get_node(conn, arguments["id"]))
        if name == "link_nodes":
            rel_mod.link_nodes(conn, arguments["from_id"], arguments["to_id"], arguments["relation_type"])
            return _ok({"ok": True})
        if name == "query_graph":
            return _ok(q_mod.query_graph(conn, **arguments))
        if name == "get_required_reads":
            return _ok(q_mod.get_required_reads(conn, arguments["spec_id"]))
        if name == "log_finding":
            fid = f_mod.log_finding(conn, **arguments)
            return _ok({"id": fid})
        if name == "mark_criterion_satisfied":
            f_mod.mark_criterion_satisfied(
                conn, arguments["spec_id"], arguments["criterion_index"], arguments["evidence"]
            )
            return _ok({"ok": True})
        if name == "validate_spec":
            ok, reasons = v_mod.validate_spec(arguments)
            return _ok({"ok": ok, "reasons": reasons})
        if name == "infer_scope":
            cwd_arg = arguments.get("cwd")
            cwd_path = Path(cwd_arg) if cwd_arg else None
            s = scope_mod.infer_scope(
                arguments["body"],
                explicit=arguments.get("explicit"),
                parent_scope=arguments.get("parent_scope"),
                cwd=cwd_path,
                recent_files=arguments.get("recent_files"),
            )
            return _ok({"scope": s})
        return _err(f"unknown tool: {name}")
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")
    finally:
        conn.close()


async def _run() -> None:
    async with stdio_server() as (read, write):
        await app.run(read, write, app.create_initialization_options())


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    asyncio.run(_run())


if __name__ == "__main__":
    main()
