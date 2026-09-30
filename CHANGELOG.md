# CoalMind — Changelog

## v0.2.0 — Architecture upgrade (current)

### New files
| File | What it adds |
|------|-------------|
| `coalmind/thesaurus.py` | Indian Coalfield Lithological Thesaurus (dh2loop-inspired). Normalises 60+ field abbreviations → canonical terms. GCV→grade classifier (G1–G17). GeoSciML record builders. UNFC class reference. |
| `coalmind/graph.py` | Lightweight GraphRAG: SQLite property-graph (Tier 5). `build_from_db()` auto-populates edges. `multi_hop()` traverses Subsidiary→Block→Borehole→Seam for multi-entity queries. Ready to swap for Neo4j Cypher with identical API. |

### Modified files
| File | Changes |
|------|---------|
| `coalmind/db.py` | +6 GeoSciML-aligned tables: `boreholes`, `strata`, `seams`, `projects`, `graph_edges` (indexed). |
| `coalmind/validate.py` | +6 geological validation rules: `BOREHOLE_DEPTH_SUM`, `CORE_RECOVERY_OVER`, `DEPTH_ORDER`, `GCV_GRADE_MISMATCH`, `RESERVE_SUM`, `STRIPPING_RATIO`. Total: 14 rules. |
| `coalmind/synth.py` | `seed_geological_demo()` seeds 3 boreholes × 18 strata × 5 seams × 5 projects with 5 planted geological errors. |
| `app.py` | +2 sidebar tabs: **🌐 Graph Explorer** (thesaurus tester, GCV classifier, multi-hop query, edge table) and **🏛️ Architecture** (global vs CoalMind comparison, 7-tier breakdown, UNFC/grade tables). Validate button shows geological flag count separately. |

### New validation rules (Tier 4)
| Rule | Checks |
|------|--------|
| `BOREHOLE_DEPTH_SUM` | Σ interval thicknesses = total drilled depth (±1 cm) |
| `CORE_RECOVERY_OVER` | Core recovery % ≤ 100 |
| `DEPTH_ORDER` | depth_to > depth_from for every strata interval |
| `GCV_GRADE_MISMATCH` | Recorded grade label matches MoC GCV band |
| `RESERVE_SUM` | Seam-level reserves balance to block total |
| `STRIPPING_RATIO` | SR in [0.5, 25] for OC; flags SR on UG projects |

## v0.1.0 — Initial prototype

- Layout-tolerant Excel parser (merged headers, section rows, serial-number columns)  
- Statistical validation (SUM_MISMATCH, NEGATIVE_QTY, PERIOD_INVALID, YOY_JUMP, UNIT_OR_DECIMAL_SHIFT, CROSS_DOC_MISMATCH)  
- Hybrid query engine (text-to-SQL + keyword RAG)  
- PQ Copilot (parse → fetch → draft → approve → audit)  
- Word report generator (python-docx with source footnotes)  
- Topic/word-cloud module (TF-IDF+NMF or BERTopic)  
- KPI evaluator on synthetic gold set  
- Free LLM adapter: Groq / Gemini / Ollama / none  
