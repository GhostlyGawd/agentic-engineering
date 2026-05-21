# mcp-server/tests/test_fixtures_phase1.py
"""Non-llm guard: prove the staged artifacts behave as the e2e assumes.

The e2e (test_phase1_e2e, llm-gated) swaps these in per iteration. If the
staging itself is wrong, the e2e would fail for the wrong reason. This test
keeps the fixtures honest without spending a Claude session.
"""
import shutil
import subprocess
import sys
from pathlib import Path

FIX = Path(__file__).resolve().parent / "fixtures" / "phase1"


def _run_spec_test_against(tmp_path, impl_file: Path) -> int:
    shutil.copy(FIX / "stubborn" / "spec_test.py", tmp_path / "test_parse_duration.py")
    shutil.copy(impl_file, tmp_path / "parse_duration.py")
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "test_parse_duration.py"],
        cwd=tmp_path, capture_output=True, text=True,
    )
    return proc.returncode


def test_stubborn_iters_1_to_3_fail(tmp_path):
    for n in (1, 2, 3):
        d = tmp_path / f"i{n}"
        d.mkdir()
        rc = _run_spec_test_against(d, FIX / "stubborn" / f"iter{n}.py")
        assert rc != 0, f"iter{n} should FAIL the spec test but passed"


def test_stubborn_iter4_passes(tmp_path):
    rc = _run_spec_test_against(tmp_path, FIX / "stubborn" / "iter4.py")
    assert rc == 0, "iter4 should PASS the spec test"


def test_mixed_and_contrarian_import_and_run():
    import importlib.util

    for rel in ("mixed/widget.py", "contrarian/rate_limiter.py"):
        path = FIX / rel
        spec = importlib.util.spec_from_file_location(path.stem, path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # must import without error
    # widget happy path
    from importlib import import_module  # noqa: F401
    wspec = importlib.util.spec_from_file_location("widget", FIX / "mixed" / "widget.py")
    w = importlib.util.module_from_spec(wspec)
    wspec.loader.exec_module(w)
    assert w.total_price([{"price": 2, "qty": 3}]) == 6
    # rate limiter happy path (single process - looks fine here)
    rspec = importlib.util.spec_from_file_location("rl", FIX / "contrarian" / "rate_limiter.py")
    r = importlib.util.module_from_spec(rspec)
    rspec.loader.exec_module(r)
    rl = r.RateLimiter(limit=2)
    assert rl.allow("k") and rl.allow("k") and not rl.allow("k")
