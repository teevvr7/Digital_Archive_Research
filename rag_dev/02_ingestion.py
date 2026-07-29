# %% [markdown]
# # Phase 2: Ingestion & Embeddings
# This interactive script runs the ingestion pipeline to:
# 1. Load the generated 200 synthetic invoices from `data/invoices.json`.
# 2. Compute 384-dimensional vector embeddings using the `all-MiniLM-L6-v2` SentenceTransformer.
# 3. Store the markdown text, raw JSON, and vector arrays inside PostgreSQL.
# 4. Verify that data is correctly loaded and indexed.

# %%
# Cell 1: Load Data and Verify DB Connection
import os
import json
import pandas as pd

from src import config
from src.db import get_db_connection
from src.ingest import ingest_invoices

# Setup paths
DATA_DIR = "data"
INVOICES_JSON_PATH = os.path.join(DATA_DIR, "invoices.json")

if not os.path.exists(INVOICES_JSON_PATH):
    raise FileNotFoundError(f"Missing invoice data at '{INVOICES_JSON_PATH}'. Run 01_foundations.py first!")

with open(INVOICES_JSON_PATH, "r") as f:
    invoices = json.load(f)

print(f"Loaded {len(invoices)} invoices from local disk.")

# Quick connection verification
conn = get_db_connection()
conn.close()
print("Database connection verified successfully. Ready for ingestion.")

# %% [markdown]
# ## Step 2.2: Execute Ingestion
# We will now pass our dataset through the ingestion processor. 
# This cell loads the embedding model locally, vectorizes each invoice's Markdown representation, and upserts it into the `invoice_chunks` table.

# %%
# Cell 2: Run Ingestion
conn = get_db_connection()
try:
    ingest_invoices(invoices, conn, model_name="all-MiniLM-L6-v2")
finally:
    conn.close()

# %% [markdown]
# ## Step 2.3: Verify Ingested Vector Records
# Let's query the database to verify the stored data and check the dimensions of the saved embeddings.

# %%
# Cell 3: Verify Ingested Records
conn = get_db_connection()
cursor = conn.cursor()

# 1. Get total record count
cursor.execute("SELECT COUNT(*) FROM invoice_chunks;")
count = cursor.fetchone()
record_count = list(count.values())[0] if isinstance(count, dict) else count[0]
print(f"Total records in invoice_chunks: {record_count}")

# 2. Retrieve a sample record to check vector structure
cursor.execute("""
    SELECT invoice_id, content_text, 
           pg_typeof(embedding) as vector_type,
           vector_dims(embedding) as dimensions,
           left(embedding::text, 100) as vector_slice
    FROM invoice_chunks 
    LIMIT 1;
""")
sample = cursor.fetchone()

if sample:
    print("\n--- Ingested Vector Record Sample ---")
    for key, val in sample.items() if isinstance(sample, dict) else enumerate(sample):
        print(f"{key}: {val}")
else:
    print("No records found. Ingestion may have failed.")

conn.close()
