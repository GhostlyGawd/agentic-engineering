"""Per-project read-only graph access + a cheap change probe.

Holds ONE persistent connection for its lifetime (PRAGMA data_version only
detects external commits when compared across reads on the SAME connection).
Opens read-only and does NOT go through db.connect -- db.connect runs
migrations, which would attempt a WRITE and break the read-only contract.
check_same_thread=False because the single refresh worker thread reads via this
connection; the HUD serializes refreshes so there is never concurrent use."""
from __future__ import annotations

import sqlite3
from pathlib import Path


class GraphSource:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        if not self.db_path.exists():
            raise FileNotFoundError(self.db_path)
        uri = f"file:{self.db_path.as_posix()}?mode=ro"
        self.conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
        self.conn.execute("PRAGMA busy_timeout = 5000")
        self._data_version = self._read_data_version()

    def _read_data_version(self) -> int:
        return self.conn.execute("PRAGMA data_version").fetchone()[0]

    def changed(self) -> bool:
        v = self._read_data_version()
        if v != self._data_version:
            self._data_version = v
            return True
        return False

    def close(self) -> None:
        self.conn.close()
