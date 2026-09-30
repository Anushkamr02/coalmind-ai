"""Hybrid query engine: text-to-SQL for numeric questions, keyword search for narrative.
Blueprint section 6.6. LLM is optional - falls back to keyword matching if unavailable."""
import re, sqlite3
from . import db, llm

SCHEMA_DESC = """
facts(id, doc_id, table_id, sheet, cell, row_ref, entity, section, column_label, qualifier,
      period, value, unit, raw_text, is_total, confidence, status)
src_tables(id, doc_id, sheet, title, unit, first_cell, last_cell, n_rows)
documents(id, sha256, filename, doc_type, kind, uploaded_at)
flags(id, fact_id, code, severity, detail, resolved)
chunks(id, doc_id, loc, kind, text)
audit_log(id, ts, user, action, target, detail)

Key columns: entity (row label e.g. "CCL"), column_label (e.g. "2023-24"), period (e.g. "2023-24"),
value (REAL), unit (e.g. "MT","Rs crore","kcal/kg"), is_total (1=totals row), status, confidence.
"""

SQL_SYSTEM = f"""You are a text-to-SQL assistant for a coal production database.
SCHEMA:
{SCHEMA_DESC}
Rules:
- Return ONLY a valid, read-only SQLite SELECT statement; no explanation, no markdown.
- Use LIKE '%...%' for entity/section/column_label matching (case-insensitive with LOWER()).
- For company totals use is_total=1 on the All India or India row; for company rows is_total=0.
- For production volumes, unit LIKE '%MT%' or unit LIKE '%t%'.
- Always LIMIT 50 unless the user asks for all."""

ROUTE_SYSTEM = """Classify the question as one of: sql, keyword, mixed.
sql  = asks for specific numbers, values, comparisons, rankings, sums (return only the word sql)
keyword = asks for explanation, description, background, definition (return only the word keyword)
mixed = both (return only the word mixed)
Reply with exactly one word."""

FEW_SHOT = [
    ("What was India's total coal production in 2023-24?",
     "SELECT entity, value, unit FROM facts WHERE LOWER(entity) LIKE '%all india%' AND period='2023-24' AND is_total=1 LIMIT 5"),
    ("Show production by subsidiary for the last 3 years",
     "SELECT f.entity, f.period, f.value, f.unit FROM facts f JOIN src_tables t ON t.id=f.table_id WHERE LOWER(t.title) LIKE '%production%' AND f.is_total=0 ORDER BY f.entity, f.period LIMIT 50"),
    ("Which company had highest production in 2023-24?",
     "SELECT entity, value, unit FROM facts WHERE period='2023-24' AND is_total=0 AND LOWER(unit) LIKE '%mt%' ORDER BY value DESC LIMIT 5"),
]

READ_GUARD = re.compile(r"\b(insert|update|delete|drop|alter|attach|create|replace)\b", re.I)


def run_readonly(sql):
    sql = sql.strip().rstrip(";")
    if not re.match(r"^\s*select\b", sql, re.I):
        raise ValueError("Only SELECT allowed")
    if ";" in sql or READ_GUARD.search(sql):
        raise ValueError("Unsafe SQL detected")
    con = db.connect()
    try:
        rows = con.execute(sql).fetchall()
        cols = [d[0] for d in con.execute(sql).description]
        return cols, [list(r) for r in rows]
    finally:
        con.close()


def route(question):
    resp = llm.chat(ROUTE_SYSTEM, question, max_tokens=10)
    if resp:
        w = resp.strip().lower().split()[0]
        if w in ("sql", "keyword", "mixed"):
            return w
    # fallback heuristic
    nums = bool(re.search(r"\d|how much|total|production|value|compare|highest|lowest|rank|which|top\s*\d|latest", question, re.I))
    narr = bool(re.search(r"what is|explain|describe|define|background|tell me about|why|how does|history", question, re.I))
    if nums and narr:
        return "mixed"
    return "sql" if nums else "keyword"


def ask_sql(question):
    examples = "\n".join(f"Q: {q}\nSQL: {s}" for q, s in FEW_SHOT)
    prompt = f"Examples:\n{examples}\n\nQuestion: {question}\nSQL:"
    sql = llm.chat(SQL_SYSTEM, prompt, max_tokens=300)
    if not sql:
        return _fallback_sql(question), True
    sql = re.sub(r"```(?:sql)?|```", "", sql).strip()
    return sql, False


def ask_keyword(question, k=5):
    words = [w.lower() for w in re.findall(r"[a-z]{3,}", question.lower())
             if w not in {"the", "and", "for", "what", "which", "that", "this", "are", "was", "been", "with", "from"}]
    if not words:
        return []
    con = db.connect()
    rows = []
    for w in words[:4]:
        rows += con.execute("SELECT doc_id, loc, text FROM chunks WHERE LOWER(text) LIKE ? LIMIT 10", (f"%{w}%",)).fetchall()
    con.close()
    seen, out = set(), []
    for r in rows:
        k2 = (r["doc_id"], r["loc"], r["text"][:40])
        if k2 not in seen:
            seen.add(k2)
            out.append(dict(doc_id=r["doc_id"], loc=r["loc"], snippet=r["text"][:300]))
    return out[:k]


def _fallback_sql(question):
    q = question.lower()
    period = None
    m = re.search(r"20\d{2}[-–/]\d{2}", question)
    if m:
        period = m.group(0).replace("–", "-").replace("/", "-")
    entity = None
    for co in ("ecl", "bccl", "ccl", "ncl", "wcl", "secl", "mcl", "nec", "cil", "sccl", "nhpc"):
        if co in q:
            entity = co.upper()
            break
    conds = ["1=1"]
    if period:
        conds.append(f"period='{period}'")
    if entity:
        conds.append(f"LOWER(entity) LIKE '%{entity.lower()}%'")
    if "production" in q:
        conds.append("LOWER(unit) LIKE '%mt%' OR LOWER(unit) LIKE '%tonne%'")
    return f"SELECT entity, period, value, unit, confidence FROM facts WHERE {' AND '.join(conds)} LIMIT 30"


def answer(question, user="officer"):
    rtype = route(question)
    result = dict(question=question, route=rtype, sql=None, rows=None, cols=None,
                  snippets=None, narrative=None, error=None)
    if rtype in ("sql", "mixed"):
        sql, fallback = ask_sql(question)
        result["sql"] = sql
        result["fallback_sql"] = fallback
        try:
            cols, rows = run_readonly(sql)
            result["cols"], result["rows"] = cols, rows
        except Exception as e:
            result["error"] = str(e)
    if rtype in ("keyword", "mixed"):
        result["snippets"] = ask_keyword(question)
    if llm.available() and result.get("rows") is not None:
        rows_str = "\n".join(str(r) for r in (result["rows"] or [])[:20])
        result["narrative"] = llm.chat(
            "You are an assistant for Indian coal sector officials. Answer using ONLY the data provided. "
            "Be concise, use units, cite subsidiary names. Never invent numbers.",
            f"Question: {question}\nData:\n{rows_str}\nAnswer:", max_tokens=400)
    db.audit("QUERY", question[:80], f"route={rtype}", user=user)
    return result
