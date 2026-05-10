# Personal Finance Tracker — AI-Powered Bank Statement Categorizer

A local-first personal finance tool that reads your bank statement, uses a locally running LLM to categorize every transaction, and lets you review and correct results — with a feedback loop that makes the model smarter over time.

**No data ever leaves your machine.**

![Python](https://img.shields.io/badge/Python-3.9+-blue)
![Streamlit](https://img.shields.io/badge/UI-Streamlit-red)
![Ollama](https://img.shields.io/badge/LLM-Ollama-black)
![License](https://img.shields.io/badge/License-MIT-green)

---

## How it works

```
Bank Statement (.xls / .xlsx)
         │
         ▼
  ┌─────────────┐
  │  Streamlit  │  ← Upload, review, correct, download
  │     UI      │
  └──────┬──────┘
         │
         ▼
  ┌─────────────┐         ┌──────────────────┐
  │  Categorizer│────────►│  Ollama (local)  │
  │             │         │  any model       │
  └──────┬──────┘         └──────────────────┘
         │
         ▼
  ┌─────────────┐
  │  Feedback DB│  ← SQLite — stores your corrections
  │  (SQLite)   │     as few-shot examples for next run
  └─────────────┘
         │
         ▼
  Output Excel
  (Transactions + Summary sheets)
```

For each transaction the LLM assigns:
- **Category** — chosen from your configurable list (e.g. `Transportation`, `Eating Out`)
- **Sub-category** — a short human-readable label it infers (e.g. `Petrol`, `McDonald's`, `FASTag`)

Every correction you make is stored locally and injected as examples into future prompts — no fine-tuning required.

---

## Features

- Upload any bank statement in `.xls` or `.xlsx` format
- Map your own column names (Date, Description, Debit, Credit)
- Fully configurable category list — edit `categories.yaml` or directly in the sidebar
- Inline review and correction of every categorized row
- Feedback loop: corrections are saved to a local SQLite DB and used as few-shot examples on the next run
- Output Excel with two sheets: `Transactions` (full detail) and `Summary` (totals by bucket and category)
- 100% local — Ollama runs on your machine, no API keys, no cloud

---

## Prerequisites

- Python 3.9+
- [Ollama](https://ollama.com) running locally (via Ollama app or AnythingLLM)
- Any Ollama-compatible model pulled and running (tested with `qwen3-vl:4b-instruct` and `qwen2.5:7b`)

---

## Setup

```bash
git clone https://github.com/YOUR_USERNAME/finance-tracker.git
cd finance-tracker

python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate

pip install -r requirements.txt
streamlit run app.py
```

Open `http://localhost:8501` in your browser.

---

## Configuration

### Categories (`categories.yaml`)

Edit this file to add, remove, or rename categories. Each category also maps to a high-level **bucket** used in the summary sheet:

| Bucket | Examples |
|---|---|
| Expenses - Mandatory | Groceries, Electricity, School, Insurance |
| Expenses - Discretionary | Eating Out, Shopping, Entertainment |
| EMI | Home loan, Car loan, Tax EMI |
| Short Term Savings | Holidays, Medical buffer |
| Long Term Savings | SIP, PPF, NPS, VPF |

You can also edit categories live from the app's sidebar — changes are saved back to `categories.yaml` immediately.

### Ollama model

Enter your model name in the Settings sidebar. To see what models you have available:

```bash
ollama list
# or check via API:
curl http://localhost:11434/api/tags
```

---

## Usage walkthrough

1. **Upload** your bank statement Excel file
2. **Map columns** — tell the app which column is Date, Description, Debit, and (optionally) Credit
3. **Run categorization** — the LLM processes each row with a progress bar
4. **Review & correct** — edit any Category or Sub-category directly in the table
5. **Save feedback** — corrections are stored and will improve future runs
6. **Download Excel** — get the categorized output with a Summary sheet

---

## Project structure

```
finance-tracker/
├── app.py            # Streamlit UI — 4-step flow
├── categorizer.py    # LLM prompt builder and Ollama client
├── feedback.py       # SQLite feedback store and retrieval
├── parser.py         # Bank statement normalizer
├── exporter.py       # Styled Excel output (2 sheets)
├── categories.yaml   # Your editable category + bucket config
└── requirements.txt
```

---

## The feedback loop explained

When you correct a row (e.g. change `Others → Transportation / Petrol`), it's saved to `feedback.db`. On the next run, before calling the LLM for any transaction, the app retrieves up to 5 keyword-matching past corrections and injects them directly into the prompt as examples. This is **in-context few-shot learning** — no model retraining, no cloud, just your own corrections making the tool progressively smarter.

---

## Privacy

- Your bank statement is processed entirely on your local machine
- The LLM runs via Ollama — no data is sent to any external server
- `feedback.db` (your corrections) stays local — it is excluded from git via `.gitignore`
- Bank statement files are also excluded from git

---

## License

MIT
