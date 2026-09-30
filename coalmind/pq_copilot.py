"""PQ Copilot - parses a Parliamentary Question, fetches facts, drafts a formal reply.
Blueprint section 6.7. Works without an LLM using template-based fallback."""
import json, re
from . import db, llm, query

PARSE_SYS = """You parse Parliamentary Questions about coal in India.
Extract and return ONLY valid JSON:
{
  "type": "starred"|"unstarred",
  "period": ["FY string or null"],
  "entities": ["subsidiary names or mine names or states"],
  "metrics": ["what is being asked e.g. production, reserves, accidents, employment"],
  "summary": "one sentence"
}"""

DRAFT_SYS = """You are a senior officer drafting a formal reply to a Parliamentary Question on behalf of 
Coal India / Ministry of Coal. Write in formal government style.
Rules:
- Use ONLY the provided data rows. Do not invent figures.
- State units clearly (Million Tonnes, Lakh Tonnes, etc.)
- If data is missing, write 'Data not available for [period/entity]'
- Structure: brief answer paragraph, then ANNEXURE table in markdown.
- End with 'Source: CoalMind Fact Store - figures subject to verification.'"""


def parse_pq(question):
    r = llm.chat(PARSE_SYS, question, json_mode=True, max_tokens=400)
    if r:
        d = llm.extract_json(r)
        if d:
            return d
    # heuristic fallback
    years = re.findall(r"20\d{2}[-–/]\d{2}", question)
    entities = [c for c in ("ECL","BCCL","CCL","NCL","WCL","SECL","MCL","NEC","CIL","SCCL") if c in question.upper()]
    return dict(type="unstarred", period=years or [None], entities=entities, metrics=["production"],
                summary=question[:80])


def fetch_data(parsed):
    rows_all, queries = [], []
    entities = parsed.get("entities") or []
    periods = [p for p in (parsed.get("period") or []) if p]
    metrics = " ".join(parsed.get("metrics") or ["production"])
    base = f"{metrics}"
    if entities:
        base += " by " + ", ".join(entities)
    if periods:
        base += " for " + ", ".join(periods)
    res = query.answer(base)
    if res.get("rows"):
        rows_all += [dict(zip(res["cols"], r)) for r in res["rows"]]
        queries.append(res["sql"])
    con = db.connect()
    if not rows_all:
        conds = []
        if periods:
            conds.append(f"period IN ({','.join('?' for _ in periods)})")
        sql = "SELECT entity,period,value,unit,column_label,confidence FROM facts WHERE " + \
              (" AND ".join(conds) if conds else "1=1") + " ORDER BY entity,period LIMIT 40"
        rows_all = [dict(r) for r in con.execute(sql, periods).fetchall()]
    con.close()
    return rows_all, queries


def draft(question, user="officer"):
    parsed = parse_pq(question)
    rows, sqls = fetch_data(parsed)
    data_str = json.dumps(rows[:30], indent=1) if rows else "No data found."
    if llm.available():
        text = llm.chat(DRAFT_SYS,
                        f"Parliamentary Question:\n{question}\n\nParsed intent:\n{json.dumps(parsed)}\n\nData:\n{data_str}\n\nDraft reply:",
                        max_tokens=900)
    else:
        # template fallback (always works, no LLM needed)
        lines = ["**Draft Reply to Parliamentary Question**\n",
                 f"**Subject:** {parsed.get('summary','Coal production data')}",
                 "",
                 "The following data is available in the CoalMind Fact Store:\n"]
        if rows:
            lines.append("| Entity | Period | Value | Unit |")
            lines.append("|--------|--------|-------|------|")
            for r in rows[:25]:
                lines.append(f"| {r.get('entity','')} | {r.get('period','')} | {r.get('value','')} | {r.get('unit','')} |")
        else:
            lines.append("Data not available for the requested parameters.")
        lines += ["", "Source: CoalMind Fact Store - figures subject to verification."]
        text = "\n".join(lines)
    confidence = "high" if rows and len(rows) >= 3 else ("medium" if rows else "low")
    con = db.connect()
    payload = json.dumps(dict(parsed=parsed, sqls=sqls, data_rows=rows[:10]))
    cur = con.execute("INSERT INTO pq_drafts(ts,question,draft,confidence,status,payload) VALUES(?,?,?,?,?,?)",
                      (db.now(), question, text or "", confidence, "draft", payload))
    pid = cur.lastrowid; con.commit(); con.close()
    db.audit("PQ_DRAFT", f"pq#{pid}", f"confidence={confidence}", user=user)
    return dict(id=pid, draft=text or "", confidence=confidence, rows=rows, parsed=parsed, sqls=sqls)


def approve(pq_id, edited_text=None, user="officer"):
    con = db.connect()
    final = edited_text or con.execute("SELECT draft FROM pq_drafts WHERE id=?", (pq_id,)).fetchone()[0]
    con.execute("UPDATE pq_drafts SET status='approved', draft=? WHERE id=?", (final, pq_id))
    con.commit(); con.close()
    db.audit("PQ_APPROVE", f"pq#{pq_id}", "", user=user)
