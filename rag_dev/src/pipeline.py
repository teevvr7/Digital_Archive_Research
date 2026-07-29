"""Unified Pipeline: Router → (Text-to-SQL Path | RAG Path) → Formatted Answer."""

from src.router import classify_query
from src.sql_engine import text_to_sql_answer
from src.rag import rag_answer
from src.config import get_llm_client

def answer_query(query: str, model, db_conn, client=None, force_method: str = None) -> dict:
    """Execute complete unified pipeline.
    
    Args:
        query: User natural language question.
        model: SentenceTransformer embedding model instance.
        db_conn: PostgreSQL connection.
        client: Optional OpenAI client instance.
        force_method: 'sql' or 'rag' to override automatic router classification (useful for benchmarks).
        
    Returns:
        Dict containing answer, classification method, and context/SQL details.
    """
    if client is None:
        client = get_llm_client()

    method = force_method if force_method else classify_query(query)

    if method == "sql":
        result = text_to_sql_answer(query, db_conn, client=client)
    else:
        result = rag_answer(query, model, db_conn, top_k=5, client=client)

    result["query"] = query
    return result
