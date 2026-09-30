from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RAW = DATA / "raw"              # put Coal Directory .xlsx / .pdf files here
SYN = DATA / "synthetic"
CACHE = DATA / "llm_cache"
OUT = ROOT / "output"
for _p in (RAW, SYN, CACHE, OUT):
    _p.mkdir(parents=True, exist_ok=True)

# words that carry no topic signal in coal reporting (blueprint section 6.9)
DOMAIN_STOP = {
    "coal", "mine", "mines", "colliery", "seam", "tonnes", "tonne", "limited", "ltd",
    "subsidiary", "table", "chapter", "directory", "india", "indian", "source", "note",
    "million", "lakh", "thousand", "sl", "no", "total", "year", "years", "fy", "page",
}
