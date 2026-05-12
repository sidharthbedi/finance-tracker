"""
Personal Finance Tracker
Upload a bank statement → LLM categorizes each row → review, correct, download.
"""

import pandas as pd
import streamlit as st
import yaml

from categorizer import categorize_transaction, load_config
from exporter import export_to_excel
from feedback import FeedbackDB
from parser import parse_statement

CONFIG_PATH = "categories.yaml"
DB_PATH = "feedback.db"
DEFAULT_MODEL = "qwen3-vl:4b-instruct"
DEFAULT_OLLAMA = "http://localhost:11434"

st.set_page_config(page_title="Finance Tracker", page_icon="💰", layout="wide")


# ── helpers ────────────────────────────────────────────────────────────────────

@st.cache_data
def _load_config():
    return load_config(CONFIG_PATH)


def reload_config():
    _load_config.clear()
    return load_config(CONFIG_PATH)


# ── sidebar ─────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("Settings")

    model_name = st.text_input("Ollama model name", value=DEFAULT_MODEL,
                               help="Run `ollama list` in a terminal to see available models.")
    ollama_host = st.text_input("Ollama host", value=DEFAULT_OLLAMA)

    st.divider()
    st.subheader("Categories")
    st.caption("One per line. Save to update the config file instantly.")

    cfg = reload_config()
    raw_cats = st.text_area(
        "Categories",
        value="\n".join(cfg["categories"]),
        height=320,
        label_visibility="collapsed",
    )

    if st.button("Save categories", use_container_width=True):
        new_cats = [c.strip() for c in raw_cats.splitlines() if c.strip()]
        cfg["categories"] = new_cats
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False)
        reload_config()
        st.success(f"Saved {len(new_cats)} categories.")

    st.divider()
    feedback_db = FeedbackDB(DB_PATH)
    st.caption(f"Feedback DB: **{feedback_db.count()}** corrections stored")


# ── main ────────────────────────────────────────────────────────────────────────

st.title("Personal Finance Tracker")

# ── Step 1: upload ──────────────────────────────────────────────────────────────
st.header("1  Upload bank statement")
uploaded = st.file_uploader("Excel file (.xlsx / .xls)", type=["xlsx", "xls"])

if not uploaded:
    st.info("Upload your bank statement to get started.")
    st.stop()

raw_df = pd.read_excel(uploaded, header=None)

# Try to detect the real header row (first row where >50 % of cells are non-empty strings)
header_row = 0
for i, row in raw_df.iterrows():
    non_empty = row.dropna()
    if len(non_empty) >= 3 and all(isinstance(v, str) for v in non_empty[:4]):
        header_row = i
        break

raw_df = pd.read_excel(uploaded, header=header_row)
raw_df.columns = raw_df.columns.astype(str).str.strip()

st.caption(f"{len(raw_df)} rows detected. Preview:")
st.dataframe(raw_df.head(5), use_container_width=True)


# ── Step 2: map columns ─────────────────────────────────────────────────────────
st.header("2  Map columns")
cols_options = ["— select —"] + raw_df.columns.tolist()

c1, c2, c3, c4 = st.columns(4)
date_col = c1.selectbox("Date", cols_options)
desc_col = c2.selectbox("Description / Narration", cols_options)
debit_col = c3.selectbox("Debit / Amount", cols_options)
credit_col = c4.selectbox("Credit (optional)", cols_options)

if any(v == "— select —" for v in [date_col, desc_col, debit_col]):
    st.warning("Map at least the Date, Description, and Debit columns to continue.")
    st.stop()

parsed_df = parse_statement(
    raw_df,
    date_col,
    desc_col,
    debit_col,
    credit_col if credit_col != "— select —" else None,
)

st.success(f"{len(parsed_df)} expense rows ready for categorization.")


# ── Step 3: categorize ──────────────────────────────────────────────────────────
st.header("3  Categorize")

if "results" not in st.session_state:
    st.session_state.results = None

if st.button("Run categorization", type="primary", use_container_width=True):
    cfg = reload_config()
    categories = cfg["categories"]
    rows = []
    progress_bar = st.progress(0, text="Starting…")

    for idx, row in parsed_df.iterrows():
        progress_bar.progress(
            (idx + 1) / len(parsed_df),
            text=f"Row {idx + 1}/{len(parsed_df)}: {row['description'][:60]}",
        )
        cat, sub = categorize_transaction(
            description=row["description"],
            amount=row["amount"],
            categories=categories,
            feedback_db=feedback_db,
            model_name=model_name,
            ollama_host=ollama_host,
        )
        rows.append({**row.to_dict(), "category": cat, "sub_category": sub})

    st.session_state.results = pd.DataFrame(rows)
    progress_bar.empty()
    st.success("Categorization complete!")


# ── Step 4: review & correct ────────────────────────────────────────────────────
if st.session_state.results is not None:
    st.header("4  Review & correct")
    st.caption(
        "Edit **category** or **sub_category** directly in the table. "
        "Changes are highlighted. Hit *Save feedback* to teach the model."
    )

    cfg = reload_config()

    edited = st.data_editor(
        st.session_state.results,
        column_config={
            "date": st.column_config.DateColumn("Date"),
            "description": st.column_config.TextColumn("Description", disabled=True),
            "amount": st.column_config.NumberColumn("Amount (₹)", format="₹%.2f", disabled=True),
            "debit": None,   # hide raw columns
            "credit": None,
            "category": st.column_config.SelectboxColumn(
                "Category", options=cfg["categories"], required=True
            ),
            "sub_category": st.column_config.TextColumn("Sub-category"),
        },
        use_container_width=True,
        num_rows="fixed",
        key="editor",
    )

    col_save, col_download = st.columns(2)

    with col_save:
        if st.button("Save feedback", use_container_width=True):
            original = st.session_state.results
            saved = 0
            for i, orig_row in original.iterrows():
                ed_row = edited.iloc[i]
                # Save every row that was changed (or explicitly confirmed by saving)
                if (
                    orig_row["category"] != ed_row["category"]
                    or orig_row["sub_category"] != ed_row["sub_category"]
                ):
                    feedback_db.save(
                        ed_row["description"],
                        float(ed_row["amount"]),
                        ed_row["category"],
                        ed_row["sub_category"],
                    )
                    saved += 1
            if saved:
                st.success(f"Saved {saved} correction(s) — the model will use them next run.")
            else:
                st.info("No changes detected.")

    with col_download:
        cfg = reload_config()
        excel_bytes = export_to_excel(edited, cfg.get("buckets", {}))

        # Before downloading, snapshot every row into the eval dataset
        # so evals have a representative sample (correct + incorrect rows)
        original = st.session_state.results
        for i, orig_row in original.iterrows():
            ed_row = edited.iloc[i]
            was_corrected = (
                orig_row["category"] != ed_row["category"]
                or orig_row["sub_category"] != ed_row["sub_category"]
            )
            feedback_db.save_eval_row(
                ed_row["description"],
                float(ed_row["amount"]),
                ed_row["category"],
                ed_row["sub_category"],
                was_corrected=was_corrected,
            )

        st.download_button(
            "Download Excel",
            data=excel_bytes,
            file_name="categorized_expenses.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )

    # ── Feedback history ─────────────────────────────────────────────────────────
    with st.expander(f"Feedback history ({feedback_db.count()} entries)"):
        hist = feedback_db.get_all()
        if hist:
            hist_df = pd.DataFrame(
                hist, columns=["Description", "Amount (₹)", "Category", "Sub-category", "Saved at"]
            )
            st.dataframe(hist_df, use_container_width=True)
        else:
            st.info("No corrections saved yet.")
