"""Pool wrapper + harness importable from the package."""
import time

from agentic_mcp import headless


def test_harness_importable_from_package():
    assert hasattr(headless, "run_claude_headless")
    assert hasattr(headless, "result_text")
    assert hasattr(headless, "stage_mcp_config")
    assert issubclass(headless.ClaudeUnavailable, RuntimeError)


def test_pool_runs_all_jobs_with_cap():
    import threading
    jobs = [{"task_id": f"t{i}"} for i in range(5)]
    lock = threading.Lock()
    concurrent = {"now": 0, "max": 0}

    def launch(job):
        with lock:
            concurrent["now"] += 1
            concurrent["max"] = max(concurrent["max"], concurrent["now"])
        time.sleep(0.05)
        with lock:
            concurrent["now"] -= 1
        return {"task_id": job["task_id"], "ok": True}

    pool = headless.Pool(max_workers=2)
    results = pool.run(jobs, launch)
    assert {r["task_id"] for r in results} == {f"t{i}" for i in range(5)}
    assert all(r["ok"] for r in results)
    assert concurrent["max"] <= 2


def test_run_claude_headless_passes_prompt_via_stdin(monkeypatch):
    """A MULTI-LINE prompt must go to claude via STDIN, never as a -p argv.

    On Windows `claude` resolves to claude.CMD (a batch shim); a multi-line prompt
    passed as an argv is truncated by cmd.exe at the first newline, which also
    drops every flag after it (including --output-format json) -> claude returns
    plain text -> json.loads fails. Feeding the prompt over stdin avoids cmd.exe
    argument parsing entirely. This test pins the stdin contract.
    """
    captured = {}

    class _FakeProc:
        def __init__(self, cmd, **kw):
            captured["cmd"] = cmd
            captured["stdin"] = kw.get("stdin")
            self.returncode = 0
            self.pid = 4321

        def communicate(self, input=None, timeout=None):
            captured["input"] = input
            return ('{"result": "ok"}', "")

    monkeypatch.setattr(headless, "_claude_exe", lambda: "claude.CMD")
    monkeypatch.setattr(headless.subprocess, "Popen",
                        lambda cmd, **kw: _FakeProc(cmd, **kw))

    multiline = "line one\nline two\nline three"
    payload = headless.run_claude_headless(multiline, cwd=".", mcp_config="cfg.json")

    assert payload == {"result": "ok"}
    # The prompt must NOT be an argv element (breaks the .CMD shim on newlines).
    assert multiline not in captured["cmd"]
    # It must arrive via stdin, and stdin must be a pipe so input can be written.
    assert captured["input"] == multiline
    assert captured["stdin"] is not None
    # Core flags + the mcp flags survive (they are no longer behind the prompt arg).
    assert "-p" in captured["cmd"]
    assert "--output-format" in captured["cmd"] and "json" in captured["cmd"]
    assert "--mcp-config" in captured["cmd"] and "--strict-mcp-config" in captured["cmd"]
