"""Text-to-SQL execution engine for structured queries over invoice_chunks.content_json."""

import json
import re
from src.config import get_llm_client, LLM_MODEL

SQL_SYSTEM_PROMPT = """You are an expert PostgreSQL data analyst.
You have a table `invoice_chunks` with a JSONB column `content_json` containing invoice data.

Column schema of `invoice_chunks`:
- invoice_id (TEXT): Unique invoice code (e.g. 'INV-2026-0145')
- content_json (JSONB): Structured JSON object with keys:
  - invoice_id (text)
  - vendor (text)
  - date (text, format YYYY-MM-DD)
  - buyer (text)
  - buyer_address (text)
  - subtotal (numeric)
  - tax_rate (text)
  - tax (numeric)
  - grand_total (numeric)
  - currency (text, e.g. 'MYR', 'USD', 'SGD')
  - payment_terms (text)
  - line_items (array of objects with keys: description, qty, unit_price, amount)

Common SQL patterns for JSONB:
1. Exact ID match:
   SELECT content_json FROM invoice_chunks WHERE content_json->>'invoice_id' = 'INV-2026-0145';
2. Vendor filter:
   SELECT content_json FROM invoice_chunks WHERE content_json->>'vendor' ILIKE '%Summit Hardware%';
3. Date range filter:
   SELECT content_json FROM invoice_chunks WHERE (content_json->>'date')::date BETWEEN '2026-03-01' AND '2026-03-31';
4. Line item search / unnesting:
   SELECT content_json->>'invoice_id' as invoice_id, item->>'description' as item_desc, (item->>'qty')::int as qty, (item->>'unit_price')::numeric as unit_price
   FROM invoice_chunks, jsonb_array_elements(content_json->'line_items') AS item
   WHERE item->>'description' ILIKE '%Laptop%';

Write ONLY a valid, read-only PostgreSQL SELECT query. Do NOT include markdown code blocks, explanation, or extra text."""

def generate_sql(query: str, client=None) -> str:
    """Generate PostgreSQL query from natural language question using LLM."""
    if client is None:
        client = get_llm_client()

    response = client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": SQL_SYSTEM_PROMPT},
            {"role": "user", "content": f"Write a SQL query to answer: {query}"}
        ],
        temperature=0,
        max_tokens=300
    )
    
    raw_sql = response.choices[0].message.content.strip()
    
    # Clean code fences if LLM included markdown
    cleaned_sql = re.sub(r'^```(?:sql)?\s*', '', raw_sql, flags=re.IGNORECASE)
    cleaned_sql = re.sub(r'\s*```$', '', cleaned_sql).strip()
    return cleaned_sql

def text_to_sql_answer(query: str, db_conn, client=None) -> dict:
    """Execute Text-to-SQL workflow: Question → SQL → Execution → Natural Language Answer."""
    if client is None:
        client = get_llm_client()

    # Fast-path optimization: Exact invoice ID lookup via direct SQL (no LLM SQL generation needed)
    id_match = re.search(r'INV-\d{4}-\d{4}', query, re.IGNORECASE)
    if id_match:
        target_id = id_match.group(0).upper()
        sql_query = f"SELECT content_json FROM invoice_chunks WHERE content_json->>'invoice_id' = '{target_id}';"
    else:
        try:
            sql_query = generate_sql(query, client)
        except Exception as e:
            return {
                "answer": f"Error generating SQL query: {str(e)}",
                "sql": None,
                "data": None,
                "method": "sql"
            }

    # Execute SQL
    cursor = db_conn.cursor()
    try:
        cursor.execute(sql_query)
        rows = cursor.fetchall()
        cursor.close()
    except Exception as e:
        cursor.close()
        try:
            db_conn.rollback()
        except Exception:
            pass
            
        # Fallback to direct ID match if generated SQL errored but an ID was present
        if id_match:
            target_id = id_match.group(0).upper()
            sql_query = f"SELECT content_json FROM invoice_chunks WHERE content_json->>'invoice_id' = '{target_id}';"
            cursor = db_conn.cursor()
            try:
                cursor.execute(sql_query)
                rows = cursor.fetchall()
                cursor.close()
            except Exception as e_sub:
                cursor.close()
                try:
                    db_conn.rollback()
                except Exception:
                    pass
                return {
                    "answer": f"SQL execution error: {str(e_sub)}",
                    "sql": sql_query,
                    "data": None,
                    "method": "sql"
                }
        else:
            return {
                "answer": f"SQL execution error: {str(e)}",
                "sql": sql_query,
                "data": None,
                "method": "sql"
            }

    if not rows:
        return {
            "answer": "No records found matching your query criteria.",
            "sql": sql_query,
            "data": [],
            "method": "sql"
        }

    # Format result using LLM
    try:
        # Convert DB rows to JSON-serializable list
        results_data = []
        for r in rows:
            if isinstance(r, dict):
                results_data.append(r)
            elif len(r) == 1 and isinstance(r[0], (dict, list)):
                results_data.append(r[0])
            else:
                results_data.append(list(r))

        data_str = json.dumps(results_data[:10], indent=2)  # Cap payload size for safety

        resp = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": "You are a financial assistant. Synthesize a concise, direct natural language answer using the query execution data."},
                {"role": "user", "content": f"User Question: {query}\n\nSQL Data Result:\n{data_str}"}
            ],
            temperature=0,
            max_tokens=300
        )
        answer = resp.choices[0].message.content.strip()
    except Exception as e:
        # Fallback formatting if LLM call fails
        answer = f"Found {len(rows)} matching record(s). Result: {results_data}"

    return {
        "answer": answer,
        "sql": sql_query,
        "data": results_data,
        "method": "sql"
    }
