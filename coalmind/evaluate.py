"""KPI measurement against the synthetic gold set (blueprint section 7)."""
import json, os, re, time
from pathlib import Path
from . import db, ingest, validate, synth
from .config import SYN


def run(log=print):
    p, key = synth.build()
    gold = json.loads(key.read_text())
    planted = gold["planted"]
    db.reset()
    t0 = time.time()
    ingest.ingest_file(p, log=log)
    t_ingest = time.time() - t0
    flags_dict = validate.run_all(log=log)
    t_validate = time.time() - t0 - t_ingest
    con = db.connect()
    tot_gold = len([k for k, v in gold["gold"].items() if v["value"] is not None])
    extracted = con.execute("SELECT COUNT(*) FROM facts WHERE value IS NOT NULL").fetchone()[0]
    correct = 0
    for cell_ref, gv in gold["gold"].items():
        if gv["value"] is None:
            continue
        sheet, cell = cell_ref.split("!", 1) if "!" in cell_ref else ("", cell_ref)
        row = con.execute("SELECT value FROM facts WHERE LOWER(sheet)=LOWER(?) AND cell=?",
                          (sheet, cell)).fetchone()
        if row and abs(float(row[0]) - float(gv["value"])) < 0.05:
            correct += 1
    caught = 0
    flags_rows = [r[0] for r in con.execute("SELECT code FROM flags").fetchall()]
    for p_item in planted:
        expected_codes = p_item["code"].split("|")
        if any(ec in flags_rows for ec in expected_codes):
            caught += 1
    con.close()
    acc = round(100 * correct / max(tot_gold, 1), 1)
    catch = round(100 * caught / max(len(planted), 1), 1)
    results = dict(
        gold_facts=tot_gold, extracted=extracted, correct=correct, extraction_accuracy_pct=acc,
        planted_errors=len(planted), caught=caught, validation_catch_rate_pct=catch,
        ingest_time_s=round(t_ingest, 2), validate_time_s=round(t_validate, 2),
        llm_status=__import__("coalmind.llm", fromlist=["status"]).status(),
        flags_by_code=flags_dict.get("flags_by_code", {}),
    )
    log(f"\n=== KPI RESULTS ===")
    for k, v in results.items():
        log(f"  {k}: {v}")
    return results
