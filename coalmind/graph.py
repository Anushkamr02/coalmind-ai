"""Lightweight GraphRAG — SQLite property-graph stand-in (Tier 5 new architecture).

Builds explicit edges: Subsidiary → Area → Block → Borehole → Seam
                       Subsidiary → Project → Block

In production swap the SQLite backend for Neo4j using the same API:
  driver.session().run(cypher, **params)

Key public functions
--------------------
  build_from_db()           – populate graph_edges from boreholes/seams/projects
  multi_hop(question)       – answer a multi-subsidiary / multi-hop query using graph traversal
  neighbours(node_type, id) – return adjacent nodes
  graph_summary()           – dict of node counts and edge counts (for the KPI panel)
"""
import re
from . import db

# ── edge builder ──────────────────────────────────────────────────────────────

def build_from_db(log=print):
    """Populate graph_edges from relational tables.  Idempotent — clears first."""
    con = db.connect()
    con.execute("DELETE FROM graph_edges")

    edges: list[tuple] = []

    # Documents → subsidiary
    for doc in con.execute("SELECT id, filename FROM documents").fetchall():
        # derive subsidiary from filename heuristics
        sub = _infer_subsidiary(doc["filename"])
        if sub:
            edges.append(("document", str(doc["id"]), "BELONGS_TO", "subsidiary", sub, 1.0))
            edges.append(("subsidiary", sub, "HAS_DOCUMENT", "document", str(doc["id"]), 1.0))

    # Boreholes → block / coalfield / subsidiary
    for bh in con.execute("SELECT * FROM boreholes").fetchall():
        bid = f"borehole:{bh['id']}"
        if bh["block"]:
            edges.append((bid.split(":")[0], bid.split(":")[1],
                          "LOCATED_IN_BLOCK", "block", bh["block"], 1.0))
            edges.append(("block", bh["block"],
                          "HAS_BOREHOLE", "borehole", str(bh["id"]), 1.0))
        if bh["subsidiary"]:
            edges.append(("borehole", str(bh["id"]),
                          "ADMINISTERED_BY", "subsidiary", bh["subsidiary"], 1.0))
        if bh["coalfield"] and bh["block"]:
            edges.append(("block", bh["block"],
                          "IN_COALFIELD", "coalfield", bh["coalfield"], 1.0))

    # Seams → borehole
    for sm in con.execute("SELECT id, borehole_id, seam FROM seams").fetchall():
        edges.append(("seam", str(sm["id"]),
                      "EVALUATED_IN", "borehole", str(sm["borehole_id"]), 1.0))
        edges.append(("borehole", str(sm["borehole_id"]),
                      "HAS_SEAM", "seam", str(sm["id"]), 1.0))
        if sm["seam"]:
            edges.append(("seam", str(sm["id"]),
                          "SEAM_NAME", "seam_label", sm["seam"], 1.0))

    # Projects → subsidiary / block
    for proj in con.execute("SELECT * FROM projects").fetchall():
        if proj["subsidiary"]:
            edges.append(("project", str(proj["id"]),
                          "OPERATED_BY", "subsidiary", proj["subsidiary"], 1.0))
        if proj["block"]:
            edges.append(("project", str(proj["id"]),
                          "COVERS_BLOCK", "block", proj["block"], 1.0))

    con.executemany(
        "INSERT INTO graph_edges(src_type,src_id,rel,tgt_type,tgt_id,weight) VALUES(?,?,?,?,?,?)",
        edges)
    con.commit()
    n = len(edges)
    con.close()
    db.audit("GRAPH_BUILD", "graph_edges", f"{n} edges written", user="system")
    log(f"  Graph built: {n} edges")
    return n


def _infer_subsidiary(filename: str) -> str | None:
    name = filename.upper()
    for sub in ("ECL","BCCL","CCL","NCL","WCL","SECL","MCL","NEC","SCCL","CIL","CMPDI"):
        if sub in name:
            return sub
    return None


# ── query helpers ─────────────────────────────────────────────────────────────

def neighbours(node_type: str, node_id: str, rel: str | None = None) -> list[dict]:
    """Return all nodes adjacent to (node_type, node_id), optionally filtered by rel."""
    con = db.connect()
    if rel:
        rows = con.execute(
            "SELECT rel, tgt_type, tgt_id, weight FROM graph_edges "
            "WHERE src_type=? AND src_id=? AND rel=?",
            (node_type, str(node_id), rel)).fetchall()
    else:
        rows = con.execute(
            "SELECT rel, tgt_type, tgt_id, weight FROM graph_edges "
            "WHERE src_type=? AND src_id=?",
            (node_type, str(node_id))).fetchall()
    con.close()
    return [dict(r) for r in rows]


def multi_hop(question: str) -> dict:
    """Lightweight multi-hop traversal: extract entities from question, walk graph,
    return structured context for the LLM or for direct answer rendering.

    Example: "SECL opencast projects with G7-G9 coal and stripping ratio below 4"
    → finds SECL subsidiary node → OPERATED_BY projects → filters SR < 4
    → COVERS_BLOCK → HAS_BOREHOLE → HAS_SEAM → filters grade G7-G9
    """
    con = db.connect()
    q = question.upper()
    found: dict[str, list] = {"subsidiaries": [], "blocks": [], "projects": [],
                               "seams": [], "boreholes": []}

    # 1. Extract mentioned subsidiaries
    for sub in ("ECL","BCCL","CCL","NCL","WCL","SECL","MCL","NEC","SCCL","CIL","CMPDI"):
        if sub in q:
            found["subsidiaries"].append(sub)

    # 2. Fetch projects for those subsidiaries
    grades_wanted = re.findall(r"G\d{1,2}", question, re.I)
    sr_limit = None
    m = re.search(r"stripping\s+ratio\s+(?:below|under|<)\s*([\d.]+)", question, re.I)
    if m:
        sr_limit = float(m.group(1))

    if found["subsidiaries"]:
        placeholders = ",".join("?" * len(found["subsidiaries"]))
        projects = con.execute(
            f"SELECT * FROM projects WHERE subsidiary IN ({placeholders})", found["subsidiaries"]).fetchall()
        if sr_limit is not None:
            projects = [p for p in projects if p["stripping_ratio"] is not None and float(p["stripping_ratio"]) < sr_limit]
        found["projects"] = [dict(p) for p in projects]

        # 3. For each project block, find seams with matching grades
        blocks = list({p["block"] for p in projects if p["block"]})
        if blocks and grades_wanted:
            grade_placeholders = ",".join("?" * len(grades_wanted))
            bh_ids = con.execute(
                "SELECT id FROM boreholes WHERE block IN ({})".format(",".join("?" * len(blocks))),
                blocks).fetchall()
            if bh_ids:
                bh_id_list = [r["id"] for r in bh_ids]
                smq = "SELECT sm.*, bh.borehole_id bh_name FROM seams sm JOIN boreholes bh ON bh.id=sm.borehole_id " \
                      f"WHERE sm.borehole_id IN ({','.join('?' * len(bh_id_list))}) " \
                      f"AND UPPER(sm.statutory_grade) IN ({grade_placeholders})"
                seams = con.execute(smq, bh_id_list + [g.upper() for g in grades_wanted]).fetchall()
                found["seams"] = [dict(s) for s in seams]

    con.close()

    # Build a readable summary
    lines = []
    if found["projects"]:
        lines.append(f"**Projects found ({len(found['projects'])}):**")
        for p in found["projects"][:10]:
            lines.append(f"- {p.get('name','?')} ({p.get('subsidiary','?')}) | "
                         f"SR={p.get('stripping_ratio','?')} | {p.get('mining_method','?')}")
    if found["seams"]:
        lines.append(f"\n**Seams matching grade filter ({len(found['seams'])}):**")
        for s in found["seams"][:10]:
            lines.append(f"- Seam '{s.get('seam','?')}' in borehole '{s.get('bh_name','?')}' | "
                         f"GCV={s.get('gcv','?')} | Grade={s.get('statutory_grade','?')}")
    if not lines:
        lines.append("No matching nodes found via graph traversal. Try the SQL query tab.")

    return {"found": found, "summary": "\n".join(lines), "hops": 3}


# ── summary ───────────────────────────────────────────────────────────────────

def graph_summary() -> dict:
    con = db.connect()
    counts = {}
    for tbl in ("boreholes","strata","seams","projects","graph_edges"):
        counts[tbl] = con.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
    rel_counts = {r["rel"]: r["cnt"] for r in con.execute(
        "SELECT rel, COUNT(*) cnt FROM graph_edges GROUP BY rel ORDER BY 2 DESC").fetchall()}
    con.close()
    return {"node_table_counts": counts, "edge_types": rel_counts}
