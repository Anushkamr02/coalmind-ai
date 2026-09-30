import datetime as dt, hashlib, os, sqlite3
from pathlib import Path
from .config import DATA

_path = Path(os.getenv("COALMIND_DB", DATA / "coalmind.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents(id INTEGER PRIMARY KEY, sha256 TEXT UNIQUE, filename TEXT,
  doc_type TEXT, kind TEXT, uploaded_at TEXT);
CREATE TABLE IF NOT EXISTS src_tables(id INTEGER PRIMARY KEY, doc_id INT, sheet TEXT, title TEXT,
  unit TEXT, first_cell TEXT, last_cell TEXT, n_rows INT);
CREATE TABLE IF NOT EXISTS facts(id INTEGER PRIMARY KEY, doc_id INT, table_id INT, sheet TEXT, cell TEXT,
  row_ref TEXT, row_no INT, section TEXT, entity TEXT, column_label TEXT, qualifier TEXT, period TEXT,
  value REAL, unit TEXT, raw_text TEXT, is_total INT, confidence TEXT, status TEXT DEFAULT 'pending');
CREATE INDEX IF NOT EXISTS ix_facts_tbl ON facts(table_id);
CREATE INDEX IF NOT EXISTS ix_facts_ent ON facts(entity);
CREATE TABLE IF NOT EXISTS flags(id INTEGER PRIMARY KEY, fact_id INT, code TEXT, severity TEXT,
  detail TEXT, resolved INT DEFAULT 0);
CREATE TABLE IF NOT EXISTS chunks(id INTEGER PRIMARY KEY, doc_id INT, loc TEXT, kind TEXT, text TEXT);
CREATE TABLE IF NOT EXISTS audit_log(id INTEGER PRIMARY KEY, ts TEXT, user TEXT, action TEXT, target TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS pq_drafts(id INTEGER PRIMARY KEY, ts TEXT, question TEXT, draft TEXT,
  confidence TEXT, status TEXT, payload TEXT);

-- GeoSciML-aligned borehole / geological tables (Tier 2-3 of new architecture)
CREATE TABLE IF NOT EXISTS boreholes(
  id INTEGER PRIMARY KEY, doc_id INT, borehole_id TEXT, block TEXT, coalfield TEXT,
  subsidiary TEXT, collar_rl REAL, total_depth REAL, easting REAL, northing REAL,
  toposheet TEXT, source_page INT);
CREATE TABLE IF NOT EXISTS strata(
  id INTEGER PRIMARY KEY, borehole_id INT,
  depth_from REAL, depth_to REAL, interval_thickness REAL,
  lithology_raw TEXT, lithology_code TEXT,   -- normalised via thesaurus
  core_recovery_pct REAL, page INT, bbox TEXT);
CREATE TABLE IF NOT EXISTS seams(
  id INTEGER PRIMARY KEY, borehole_id INT, seam TEXT, thickness REAL,
  moisture_pct REAL, ash_pct REAL, volatile_matter_pct REAL, fixed_carbon_pct REAL,
  gcv REAL, statutory_grade TEXT,            -- auto-classified by thesaurus.classify_seam_grade
  reserve_mt REAL, reserve_class TEXT,       -- Proved / Indicated / Inferred (UNFC)
  page INT, bbox TEXT);
CREATE TABLE IF NOT EXISTS projects(
  id INTEGER PRIMARY KEY, doc_id INT, name TEXT, subsidiary TEXT, mining_method TEXT,
  stripping_ratio REAL, ob_volume_mcm REAL, coal_weight_mt REAL, capacity_mty REAL, block TEXT);

-- Lightweight graph edge table (GraphRAG Tier 5 — SQLite stand-in for Neo4j)
CREATE TABLE IF NOT EXISTS graph_edges(
  id INTEGER PRIMARY KEY,
  src_type TEXT, src_id TEXT,
  rel TEXT,
  tgt_type TEXT, tgt_id TEXT,
  weight REAL DEFAULT 1.0);
CREATE INDEX IF NOT EXISTS ix_ge_src ON graph_edges(src_type, src_id);
CREATE INDEX IF NOT EXISTS ix_ge_tgt ON graph_edges(tgt_type, tgt_id);

DROP VIEW IF EXISTS v_facts;
CREATE VIEW v_facts AS
SELECT f.id fact_id, d.filename, f.sheet, f.cell, t.title table_title, f.section, f.entity,
       f.column_label, f.period, f.value, f.unit, f.confidence, f.status,
       (SELECT COUNT(*) FROM flags x WHERE x.fact_id=f.id AND x.severity IN ('warn','error') AND x.resolved=0) flag_count
FROM facts f JOIN documents d ON d.id=f.doc_id JOIN src_tables t ON t.id=f.table_id;
"""


def set_path(p):
    global _path
    _path = Path(p)


def get_path():
    return _path


def connect(readonly=False):
    _path.parent.mkdir(parents=True, exist_ok=True)
    if readonly:
        con = sqlite3.connect(f"file:{_path}?mode=ro", uri=True)
    else:
        con = sqlite3.connect(_path)
        con.executescript(SCHEMA)
    con.row_factory = sqlite3.Row
    return con


def reset():
    if _path.exists():
        _path.unlink()
    connect().close()


def now():
    return dt.datetime.now().isoformat(timespec="seconds")


def audit(action, target="", detail="", user="officer"):
    con = connect()
    con.execute("INSERT INTO audit_log(ts,user,action,target,detail) VALUES(?,?,?,?,?)",
                (now(), user, action, str(target), str(detail)))
    con.commit(); con.close()


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()
