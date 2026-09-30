# ⛏️ CoalMind — Smart India Hackathon Prototype

> Verified AI for Geological, Mining and Production Reporting  
> CMPDI / Coal India problem statement · Built for a 24-hour hackathon

---

## What it does

| Module | Feature |
|--------|---------|
| **Ingest** | Upload Coal Directory Excel chapters (any year) or scanned/digital PDFs → every number stored with sheet + cell provenance |
| **Validate** | 6 deterministic rules: sum checks, grade vs GCV, invalid periods, negative quantities, year-on-year anomaly detection, cross-document mismatch |
| **Query** | Hybrid: numeric questions → text-to-SQL on Fact Store (shows the SQL); narrative → keyword search on text chunks |
| **PQ Copilot** | Paste a Parliamentary Question → facts fetched → formal draft reply + annexure → officer edits & approves → audit log written |
| **Report** | One-click Word `.docx` with production tables, validation flags, source footnotes, and audit trail |
| **Topics** | Word cloud + topic discovery from ingested text (BERTopic or TF-IDF+NMF fallback) |
| **KPI Dashboard** | Measured accuracy % and validation catch rate on the synthetic gold set |

---

## Project layout

```
coalmind_proj/
├── app.py                   ← Streamlit app (entry point)
├── requirements.txt
├── coalmind/
│   ├── config.py            ← paths, stop-words
│   ├── db.py                ← SQLite schema + helpers
│   ├── llm.py               ← free-LLM adapter (Groq / Gemini / Ollama / none)
│   ├── excel_parser.py      ← layout-tolerant xlsx → Fact rows
│   ├── pdf_parser.py        ← PDF text chunks + OCR fallback (PyMuPDF)
│   ├── ingest.py            ← orchestrates parse → DB insert
│   ├── validate.py          ← 6 deterministic validation rules
│   ├── query.py             ← route → SQL or keyword search
│   ├── pq_copilot.py        ← PQ parsing, draft, approve workflow
│   ├── report_gen.py        ← python-docx report builder
│   ├── topics.py            ← word cloud + topic model
│   ├── synth.py             ← synthetic demo workbook with planted errors
│   └── evaluate.py          ← KPI measurement against gold set
├── data/
│   ├── raw/                 ← put real Coal Directory files here
│   ├── synthetic/           ← auto-generated demo data
│   └── llm_cache/           ← cached LLM responses (demo runs offline)
└── output/                  ← generated reports
```

---

## Quick start (5 minutes)

### 1. Install Python dependencies

```bash
pip install pandas openpyxl python-docx scikit-learn requests streamlit matplotlib
# Recommended extras:
pip install pymupdf          # PDF text extraction
pip install wordcloud        # word cloud visuals
# For BERTopic (optional, falls back to TF-IDF+NMF):
pip install bertopic sentence-transformers
```

> Python **3.10+** required.

### 2. Choose a free LLM (optional but recommended)

The app works fully without an LLM — all validation, ingestion, and reporting are deterministic. The LLM enhances query narration, PQ drafting, and SQL generation.

#### Option A — Groq (free API, fastest)
1. Sign up at https://console.groq.com → create a free API key
2. `export GROQ_API_KEY=gsk_...`

#### Option B — Google Gemini (free API)
1. Get a key at https://aistudio.google.com/app/apikey
2. `export GEMINI_API_KEY=AIza...`

#### Option C — Ollama (fully local / air-gapped)
```bash
# Install ollama: https://ollama.com
ollama pull qwen2.5:7b      # ~4 GB; use llama3.2:3b on low-RAM machines
# ollama runs automatically on http://localhost:11434
```

#### No LLM at all
```bash
export COALMIND_LLM=none    # deterministic fallback for everything
```

The app detects the provider automatically in this order: Groq → Gemini → Ollama → none.

### 3. Run the Streamlit app

```bash
cd coalmind_proj
streamlit run app.py
```

Opens at **http://localhost:8501**

---

## Using real Coal Directory data

The Ministry of Coal publishes the Coal Directory of India (Coal Statistics section at coalcontroller.gov.in). You can see the file listing in the screenshots in this repo — Chapters 1–11 are Excel files.

1. Download any chapters (e.g. `cdchap3.xlsx`) from the Ministry of Coal website
2. Place the `.xlsx` files in `data/raw/` **or** drag-and-drop them in the app's **Ingest & Validate** tab
3. Click **⚡ Ingest uploaded files**
4. Click **🛡 Validate all facts**
5. Run a query or generate a report

The parser handles:
- Multi-level merged headers
- Section headings between data rows
- `(1) (2) (3)` column index rows
- Serial-number columns
- Mixed `MT` / `lakh t` / `'000 t` units in the same workbook
- Fiscal years like `2023-24` or `2023/24`

---

## Demo flow (for the hackathon presentation)

1. **Ingest tab** → click *"Generate & ingest synthetic Coal Directory"* (no file download needed)
2. **Validate** → click *"Validate all facts"* → show 4 flags: 2 anomalies, 1 invalid period, 1 negative value
3. **Fact viewer** → filter by `flagged` → show the detail of each flag
4. **Query tab** → ask *"What was All India coal production in 2023-24?"* → show the SQL and the answer
5. **PQ Copilot** → paste *"What is the subsidiary-wise coal production for the last 3 years?"* → show draft → approve
6. **Reports** → click *"Generate Word Report"* → download and open the `.docx`
7. **KPI Dashboard** → click *"Run KPI Evaluation"* → show measured numbers

---

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `COALMIND_LLM` | `auto` | `groq` / `gemini` / `ollama` / `none` / `auto` |
| `COALMIND_MODEL` | provider default | Override the model name |
| `COALMIND_DB` | `data/coalmind.db` | SQLite database path |
| `GROQ_API_KEY` | — | Groq free-tier API key |
| `GEMINI_API_KEY` | — | Google AI Studio API key |
| `OLLAMA_URL` | `http://localhost:11434` | Ollama endpoint |

---

## Architecture (blueprint section 5)

```
INPUTS  →  INGEST  →  PARSE  →  EXTRACT  →  VALIDATE  →  FACT STORE
  xlsx/pdf    hash    openpyxl   LLM (opt.)   6 rules      SQLite + text chunks
              type    pdfplumber  + heuristic  deterministic  with cell provenance
              class.  PaddleOCR              + anomaly check
                      (optional)
                           ↓                      ↓
                     MODULE 1          MODULE 3          MODULE 2
                  Report generator   Query + PQ        Topics + word cloud
                    python-docx      text-to-SQL +     TF-IDF/NMF or BERTopic
                                     keyword RAG
                           ↓                      ↓
                     HITL CONSOLE + OUTPUTS: docx · audit log · approved PQ drafts
```

**Key design principle:** The LLM reads documents and phrases answers. It **never invents numbers**. Every value is traced to its source (file → sheet → cell).

---

## Validation rules

| Rule | What it checks |
|------|---------------|
| `SUM_MISMATCH` | Subtotals / All India row ≠ sum of components (±0.5% tolerance) |
| `NEGATIVE_QTY` | Negative value in a quantity column (production, reserves, etc.) |
| `PERIOD_INVALID` | Column header has an invalid fiscal year (e.g. `2023-25`) |
| `UNIT_MISSING` | No unit detected for a table |
| `PERIOD_MISSING` | No period detected for a table |
| `UNIT_OR_DECIMAL_SHIFT` | YoY ratio is ~×10 or ~×100 (decimal or unit slip) |
| `YOY_JUMP` | Year-on-year change > 3× (anomaly flag) |
| `CROSS_DOC_MISMATCH` | Same entity/period/metric differs between two documents |

---

## Extending to real CMPDI documents

- **Borehole logs / geological reports:** extend `coalmind/db.py` (add `boreholes`, `strata`, `seams` tables from blueprint section 6.4) and write a `parse_borehole()` extractor in `excel_parser.py`
- **Scanned PDFs:** install `pytesseract` + Tesseract binary + `Pillow`; `pdf_parser.py` falls back automatically
- **Hindi text:** install `paddleocr` with Hindi models; update `pdf_parser.py`
- **On-prem LLM:** `export COALMIND_LLM=ollama COALMIND_MODEL=llama3.1:8b` (or any GGUF via Ollama)
- **PostgreSQL:** change `db.connect()` in `db.py` to use `psycopg2`; schema is standard SQL

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `ModuleNotFoundError: streamlit` | `pip install streamlit` |
| `ModuleNotFoundError: fitz` | `pip install pymupdf` |
| LLM rate-limit errors | Use `export COALMIND_LLM=none` for the demo; responses are cached after first call |
| Excel file not parsed | Ensure it is `.xlsx` not `.xls`; if `.xls`, install `xlrd` and rename |
| Word cloud not showing | `pip install wordcloud matplotlib` |
| Port already in use | `streamlit run app.py --server.port 8502` |

---

*Built for the Smart India Hackathon · CMPDI / CIL problem statement · All synthetic data labelled as synthetic*
