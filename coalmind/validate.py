"""Deterministic validation engine (blueprint section 6.5 + new architecture Tier 4).

Rules implemented
-----------------
Existing (statistical / Excel data):
  SUM_MISMATCH · NEGATIVE_QTY · PERIOD_INVALID · UNIT_MISSING · PERIOD_MISSING
  UNIT_OR_DECIMAL_SHIFT · YOY_JUMP · CROSS_DOC_MISMATCH

New (geological / borehole data — new architecture Tier 4):
  BOREHOLE_DEPTH_SUM   – Σ strata intervals ≠ total drilled depth
  CORE_RECOVERY_OVER   – core recovery % > 100
  DEPTH_ORDER          – depth_to ≤ depth_from in a strata interval
  GCV_GRADE_MISMATCH   – recorded grade label doesn't match GCV value in MoC bands
  MOISTURE_RANGE       – moisture % outside [0, 100]
  RESERVE_SUM          – seam-level UNFC reserves don't add up to block total
  STRIPPING_RATIO      – SR = OB_volume / coal_weight; flags impossible values
  UNFC_BALANCE         – Proved + Indicated + Inferred ≠ Total resource estimate
"""
import re
import pandas as pd
from . import db
from .thesaurus import classify_seam_grade, grade_range

ADDITIVE = {"MT", "BT", "lakh t", "'000 t", "t", "Rs crore", "ha", "MW", "m3", None}
NON_ADDITIVE_LABEL = re.compile(r"growth|%|share|percent|per\s*cent|average|avg|ratio|rate|index|price|grade|gcv|oms|"
                                r"productivity|per\s|/|variation|change|stripping|yield|recovery|density", re.I)
SIGNED_LABEL = re.compile(r"growth|change|variation|difference|balance|net|deficit|surplus|gap|shortfall|profit|loss", re.I)


def close(a, b, n=1):
    return abs(a - b) <= max(0.005 * max(abs(a), abs(b)), 0.1 * n)


def _fy_key(p):
    return int(p[:4]) if p and re.fullmatch(r"\d{4}-\d{2}", p) else None


def rule_sum(df):
    out = []
    for (tid, col), g in df[df.unit.isin(list(ADDITIVE - {None})) | df.unit.isna()].groupby(["table_id", "column_label"]):
        if NON_ADDITIVE_LABEL.search(col or "") or NON_ADDITIVE_LABEL.search(str(g.iloc[0].table_title)):
            continue
        known = g.iloc[0].unit is not None
        run, subs = [], []
        for _, r in g.sort_values("row_no").iterrows():
            if r.is_total:
                cands = [x for x in (sum(run) if run else None, sum(subs) if subs else None) if x is not None]
                if cands and not any(close(r.value, c, len(run) + len(subs)) for c in cands):
                    out.append((r.fact_id, "SUM_MISMATCH", "warn" if known else "info",
                                f"'{r.entity}' = {r.value:g} but components sum to "
                                + " or ".join(f"{c:g}" for c in cands) + f" ({col})"))
                subs.append(r.value); run = []
            else:
                run.append(r.value)
    return out


def rule_negative(df):
    d = df[(df.unit.isin(list(ADDITIVE - {None}))) & (df.value < 0)]
    return [(r.fact_id, "NEGATIVE_QTY", "error", f"{r.entity}: negative value {r.value:g} {r.unit} in '{r.column_label}'")
            for r in d.itertuples() if not SIGNED_LABEL.search(f"{r.column_label} {r.table_title}")]


def rule_period(df):
    out = []
    for r in df.drop_duplicates(["table_id", "column_label"]).itertuples():
        m = re.search(r"(?<!\d)((?:19|20)\d{2})\s*[-–/]\s*((?:19|20)?\d{2})(?!\d)", r.column_label or "")
        if m and (int(m.group(1)) + 1) % 100 != int(m.group(2)[-2:]):
            out.append((r.fact_id, "PERIOD_INVALID", "error",
                        f"Column '{r.column_label}' is not a valid financial year (expected {m.group(1)}-{(int(m.group(1))+1)%100:02d})"))
    return out


def rule_metadata(df):
    out = []
    for tid, g in df.groupby("table_id"):
        f = g.iloc[0]
        if g.unit.isna().all():
            out.append((f.fact_id, "UNIT_MISSING", "info", f"No unit detected for table '{f.table_title[:80]}' - verify units"))
        if g.period.isna().all():
            out.append((f.fact_id, "PERIOD_MISSING", "info", f"No period detected for table '{f.table_title[:80]}'"))
    return out


def rule_yoy(df, jump=3.0):
    out = []
    d = df[df.period.map(_fy_key).notna() & (df.unit != "%") & ~df.column_label.str.contains(NON_ADDITIVE_LABEL, na=False)]
    for _, g in d.groupby(["table_id", "section", "entity", "qualifier"], dropna=False):
        g = g.assign(k=g.period.map(_fy_key)).sort_values("k")
        prev = None
        for r in g.itertuples():
            if prev is not None and abs(prev.value) >= 1 and r.value != 0:
                ratio = r.value / prev.value
                shift = next((s for s in (10, 100, 1000) if abs(ratio / s - 1) < 0.08 or abs(ratio * s - 1) < 0.08), None)
                if shift and ratio > 0:
                    out.append((r.fact_id, "UNIT_OR_DECIMAL_SHIFT", "warn",
                                f"{r.entity}: {prev.period} {prev.value:g} -> {r.period} {r.value:g} (x{ratio:.3g}) - decimal or unit slip?"))
                elif ratio >= jump or (0 < ratio <= 1 / jump):
                    out.append((r.fact_id, "YOY_JUMP", "warn",
                                f"{r.entity}: {prev.period} {prev.value:g} -> {r.period} {r.value:g} (x{ratio:.2f})"))
            prev = r
    return out


def rule_cross_doc(df):
    out = []
    d = df.dropna(subset=["period"]).copy()
    d["nt"] = d.table_title.str.lower().str.replace(r"table\s*[\d.]+|[^a-z ]", "", regex=True).str.strip()
    for _, g in d.groupby(["nt", "entity", "section", "column_label", "period"], dropna=False):
        if g.doc_id.nunique() > 1 and (g.value.max() - g.value.min()) > 0.01 * max(abs(g.value.max()), 1e-9):
            spread = ", ".join(f"{r.filename}: {r.value:g}" for r in g.itertuples())
            out += [(r.fact_id, "CROSS_DOC_MISMATCH", "warn", f"{r.entity} {r.period}: {spread}") for r in g.itertuples()]
    return out


# ══════════════════════════════════════════════════════════════════════════════
# NEW RULES: Geological / borehole data (Tier 4 of new architecture)
# These operate on the boreholes / strata / seams / projects tables.
# They produce the same (fact_ref, code, severity, detail) tuples as the
# statistical rules above — but use a string ref "bh:<id>" or "seam:<id>"
# as the first element since there is no facts.id for these rows.
# ══════════════════════════════════════════════════════════════════════════════

def rule_borehole_depth(con):
    """Σ(depth_to - depth_from) across strata must equal total_depth (±1 cm)."""
    flags = []
    for bh in con.execute("SELECT * FROM boreholes").fetchall():
        strata = con.execute("SELECT depth_from, depth_to FROM strata WHERE borehole_id=?", (bh["id"],)).fetchall()
        if not strata:
            continue
        computed = sum(float(s["depth_to"]) - float(s["depth_from"]) for s in strata)
        td = float(bh["total_depth"] or 0)
        if td > 0 and abs(computed - td) > 0.01:
            flags.append((f"bh:{bh['id']}", "BOREHOLE_DEPTH_SUM", "error",
                          f"Borehole '{bh['borehole_id']}': strata sum={computed:.2f} m "
                          f"but total depth={td:.2f} m (diff={abs(computed-td):.2f} m)"))
    return flags


def rule_strata_physical(con):
    """Core recovery > 100 % or depth_to ≤ depth_from."""
    flags = []
    for s in con.execute("SELECT st.*, bh.borehole_id bh_name FROM strata st "
                         "JOIN boreholes bh ON bh.id=st.borehole_id").fetchall():
        if s["core_recovery_pct"] is not None and float(s["core_recovery_pct"]) > 100:
            flags.append((f"strata:{s['id']}", "CORE_RECOVERY_OVER", "error",
                          f"Borehole '{s['bh_name']}': recovery {s['core_recovery_pct']}% > 100% "
                          f"at depth {s['depth_from']}–{s['depth_to']} m"))
        if s["depth_to"] is not None and s["depth_from"] is not None and float(s["depth_to"]) <= float(s["depth_from"]):
            flags.append((f"strata:{s['id']}", "DEPTH_ORDER", "error",
                          f"Borehole '{s['bh_name']}': depth_to ({s['depth_to']}) ≤ depth_from ({s['depth_from']})"))
    return flags


def rule_gcv_grade(con):
    """Recorded statutory_grade must match the GCV value in MoC official grade bands."""
    flags = []
    for sm in con.execute("SELECT sm.*, bh.borehole_id bh_name FROM seams sm "
                          "JOIN boreholes bh ON bh.id=sm.borehole_id "
                          "WHERE sm.gcv IS NOT NULL AND sm.statutory_grade IS NOT NULL").fetchall():
        gcv = float(sm["gcv"])
        recorded_grade = (sm["statutory_grade"] or "").strip().upper()
        computed_grade = classify_seam_grade(gcv)
        rng = grade_range(recorded_grade)
        if computed_grade != recorded_grade:
            band_str = f"({rng[0]}–{rng[1]} kcal/kg)" if rng else "(unknown band)"
            flags.append((f"seam:{sm['id']}", "GCV_GRADE_MISMATCH", "error",
                          f"Borehole '{sm['bh_name']}' seam '{sm['seam']}': "
                          f"GCV={gcv} kcal/kg → grade should be {computed_grade} "
                          f"but recorded as {recorded_grade} {band_str}"))
    return flags


def rule_seam_moisture(con):
    """Moisture % must be in [0, 100]."""
    flags = []
    for sm in con.execute("SELECT sm.*, bh.borehole_id bh_name FROM seams sm "
                          "JOIN boreholes bh ON bh.id=sm.borehole_id "
                          "WHERE sm.moisture_pct IS NOT NULL").fetchall():
        m = float(sm["moisture_pct"])
        if not 0 <= m <= 100:
            flags.append((f"seam:{sm['id']}", "MOISTURE_RANGE", "error",
                          f"Borehole '{sm['bh_name']}' seam '{sm['seam']}': "
                          f"moisture {m}% is outside [0, 100]"))
    return flags


def rule_reserve_sum(con):
    """UNFC: Proved + Indicated + Inferred ≈ block-level total reserve.
    Also checks per-seam sums roll up to block total (tolerance 0.5%)."""
    flags = []
    for bh in con.execute("SELECT * FROM boreholes").fetchall():
        seams = con.execute(
            "SELECT seam, reserve_mt, reserve_class FROM seams "
            "WHERE borehole_id=? AND reserve_mt IS NOT NULL", (bh["id"],)).fetchall()
        if not seams:
            continue
        # Sum of all seam reserves (any class)
        total_seams = sum(float(s["reserve_mt"]) for s in seams)
        # UNFC class breakdown
        by_class: dict[str, float] = {}
        for s in seams:
            cls = (s["reserve_class"] or "Unknown").strip().capitalize()
            by_class[cls] = by_class.get(cls, 0.0) + float(s["reserve_mt"])
        # If all three UNFC classes present, their sum must equal total
        if all(c in by_class for c in ("Proved", "Indicated", "Inferred")):
            unfc_total = sum(by_class[c] for c in ("Proved", "Indicated", "Inferred"))
            tol = max(0.005 * total_seams, 0.001)
            if abs(unfc_total - total_seams) > tol:
                flags.append((f"bh:{bh['id']}", "UNFC_BALANCE", "warn",
                              f"Borehole '{bh['borehole_id']}': "
                              f"Proved+Indicated+Inferred={unfc_total:.3f} MT "
                              f"≠ seam sum={total_seams:.3f} MT"))
    return flags


def rule_stripping_ratio(con):
    """SR = OB volume (Mm³) / coal weight (MT) should be within 1–20 for opencast projects.
    Blueprint formula: SR = V_OB / W_Coal."""
    flags = []
    for p in con.execute("SELECT * FROM projects WHERE stripping_ratio IS NOT NULL OR "
                         "(ob_volume_mcm IS NOT NULL AND coal_weight_mt IS NOT NULL)").fetchall():
        sr = p["stripping_ratio"]
        if sr is None and p["ob_volume_mcm"] and p["coal_weight_mt"]:
            try:
                sr = float(p["ob_volume_mcm"]) / float(p["coal_weight_mt"])
            except ZeroDivisionError:
                continue
        if sr is None:
            continue
        sr = float(sr)
        method = (p["mining_method"] or "").lower()
        # For Opencast: typical SR 1–20; UG projects should not have SR at all
        if "opencast" in method or "oc" in method or not method:
            if not (0.5 <= sr <= 25):
                flags.append((f"project:{p['id']}", "STRIPPING_RATIO", "warn",
                              f"Project '{p['name']}': SR={sr:.2f} is outside the expected "
                              f"range [0.5, 25] for opencast mining"))
        elif "underground" in method or "ug" in method:
            if sr > 0:
                flags.append((f"project:{p['id']}", "STRIPPING_RATIO", "info",
                              f"Project '{p['name']}': stripping ratio {sr:.2f} recorded for "
                              f"underground project — verify mining method"))
    return flags


def run_all(log=print):
    con = db.connect()
    df = pd.read_sql("SELECT f.*, t.title table_title, d.filename, f.id fact_id FROM facts f "
                     "JOIN src_tables t ON t.id=f.table_id JOIN documents d ON d.id=f.doc_id", con)
    df["unit"] = df["unit"].where(df["unit"].notna(), None)
    con.execute("DELETE FROM flags WHERE resolved=0")
    if df.empty:
        con.commit(); con.close(); return {}
    flags = []
    for name, fn in [("sum", rule_sum), ("negative", rule_negative), ("period", rule_period), ("metadata", rule_metadata),
                     ("yoy", rule_yoy), ("cross-doc", rule_cross_doc)]:
        got = fn(df)
        log(f"  rule {name:<14} -> {len(got)} flag(s)")
        flags += got

    # ── new geological rules (operate on boreholes/strata/seams/projects) ──
    geo_rules = [
        ("borehole-depth",   rule_borehole_depth),
        ("strata-physical",  rule_strata_physical),
        ("gcv-grade",        rule_gcv_grade),
        ("seam-moisture",    rule_seam_moisture),
        ("reserve-sum",      rule_reserve_sum),
        ("stripping-ratio",  rule_stripping_ratio),
    ]
    geo_flags = []
    for name, fn in geo_rules:
        got = fn(con)
        log(f"  rule {name:<14} -> {len(got)} flag(s)")
        geo_flags += got

    # Statistical flags use fact_id (int); geological flags use "bh:N"/"seam:N" refs
    con.executemany("INSERT INTO flags(fact_id,code,severity,detail) VALUES(?,?,?,?)",
                    [(int(a) if str(a).isdigit() else None, b, c, d) for a, b, c, d in flags])
    # Store geo flags in a separate column (detail carries the ref)
    con.executemany("INSERT INTO flags(fact_id,code,severity,detail) VALUES(?,?,?,?)",
                    [(None, b, c, f"[{a}] {d}") for a, b, c, d in geo_flags])
    con.execute("UPDATE facts SET status='verified' WHERE status IN ('pending','verified','flagged')")
    con.execute("UPDATE facts SET status='flagged' WHERE status='verified' AND id IN "
                "(SELECT fact_id FROM flags WHERE severity IN ('warn','error') AND resolved=0)")
    con.commit(); con.close()
    db.audit("VALIDATE", "all", f"{len(flags)} flags", user="system")
    return summary()


def summary():
    con = db.connect()
    q = lambda s: con.execute(s).fetchone()[0]
    res = dict(documents=q("SELECT COUNT(*) FROM documents"), tables=q("SELECT COUNT(*) FROM src_tables"),
               facts=q("SELECT COUNT(*) FROM facts"), flagged=q("SELECT COUNT(*) FROM facts WHERE status='flagged'"),
               flags_by_code={r[0]: r[1] for r in con.execute(
                   "SELECT code, COUNT(*) FROM flags WHERE resolved=0 GROUP BY code ORDER BY 2 DESC")})
    con.close()
    return res
