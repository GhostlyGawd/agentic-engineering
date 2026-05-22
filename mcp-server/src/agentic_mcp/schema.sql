-- Shared column shape for entity tables. Repeated inline because SQLite has no inheritance.
-- Required fields per PRD: id, type, status, severity, owner, created_at, last_touched, body, summary, tags, scope.

-- Generic entity tables. Each entity type gets its own table for query clarity; columns are uniform.

CREATE TABLE IF NOT EXISTS goal (
  id TEXT PRIMARY KEY,
  type TEXT NOT NULL CHECK(type='Goal'),
  status TEXT NOT NULL,
  severity TEXT,
  owner TEXT,
  created_at TEXT NOT NULL,
  last_touched TEXT NOT NULL,
  body TEXT NOT NULL,
  summary TEXT,
  tags TEXT,     -- JSON array
  scope TEXT
);

CREATE TABLE IF NOT EXISTS epic (
  id TEXT PRIMARY KEY,
  type TEXT NOT NULL CHECK(type='Epic'),
  status TEXT NOT NULL,
  severity TEXT,
  owner TEXT,
  created_at TEXT NOT NULL,
  last_touched TEXT NOT NULL,
  body TEXT NOT NULL,
  summary TEXT,
  tags TEXT,
  scope TEXT
);

CREATE TABLE IF NOT EXISTS task (
  id TEXT PRIMARY KEY,
  type TEXT NOT NULL CHECK(type='Task'),
  status TEXT NOT NULL,
  severity TEXT,
  owner TEXT,
  created_at TEXT NOT NULL,
  last_touched TEXT NOT NULL,
  body TEXT NOT NULL,
  summary TEXT,
  tags TEXT,
  scope TEXT
);

CREATE TABLE IF NOT EXISTS subtask (
  id TEXT PRIMARY KEY,
  type TEXT NOT NULL CHECK(type='Subtask'),
  status TEXT NOT NULL,
  severity TEXT,
  owner TEXT,
  created_at TEXT NOT NULL,
  last_touched TEXT NOT NULL,
  body TEXT NOT NULL,
  summary TEXT,
  tags TEXT,
  scope TEXT
);

CREATE TABLE IF NOT EXISTS spec (
  id TEXT PRIMARY KEY,
  type TEXT NOT NULL CHECK(type='Spec'),
  status TEXT NOT NULL,
  severity TEXT,
  owner TEXT,
  created_at TEXT NOT NULL,
  last_touched TEXT NOT NULL,
  body TEXT NOT NULL,           -- full markdown spec
  summary TEXT,
  tags TEXT,
  scope TEXT,
  criteria_json TEXT NOT NULL,  -- JSON array of {text, verify, satisfied:bool, evidence:str}
  feedback_loop TEXT NOT NULL,
  required_reads TEXT           -- JSON array of node ids
);

CREATE TABLE IF NOT EXISTS decision (
  id TEXT PRIMARY KEY,
  type TEXT NOT NULL CHECK(type='Decision'),
  status TEXT NOT NULL,
  severity TEXT,
  owner TEXT,
  created_at TEXT NOT NULL,
  last_touched TEXT NOT NULL,
  body TEXT NOT NULL,
  summary TEXT,
  tags TEXT,
  scope TEXT
);

CREATE TABLE IF NOT EXISTS bug (
  id TEXT PRIMARY KEY,
  type TEXT NOT NULL CHECK(type='Bug'),
  status TEXT NOT NULL,
  severity TEXT,
  owner TEXT,
  created_at TEXT NOT NULL,
  last_touched TEXT NOT NULL,
  body TEXT NOT NULL,
  summary TEXT,
  tags TEXT,
  scope TEXT
);

CREATE TABLE IF NOT EXISTS finding (
  id TEXT PRIMARY KEY,
  type TEXT NOT NULL CHECK(type='Finding'),
  status TEXT NOT NULL,
  severity TEXT NOT NULL CHECK(severity IN ('Critical','Important','Suggested','Strength')),
  owner TEXT,
  created_at TEXT NOT NULL,
  last_touched TEXT NOT NULL,
  body TEXT NOT NULL,
  summary TEXT,
  tags TEXT,
  scope TEXT,
  subtype TEXT,                -- 'SystemUsabilityBug' or NULL
  parent_id TEXT               -- node this finding is attached to
);

CREATE TABLE IF NOT EXISTS pattern (
  id TEXT PRIMARY KEY,
  type TEXT NOT NULL CHECK(type='Pattern'),
  status TEXT NOT NULL,
  severity TEXT,
  owner TEXT,
  created_at TEXT NOT NULL,
  last_touched TEXT NOT NULL,
  body TEXT NOT NULL,
  summary TEXT,
  tags TEXT,
  scope TEXT
);

CREATE TABLE IF NOT EXISTS module (
  id TEXT PRIMARY KEY,
  type TEXT NOT NULL CHECK(type='Module'),
  status TEXT NOT NULL,
  severity TEXT,
  owner TEXT,
  created_at TEXT NOT NULL,
  last_touched TEXT NOT NULL,
  body TEXT NOT NULL,
  summary TEXT,
  tags TEXT,
  scope TEXT
);

CREATE TABLE IF NOT EXISTS file (
  id TEXT PRIMARY KEY,
  type TEXT NOT NULL CHECK(type='File'),
  status TEXT NOT NULL,
  severity TEXT,
  owner TEXT,
  created_at TEXT NOT NULL,
  last_touched TEXT NOT NULL,
  body TEXT NOT NULL,
  summary TEXT,
  tags TEXT,
  scope TEXT,
  path TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS review (
  id TEXT PRIMARY KEY,
  type TEXT NOT NULL CHECK(type='Review'),
  status TEXT NOT NULL,
  severity TEXT,
  owner TEXT,
  created_at TEXT NOT NULL,
  last_touched TEXT NOT NULL,
  body TEXT NOT NULL,
  summary TEXT,
  tags TEXT,
  scope TEXT,
  verdict TEXT
);

CREATE TABLE IF NOT EXISTS retro (
  id TEXT PRIMARY KEY,
  type TEXT NOT NULL CHECK(type='Retro'),
  status TEXT NOT NULL,
  severity TEXT,
  owner TEXT,
  created_at TEXT NOT NULL,
  last_touched TEXT NOT NULL,
  body TEXT NOT NULL,
  summary TEXT,
  tags TEXT,
  scope TEXT,
  failed_layer TEXT CHECK(failed_layer IN ('spec','implementation','integration','review','unknowable'))
);

CREATE TABLE IF NOT EXISTS arch_debt (
  id TEXT PRIMARY KEY,
  type TEXT NOT NULL CHECK(type='ArchDebt'),
  status TEXT NOT NULL,
  severity TEXT,
  owner TEXT,
  created_at TEXT NOT NULL,
  last_touched TEXT NOT NULL,
  body TEXT NOT NULL,
  summary TEXT,
  tags TEXT,
  scope TEXT
);

CREATE TABLE IF NOT EXISTS relations (
  from_id TEXT NOT NULL,
  to_id TEXT NOT NULL,
  relation_type TEXT NOT NULL CHECK(relation_type IN (
    'implements','depends-on','blocks','supersedes',
    'caused-by','observed-in','touches','references','derived-from'
  )),
  created_at TEXT NOT NULL,
  PRIMARY KEY (from_id, to_id, relation_type)
);

-- Indexes for the three indexing modes in the PRD.
CREATE INDEX IF NOT EXISTS idx_task_status ON task(status);
CREATE INDEX IF NOT EXISTS idx_finding_status ON finding(status);
CREATE INDEX IF NOT EXISTS idx_finding_severity ON finding(severity);
CREATE INDEX IF NOT EXISTS idx_finding_scope ON finding(scope);
CREATE INDEX IF NOT EXISTS idx_finding_parent ON finding(parent_id);
CREATE INDEX IF NOT EXISTS idx_relations_from ON relations(from_id, relation_type);
CREATE INDEX IF NOT EXISTS idx_relations_to ON relations(to_id, relation_type);
CREATE INDEX IF NOT EXISTS idx_spec_status ON spec(status);

-- Vector index (sqlite-vec / vec0 virtual table) is deferred to Phase 3 when the
-- pattern-finder needs it. Keeping Phase 0 dependency-light.
