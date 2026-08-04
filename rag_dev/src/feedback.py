"""Feedback and monitoring logger for InvoiceInsight RAG sandbox."""

import pandas as pd

def ensure_feedback_table(conn):
    """Ensure the feedback table exists with all required columns."""
    cursor = conn.cursor()
    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS feedback (
                id SERIAL PRIMARY KEY,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                method TEXT NOT NULL DEFAULT 'rag',
                retrieved_ids TEXT[],
                relevance_score REAL,
                response_time_ms INT,
                user_rating INT,
                created_at TIMESTAMP DEFAULT NOW()
            );
        """)
        conn.commit()
        cursor.close()
    except Exception as e:
        cursor.close()
        try:
            conn.rollback()
        except Exception:
            pass

def log_feedback(conn, question: str, answer: str, method: str, retrieved_ids: list, response_time_ms: int, user_rating: int):
    """Insert user feedback (+1 or -1) and performance metrics into the feedback table."""
    ensure_feedback_table(conn)
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO feedback (question, answer, method, retrieved_ids, response_time_ms, user_rating)
            VALUES (%s, %s, %s, %s, %s, %s);
        """, (question, answer, method, retrieved_ids, response_time_ms, user_rating))
        conn.commit()
        cursor.close()
    except Exception as e:
        cursor.close()
        try:
            conn.rollback()
        except Exception:
            pass

def fetch_feedback_data(conn) -> pd.DataFrame:
    """Fetch all feedback records for dashboard reporting."""
    ensure_feedback_table(conn)
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT id, question, answer, method, retrieved_ids, response_time_ms, user_rating, created_at
            FROM feedback
            ORDER BY created_at DESC;
        """)
        rows = cursor.fetchall()
        cursor.close()
    except Exception as e:
        cursor.close()
        try:
            conn.rollback()
        except Exception:
            pass
        return pd.DataFrame(columns=["id", "question", "answer", "method", "retrieved_ids", "response_time_ms", "user_rating", "created_at"])
    
    if not rows:
        return pd.DataFrame(columns=["id", "question", "answer", "method", "retrieved_ids", "response_time_ms", "user_rating", "created_at"])
    
    data = []
    for r in rows:
        if isinstance(r, dict):
            data.append(r)
        else:
            data.append({
                "id": r[0],
                "question": r[1],
                "answer": r[2],
                "method": r[3],
                "retrieved_ids": r[4],
                "response_time_ms": r[5],
                "user_rating": r[6],
                "created_at": r[7]
            })
    return pd.DataFrame(data)

