import tempfile, os
from pathlib import Path
from . import db
from .excel_parser import parse_workbook, legacy_to_xlsx
from .pdf_parser import parse_pdf

EXCEL = {".xlsx", ".xlsm", ".xls", ".csv"}


def classify(name):
    n = name.lower()
    if "calendar" in n: return "Release calendar"
    if "chap" in n: return "Coal Directory chapter"
    if "directory" in n: return "Coal Directory (full)"
    if "statistic" in n: return "Coal Statistics"
    if n.endswith(".pdf"): return "PDF report"
    return "Spreadsheet"


def ingest_file(path, max_pdf_pages=None, log=print):
    path = Path(path)
    sha = db.sha256_file(path)
    con = db.connect()
    row = con.execute("SELECT id FROM documents WHERE sha256=?", (sha,)).fetchone()
    if row:
        log(f"= {path.name}: already ingested (same SHA-256), skipped")
        con.close(); return None
    ext = path.suffix.lower()
    cur = con.execute("INSERT INTO documents(sha256,filename,doc_type,kind,uploaded_at) VALUES(?,?,?,?,?)",
                      (sha, path.name, classify(path.name), "excel" if ext in EXCEL else "pdf", db.now()))
    doc_id, n_facts, n_tables = cur.lastrowid, 0, 0
    if ext in EXCEL:
        src = path
        if ext in (".xls", ".csv"):
            src = legacy_to_xlsx(path, Path(tempfile.gettempdir()) / (path.stem + "_conv.xlsx"))
        tables, snippets = parse_workbook(src)
        for t in tables:
            tc = con.execute("INSERT INTO src_tables(doc_id,sheet,title,unit,first_cell,last_cell,n_rows) VALUES(?,?,?,?,?,?,?)",
                             (doc_id, t["sheet"], t["title"], t["unit"], t["first_cell"], t["last_cell"], t["n_rows"]))
            tid = tc.lastrowid
            con.executemany(
                "INSERT INTO facts(doc_id,table_id,sheet,cell,row_ref,row_no,section,entity,column_label,qualifier,period,"
                "value,unit,raw_text,is_total,confidence) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [(doc_id, tid, f["sheet"], f["cell"], f["row_ref"], f["row_no"], f["section"], f["entity"],
                  f["column_label"], f["qualifier"], f["period"], f["value"], f["unit"], f["raw_text"],
                  f["is_total"], f["confidence"]) for f in t["facts"]])
            n_facts += len(t["facts"]); n_tables += 1
        con.executemany("INSERT INTO chunks(doc_id,loc,kind,text) VALUES(?,?,?,?)",
                        [(doc_id, s, "table_title", t) for s, t in snippets])
    else:
        chunks = parse_pdf(path, max_pages=max_pdf_pages, log=log)
        con.executemany("INSERT INTO chunks(doc_id,loc,kind,text) VALUES(?,?,?,?)",
                        [(doc_id, p, "pdf", t) for p, t in chunks])
        n_tables = len(chunks)
    con.commit(); con.close()
    db.audit("INGEST", path.name, f"sha256={sha[:12]} tables/chunks={n_tables} facts={n_facts}", user="system")
    log(f"+ {path.name}: {n_tables} {'tables' if ext in EXCEL else 'text chunks'}, {n_facts} facts")
    return doc_id


def ingest_paths(paths, max_pdf_pages=None, log=print):
    files = []
    for p in map(Path, paths):
        files += sorted(f for f in p.rglob("*") if f.is_file() and f.suffix.lower() in EXCEL | {".pdf"}) if p.is_dir() else [p]
    for f in files:
        try:
            ingest_file(f, max_pdf_pages, log)
        except Exception as e:
            log(f"! {f.name}: failed ({type(e).__name__}: {e})")
    return len(files)
