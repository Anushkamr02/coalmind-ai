"""Layout-tolerant parser for statistical workbooks such as the Coal Directory chapters.

Each numeric cell becomes a Fact with provenance (sheet + cell address + row range):
  entity (row label) | section (group heading) | column_label | period | value | unit

Heuristics (no per-file configuration): find runs of numeric rows -> table blocks; header = text rows
directly above; title = single-cell text rows above the header; merged header cells are expanded;
serial-number columns and "(1) (2) (3)" column-index rows are dropped.
"""
import math, re
from openpyxl import Workbook, load_workbook
from openpyxl.utils import get_column_letter as L

NA = {"", "-", "–", "—", "na", "n.a.", "n.a", "..", "...", "nil", "n/a", "#n/a", "*", "--", "@"}
PERIOD_RE = re.compile(r"(?<!\d)((?:19|20)\d{2})\s*[-–/]\s*((?:19|20)?\d{2})(?!\d)")
COLNUM_RE = re.compile(r"\(\s*\d{1,3}\s*\)")
TOTAL_RE = re.compile(r"\btotal\b|^all[\s-]*india|^india$|^grand", re.I)
NOTE_RE = re.compile(r"^\s*(source|note|notes|\*|@|\(p\)|p:|provisional)", re.I)

UNIT_PATTERNS = [
    (r"million\s+tonnes?|\bmt\b|\bmmt\b|\bmty\b", "MT"),
    (r"billion\s+tonnes?|\bbt\b", "BT"),
    (r"lakh\s+tonnes?", "lakh t"),
    (r"'?000\s*tonnes?|thousand\s+tonnes?|\bkt\b|\bth\.?\s*tonnes?", "'000 t"),
    (r"kcal\s*/\s*kg", "kcal/kg"),
    (r"rs\.?\s*/\s*(?:tonne|t)\b|₹\s*/\s*tonne|per\s+tonne", "Rs/t"),
    (r"rs\.?\s*crores?|₹\s*crores?|crores?\s*rs|rupees?\s+crores?", "Rs crore"),
    (r"hectares?|\bha\b", "ha"),
    (r"\bm3\b|cubic\s+met", "m3"),
    (r"\bmw\b", "MW"),
    (r"\btonnes?\b", "t"),
]
PCT_RE = re.compile(r"%|per\s*cent|percent|growth|share", re.I)


def to_num(v):
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return None if (isinstance(v, float) and math.isnan(v)) else float(v)
    if isinstance(v, str):
        s = v.strip().replace(",", "").replace("%", "")
        if s.lower() in NA:
            return None
        neg = s.startswith("(") and s.endswith(")")
        s = s.strip("()")
        try:
            x = float(s)
        except ValueError:
            return None
        return -x if neg else x
    return None


def kind(v):
    if v is None:
        return "blank"
    if isinstance(v, str):
        s = v.strip()
        if s.lower() in NA:
            return "na" if s else "blank"
        if COLNUM_RE.fullmatch(s):
            return "colnum"
        return "num" if to_num(s) is not None else "text"
    return "num" if to_num(v) is not None else "blank"


def clean(v):
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return re.sub(r"\s+", " ", str(v)).strip()


def norm_period(text):
    """'2023-24' / '2023-2024' / 'FY 2023/24' -> ('2023-24', valid?)  ; None if no period."""
    m = PERIOD_RE.search(text or "")
    if not m:
        return None, True
    a, b = m.group(1), m.group(2)
    b2 = b[-2:]
    return f"{a}-{b2}", ((int(a) + 1) % 100 == int(b2))


def detect_unit(text, allow_pct=False):
    t = (text or "").lower()
    if allow_pct and PCT_RE.search(t):
        return "%"
    for pat, u in UNIT_PATTERNS:
        if re.search(pat, t):
            return u
    return None


def sheet_grid(ws, max_rows=6000, max_cols=80):
    nr, nc = min(ws.max_row or 0, max_rows), min(ws.max_column or 0, max_cols)
    raw = [[None] * (nc + 1) for _ in range(nr + 1)]
    for r, row in enumerate(ws.iter_rows(min_row=1, max_row=nr, max_col=nc), 1):
        for c, cell in enumerate(row, 1):
            raw[r][c] = cell.value
    filled = [row[:] for row in raw]
    for mr in ws.merged_cells.ranges:                     # expand merged headers
        if mr.min_row > nr or mr.min_col > nc:
            continue
        v = raw[mr.min_row][mr.min_col]
        for r in range(mr.min_row, min(mr.max_row, nr) + 1):
            for c in range(mr.min_col, min(mr.max_col, nc) + 1):
                filled[r][c] = v
    return raw, filled, nr, nc


def row_type(raw_row):
    ks = [(c, kind(v)) for c, v in enumerate(raw_row) if c > 0 and v is not None]
    nums = [c for c, k in ks if k == "num"]
    texts = [c for c, k in ks if k == "text"]
    colnum = [c for c, k in ks if k == "colnum"]
    if not nums and not texts and not colnum:
        return "blank"
    if colnum and len(colnum) >= 2 and not nums:
        return "colnum"
    if len(nums) >= 2:
        vals = [to_num(raw_row[c]) for c in nums]
        if all(float(x).is_integer() and 1990 <= x <= 2100 for x in vals) and len(texts) <= 1:
            return "yearrow"
        ints = [int(x) for x in vals if float(x).is_integer()]
        if len(ints) == len(vals) and ints == list(range(ints[0], ints[0] + len(ints))) and ints[0] in (0, 1) and len(texts) == 0:
            return "colnum"                                # 1 2 3 4 ... column index row
    if nums:
        return "data"
    if len(texts) == 1:
        return "single"
    return "header"


def find_blocks(rt, n):
    blocks, r = [], 1
    while r <= n:
        if rt[r] != "data":
            r += 1
            continue
        start = end = r
        j, blanks = r + 1, 0
        while j <= n:
            t = rt[j]
            if t == "data":
                end, blanks = j, 0
            elif t == "single":
                k = j + 1
                while k <= n and rt[k] == "blank":
                    k += 1
                if not (k <= n and rt[k] == "data"):
                    break
            elif t == "blank":
                blanks += 1
                if blanks > 1:
                    break
            elif t == "colnum":
                pass
            else:
                break
            j += 1
        blocks.append((start, end))
        r = end + 1
    return blocks


def parse_block(raw, filled, rt, start, end, prev_title, sheet, nc):
    # ---- header rows above the block --------------------------------------------------------
    k, pre_singles = start - 1, []
    while k >= 1 and rt[k] == "single":
        pre_singles.insert(0, k); k -= 1
    hdr, skipped_blank = [], False
    while k >= 1 and len(hdr) < 5:
        t = rt[k]
        if t in ("header", "yearrow"):
            hdr.insert(0, k)
        elif t == "colnum":
            pass
        elif t == "blank" and not hdr and not skipped_blank:
            skipped_blank = True
        else:
            break
        k -= 1
    # ---- title rows above the header ---------------------------------------------------------
    titles, t_end = [], (hdr[0] - 1 if hdr else start - 1)
    if not hdr:
        titles = [raw_text(raw, r) for r in pre_singles]
        t_end = (pre_singles[0] - 1) if pre_singles else start - 1
        pre_singles = []
    r, blanks = t_end, 0
    while r >= 1 and len(titles) < 4 and rt[r] in ("single", "blank", "header"):
        if rt[r] == "blank":
            blanks += 1
            if blanks > 2: break
        elif rt[r] == "single":
            s = raw_text(raw, r)
            if not NOTE_RE.match(s): titles.insert(0, s)
        else:
            break
        r -= 1
    title = " ".join(titles).strip() or prev_title or sheet
    body_start = pre_singles[0] if pre_singles else start
    body = list(range(body_start, end + 1))
    data_rows = [r for r in body if rt[r] == "data"]
    if len(data_rows) < 2:
        return None
    # ---- columns -----------------------------------------------------------------------------
    numcols = sorted({c for r in data_rows for c in range(1, nc + 1) if kind(raw[r][c]) == "num"})
    if not numcols:
        return None
    first_num = numcols[0]
    label_col, best = None, 0.0
    for c in range(1, first_num + 1):
        share = sum(kind(raw[r][c]) == "text" for r in data_rows) / len(data_rows)
        if share >= 0.5 and (label_col is None or share > best + 0.2):
            label_col, best = c, share
    serial = set()
    for c in numcols:                                      # serial-number column: 1,2,3...
        vs = [to_num(raw[r][c]) for r in data_rows if kind(raw[r][c]) == "num"]
        if len(vs) >= 3 and all(float(x).is_integer() for x in vs):
            inc = sum(1 for a, b in zip(vs, vs[1:]) if b - a == 1)
            if inc / (len(vs) - 1) >= 0.7 and vs[0] in (0, 1) and (label_col is None or c < label_col):
                serial.add(c)
    numcols = [c for c in numcols if c not in serial and c != label_col]
    labels = {}
    for c in numcols:
        parts = []
        for r in hdr:
            if filled[r][c] is not None and str(filled[r][c]).strip():
                s = clean(filled[r][c])
                if not parts or parts[-1] != s:
                    parts.append(s)
        labels[c] = " | ".join(parts) if parts else f"Col {L(c)}"
    title_period, _ = norm_period(title)
    table_unit = detect_unit(title)
    facts, section, last_label = [], None, None
    for r in body:
        if rt[r] == "single":
            section = raw_text(raw, r)
            continue
        if rt[r] != "data":
            continue
        entity = clean(raw[r][label_col]) if label_col and raw[r][label_col] is not None else None
        if entity and kind(raw[r][label_col]) != "text":
            entity = None
        if entity:
            last_label = entity
        entity = entity or (f"{last_label} (cont.)" if last_label else f"Row {r}")
        cells = [c for c in numcols if kind(raw[r][c]) == "num"]
        if not cells:
            continue
        rng = f"{L(min(cells))}{r}:{L(max(cells))}{r}"
        for c in cells:
            lab = labels[c]
            per, valid = norm_period(lab)
            if per:
                qual = clean(PERIOD_RE.sub("", lab).replace("|", " ").strip(" -|()"))
            elif re.fullmatch(r"(?:19|20)\d{2}", lab):
                per, qual = f"CY{lab}", ""
            else:
                per, qual = title_period, lab
            unit = detect_unit(lab, allow_pct=True) or table_unit
            facts.append(dict(sheet=sheet, cell=f"{L(c)}{r}", row_ref=rng, row_no=r, section=section,
                              entity=entity, column_label=lab, qualifier=qual, period=per,
                              value=to_num(raw[r][c]), unit=unit, raw_text=str(raw[r][c]),
                              is_total=int(bool(TOTAL_RE.search(entity))),
                              confidence="high" if (unit and per) else ("medium" if (unit or per) else "low")))
    if not facts:
        return None
    return dict(sheet=sheet, title=title, unit=table_unit, first_cell=f"{L(min(numcols))}{data_rows[0]}",
                last_cell=f"{L(max(numcols))}{data_rows[-1]}", n_rows=len(data_rows), facts=facts)


def raw_text(raw, r):
    return " ".join(clean(v) for v in raw[r] if v is not None and str(v).strip())


def parse_workbook(path):
    """Returns (tables, text_snippets). text_snippets feed the topic module."""
    wb = load_workbook(path, data_only=True)
    tables, snippets = [], []
    for ws in wb.worksheets:
        raw, filled, nr, nc = sheet_grid(ws)
        if nr == 0:
            continue
        rt = [None] + [row_type(raw[r]) for r in range(1, nr + 1)]
        prev_title = None
        for (s, e) in find_blocks(rt, nr):
            t = parse_block(raw, filled, rt, s, e, prev_title, ws.title, nc)
            if t:
                tables.append(t)
                prev_title = t["title"]
                snippets.append((ws.title, t["title"]))
    return tables, snippets


def legacy_to_xlsx(path, tmp_path):
    """.xls / .csv -> temporary .xlsx (needs xlrd for .xls)."""
    import pandas as pd
    if str(path).lower().endswith(".csv"):
        sheets = {"Sheet1": pd.read_csv(path, header=None)}
    else:
        sheets = pd.read_excel(path, sheet_name=None, header=None)
    wb = Workbook(); wb.remove(wb.active)
    for name, df in sheets.items():
        ws = wb.create_sheet(str(name)[:31])
        for row in df.itertuples(index=False):
            ws.append([None if (isinstance(x, float) and math.isnan(x)) else x for x in row])
    wb.save(tmp_path)
    return tmp_path
