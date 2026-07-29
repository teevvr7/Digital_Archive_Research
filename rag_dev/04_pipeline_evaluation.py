"""Phase 4 Evaluation: Unified Router + Pipeline Benchmark.

Measures Router classification distribution, Pipeline Hit Rate, and MRR.
"""

import os
import pandas as pd
import psycopg
from psycopg.rows import dict_row
from sentence_transformers import SentenceTransformer
from src.router import classify_query
from src.pipeline import answer_query
from src.config import DATABASE_URL

# Path configuration
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
GROUND_TRUTH_PATH = os.path.join(BASE_DIR, "data", "ground_truth.csv")

print("Loading dataset and model...")
df_gt = pd.read_csv(GROUND_TRUTH_PATH)
model = SentenceTransformer("all-MiniLM-L6-v2")
conn = psycopg.connect(DATABASE_URL, row_factory=dict_row)

print(f"Loaded {len(df_gt)} evaluation questions.")

# 1. Router Classification Audit
methods = df_gt['question'].apply(classify_query)
sql_count = (methods == 'sql').sum()
rag_count = (methods == 'rag').sum()

print("\n=== ROUTER CLASSIFICATION AUDIT ===")
print(f"Total Questions: {len(df_gt)}")
print(f"Routed to SQL Path: {sql_count} ({sql_count/len(df_gt)*100:.1f}%)")
print(f"Routed to RAG Path: {rag_count} ({rag_count/len(df_gt)*100:.1f}%)")

# 2. Pipeline Retrieval Benchmark
hits = 0
mrr_sum = 0.0

print("\nRunning Pipeline Evaluation...")

for idx, row in df_gt.iterrows():
    q = row['question']
    expected_id = row['source_invoice_id']
    
    # Run through unified pipeline (offline mock mode if no API key)
    # The pipeline executes routing and retrieval/SQL lookup
    res = answer_query(q, model, conn)
    
    found = False
    rank = 0

    if res['method'] == 'sql':
        # Check if expected_id is present in SQL query data or SQL string
        data = res.get('data') or []
        data_str = str(data) + str(res.get('sql', ''))
        if expected_id in data_str:
            found = True
            rank = 1
    else:
        # Check if expected_id is present in retrieved chunks
        chunks = res.get('retrieved_chunks') or []
        for r_idx, chunk in enumerate(chunks, 1):
            if chunk.get('invoice_id') == expected_id:
                found = True
                rank = r_idx
                break

    if found:
        hits += 1
        mrr_sum += 1.0 / rank

hit_rate = (hits / len(df_gt)) * 100
mrr = mrr_sum / len(df_gt)

print("\n=== UNIFIED PIPELINE EVALUATION RESULTS ===")
print(f"Total Queries Evaluated : {len(df_gt)}")
print(f"Successful Hits         : {hits}")
print(f"Hit Rate @ 5 (%)        : {hit_rate:.2f}%")
print(f"MRR @ 5                 : {mrr:.4f}")

conn.close()
