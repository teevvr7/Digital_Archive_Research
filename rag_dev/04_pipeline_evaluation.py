# %% [markdown]
# # Phase 4: Unified Router & Pipeline Evaluation (Fix A + Fix B)
# This interactive notebook/script evaluates the Phase 4 hybrid architecture across both structured and fuzzy RAG queries:
# - **Step 4.1**: Setup and Environment Initialization
# - **Step 4.2**: Query Router Test (Small-scale inspection on sample queries)
# - **Step 4.3**: Query Router Audit (Classification breakdown across SQL and RAG queries)
# - **Step 4.4**: Single Query Walkthrough (Detailed inspection of SQL path vs RAG path)
# - **Step 4.5**: Unified Pipeline Benchmark (Hit Rate@5 and MRR@5 across full dataset)
# - **Step 4.6**: Architecture Comparison Benchmark (Pure RAG vs Pure SQL vs Routed Pipeline side-by-side)

# %%
# Cell 1: Setup & Environment
import os
import pandas as pd
from sentence_transformers import SentenceTransformer

from src import config
from src.db import get_db_connection
from src.router import classify_query
from src.sql_engine import text_to_sql_answer
from src.rag import rag_answer
from src.pipeline import answer_query

# Re-generate ground truth if needed to ensure fuzzy RAG questions exist
from data.generate_ground_truth import main as generate_gt
generate_gt()

# Load ground-truth dataset
GROUND_TRUTH_PATH = os.path.join("data", "ground_truth.csv")
df_gt = pd.read_csv(GROUND_TRUTH_PATH)
print(f"✅ Loaded {len(df_gt)} ground-truth questions for evaluation.")

# Initialize embedding model and DB connection
print("Loading embedding model 'all-MiniLM-L6-v2'...")
model = SentenceTransformer("all-MiniLM-L6-v2")
conn = get_db_connection()
print("✅ Database connection and embedding model ready.")

# %% [markdown]
# ## Step 4.2: Query Router Test (Small Scale Inspection)
# Test `classify_query()` incrementally on representative sample questions.

# %%
# Cell 2: Small Scale Router Test
test_queries = [
    "What is the billing date for invoice INV-2026-0145?",
    "What was the total amount spent on Laptops last month?",
    "Show me all invoices from Summit Hardware",
    "Find the invoice document where we purchased Laptop.",
    "I remember placing an order with PrintPro Solutions, can you locate the matching invoice record?"
]

print("--- Small-Scale Query Classification Test ---")
for q in test_queries:
    method = classify_query(q)
    print(f"Query  : '{q}'")
    print(f"Routed : [{method.upper()}]\n")

# %% [markdown]
# ## Step 4.3: Query Router Audit Across Dataset
# Run the router on all ground-truth questions and audit classification distribution across question types.

# %%
# Cell 3: Full Router Audit
df_gt["routed_method"] = df_gt["question"].apply(classify_query)

sql_count = (df_gt["routed_method"] == "sql").sum()
rag_count = (df_gt["routed_method"] == "rag").sum()

print("=== ROUTER CLASSIFICATION AUDIT ===")
print(f"Total Questions        : {len(df_gt)}")
print(f"Routed to SQL Path     : {sql_count} ({sql_count/len(df_gt)*100:.1f}%)")
print(f"Routed to RAG Path     : {rag_count} ({rag_count/len(df_gt)*100:.1f}%)\n")

print("--- Classification Breakdown by Question Type ---")
type_breakdown = df_gt.groupby(["question_type", "routed_method"]).size().unstack(fill_value=0)
print(type_breakdown)

# %% [markdown]
# ## Step 4.4: Single Query Pipeline Walkthrough
# Inspect pipeline execution outputs for a SQL query and a fuzzy RAG query.

# %%
# Cell 4: Single Query Inspection
# 1. SQL Path Inspection
sql_sample = df_gt[df_gt["routed_method"] == "sql"].iloc[0]
print("--- SQL Path Walkthrough ---")
print(f"Question : {sql_sample['question']}")
print(f"Expected : {sql_sample['expected_answer']} (Invoice: {sql_sample['source_invoice_id']})")

sql_res = answer_query(sql_sample["question"], model, conn)
print(f"Method   : {sql_res['method'].upper()}")
print(f"SQL Query: {sql_res.get('sql')}")
print(f"Answer   : {sql_res.get('answer')}\n")

# 2. RAG Path Inspection
rag_samples = df_gt[df_gt["routed_method"] == "rag"]
if not rag_samples.empty:
    rag_sample = rag_samples.iloc[0]
    print("--- RAG Path Walkthrough ---")
    print(f"Question : {rag_sample['question']}")
    print(f"Expected : {rag_sample['source_invoice_id']}")

    rag_res = answer_query(rag_sample["question"], model, conn)
    print(f"Method   : {rag_res['method'].upper()}")
    top_hit = rag_res['retrieved_chunks'][0]['invoice_id'] if rag_res.get('retrieved_chunks') else 'None'
    print(f"Top Hit  : {top_hit}")
    print(f"Answer   : {rag_res.get('answer')}\n")

# %% [markdown]
# ## Step 4.5: Full Pipeline Benchmark
# Evaluate Hit Rate@5 and MRR@5 across all ground-truth queries using the unified pipeline.

# %%
# Cell 5: Unified Pipeline Benchmark
hits = 0
mrr_sum = 0.0

print("Running Unified Pipeline Retrieval Benchmark...")

for idx, row in df_gt.iterrows():
    q = row["question"]
    expected_id = row["source_invoice_id"]
    
    res = answer_query(q, model, conn)
    
    found = False
    rank = 0

    if res["method"] == "sql":
        data_str = str(res.get("data", "")) + str(res.get("sql", ""))
        if expected_id in data_str:
            found = True
            rank = 1
    else:
        chunks = res.get("retrieved_chunks") or []
        for r_idx, chunk in enumerate(chunks, 1):
            if chunk.get("invoice_id") == expected_id:
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
print(f"Hits                    : {hits}")
print(f"Hit Rate @ 5 (%)        : {hit_rate:.2f}%")
print(f"MRR @ 5                 : {mrr:.4f}\n")

# %% [markdown]
# ## Step 4.6: Fix A — Comparative Architecture Benchmark
# Side-by-side evaluation comparing Pure RAG, Pure SQL, and the Routed Pipeline across the same dataset.

# %%
# Cell 6: Side-by-Side Comparative Benchmark
def evaluate_mode(mode_name: str, force_method: str = None) -> dict:
    hits = 0
    mrr_sum = 0.0
    
    for idx, row in df_gt.iterrows():
        q = row["question"]
        expected_id = row["source_invoice_id"]
        
        res = answer_query(q, model, conn, force_method=force_method)
        
        found = False
        rank = 0
        if res["method"] == "sql":
            data_str = str(res.get("data", "")) + str(res.get("sql", ""))
            if expected_id in data_str:
                found = True
                rank = 1
        else:
            chunks = res.get("retrieved_chunks") or []
            for r_idx, chunk in enumerate(chunks, 1):
                if chunk.get("invoice_id") == expected_id:
                    found = True
                    rank = r_idx
                    break
                    
        if found:
            hits += 1
            mrr_sum += 1.0 / rank

    return {
        "Architecture Mode": mode_name,
        "Total Queries": len(df_gt),
        "Hits": hits,
        "Hit Rate @ 5 (%)": round((hits / len(df_gt)) * 100, 2),
        "MRR @ 5": round(mrr_sum / len(df_gt), 4)
    }

print("Running Side-by-Side Comparative Benchmark across Architecture Modes...")
rag_metrics = evaluate_mode("Pure RAG Mode", force_method="rag")
sql_metrics = evaluate_mode("Pure SQL Mode", force_method="sql")
routed_metrics = evaluate_mode("Routed Pipeline (Hybrid)", force_method=None)

df_comp = pd.DataFrame([rag_metrics, sql_metrics, routed_metrics])

print("\n=== ARCHITECTURE COMPARISON BENCHMARK ===")
print(df_comp.to_string(index=False))

# Close database connection
conn.close()
