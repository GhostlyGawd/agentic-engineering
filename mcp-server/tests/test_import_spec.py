import json
import pytest
from agentic_mcp import db, import_spec, nodes


GOOD = """\
# Imported spec

### Acceptance Criteria
```json
[
  {"text": "x", "verify": "pytest tests/x.py -v passes", "satisfied": false}
]
```

### Feedback Loop
If a user reports a regression, file a bug and write a retro.
"""

BAD = """\
# Imported spec

### Acceptance Criteria
```json
[
  {"text": "x", "verify": "tbd", "satisfied": false}
]
```

### Feedback Loop
tbd
"""


@pytest.fixture
def conn(tmp_db_path):
    db.init_db(tmp_db_path)
    c = db.connect(tmp_db_path)
    yield c
    c.close()


def test_good_spec_imports(conn):
    sid, reasons = import_spec.from_markdown(conn, GOOD, owner="alice")
    assert sid is not None
    assert reasons == []
    spec = nodes.get_node(conn, sid)
    assert spec["type"] == "Spec"
    assert spec["status"] == "draft"


def test_bad_spec_rejected(conn):
    sid, reasons = import_spec.from_markdown(conn, BAD, owner="alice")
    assert sid is None
    assert any("tbd" in r.lower() or "verify" in r.lower() for r in reasons)


def test_bad_spec_does_not_create_node(conn):
    before = conn.execute("SELECT count(*) FROM spec").fetchone()[0]
    import_spec.from_markdown(conn, BAD, owner="alice")
    after = conn.execute("SELECT count(*) FROM spec").fetchone()[0]
    assert before == after
