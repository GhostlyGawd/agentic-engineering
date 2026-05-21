# fixtures/phase1/contrarian/rate_limiter.py
"""Per-key rate limiter.

DEPLOYMENT (from the spec staged in the e2e): this service runs behind a
multi-worker server (several processes). The implementation below is correct
line-by-line and passes a single-process test, but its counter lives in a
plain in-process dict - so each worker has its own counter and the real,
cluster-wide limit is (workers * limit). That is an architectural/assumption
flaw, not a line bug: exactly what the contrarian should catch and the
code-reviewer is likely to wave through.
"""


class RateLimiter:
    def __init__(self, limit: int):
        self.limit = limit
        self._counts: dict[str, int] = {}

    def allow(self, key: str) -> bool:
        n = self._counts.get(key, 0)
        if n >= self.limit:
            return False
        self._counts[key] = n + 1
        return True
