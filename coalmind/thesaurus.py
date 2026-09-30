"""Indian Coalfield Lithological Thesaurus (dh2loop-inspired, blueprint Tier 2).

Normalises historical logging shorthand into standard terms BEFORE data reaches
the retrieval engine — so we don't need complex LLM prompts to decode field
abbreviations.  Token-level fuzzy matching (no heavy dependencies).

Usage
-----
    from coalmind.thesaurus import normalise, classify_seam_grade

    normalise("Carb. Sh")           # -> "Carbonaceous Shale"
    normalise("Sh-Sst inter.")      # -> "Shale-Sandstone Interlamination"
    classify_seam_grade(4750)       # -> "G9"
"""
import re
from difflib import get_close_matches

# ── lithology master dictionary ────────────────────────────────────────────────
# Keys are canonical forms; values are lists of known abbreviations / variants
# Sourced from GSI Borehole Log conventions and CMPDI field practice
LITHO_DICT: dict[str, list[str]] = {
    "Carbonaceous Shale":     ["carb. sh", "carb sh", "carb.sh", "c.sh", "carbonaceous sh",
                               "carb shale", "c. shale", "carbonaceous shale"],
    "Shale":                  ["sh", "shl", "shale", "argillite"],
    "Sandstone":              ["sst", "ss", "s.st", "sstone", "sandstone", "fine sst",
                               "medium sst", "coarse sst", "f.sst", "m.sst", "c.sst"],
    "Shale-Sandstone Interlamination": ["sh-sst", "sh/sst", "sh-ss", "sst-sh",
                                        "sh-sst inter", "sh-sst interlamination",
                                        "shale-sandstone", "shale sandstone interbed",
                                        "shale sandstone interlamination"],
    "Coal":                   ["coal", "cl", "c", "coal seam"],
    "Carbonaceous Coal":      ["carb. coal", "carb coal", "c.coal"],
    "Fire Clay":              ["fc", "f.c.", "fire clay", "fireclay", "underclay"],
    "Limestone":              ["ls", "lst", "l.st", "limestone"],
    "Siltstone":              ["sltst", "slst", "siltstone", "silty sst", "silty shale"],
    "Conglomerate":           ["cong", "congl", "conglomerate"],
    "Igneous Intrusion":      ["ign.", "trap", "dolerite", "basalt", "igneous", "intrusion",
                               "dyke", "sill"],
    "Fault Gouge / Breccia":  ["gouge", "breccia", "flt", "fault zone"],
    "Overburden":             ["ob", "o.b.", "overburden", "soil", "alluvium"],
    "Drift":                  ["drift", "dft", "gravel", "sand", "clay", "laterite"],
    "Parting":                ["parting", "dirt band", "dirt", "band"],
}

# Flat reverse index: abbreviated form -> canonical
_REV: dict[str, str] = {}
for _canon, _abbrs in LITHO_DICT.items():
    for _a in _abbrs:
        _REV[_a.lower().strip()] = _canon

# Pre-built list of all abbreviated keys for fuzzy fallback
_KEYS = list(_REV.keys())


def _tok_match(token: str) -> str | None:
    """Try exact then fuzzy match for a single token."""
    t = token.lower().strip(" .")
    if t in _REV:
        return _REV[t]
    # allow abbreviation prefix: "carb" -> "carb. sh" ≈ "carbonaceous shale"
    hits = [k for k in _REV if k.startswith(t) and len(t) >= 3]
    if len(hits) == 1:
        return _REV[hits[0]]
    close = get_close_matches(t, _KEYS, n=1, cutoff=0.82)
    return _REV[close[0]] if close else None


def normalise(raw: str) -> str:
    """Return canonical lithology name, or the original string cleaned up.

    Matching priority (stops at first hit):
    1. Exact match of the whole string in _REV
    2. Exact match after stripping trailing punctuation / spaces
    3. Fuzzy whole-phrase match against _KEYS (cutoff 0.80)
    4. Single-token lookup
    5. Majority-token heuristic (each token normalised independently)
    """
    if not isinstance(raw, str) or not raw.strip():
        return raw
    cleaned = re.sub(r"\s+", " ", raw.strip())
    lo = cleaned.lower().rstrip(". ")

    # 1 & 2 — exact or stripped exact
    if lo in _REV:
        return _REV[lo]
    stripped = lo.strip("()[].")
    if stripped in _REV:
        return _REV[stripped]

    # 3 — fuzzy whole-phrase (handles "sh-sst inter." → "sh-sst interlamination")
    #     normalise punctuation before fuzzy comparison
    lo_norm = re.sub(r"[.\-/\s]+", " ", lo).strip()
    keys_norm = {re.sub(r"[.\-/\s]+", " ", k).strip(): k for k in _KEYS}
    if lo_norm in keys_norm:
        return _REV[keys_norm[lo_norm]]
    close = get_close_matches(lo_norm, list(keys_norm.keys()), n=1, cutoff=0.80)
    if close:
        return _REV[keys_norm[close[0]]]

    # 4 — single token
    tokens = re.split(r"[\s\-/,]+", cleaned)
    if len(tokens) == 1:
        return _tok_match(tokens[0]) or cleaned

    # 5 — majority-token: only apply if the RECONSTRUCTED phrase is meaningfully
    #     shorter than (i.e. actually maps) original — avoids "Shale Sandstone Interlamination…" explosions
    mapped = []
    for tok in tokens:
        hit = _tok_match(tok)
        # Only add the canonical if it's a SINGLE canonical word, not a multi-word phrase
        # (prevents "Sh" → "Shale" and "Sst" → "Sandstone" both appended before "Sh-Sst" phrase)
        if hit and " " not in hit:
            mapped.append(hit)
        else:
            mapped.append(tok)
    changed = sum(1 for m, t in zip(mapped, tokens) if m.lower() != t.lower())
    if changed >= max(1, len(tokens) // 2):
        return " ".join(dict.fromkeys(mapped))  # deduplicate while preserving order
    return cleaned


# ── GCV → statutory grade bands (MoC notification, non-coking coal) ────────────
# G1 = highest grade; G17 = lowest.  Verify against latest MoC notification before use.
_GRADES: list[tuple[str, float, float]] = [
    ("G1",  7001, 99999), ("G2",  6701, 7000), ("G3",  6401, 6700),
    ("G4",  6101, 6400),  ("G5",  5801, 6100), ("G6",  5501, 5800),
    ("G7",  5201, 5500),  ("G8",  4901, 5200), ("G9",  4601, 4900),
    ("G10", 4301, 4600),  ("G11", 4001, 4300), ("G12", 3701, 4000),
    ("G13", 3401, 3700),  ("G14", 3101, 3400), ("G15", 2801, 3100),
    ("G16", 2501, 2800),  ("G17", 2201, 2500),
]

def classify_seam_grade(gcv_kcal_per_kg: float) -> str:
    """Return MoC grade label (G1–G17) or 'Ungraded' for non-coking coal."""
    for grade, lo, hi in _GRADES:
        if lo <= gcv_kcal_per_kg <= hi:
            return grade
    return "Ungraded"


def grade_range(grade: str) -> tuple[float, float] | None:
    """Return (lo, hi) kcal/kg for a grade label, or None if unknown."""
    for g, lo, hi in _GRADES:
        if g.upper() == grade.upper():
            return lo, hi
    return None


# ── UNFC reserve confidence classes (Indian exploration guidelines) ─────────────
# Borehole spacing (m) that qualifies each confidence class — indicative only
UNFC_SPACING: dict[str, str] = {
    "Proved":    "< 400 m borehole spacing (or geological continuity confirmed)",
    "Indicated": "400–800 m borehole spacing",
    "Inferred":  "> 800 m borehole spacing",
}

UNFC_STAGE_CODES: dict[str, str] = {
    # (F,G,E) = (Feasibility, Geology, Economics)
    "111": "Proved, Measured, Economically Viable",
    "121": "Indicated, Measured, Potentially Economically Viable",
    "221": "Inferred, Measured, Potentially Economically Viable",
    "334": "Hypothetical, Not Evaluated, Not Viable",
}


# ── GeoSciML-aligned schema helpers ────────────────────────────────────────────
def borehole_interval_record(depth_from, depth_to, raw_litho, core_recovery_pct=None):
    """Return a dict conforming to OGC GeoSciML BoreholeInterval."""
    return {
        "depth_from": depth_from,
        "depth_to": depth_to,
        "interval_thickness": round(float(depth_to) - float(depth_from), 3),
        "lithology_raw": raw_litho,
        "lithology_code": normalise(raw_litho),
        "core_recovery_pct": core_recovery_pct,
    }


def coal_quality_record(seam, moisture, ash, volatile_matter, fixed_carbon, gcv):
    """Return a dict conforming to GeoSciML CoalQuality."""
    return {
        "seam": seam,
        "moisture_pct": moisture,
        "ash_pct": ash,
        "volatile_matter_pct": volatile_matter,
        "fixed_carbon_pct": fixed_carbon,
        "gcv_kcal_per_kg": gcv,
        "statutory_grade": classify_seam_grade(gcv) if gcv else None,
    }
