"""Retrieval logic: includes Vector, Keyword (FTS), and Hybrid (RRF) search capabilities."""

import json

def vector_search(query: str, model, db_conn, top_k: int = 5) -> list[dict]:
    """Retrieve top_k documents using Cosine Similarity on embeddings.
    
    In pgvector, `<=>` calculates cosine distance. 
    Similarity score = 1 - Cosine Distance.
    """
    q_vec = model.encode(query).tolist()
    cursor = db_conn.cursor()
    
    cursor.execute("""
        SELECT invoice_id, content_text, content_json,
               1 - (embedding <=> %s::vector) AS similarity
        FROM invoice_chunks
        ORDER BY embedding <=> %s::vector
        LIMIT %s;
    """, (q_vec, q_vec, top_k))
    
    rows = cursor.fetchall()
    cursor.close()
    
    results = []
    for row in rows:
        if isinstance(row, dict):
            results.append(row)
        else:
            results.append({
                "invoice_id": row[0],
                "content_text": row[1],
                "content_json": row[2],
                "similarity": float(row[3])
            })
    return results

def keyword_search(query: str, db_conn, top_k: int = 5) -> list[dict]:
    """Retrieve top_k documents using PostgreSQL Full-Text Search (FTS).
    
    Uses `plainto_tsquery` against the GIN-indexed `search_tsv` column.
    """
    cursor = db_conn.cursor()
    
    cursor.execute("""
        SELECT invoice_id, content_text, content_json,
               ts_rank(search_tsv, plainto_tsquery('english', %s)) AS rank_score
        FROM invoice_chunks
        WHERE search_tsv @@ plainto_tsquery('english', %s)
        ORDER BY rank_score DESC
        LIMIT %s;
    """, (query, query, top_k))
    
    rows = cursor.fetchall()
    cursor.close()
    
    results = []
    for row in rows:
        if isinstance(row, dict):
            results.append(row)
        else:
            results.append({
                "invoice_id": row[0],
                "content_text": row[1],
                "content_json": row[2],
                "similarity": float(row[3])
            })
    return results

def hybrid_search(query: str, model, db_conn, top_k: int = 5, k: int = 60, keyword_weight: float = 2.5) -> list[dict]:
    """Retrieve top_k documents using Weighted Reciprocal Rank Fusion (RRF) on Vector + FTS results.
    
    RRF Score = (1.0 / (k + rank_vector)) + (keyword_weight / (k + rank_keyword)).
    Weighted RRF prevents noisy vector candidates from diluting exact keyword matches.
    """
    # Fetch candidate lists from vector and keyword search
    vector_results = vector_search(query, model, db_conn, top_k=20)
    keyword_results = keyword_search(query, db_conn, top_k=20)
    
    rrf_scores = {}  # invoice_id -> {score, doc}
    
    # 1. Score vector ranks (weight = 1.0)
    for rank, doc in enumerate(vector_results, 1):
        inv_id = doc["invoice_id"]
        rrf_scores[inv_id] = {
            "score": 1.0 / (k + rank),
            "doc": doc
        }
        
    # 2. Score keyword ranks and combine (weight = 2.5)
    for rank, doc in enumerate(keyword_results, 1):
        inv_id = doc["invoice_id"]
        if inv_id in rrf_scores:
            rrf_scores[inv_id]["score"] += keyword_weight / (k + rank)
        else:
            rrf_scores[inv_id] = {
                "score": keyword_weight / (k + rank),
                "doc": doc
            }
            
    # Sort candidates by combined RRF score
    sorted_candidates = sorted(rrf_scores.values(), key=lambda x: x["score"], reverse=True)
    
    final_results = []
    for item in sorted_candidates[:top_k]:
        doc = item["doc"].copy()
        doc["similarity"] = round(item["score"], 4)  # Store RRF score in similarity field
        final_results.append(doc)
        
    return final_results
