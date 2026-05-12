import sqlite3
from typing import Dict, List, Optional, Tuple


class FeedbackDB:
    def __init__(self, db_path="feedback.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS corrections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    description TEXT NOT NULL,
                    amount REAL,
                    category TEXT NOT NULL,
                    sub_category TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_description
                ON corrections (description)
            """)
            # Separate table for eval — stores ALL rows (correct + incorrect)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS eval_dataset (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    description TEXT NOT NULL,
                    amount REAL,
                    true_category TEXT NOT NULL,
                    true_sub_category TEXT NOT NULL,
                    was_corrected INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

    def save(self, description: str, amount: float, category: str, sub_category: str):
        """Upsert a correction — same description+amount overwrites the old one."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO corrections (description, amount, category, sub_category)
                VALUES (?, ?, ?, ?)
                ON CONFLICT DO NOTHING
            """, (description.strip(), amount, category, sub_category))

    def get_similar(self, description: str, limit: int = 5) -> List[Dict]:
        """Return up to `limit` past corrections whose description shares keywords."""
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
                       LIMIT ?""",
                    (f"%{word}%", limit),
                ).fetchall()
                for desc, cat, sub in rows:
                    if desc not in seen:
                        seen.add(desc)
                        results.append({"description": desc, "category": cat, "sub_category": sub})
                    if len(results) >= limit:
                        return results
        return results

    def get_all(self) -> List[Tuple]:
        with sqlite3.connect(self.db_path) as conn:
            return conn.execute(
                """SELECT description, amount, category, sub_category, created_at
                   FROM corrections ORDER BY created_at DESC"""
            ).fetchall()

    def count(self) -> int:
        with sqlite3.connect(self.db_path) as conn:
            return conn.execute("SELECT COUNT(*) FROM corrections").fetchone()[0]

    def save_eval_row(self, description: str, amount: float, category: str, sub_category: str, was_corrected: bool):
        """Save a single row to the eval dataset (called for every row on download)."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO eval_dataset (description, amount, true_category, true_sub_category, was_corrected)
                VALUES (?, ?, ?, ?, ?)
            """, (description.strip(), amount, category, sub_category, int(was_corrected)))

    def get_eval_dataset(self) -> List[Tuple]:
        with sqlite3.connect(self.db_path) as conn:
            return conn.execute(
                """SELECT description, amount, true_category, true_sub_category, was_corrected
                   FROM eval_dataset ORDER BY created_at"""
            ).fetchall()

    def eval_count(self) -> int:
        with sqlite3.connect(self.db_path) as conn:
            return conn.execute("SELECT COUNT(*) FROM eval_dataset").fetchone()[0]
