from typing import Optional

import pandas as pd


def parse_statement(
    df: pd.DataFrame,
    date_col: str,
    description_col: str,
    debit_col: str,
    credit_col: Optional[str] = None,
) -> pd.DataFrame:
    """
    Normalise raw bank-statement DataFrame into a standard schema:
        date | description | debit | credit | amount
    Only rows with a positive debit amount are kept (expense rows).
    """
    result = pd.DataFrame()
    result["date"] = pd.to_datetime(df[date_col], errors="coerce")
    result["description"] = df[description_col].astype(str).str.strip()
    result["debit"] = pd.to_numeric(df[debit_col], errors="coerce").fillna(0)
    result["credit"] = (
        pd.to_numeric(df[credit_col], errors="coerce").fillna(0)
        if credit_col
        else 0
    )
    result["amount"] = result["debit"]

    # Drop header-like rows and zero-amount rows
    result = result[
        result["description"].str.strip().ne("")
        & result["description"].ne("nan")
        & result["debit"].gt(0)
    ].copy()

    return result.reset_index(drop=True)
