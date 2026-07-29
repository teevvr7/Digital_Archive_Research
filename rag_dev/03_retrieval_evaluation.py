# %% [markdown]
# # Phase 3: Retrieval & Evaluation
# This interactive script tests vector search, keyword search, and hybrid search (RRF).
# We will evaluate retrieval performance across 150 ground-truth test questions using:
# 1. **Hit Rate@5**: Percentage of queries where the correct invoice is in top 5 results.
# 2. **MRR@5 (Mean Reciprocal Rank)**: Position metric measuring how early the correct invoice appears.

# %%
# Cell 1: Setup & Environment
import os
import json
import pandas as pd
from sentence_transformers import SentenceTransformer

from src import config
from src.db import get_db_connection
from src.search import vector_search, keyword_search, hybrid_search

# Load ground-truth CSV
GROUND_TRUTH_PATH = os.path.join("data", "ground_truth.csv")
if not os.path.exists(GROUND_TRUTH_PATH):
    raise FileNotFoundError(f"Missing '{GROUND_TRUTH_PATH}'. Run 01_foundations.py first!")

df_gt = pd.read_csv(GROUND_TRUTH_PATH)
print(f"Loaded {len(df_gt)} ground-truth questions for evaluation.")

# Load embedding model & DB connection
print("Loading embedding model 'all-MiniLM-L6-v2'...")
model = SentenceTransformer("all-MiniLM-L6-v2")
conn = get_db_connection()
print("Model and database connection ready.")

# %% [markdown]
# ## Step 3.1: Single Query Inspection
# Test a single query to see vector, keyword, and hybrid search outputs side-by-side.

# %%
# Cell 2: Single Query Test
sample_row = df_gt.iloc[0]
query = sample_row["question"]
target_id = sample_row["source_invoice_id"]

print(f"Query:  '{query}'")
print(f"Target: '{target_id}'\n")

print("--- Vector Search Results (Top 3) ---")
v_results = vector_search(query, model, conn, top_k=3)
for r in v_results:
    print(f"ID: {r['invoice_id']} | Sim: {r['similarity']:.4f}")

print("\n--- Hybrid (RRF) Search Results (Top 3) ---")
h_results = hybrid_search(query, model, conn, top_k=3)
for r in h_results:
    print(f"ID: {r['invoice_id']} | Score: {r['similarity']:.4f}")

# %% [markdown]
# ## Step 3.2: Retrieval Benchmark (Hit Rate@5 & MRR@5)
# Now we evaluate all ground-truth queries to measure exact performance metrics.

# %%
# Cell 3: Run Full Benchmark
def evaluate_retrieval(search_fn, search_name: str, top_k: int = 5):
    hits = 0
    mrr_total = 0.0
    total_eval = 0

    for idx, row in df_gt.iterrows():
        target_id = row["source_invoice_id"]
        # Skip multi-document count aggregations for single-doc retrieval check
        if target_id == "multiple" or pd.isna(target_id):
            continue
            
        total_eval += 1
        query = row["question"]
        
        # Call search function
        if search_fn == keyword_search:
            results = search_fn(query, conn, top_k=top_k)
        else:
            results = search_fn(query, model, conn, top_k=top_k)
            
        retrieved_ids = [r["invoice_id"] for r in results]

        # Calculate Hit Rate & MRR
        if target_id in retrieved_ids:
            hits += 1
            rank = retrieved_ids.index(target_id) + 1
            mrr_total += 1.0 / rank

    hit_rate = (hits / total_eval) * 100 if total_eval > 0 else 0
    mrr = (mrr_total / total_eval) if total_eval > 0 else 0

    return {
        "Algorithm": search_name,
        "Total Queries": total_eval,
        "Hits": hits,
        "Hit Rate @ 5 (%)": round(hit_rate, 2),
        "MRR @ 5": round(mrr, 4)
    }

print("Running Retrieval Benchmark across algorithms...")
vec_metrics = evaluate_retrieval(vector_search, "Vector Search (Cosine)")
key_metrics = evaluate_retrieval(keyword_search, "Keyword Search (FTS)")
hyb_metrics = evaluate_retrieval(hybrid_search, "Hybrid Search (RRF)")

df_results = pd.DataFrame([vec_metrics, key_metrics, hyb_metrics])
print("\n=== RETRIEVAL EVALUATION RESULTS ===")
print(df_results.to_string(index=False))

# Close DB connection
conn.close()
