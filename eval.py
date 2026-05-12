"""
Evals for the finance tracker categorizer.

Pulls every correction from feedback.db as ground truth, then runs two tests:
  - Baseline : LLM with NO feedback examples (raw model ability)
  - With feedback : LLM with examples from DB, excluding the row being tested
                    (leave-one-out so the answer isn't just looked up)

Prints accuracy, fallback rate, worst-performing categories, and the
improvement the feedback loop delivers.

Usage:
    python eval.py
    python eval.py --limit 20      # test only the first 20 corrections
    python eval.py --no-baseline   # skip the slower baseline run
"""

import argparse
import sqlite3
import sys
import time
from collections import defaultdict

from categorizer import categorize_transaction, load_config
from feedback import FeedbackDB


# ── helpers ────────────────────────────────────────────────────────────────────

class _EmptyDB:
    """Drop-in for FeedbackDB that always returns zero examples — used for baseline."""
    def get_similar(self, *_, **__):
        return []


class _LeaveOneOutDB:
    """Returns examples from feedback.db excluding the row currently being tested."""
    def __init__(self, db_path, exclude_description):
        self.db_path = db_path
        self.exclude = exclude_description

    def get_similar(self, description, limit=5):
        words = [w for w in description.upper().split() if len(w) > 3][:4]
        if not words:
            return []
        seen, results = set(), []
        with sqlite3.connect(self.db_path) as conn:
            for word in words:
                rows = conn.execute(
                    """SELECT description, category, sub_category
                       FROM corrections
                       WHERE UPPER(description) LIKE ?
                         AND description != ?
                       LIMIT ?""",
                    (f"%{word}%", self.exclude, limit),
                ).fetchall()
                for desc, cat, sub in rows:
                    if desc not in seen:
                        seen.add(desc)
                        results.append({"description": desc, "category": cat, "sub_category": sub})
                    if len(results) >= limit:
                        return results
        return results


def _bar(value, total, width=30):
    filled = int(round(value / total * width)) if total else 0
    return "█" * filled + "░" * (width - filled)


def _pct(num, denom):
    return (num / denom * 100) if denom else 0.0


# ── core eval logic ────────────────────────────────────────────────────────────

def run_eval(ground_truth, categories, model_name, ollama_host, db_path, use_feedback):
    """
    Run one pass over ground_truth records.
    Returns a dict with per-record results.
    """
    results = []
    total = len(ground_truth)

    for i, (description, amount, true_category, true_sub) in enumerate(ground_truth):
        print(f"  [{i+1:>3}/{total}] {description[:55]:<55}", end="\r", flush=True)

        if use_feedback:
            db = _LeaveOneOutDB(db_path, description)
        else:
            db = _EmptyDB()

        pred_category, pred_sub = categorize_transaction(
            description=description,
            amount=amount or 0.0,
            categories=categories,
            feedback_db=db,
            model_name=model_name,
            ollama_host=ollama_host,
        )

        results.append({
            "description": description,
            "true_category": true_category,
            "pred_category": pred_category,
            "true_sub": true_sub,
            "pred_sub": pred_sub,
            "correct": pred_category == true_category,
            "fallback": pred_category == "Others" and true_category != "Others",
        })

    print(" " * 70, end="\r")  # clear progress line
    return results


# ── report printing ────────────────────────────────────────────────────────────

def print_report(results, label):
    total     = len(results)
    correct   = sum(r["correct"] for r in results)
    fallbacks = sum(r["fallback"] for r in results)
    wrong     = total - correct

    print(f"\n{'─'*60}")
    print(f"  {label}")
    print(f"{'─'*60}")
    print(f"  Transactions tested : {total}")
    print(f"  Correct             : {correct:>4}  ({_pct(correct, total):.1f}%)")
    print(f"  Wrong               : {wrong:>4}  ({_pct(wrong, total):.1f}%)")
    print(f"  Fell back to Others : {fallbacks:>4}  ({_pct(fallbacks, total):.1f}%)")

    # Per-category accuracy
    cat_total   = defaultdict(int)
    cat_correct = defaultdict(int)
    confusions  = defaultdict(lambda: defaultdict(int))  # true → predicted → count

    for r in results:
        cat_total[r["true_category"]] += 1
        if r["correct"]:
            cat_correct[r["true_category"]] += 1
        else:
            confusions[r["true_category"]][r["pred_category"]] += 1

    # Sort categories by accuracy ascending (worst first)
    sorted_cats = sorted(
        cat_total.keys(),
        key=lambda c: _pct(cat_correct[c], cat_total[c])
    )

    print(f"\n  {'Category':<28} {'Accuracy':>8}   {'Bar':<32} {'n':>4}")
    print(f"  {'─'*28} {'─'*8}   {'─'*32} {'─'*4}")
    for cat in sorted_cats:
        n   = cat_total[cat]
        acc = _pct(cat_correct[cat], n)
        bar = _bar(cat_correct[cat], n)
        print(f"  {cat:<28} {acc:>7.1f}%   {bar}  {n:>4}")

    # Top confusions
    flat_confusions = [
        (true, pred, count)
        for true, preds in confusions.items()
        for pred, count in preds.items()
    ]
    flat_confusions.sort(key=lambda x: -x[2])

    if flat_confusions:
        print(f"\n  Top misclassifications:")
        for true, pred, count in flat_confusions[:8]:
            print(f"    {true:<28} → predicted as  {pred:<28}  ({count}x)")


def print_comparison(baseline, with_feedback):
    total = len(baseline)
    acc_base = _pct(sum(r["correct"] for r in baseline), total)
    acc_fb   = _pct(sum(r["correct"] for r in with_feedback), total)
    delta    = acc_fb - acc_base

    sign = "+" if delta >= 0 else ""
    print(f"\n{'═'*60}")
    print(f"  FEEDBACK LOOP IMPACT")
    print(f"{'═'*60}")
    print(f"  Accuracy without feedback : {acc_base:.1f}%")
    print(f"  Accuracy with feedback    : {acc_fb:.1f}%")
    print(f"  Improvement               : {sign}{delta:.1f} percentage points")

    if delta > 5:
        print("\n  The feedback loop is working well.")
    elif delta > 0:
        print("\n  Small improvement — add more corrections to grow the effect.")
    else:
        print("\n  No improvement yet — you may need more corrections in feedback.db.")
    print(f"{'═'*60}\n")


# ── main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Run evals on the finance tracker.")
    parser.add_argument("--limit",       type=int, default=None, help="Max rows to test")
    parser.add_argument("--no-baseline", action="store_true",    help="Skip baseline run")
    parser.add_argument("--model",       default="qwen3-vl:4b-instruct")
    parser.add_argument("--ollama-host", default="http://localhost:11434")
    parser.add_argument("--db",          default="feedback.db")
    args = parser.parse_args()

    # Load ground truth from eval_dataset (all rows, correct + incorrect)
    # Falls back to corrections table if eval_dataset is empty (old behaviour)
    with sqlite3.connect(args.db) as conn:
        rows = conn.execute(
            "SELECT description, amount, true_category, true_sub_category FROM eval_dataset ORDER BY created_at"
        ).fetchall()

    if not rows:
        print(
            "No eval data yet.\n"
            "Run the app, categorize a statement, then click Download Excel — "
            "that saves every row (correct + incorrect) to the eval dataset.\n"
            "Then re-run eval.py."
        )
        sys.exit(1)

    corrected_count = 0
    with sqlite3.connect(args.db) as conn:
        result = conn.execute("SELECT COUNT(*) FROM eval_dataset WHERE was_corrected=1").fetchone()
        corrected_count = result[0] if result else 0

    if args.limit:
        rows = rows[:args.limit]

    cfg        = load_config("categories.yaml")
    categories = cfg["categories"]

    print(f"\n  Finance Tracker — Eval Suite")
    print(f"  Model       : {args.model}")
    print(f"  Total rows  : {len(rows)}  ({corrected_count} were corrected by you, {len(rows)-corrected_count} were already correct)")

    # ── Run with feedback ──────────────────────────────────────────────────────
    print(f"\n  Running: WITH feedback examples (leave-one-out)…")
    t0 = time.time()
    results_fb = run_eval(rows, categories, args.model, args.ollama_host, args.db, use_feedback=True)
    print(f"  Done in {time.time()-t0:.1f}s")
    print_report(results_fb, "WITH FEEDBACK EXAMPLES")

    # ── Baseline (optional) ───────────────────────────────────────────────────
    if not args.no_baseline:
        print(f"\n  Running: BASELINE (no feedback examples)…")
        t0 = time.time()
        results_base = run_eval(rows, categories, args.model, args.ollama_host, args.db, use_feedback=False)
        print(f"  Done in {time.time()-t0:.1f}s")
        print_report(results_base, "BASELINE — no feedback")
        print_comparison(results_base, results_fb)
    else:
        total   = len(results_fb)
        correct = sum(r["correct"] for r in results_fb)
        print(f"\n  Final accuracy: {_pct(correct, total):.1f}%  ({correct}/{total})\n")


if __name__ == "__main__":
    main()
