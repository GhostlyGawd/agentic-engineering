"""Shared pytest fixtures for agentic_mcp tests."""
import pytest


@pytest.fixture
def tmp_db_path(tmp_path):
    """Path for a temp SQLite DB unique to each test."""
    return tmp_path / "graph.db"
