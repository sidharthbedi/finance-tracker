import json
from typing import Dict, List, Tuple

import ollama
import yaml

from feedback import FeedbackDB


def load_config(config_path: str = "categories.yaml") -> dict:
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _strip_thinking(text: str) -> str:
    """Remove Qwen3 <think>...</think> blocks before parsing JSON."""
    if "<think>" in text and "</think>" in text:
        text = text.split("</think>", 1)[-1]
    return text.strip()


def _extract_json(text: str) -> dict:
    """Pull the first {...} block out of the model response."""
    start = text.find("{")
    end = text.rfind("}") + 1
    if start == -1 or end == 0:
        raise ValueError(f"No JSON object found in: {text!r}")
    return json.loads(text[start:end])


def _build_prompt(description: str, amount: float, categories: List[str], examples: List[Dict]) -> str:
    category_list = "\n".join(f"  - {c}" for c in categories)

    examples_block = ""
    if examples:
        lines = "\n".join(
            f'  "{ex["description"]}" → category: {ex["category"]}, sub_category: {ex["sub_category"]}'
            for ex in examples
        )
        examples_block = f"\nPast corrections (use these as guidance):\n{lines}\n"

    return f"""You are a personal finance categorizer for an Indian household. /nothink

Valid categories (you MUST pick exactly one):
{category_list}
{examples_block}
Transaction to classify:
  Description : {description}
  Amount (INR): {amount}

Rules:
1. Pick the single best-matching category from the list above.
2. Write a short sub_category (2–4 words) describing the specific expense — e.g. "Petrol", "McDonald's", "FASTag recharge".
3. If unsure, use "Others".

Reply with ONLY this JSON — no explanation, no markdown:
{{"category": "...", "sub_category": "..."}}"""


def categorize_transaction(
    description: str,
    amount: float,
    categories: List[str],
    feedback_db: FeedbackDB,
    model_name: str,
    ollama_host: str = "http://localhost:11434",
) -> Tuple[str, str]:
    examples = feedback_db.get_similar(description, limit=5)
    prompt = _build_prompt(description, amount, categories, examples)

    try:
        client = ollama.Client(host=ollama_host)
        response = client.chat(
            model=model_name,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.0},
        )
        raw = response["message"]["content"]
        raw = _strip_thinking(raw)
        result = _extract_json(raw)

        category = result.get("category", "Others")
        sub_category = result.get("sub_category", "—")

        if category not in categories:
            category = "Others"

        return category, sub_category

    except Exception as exc:
        return "Others", f"[error: {exc}]"
