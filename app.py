"""CoalMind Streamlit app — Smart India Hackathon prototype.
Run: streamlit run app.py
"""
import io, json, os, sys, time
from pathlib import Path

# ── must be first Streamlit call ──────────────────────────────────────────────
import streamlit as st

st.set_page_config(page_title="CoalMind – SIH Prototype", page_icon="⛏️", layout="wide")

# ── allow running from the project root without installation ──────────────────
sys.path.insert(0, str(Path(__file__).parent))

from coalmind import db, ingest, validate, report_gen, topics, pq_copilot, query, evaluate, llm, synth, graph
from coalmind.thesaurus import normalise, classify_seam_grade, LITHO_DICT, UNFC_SPACING
from coalmind.config import RAW, OUT

# ── sidebar ───────────────────────────────────────────────────────────────────
st.sidebar.image("https://upload.wikimedia.org/wikipedia/commons/thumb/4/41/Flag_of_India.svg/120px-Flag_of_India.svg.png",
                 width=40)
st.sidebar.title("⛏️ CoalMind")
st.sidebar.caption("Verified AI · Smart India Hackathon")
st.sidebar.divider()

tab_names = ["📥 Ingest & Validate", "🔍 Query", "📜 PQ Copilot",
             "📊 Reports", "☁️ Topics", "📈 KPI Dashboard",
             "🌐 Graph Explorer", "🏛️ Architecture"]
tab = st.sidebar.radio("Navigation", tab_names)

st.sidebar.divider()
with st.sidebar.expander("🤖 LLM Settings"):
    st.caption(f"Provider: **{llm.status()}**")
    st.caption("Set env var:\n`GROQ_API_KEY` (groq)\n`GEMINI_API_KEY` (gemini)\nor run `ollama pull qwen2.5:7b`")
    if llm.last_error:
        st.warning(f"Last error: {llm.last_error}")

with st.sidebar.expander("🗄️ DB"):
    st.caption(str(db.get_path()))
    if st.button("🗑 Reset DB"):
        db.reset()
        st.success("DB reset."); st.rerun()

# ── helpers ──────────────────────────────────────────────────────────────────
def _status_badge(s):
    colors = {"pending":"#888","verified":"#2e7d32","flagged":"#d84315"}
    return f"<span style='background:{colors.get(s,'#888')};color:white;padding:1px 6px;border-radius:4px;font-size:11px'>{s}</span>"

def _sev_badge(s):
    c = {"error":"#c00","warn":"#e65c00","info":"#1565c0"}.get(s,"#555")
    return f"<span style='background:{c};color:white;padding:1px 6px;border-radius:4px;font-size:11px'>{s}</span>"

# ══════════════════════════════════════════════════════════════════════════════
# TAB 1: INGEST & VALIDATE
# ══════════════════════════════════════════════════════════════════════════════
if tab == tab_names[0]:
    st.title("📥 Ingest & Validate")

    col1, col2 = st.columns([3,2])
    with col1:
        st.subheader("Upload files")
        uploaded = st.file_uploader("Coal Directory chapters (.xlsx, .xls, .csv) or PDF reports",
                                    accept_multiple_files=True,
                                    type=["xlsx","xls","csv","pdf","xlsm"])
        if uploaded and st.button("⚡ Ingest uploaded files", type="primary"):
            prog = st.progress(0)
            logs = []
            for i, f in enumerate(uploaded):
                tmp = RAW / f.name
                tmp.write_bytes(f.read())
                def _log(m, logs=logs): logs.append(m)
                ingest.ingest_file(tmp, log=_log)
                prog.progress((i+1)/len(uploaded))
            with st.expander("Ingest log", expanded=True):
                st.code("\n".join(logs))
            st.rerun()

        st.subheader("Or load demo data (synthetic)")
        if st.button("🔬 Generate & ingest synthetic Coal Directory"):
            p, _ = synth.build()
            logs = []
            ingest.ingest_file(p, log=lambda m: logs.append(m))
            n_bh = synth.seed_geological_demo()
            logs.append(f"+ Seeded {n_bh} synthetic boreholes with strata/seams/projects (Tier 2-4 demo)")
            n_edges = graph.build_from_db(log=lambda m: logs.append(m))
            logs.append(f"+ Graph built: {n_edges} edges (Tier 5 demo)")
            st.code("\n".join(logs))
            st.rerun()

    with col2:
        import pandas as pd
        con = db.connect()
        docs = pd.read_sql("SELECT id, filename, doc_type, kind, uploaded_at FROM documents", con)
        st.metric("Documents", len(docs))
        st.metric("Tables", con.execute("SELECT COUNT(*) FROM src_tables").fetchone()[0])
        st.metric("Facts", con.execute("SELECT COUNT(*) FROM facts").fetchone()[0])
        st.metric("Flagged facts", con.execute("SELECT COUNT(*) FROM facts WHERE status='flagged'").fetchone()[0])
        con.close()
        if not docs.empty:
            st.dataframe(docs[["filename","doc_type","kind","uploaded_at"]], use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("▶ Run Validation Engine")
    if st.button("🛡 Validate all facts"):
        with st.spinner("Running statistical + geological validation rules…"):
            logs = []
            summ = validate.run_all(log=lambda m: logs.append(m))
        st.code("\n".join(logs))
        geo = summ.get("flags_by_code", {})
        geo_count = sum(v for k, v in geo.items()
                        if k in {"BOREHOLE_DEPTH_SUM","CORE_RECOVERY_OVER","DEPTH_ORDER",
                                  "GCV_GRADE_MISMATCH","MOISTURE_RANGE","RESERVE_SUM",
                                  "STRIPPING_RATIO","UNFC_BALANCE"})
        st.success(f"Done — {summ.get('flagged',0)} statistical facts flagged · "
                   f"{geo_count} geological rule violations")
        st.json(summ.get("flags_by_code",{}))
        st.rerun()

    st.divider()
    st.subheader("📋 Fact viewer")
    import pandas as pd
    con = db.connect()
    fdf = pd.read_sql("SELECT * FROM v_facts ORDER BY flag_count DESC, fact_id LIMIT 500", con)
    flags_df = pd.read_sql("SELECT fact_id, code, severity, detail FROM flags WHERE resolved=0", con)
    con.close()
    if fdf.empty:
        st.info("No facts yet — upload files and click Ingest.")
    else:
        fil_status = st.selectbox("Filter by status", ["all","pending","verified","flagged"])
        if fil_status != "all":
            fdf = fdf[fdf.status == fil_status]
        search = st.text_input("Search entity/table", "")
        if search:
            mask = fdf.apply(lambda r: search.lower() in str(r.get("entity","")).lower()
                                        or search.lower() in str(r.get("table_title","")).lower(), axis=1)
            fdf = fdf[mask]
        st.dataframe(fdf, use_container_width=True, height=350, hide_index=True)

        if not flags_df.empty:
            st.subheader("🚩 Validation flags")
            for _, fl in flags_df.iterrows():
                col_a, col_b = st.columns([1, 8])
                col_a.markdown(_sev_badge(fl.severity), unsafe_allow_html=True)
                col_b.markdown(f"**{fl.code}** — {fl.detail}")
                frow = fdf[fdf.fact_id == fl.fact_id]
                if not frow.empty:
                    r = frow.iloc[0]
                    col_b.caption(f"📄 {r.get('filename','')} | Sheet: {r.get('sheet','')} | Cell: {fdf[fdf.fact_id==fl.fact_id]['fact_id'].iloc[0]}")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 2: QUERY
# ══════════════════════════════════════════════════════════════════════════════
elif tab == tab_names[1]:
    st.title("🔍 Hybrid Query Engine")
    st.caption("Numeric questions → text-to-SQL on Fact Store | Narrative → keyword search on text chunks")

    presets = [
        "What was All India coal production in 2023-24?",
        "Show production by subsidiary for all years",
        "Which company had highest coal production?",
        "Total All India despatch by sector",
        "Flag any anomalies or negative production values",
    ]
    q_preset = st.selectbox("Try a preset question", ["(type your own)"] + presets)
    q_input = st.text_area("Your question", value="" if q_preset == "(type your own)" else q_preset, height=80)

    if st.button("🔎 Ask", type="primary") and q_input.strip():
        with st.spinner("Processing…"):
            res = query.answer(q_input.strip())
        st.markdown(f"**Route:** `{res['route']}`")
        if res.get("sql"):
            with st.expander("SQL (click-to-source / read-only)", expanded=True):
                st.code(res["sql"], language="sql")
                if res.get("fallback_sql"):
                    st.caption("(deterministic fallback SQL — no LLM available)")
        if res.get("error"):
            st.error(f"SQL error: {res['error']}")
        if res.get("rows") is not None:
            import pandas as pd
            df = pd.DataFrame(res["rows"], columns=res["cols"])
            st.dataframe(df, use_container_width=True, hide_index=True)
        if res.get("narrative"):
            st.markdown("### 💬 Answer")
            st.markdown(res["narrative"])
        if res.get("snippets"):
            with st.expander("📄 Relevant text chunks"):
                for s in res["snippets"]:
                    st.markdown(f"**Doc {s['doc_id']} · page {s['loc']}:** {s['snippet']}")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 3: PQ COPILOT
# ══════════════════════════════════════════════════════════════════════════════
elif tab == tab_names[2]:
    st.title("📜 PQ Copilot")
    st.caption("Paste a Parliamentary Question → CoalMind fetches facts, drafts a formal reply → officer reviews and approves")

    pq_examples = [
        "What is the subsidiary-wise coal production in India for the last 3 years?",
        "Please provide state-wise production of coal during 2023-24.",
        "What steps has Coal India taken to increase production and dispatch?",
    ]
    pq_ex = st.selectbox("Example PQ", ["(write your own)"] + pq_examples)
    pq_q = st.text_area("Parliamentary Question text", value="" if pq_ex == "(write your own)" else pq_ex, height=110)

    if st.button("🚀 Generate Draft Reply", type="primary") and pq_q.strip():
        with st.spinner("Parsing question, fetching facts, drafting reply…"):
            result = pq_copilot.draft(pq_q.strip())
        st.session_state["_pq_result"] = result

    if "_pq_result" in st.session_state:
        result = st.session_state["_pq_result"]
        conf_colors = {"high":"🟢","medium":"🟡","low":"🔴"}
        st.markdown(f"**Confidence:** {conf_colors.get(result['confidence'],'⚪')} {result['confidence']}")
        if result.get("parsed"):
            with st.expander("Parsed intent"):
                st.json(result["parsed"])
        if result.get("sqls"):
            with st.expander("SQL used"):
                for s in result["sqls"]:
                    st.code(s, language="sql")
        if result.get("rows"):
            import pandas as pd
            with st.expander(f"Data fetched ({len(result['rows'])} rows)"):
                st.dataframe(pd.DataFrame(result["rows"]), use_container_width=True)

        st.subheader("📄 Draft Reply")
        edited = st.text_area("Edit before approving:", value=result.get("draft",""), height=300)
        col1, col2 = st.columns(2)
        if col1.button("✅ Approve & log to audit trail"):
            pq_copilot.approve(result["id"], edited)
            st.success(f"PQ #{result['id']} approved and logged.")
            del st.session_state["_pq_result"]
            st.rerun()
        if col2.button("🗑 Discard"):
            del st.session_state["_pq_result"]
            st.rerun()

    st.divider()
    st.subheader("Past drafts")
    import pandas as pd
    con = db.connect()
    pqs = pd.read_sql(
        "SELECT id, ts, substr(question, 1, 60) AS question, confidence, status "
        "FROM pq_drafts ORDER BY id DESC LIMIT 20",
        con
    )
    con.close()
    if not pqs.empty:
        st.dataframe(pqs, use_container_width=True, hide_index=True)

# ══════════════════════════════════════════════════════════════════════════════
# TAB 4: REPORTS
# ══════════════════════════════════════════════════════════════════════════════
elif tab == tab_names[3]:
    st.title("📊 AI-Focused Report Generator")

    st.caption(
        "Describe what the report should be about. "
        "Gemini identifies the required scope, CoalMind retrieves only relevant evidence, "
        "and Python generates the final Word report."
    )

    st.info(
        "💡 The report will NOT reproduce all uploaded documents. "
        "Only information relevant to your requested topic will be selected."
    )

    report_examples = [
        "Generate a management report on CIL coal production during 2024-25. "
        "Compare it with 2023-24, include major figures, percentage changes, "
        "important observations and relevant data-quality findings.",

        "Prepare a focused report on CMPDI's exploration and drilling activities "
        "during 2024-25. Include targets, achievements, observations and relevant "
        "data-quality findings.",

        "Prepare a report on coal production and dispatch during 2024-25. "
        "Compare the available figures with 2023-24 and explain the major changes.",

        "Create an executive briefing on the uploaded coal-sector data. "
        "Focus only on production, CIL performance and CMPDI exploration. "
        "Do not include unrelated sections."
    ]

    selected_example = st.selectbox(
        "Example report request",
        ["✍️ Write my own"] + report_examples
    )

    if selected_example == "✍️ Write my own":
        default_request = ""
    else:
        default_request = selected_example

    report_request = st.text_area(
        "What should the report be about?",
        value=default_request,
        height=150,
        placeholder=(
            "Example: Prepare a report on CIL production in 2024-25, "
            "compare it with 2023-24, explain the major changes and include "
            "relevant data-quality findings."
        ),
    )

    st.caption(
        "Tip: Mention the topic, organization, period, comparison you want, "
        "and what you want explained."
    )

    if st.button(
        "🧠 Generate Focused Word Report",
        type="primary",
        width="stretch",
    ):

        if not report_request.strip():
            st.warning(
                "Please describe what you want the report to be about."
            )
        else:

            try:

                # ----------------------------------------------------------
                # Step 1 — Ask Gemini to understand the report objective
                # ----------------------------------------------------------

                with st.spinner(
                    "Understanding your report requirement..."
                ):
                    plan = report_gen.build_report_plan(
                        report_request.strip()
                    )

                # Show the generated scope before creating the report.
                with st.expander(
                    "🔎 Report scope understood by CoalMind",
                    expanded=True,
                ):

                    st.markdown(
                        f"**Title:** "
                        f"{plan.get('title', 'CoalMind Focused Report')}"
                    )

                    st.markdown(
                        f"**Purpose:** "
                        f"{plan.get('purpose', '')}"
                    )

                    if plan.get("focus_topics"):
                        st.markdown(
                            "**Topics:** "
                            + ", ".join(plan["focus_topics"])
                        )

                    if plan.get("entities"):
                        st.markdown(
                            "**Entities:** "
                            + ", ".join(plan["entities"])
                        )

                    if plan.get("periods"):
                        st.markdown(
                            "**Periods:** "
                            + ", ".join(plan["periods"])
                        )

                    if plan.get("exclude"):
                        st.markdown(
                            "**Excluded:** "
                            + ", ".join(plan["exclude"])
                        )

                # ----------------------------------------------------------
                # Step 2 — Retrieve evidence + analyze + create DOCX
                # ----------------------------------------------------------

                with st.spinner(
                    "Retrieving relevant evidence and generating focused report..."
                ):

                    out = Path(
                        OUT / "CoalMind_Focused_Report.docx"
                    )

                    path = report_gen.generate_report(
                        out_path=out,
                        report_request=report_request.strip(),
                        plan=plan,
                    )

                st.success(
                    "✅ Focused report generated successfully."
                )

                with open(path, "rb") as f:
                    report_bytes = f.read()

                st.download_button(
                    "⬇️ Download Focused CoalMind Report",
                    report_bytes,
                    file_name="CoalMind_Focused_Report.docx",
                    mime=(
                        "application/vnd.openxmlformats-officedocument."
                        "wordprocessingml.document"
                    ),
                    width="stretch",
                )

            except Exception as e:
                st.error(
                    f"Report generation failed: {e}"
                )

    st.divider()

    st.subheader("📋 Audit Trail")

    import pandas as pd

    con = db.connect()

    audit = pd.read_sql(
        "SELECT ts, user, action, target, detail "
        "FROM audit_log ORDER BY id DESC LIMIT 40",
        con,
    )

    con.close()

    if not audit.empty:
        st.dataframe(
            audit,
            width="stretch",
            height=350,
            hide_index=True,
        )
    else:
        st.info("No audit events yet.")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 5: TOPICS
# ══════════════════════════════════════════════════════════════════════════════
elif tab == tab_names[4]:
    st.title("☁️ Topics & Word Cloud")

    if st.button("🔄 Run Topic Analysis"):
        with st.spinner("Analysing text chunks…"):
            t = topics.get_topics()
        st.session_state["_topics"] = t

    res = st.session_state.get("_topics")
    if res:
        st.caption(f"Source: {res['source']} · {res['n_docs']} text chunks")
        if res.get("freqs"):
            try:
                from wordcloud import WordCloud
                import matplotlib.pyplot as plt
                wc = WordCloud(width=900, height=360, background_color="white",
                               colormap="Blues", max_words=80).generate_from_frequencies(res["freqs"])
                fig, ax = plt.subplots(figsize=(9,3.6))
                ax.imshow(wc, interpolation="bilinear"); ax.axis("off")
                st.pyplot(fig)
            except ImportError:
                st.info("Install `wordcloud` and `matplotlib` for the word cloud.")
                import pandas as pd
                st.bar_chart(pd.Series(res["freqs"]).nlargest(30))
        if res.get("topics"):
            st.subheader(f"Discovered topics ({len(res['topics'])})")
            for t_item in res["topics"][:8]:
                with st.expander(f"Topic {t_item['topic']}: {t_item['label']}"):
                    st.write(", ".join(t_item["words"][:15]))
    else:
        st.info("Click 'Run Topic Analysis' above.")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 6: KPI DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════
elif tab == tab_names[5]:
    st.title("📈 KPI Dashboard")
    st.caption("Measured on the synthetic gold set (blueprint section 7). Real results, not estimates.")

    if st.button("🧪 Run KPI Evaluation on synthetic data", type="primary"):
        logs = []
        with st.spinner("Building synthetic workbook, ingesting, extracting, validating, measuring…"):
            old_db = str(db.get_path())
            db.set_path(db.get_path().parent / "_eval_tmp.db")
            db.reset()
            kpis = evaluate.run(log=lambda m: logs.append(m))
            db.reset()
            db.set_path(Path(old_db))
        with st.expander("Evaluation log"):
            st.code("\n".join(logs))
        st.session_state["_kpis"] = kpis
        st.rerun()

    kpis = st.session_state.get("_kpis")
    if kpis:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Extraction accuracy", f"{kpis['extraction_accuracy_pct']}%", delta="target ≥ 85%")
        c2.metric("Validation catch rate", f"{kpis['validation_catch_rate_pct']}%", delta="target 100%")
        c3.metric("Ingest time (s)", kpis["ingest_time_s"])
        c4.metric("Validate time (s)", kpis["validate_time_s"])
        st.divider()
        import pandas as pd
        rows = [
            ["Gold facts in test set", kpis["gold_facts"], "—"],
            ["Facts extracted", kpis["extracted"], "—"],
            ["Correct values", kpis["correct"], "—"],
            ["Extraction accuracy", f"{kpis['extraction_accuracy_pct']}%", "≥ 85%"],
            ["Planted errors", kpis["planted_errors"], "—"],
            ["Errors caught by rules", kpis["caught"], "—"],
            ["Validation catch rate", f"{kpis['validation_catch_rate_pct']}%", "100%"],
            ["LLM provider", kpis["llm_status"], "—"],
        ]
        st.table(
            pd.DataFrame(
                rows,
                columns=["KPI", "Measured", "Target"]
            ).astype(str)
        )
        if kpis.get("flags_by_code"):
            st.subheader("Flags by rule")
            st.json(kpis["flags_by_code"])
    else:
        import pandas as pd
        con = db.connect()
        s = validate.summary()
        con.close()
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Documents", s.get("documents",0))
        c2.metric("Facts", s.get("facts",0))
        c3.metric("Flagged", s.get("flagged",0))
        c4.metric("LLM", llm.status())
        st.info("Click '🧪 Run KPI Evaluation' for measured accuracy numbers.")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 7: GRAPH EXPLORER
# ══════════════════════════════════════════════════════════════════════════════
elif tab == tab_names[6]:
    st.title("🌐 Graph Explorer (GraphRAG)")
    st.caption("SQLite property-graph of Subsidiary → Block → Borehole → Seam relationships. "
               "Production: swap for Neo4j Cypher with identical API.")

    col1, col2 = st.columns([2, 3])

    with col1:
        st.subheader("Build / Rebuild Graph")
        if st.button("🔨 Build graph from ingested data", type="primary"):
            n = graph.build_from_db(log=lambda m: None)
            st.success(f"Graph built: {n} edges written.")
            st.rerun()

        summ = graph.graph_summary()
        st.subheader("Graph Statistics")
        for tbl, cnt in summ["node_table_counts"].items():
            st.metric(tbl, cnt)

        if summ["edge_types"]:
            import pandas as pd
            st.subheader("Edge types")
            st.dataframe(pd.DataFrame(list(summ["edge_types"].items()),
                                      columns=["Relationship", "Count"]),
                         hide_index=True, use_container_width=True)

    with col2:
        st.subheader("Multi-hop Query")
        st.caption("Examples: *'SECL opencast projects with stripping ratio below 6'* · "
                   "*'NCL boreholes with G9 coal'* · *'BCCL blocks in Jharia coalfield'*")
        mh_q = st.text_input("Multi-hop question", "SECL projects with stripping ratio below 6")
        if st.button("🔗 Traverse graph"):
            result = graph.multi_hop(mh_q)
            st.markdown(result["summary"] or "_No results_")
            with st.expander("Raw found nodes"):
                st.json(result["found"])

        st.divider()
        st.subheader("🔬 Lithological Thesaurus")
        st.caption("Normalises historical field shorthand → canonical terms (dh2loop-inspired)")
        raw_litho = st.text_input("Enter raw lithology text", "Carb. Sh")
        if raw_litho:
            normed = normalise(raw_litho)
            arrow = "✅" if normed != raw_litho else "⚪"
            st.markdown(f"{arrow} **`{raw_litho}`** → **{normed}**")

        with st.expander("Full thesaurus dictionary"):
            import pandas as pd
            rows = [(canon, ", ".join(abbrs[:5])) for canon, abbrs in LITHO_DICT.items()]
            st.dataframe(pd.DataFrame(rows, columns=["Canonical", "Variants (sample)"]),
                         hide_index=True, use_container_width=True)

        st.divider()
        st.subheader("🏔️ GCV Grade Classifier")
        st.caption("MoC official grade bands G1–G17 for non-coking coal")
        gcv_val = st.number_input("Enter GCV (kcal/kg)", min_value=0, max_value=9999,
                                  value=4750, step=50)
        grade = classify_seam_grade(gcv_val)
        from coalmind.thesaurus import grade_range
        rng = grade_range(grade)
        band = f"({rng[0]}–{rng[1]} kcal/kg)" if rng else ""
        color = "#2e7d32" if grade != "Ungraded" else "#888"
        st.markdown(f"<h3 style='color:{color}'>Grade: {grade} {band}</h3>", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# TAB 8: ARCHITECTURE (comparison slide for demo)
# ══════════════════════════════════════════════════════════════════════════════
elif tab == tab_names[7]:
    st.title("🏛️ Architecture & Global Comparison")
    st.caption("How CoalMind fuses global geoscientific standards with India's administrative governance needs")

    st.markdown("""
    <style>
    .arch-card { background:#EBF3FB; border-left:4px solid #1F497D;
                 padding:10px 16px; border-radius:6px; margin-bottom:8px; }
    .arch-card h4 { margin:0 0 4px 0; color:#1F497D; }
    .arch-card p  { margin:0; font-size:13px; color:#333; }
    .vs-left  { background:#FFF8E1; border-left:4px solid #F9A825;
                padding:8px 14px; border-radius:6px; }
    .vs-right { background:#E8F5E9; border-left:4px solid #2E7D32;
                padding:8px 14px; border-radius:6px; }
    </style>
    """, unsafe_allow_html=True)

    st.subheader("Global Systems vs CoalMind")

    c1, c2 = st.columns(2)
    with c1:
        st.markdown('<div class="vs-left"><b>🌍 Global Platforms</b><br>'
                    '(CSIRO dh2loop · USGS Earth MRI · Canada GSC · OGC/IUGS GeoSciML)<br><br>'
                    '✔ Scientific resource modelling<br>'
                    '✔ Academic mapping<br>'
                    '✔ Exploration tools<br>'
                    '✘ No parliamentary deadline support<br>'
                    '✘ No CAG audit trail<br>'
                    '✘ No multi-subsidiary PQ reconciliation<br>'
                    '✘ No deterministic public-audit math</div>',
                    unsafe_allow_html=True)
    with c2:
        st.markdown('<div class="vs-right"><b>⛏️ CoalMind (This System)</b><br>'
                    'Global standards + India governance layer<br><br>'
                    '✔ GeoSciML borehole schemas<br>'
                    '✔ dh2loop-style lithology thesaurus<br>'
                    '✔ Deterministic validation (sum/GCV/SR/UNFC)<br>'
                    '✔ Parliamentary Q&A in 24–72 h window<br>'
                    '✔ SHA-256 + bounding-box provenance<br>'
                    '✔ HITL approval + full audit log<br>'
                    '✔ Air-gapped open-source LLM ready</div>',
                    unsafe_allow_html=True)

    st.divider()
    st.subheader("Seven-Tier Architecture")

    tiers = [
        ("Tier 1", "Document Ingestion & Vision Parsing",
         "Layout-aware parsing (openpyxl + PyMuPDF + PaddleOCR). Adaptive pre-processing for scanned reports.",
         "Docling / MinerU · TableFormer (roadmap)"),
        ("Tier 2", "Spatial & Lithological Normalisation",
         "Indian Coalfield Thesaurus (dh2loop-inspired). Fuzzy matching converts 'Carb. Sh' → 'Carbonaceous Shale'. "
         "Survey of India toposheet coordinate extraction.",
         "✅ thesaurus.py — live in this prototype"),
        ("Tier 3", "GeoSciML Schema Transformation",
         "Validated data mapped to OGC/IUGS-aligned JSON: BoreholeInterval, CoalQuality, ResourceEstimate, MiningParameters.",
         "✅ boreholes/strata/seams tables in DB"),
        ("Tier 4", "Deterministic Validation Engine",
         "7 rules: depth sum, core recovery, GCV↔grade, moisture range, UNFC balance, stripping ratio, reserve sum. "
         "Zero arithmetic hallucinations from LLM.",
         "✅ validate.py — 8 statistical + 6 geological rules"),
        ("Tier 5", "Knowledge Graph & Hybrid Retrieval (GraphRAG)",
         "SQLite property-graph: Subsidiary→Area→Block→Borehole→Seam. "
         "Reciprocal Rank Fusion of Cypher graph traversal + dense vector search.",
         "✅ graph.py (Neo4j on roadmap)"),
        ("Tier 6", "Tripartite Operational Applications",
         "Module 1: Automated Word report. Module 2: BERTopic word cloud. Module 3: PQ Copilot.",
         "✅ All three modules live"),
        ("Tier 7", "Traceability & Governance",
         "SHA-256 document hashing. Cell-level provenance (sheet + cell address). HITL console. Audit log.",
         "✅ Every fact traceable to its source cell"),
    ]

    for tier, title, desc, status in tiers:
        st.markdown(f'<div class="arch-card"><h4>{tier}: {title}</h4>'
                    f'<p>{desc}</p>'
                    f'<p style="margin-top:4px;color:#555;font-size:12px">↳ {status}</p></div>',
                    unsafe_allow_html=True)

    st.divider()
    st.subheader("UNFC Reserve Confidence Classes")
    import pandas as pd
    st.dataframe(pd.DataFrame(list(UNFC_SPACING.items()), columns=["Class", "Borehole Spacing Criterion"]),
                 hide_index=True, use_container_width=True)

    st.subheader("MoC Statutory Grade Bands (Non-Coking Coal)")
    from coalmind.thesaurus import _GRADES
    grade_df = pd.DataFrame(_GRADES, columns=["Grade", "GCV Lo (kcal/kg)", "GCV Hi (kcal/kg)"])
    st.dataframe(grade_df, hide_index=True, use_container_width=True, height=350)
