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
