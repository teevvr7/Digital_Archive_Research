"""Query intent router: classifies incoming user queries as 'sql' or 'rag'."""

import re

def classify_query(query: str) -> str:
    """Classify query intent using deterministic rule matching.
    
    Returns:
        'sql': Query requires structured SQL (exact ID lookup, aggregation, date range, vendor filtering).
        'rag': Query is fuzzy, semantic, or unstructured contextual search.
    """
    q = query.strip().lower()

    # Rule 1: Explicit Invoice ID pattern (e.g., INV-2026-0145)
    if re.search(r'INV-\d{4}-\d{4}', query, re.IGNORECASE):
        return "sql"

    # Rule 2: Aggregation & mathematical operations
    aggregation_keywords = [
        "total", "sum", "how many", "count", "average", "avg",
        "highest", "lowest", "most", "least", "subtotal", "grand total",
        "unit price", "unit cost", "quantity", "qty", "amount spent",
        "total spent", "total sales", "total number"
    ]
    if any(kw in q for kw in aggregation_keywords):
        return "sql"

    # Rule 3: Structured lookup / specific attribute queries
    lookup_keywords = [
        "billing date", "issue date", "date of invoice", "payment terms",
        "vendor issued", "which vendor", "who issued"
    ]
    if any(kw in q for kw in lookup_keywords):
        return "sql"

    # Rule 4: Temporal / date range filtering
    date_keywords = [
        "last month", "this month", "between", "in 2025", "in 2026", "in 2027",
        "january", "february", "march", "april", "may", "june", "july",
        "august", "september", "october", "november", "december"
    ]
    if any(kw in q for kw in date_keywords):
        return "sql"

    # Rule 5: Structured list / vendor filtering
    filter_keywords = ["all invoices from", "invoices issued by", "from vendor", "list all"]
    if any(kw in q for kw in filter_keywords):
        return "sql"

    # Default fallback: Fuzzy semantic RAG search
    return "rag"
