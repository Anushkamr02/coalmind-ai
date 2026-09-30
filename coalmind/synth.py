"""Synthetic Coal-Directory-style workbook with a known answer key and PLANTED errors.
Used for the demo and for measured KPIs (blueprint section 7). All figures are SYNTHETIC."""
import json
from pathlib import Path
from openpyxl import Workbook
from openpyxl.utils import get_column_letter as L
from .config import SYN

YEARS = ["2021-22", "2022-23", "2023-24"]
COMP = {  # synthetic production, million tonnes
    "ECL": [50.2, 52.4, 54.1], "BCCL": [30.1, 31.5, 33.0], "CCL": [135.0, 142.6, 150.2],
    "NCL": [119.5, 123.1, 128.4], "WCL": [56.8, 60.2, 64.3], "SECL": [155.4, 162.9, 170.1],
    "MCL": [205.1, 221.3, 240.6], "NEC": [0.9, 0.8, 0.7],
}
OTHERS = {"SCCL": [65.0, 67.6, 70.2], "Captive & Others": [140.3, 168.9, 210.4]}


def build(path=None):
    path = Path(path or SYN / "CoalDirectory_synthetic_ch3.xlsx")
    gold, planted = {}, []
    wb = Workbook(); ws = wb.active; ws.title = "Table 3.1"
    ws.append(["SYNTHETIC DEMO DATA - Coal Directory style"]); ws.append([])
    ws.append(["Table 3.1: Company-wise Production of Raw Coal (Million Tonnes)"])
    ws.append(["S.No", "Company"] + YEARS)
    ws.append([None, None, "(1)", "(2)", "(3)"] if False else [])
    r0 = ws.max_row + 1
    rows = list(COMP.items())
    cil = [round(sum(v[i] for v in COMP.values()), 1) for i in range(3)]
    allrows = [(k, v[:]) for k, v in rows] + [("Coal India Ltd. (Total)", cil)] + [(k, v[:]) for k, v in OTHERS.items()]
    allrows[-1][1][2] = allrows[-1][1][2]
    sccl = [i for i, (k, _) in enumerate(allrows) if k == "SCCL"][0]
    total = [round(cil[i] + OTHERS["SCCL"][i] + OTHERS["Captive & Others"][i], 1) for i in range(3)]
    allrows.append(("All India", total))
    # planted errors ---------------------------------------------------------------------------
    allrows[sccl][1][1] = round(allrows[sccl][1][1] * 10, 1)                 # decimal slip (x10)
    cil_i = [i for i, (k, _) in enumerate(allrows) if k.startswith("Coal India")][0]
    allrows[cil_i][1][2] = round(cil[2] + 25.0, 1)                            # total does not add up
    sn = 0
    first = ws.max_row + 1
    for k, vals in allrows:
        is_comp = k in COMP
        sn += 1 if is_comp else 0
        ws.append([sn if is_comp else None, k] + vals)
    for i, (k, vals) in enumerate(allrows):
        for j, v in enumerate(vals):
            gold[f"Table 3.1!{L(3+j)}{first+i}"] = dict(value=v, entity=k, col=YEARS[j])
    planted.append(dict(cell=f"Table 3.1!D{first+sccl}", code="UNIT_OR_DECIMAL_SHIFT|YOY_JUMP"))
    planted.append(dict(cell=f"Table 3.1!E{first+cil_i}", code="SUM_MISMATCH"))
    ws.append([]); ws.append(["Source: synthetic"])
    # second table: merged headers, negative value, invalid period -------------------------------
    ws.append([]); ws.append(["Table 3.2: State-wise Production of Coal (Million Tonnes)"])
    h1 = ws.max_row + 1
    ws.append(["State", "Coking Coal", None, "Non-Coking Coal", None]); ws.merge_cells(f"B{h1}:C{h1}"); ws.merge_cells(f"D{h1}:E{h1}")
    ws.append([None, "2022-23", "2023-25", "2022-23", "2023-24"])            # 2023-25 planted invalid period
    st = [("Jharkhand", 38.1, 40.2, 25.4, 27.0), ("Odisha", 0.0, 0.0, 185.0, 198.8),
          ("Chhattisgarh", 0.0, 0.0, 158.2, 170.4), ("Madhya Pradesh", 0.0, 0.0, 145.1, 150.0),
          ("West Bengal", 3.1, 3.2, 28.0, -29.5)]                            # negative planted
    s0 = ws.max_row + 1
    for row in st:
        ws.append(list(row))
    ws.append(["Total", *[round(sum(x[i] for x in st), 1) for i in range(1, 5)]])
    for i, row in enumerate(st + [("Total", *[round(sum(x[i] for x in st), 1) for i in range(1, 5)])]):
        for j in range(4):
            gold[f"Table 3.1!{L(2+j)}{s0+i}"] = dict(value=row[1 + j], entity=row[0], col=["Coking Coal | 2022-23", "Coking Coal | 2023-25", "Non-Coking Coal | 2022-23", "Non-Coking Coal | 2023-24"][j])
    planted.append(dict(cell=f"Table 3.1!E{s0+4}", code="NEGATIVE_QTY"))
    planted.append(dict(cell=f"Table 3.1!C{s0}", code="PERIOD_INVALID"))
    # sheet 2: section headings + subtotals ------------------------------------------------------
    w2 = wb.create_sheet("Table 3.3")
    w2.append(["Table 3.3: Despatch of Coal by Sector ('000 Tonnes)"]); w2.append(["Sector", "2022-23", "2023-24"])
    w2.append(["Coking"]); w2.append(["Steel", 1000, 1100]); w2.append(["Other coking", 250, 275]); w2.append(["Total Coking", 1250, 1375])
    w2.append(["Non-Coking"]); w2.append(["Power", 9000, 9500]); w2.append(["Cement", 700, 720]); w2.append(["Total Non-Coking", 9700, 10220])
    w2.append(["All India", 10950, 11595])
    wb.save(path)
    key = path.with_suffix(".gold.json")
    key.write_text(json.dumps(dict(gold=gold, planted=planted), indent=1))
    return path, key


# ── seed borehole / seam data directly into DB ───────────────────────────────
def seed_geological_demo():
    """Insert synthetic boreholes / strata / seams / projects to demo Tier 4 rules.
    Called after ingest so the DB already exists."""
    from . import db
    from .thesaurus import classify_seam_grade, normalise
    con = db.connect()

    # Get any doc_id
    row = con.execute("SELECT id FROM documents LIMIT 1").fetchone()
    doc_id = row["id"] if row else 1

    boreholes = [
        # (borehole_id, block, coalfield, subsidiary, collar_rl, total_depth)
        ("BH-SECL-001", "Block-A", "Korba",  "SECL", 310.5, 150.0),
        ("BH-NCL-001",  "Block-B", "Singrauli", "NCL", 285.2, 120.0),  # planted: depth sum off
        ("BH-MCL-001",  "Block-C", "Talcher", "MCL",  225.0, 180.0),
    ]
    bh_ids = []
    for b in boreholes:
        cur = con.execute(
            "INSERT INTO boreholes(doc_id,borehole_id,block,coalfield,subsidiary,collar_rl,total_depth) "
            "VALUES(?,?,?,?,?,?,?)", (doc_id, *b))
        bh_ids.append(cur.lastrowid)

    # Strata for BH-SECL-001: correct sum = 150.0 m
    secl_strata = [
        (0.0, 18.5, "OB"),         (18.5, 42.0, "Sst"),
        (42.0, 58.3, "Sh"),        (58.3, 62.1, "Coal"),     # coal seam I
        (62.1, 89.0, "Carb. Sh"), (89.0, 110.5, "Sst"),
        (110.5, 118.2, "Coal"),    # coal seam II
        (118.2, 150.0, "Sh-Sst"),
    ]
    for df, dt, litho in secl_strata:
        canon = normalise(litho)
        con.execute("INSERT INTO strata(borehole_id,depth_from,depth_to,interval_thickness,"
                    "lithology_raw,lithology_code,core_recovery_pct) VALUES(?,?,?,?,?,?,?)",
                    (bh_ids[0], df, dt, round(dt-df,2), litho, canon, min(95.0+df*0.02, 100.0)))

    # Strata for BH-NCL-001: PLANTED depth sum error — totals 115 m not 120 m
    ncl_strata = [
        (0.0, 25.0, "OB"), (25.0, 60.0, "Sst"), (60.0, 90.0, "Sh"),
        (90.0, 95.0, "Coal"), (95.0, 115.0, "Carb. Sh"),  # 115 m total, not 120
    ]
    for df, dt, litho in ncl_strata:
        canon = normalise(litho)
        con.execute("INSERT INTO strata(borehole_id,depth_from,depth_to,interval_thickness,"
                    "lithology_raw,lithology_code,core_recovery_pct) VALUES(?,?,?,?,?,?,?)",
                    (bh_ids[1], df, dt, round(dt-df,2), litho, canon, 88.0))

    # Strata for BH-MCL-001: PLANTED core recovery > 100%
    mcl_strata = [
        (0.0, 30.0, "OB"), (30.0, 80.0, "Sst"), (80.0, 130.0, "Sh"),
        (130.0, 145.0, "Coal"), (145.0, 180.0, "Carb. Sh"),
    ]
    for i, (df, dt, litho) in enumerate(mcl_strata):
        canon = normalise(litho)
        recovery = 105.0 if i == 2 else 92.0   # PLANTED: 105% > 100
        con.execute("INSERT INTO strata(borehole_id,depth_from,depth_to,interval_thickness,"
                    "lithology_raw,lithology_code,core_recovery_pct) VALUES(?,?,?,?,?,?,?)",
                    (bh_ids[2], df, dt, round(dt-df,2), litho, canon, recovery))

    # Seams for BH-SECL-001: PLANTED GCV-grade mismatch on seam II
    seams = [
        (bh_ids[0], "Seam I",  3.8, 6.5, 28.2, 22.1, 43.2, 4750.0, "G9",   "Proved",    0.45),
        (bh_ids[0], "Seam II", 7.7, 5.8, 31.0, 23.5, 39.7, 6800.0, "G5",   "Indicated", 0.90),  # GCV 6800 → G2 not G5 PLANTED
        (bh_ids[1], "Seam A",  5.2, 7.2, 26.0, 20.5, 46.3, 5150.0, "G8",   "Proved",    0.60),
        (bh_ids[2], "Seam X",  15.0,5.1, 22.0, 18.0, 54.9, 4420.0, "G10",  "Proved",    1.20),
        (bh_ids[2], "Seam Y",  12.0,6.0, 20.0, 16.0, 58.0, -50.0,  None,   "Inferred",  0.80),  # PLANTED negative GCV
    ]
    for (bh_id, seam, thk, moist, ash, vm, fc, gcv, grade, cls, reserve) in seams:
        auto_grade = classify_seam_grade(gcv) if gcv and gcv > 0 else grade
        # Keep planted wrong grade for the demo validation
        con.execute("INSERT INTO seams(borehole_id,seam,thickness,moisture_pct,ash_pct,"
                    "volatile_matter_pct,fixed_carbon_pct,gcv,statutory_grade,reserve_mt,reserve_class) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (bh_id, seam, thk, moist, ash, vm, fc, gcv, grade or auto_grade, reserve, cls))

    # Projects
    projects = [
        # (doc_id, name, subsidiary, method, SR, ob_mcm, coal_wt, capacity, block)
        (doc_id, "Gevra OC",    "SECL", "Opencast",    3.21, 120.5, 37.5,  25.0, "Block-A"),
        (doc_id, "Dudhichua OC","NCL",  "Opencast",    5.80, 200.0, 34.5,  20.0, "Block-B"),
        (doc_id, "Lakhanpur OC","MCL",  "Opencast",    1.85, 50.2,  27.2,  10.0, "Block-C"),
        (doc_id, "Moonidih UG", "BCCL", "Underground", None, None,  None,   4.5, None),    # SR for UG = None (correct)
        (doc_id, "Kusunda UG",  "BCCL", "Underground", 2.50, None,  None,   2.0, None),    # PLANTED SR on UG project
    ]
    for (did, name, sub, method, sr, ob, coal, cap, block) in projects:
        con.execute("INSERT INTO projects(doc_id,name,subsidiary,mining_method,stripping_ratio,"
                    "ob_volume_mcm,coal_weight_mt,capacity_mty,block) VALUES(?,?,?,?,?,?,?,?,?)",
                    (did, name, sub, method, sr, ob, coal, cap, block))

    con.commit(); con.close()
    return len(bh_ids)
