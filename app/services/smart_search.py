from __future__ import annotations

from app.utils.text import clean_csv_value, normalize_phone, normalize_search_ar


def _digits_only(value: str) -> str:
    return "".join(ch for ch in clean_csv_value(value) if ch.isdigit())


def smart_search_clause(query, *, text_columns=(), phone_columns=(), extra_columns=()):
    """Build a forgiving SQL search clause.

    Text terms are matched independently, so "احمد محمد" can match
    "احمد جمال محمد". Numeric terms are matched as substrings against phone-like
    columns, so "3337" can match "0599043337".
    """
    raw = clean_csv_value(query)
    if not raw:
        return "", []

    normalized = normalize_search_ar(raw)
    terms = [term for term in normalized.split() if term]
    if not terms:
        return "", []

    text_cols = list(text_columns or ())
    phone_cols = list(phone_columns or ())
    extra_cols = list(extra_columns or ())
    all_text_cols = text_cols + extra_cols

    clauses = []
    params = []

    for term in terms:
        term_parts = []
        like = f"%{term}%"
        for col in all_text_cols:
            term_parts.append(f"COALESCE({col}, '') ILIKE %s")
            params.append(like)

        digits = _digits_only(term)
        if digits:
            phone_like = f"%{digits}%"
            for col in phone_cols:
                term_parts.append(f"COALESCE({col}, '') LIKE %s")
                params.append(phone_like)

            normalized_phone = normalize_phone(term)
            if normalized_phone and normalized_phone != digits:
                normalized_like = f"%{normalized_phone}%"
                for col in phone_cols:
                    term_parts.append(f"COALESCE({col}, '') LIKE %s")
                    params.append(normalized_like)

        if term_parts:
            clauses.append("(" + " OR ".join(term_parts) + ")")

    if not clauses:
        return "", []
    return "(" + " AND ".join(clauses) + ")", params

