# %% [markdown]
# # Phase 1: Foundations (Data Generation & Database Setup)
# This interactive script validates the Phase 1 setup of the RAG sandbox. We will:
# 1. Generate 200 synthetic invoices using Faker and custom item templates.
# 2. Extract 150 ground-truth Q&A pairs.
# 3. Verify our local PostgreSQL vector database connection.
# 4. Preview JSON-to-Markdown serialisation formatting.

# %%
# Cell 1: Environment Setup
# Import required packages and load configuration settings from local module.
import os
import json
import csv
import random
import pandas as pd
# pyrefly: ignore [missing-import]
from faker import Faker

from src import config
from src.db import get_db_connection

# Define data directory paths
DATA_DIR = "data"
INVOICES_JSON_PATH = os.path.join(DATA_DIR, "invoices.json")
GROUND_TRUTH_CSV_PATH = os.path.join(DATA_DIR, "ground_truth.csv")

print("--- Configurations Loaded ---")
print(f"Database URL: {config.DATABASE_URL}")
print(f"Model Name:   {config.LLM_MODEL}")
print(f"vLLM Base URL: {config.LLM_BASE_URL}")
print(f"Data Dir:     {DATA_DIR}")

# %% [markdown]
# ## Step 1.2: Invoices Data Generation
# We will define a list of vendors and products, and generate 200 realistic invoice records.

# %%
# Cell 2: Invoice Generator Configuration
fake = Faker()
random.seed(42)
Faker.seed(42)

VENDORS = [
    "TechCorp Sdn Bhd", "GlobalSupply Pte Ltd", "OfficeMart Trading",
    "PrintPro Solutions", "CloudNet Services", "FreshFood Distribution",
    "Apex Engineering", "BuildMart Materials", "Swift Logistics",
    "SecureGuard Systems", "Optima Consultants", "Pinnacle Designs",
    "Prime Catering", "Elite Cleaners", "Zenith Software",
    "Aero Industries", "Delta Energy", "Nexus Utilities",
    "Stellar Media", "Quantum Labs", "Summit Hardware"
]

PRODUCTS = [
    ("Laptop", 800, 2500), ("Monitor", 200, 800), ("Keyboard", 20, 80),
    ("Office Chair", 100, 500), ("Printer Ink", 15, 60), ("A4 Paper (Box)", 8, 25),
    ("Consulting Hour", 150, 300), ("Software License", 50, 400),
    ("Desk Organizer", 15, 45), ("Whiteboard", 40, 120), ("Extension Cord", 10, 30),
    ("Coffee Beans (Bag)", 25, 60), ("Cleaning Supplies Kit", 30, 90),
    ("First Aid Kit", 20, 50), ("Network Cable (10m)", 12, 35),
    ("Server Rack", 500, 1500), ("UPS Backup Unit", 120, 450)
]

def generate_invoice(idx: int) -> dict:
    vendor = random.choice(VENDORS)
    num_items = random.randint(1, 6)
    picked_products = random.sample(PRODUCTS, num_items)
    
    line_items = []
    for name, lo, hi in picked_products:
        qty = random.randint(1, 15)
        price = round(random.uniform(lo, hi), 2)
        line_items.append({
            "description": name,
            "qty": qty,
            "unit_price": price,
            "amount": round(qty * price, 2)
        })
        
    subtotal = round(sum(i["amount"] for i in line_items), 2)
    tax_rate = random.choice([0.06, 0.08, 0.10])
    tax = round(subtotal * tax_rate, 2)
    
    return {
        "invoice_id": f"INV-{2025 + idx // 100}-{idx:04d}",
        "vendor": vendor,
        "date": fake.date_between(start_date="-1y", end_date="today").isoformat(),
        "buyer": fake.company(),
        "buyer_address": fake.address().replace("\n", ", "),
        "line_items": line_items,
        "subtotal": subtotal,
        "tax_rate": f"{tax_rate*100:.0f}%",
        "tax": tax,
        "grand_total": round(subtotal + tax, 2),
        "currency": random.choice(["MYR", "USD", "SGD"]),
        "payment_terms": random.choice(["Net 30", "Net 60", "Due on Receipt"]),
    }

# Generate and save
os.makedirs(DATA_DIR, exist_ok=True)
invoices = [generate_invoice(i) for i in range(1, 201)]

with open(INVOICES_JSON_PATH, "w") as f:
    json.dump(invoices, f, indent=2)

print(f"Generated {len(invoices)} invoices saved to '{INVOICES_JSON_PATH}'")

# %% [markdown]
# ## Step 1.3: Ground-Truth Q&A Generation
# Next, we build questions and answers referencing the generated invoices to benchmark retrieval (Hit Rate, MRR) and generation quality.

# %%
# Cell 3: Ground-Truth Generator
vendor_invoice_counts = {}
for inv in invoices:
    v = inv["vendor"]
    vendor_invoice_counts[v] = vendor_invoice_counts.get(v, 0) + 1

qa_pairs = []

for inv in invoices:
    inv_id = inv["invoice_id"]
    vendor = inv["vendor"]
    total = f"{inv['currency']} {inv['grand_total']:.2f}"
    subtotal = f"{inv['currency']} {inv['subtotal']:.2f}"
    date = inv["date"]
    
    # 1. Vendor Lookup
    qa_pairs.append({
        "question": f"Which vendor issued invoice {inv_id}?",
        "expected_answer": vendor,
        "source_invoice_id": inv_id,
        "question_type": "vendor_lookup"
    })
    
    # 2. Total Lookup
    qa_pairs.append({
        "question": f"What is the grand total for invoice {inv_id}?",
        "expected_answer": total,
        "source_invoice_id": inv_id,
        "question_type": "total_lookup"
    })
    
    # 3. Subtotal Lookup
    qa_pairs.append({
        "question": f"What was the subtotal amount on invoice {inv_id}?",
        "expected_answer": subtotal,
        "source_invoice_id": inv_id,
        "question_type": "subtotal_lookup"
    })

    # 4. Date Lookup
    qa_pairs.append({
        "question": f"What is the billing date for invoice {inv_id}?",
        "expected_answer": date,
        "source_invoice_id": inv_id,
        "question_type": "date_lookup"
    })

    # 5. Line Item Details
    items = inv["line_items"]
    if items:
        item = random.choice(items)
        desc = item["description"]
        qty = str(item["qty"])
        uprice = f"{inv['currency']} {item['unit_price']:.2f}"
        
        qa_pairs.append({
            "question": f"How many {desc} items were purchased in invoice {inv_id}?",
            "expected_answer": qty,
            "source_invoice_id": inv_id,
            "question_type": "line_item_qty"
        })
        
        qa_pairs.append({
            "question": f"What was the unit price of {desc} on invoice {inv_id}?",
            "expected_answer": uprice,
            "source_invoice_id": inv_id,
            "question_type": "line_item_price"
        })
        
# Add aggregation queries
for v in list(vendor_invoice_counts.keys())[:10]:
    count = str(vendor_invoice_counts[v])
    qa_pairs.append({
        "question": f"How many invoices are in the database from {v}?",
        "expected_answer": count,
        "source_invoice_id": "multiple",
        "question_type": "count_aggregation"
    })

# Shuffle and slice to 150
random.shuffle(qa_pairs)
qa_selected = qa_pairs[:150]

# Save to CSV
with open(GROUND_TRUTH_CSV_PATH, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=["question", "expected_answer", "source_invoice_id", "question_type"])
    writer.writeheader()
    writer.writerows(qa_selected)

print(f"Generated {len(qa_selected)} ground-truth rows saved to '{GROUND_TRUTH_CSV_PATH}'")

# %% [markdown]
# ## Step 1.4: Verify Outputs & Database Connection
# Print sample outputs and verify Postgres pgvector connection.

# %%
# Cell 4: View Data Samples
print("--- Invoice Sample (First Row) ---")
print(json.dumps(invoices[0], indent=2))
print("\n--- Ground-Truth Q&A Sample ---")
df_gt = pd.read_csv(GROUND_TRUTH_CSV_PATH)
print(df_gt.head(3))

# %%
# Cell 5: Test Database Connection
# Make sure your database container is running (docker-compose up -d) before executing this cell.
try:
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT version();")
    row = cur.fetchone()
    db_version = list(row.values())[0] if isinstance(row, dict) else row[0]
    print(f"Connected successfully to PostgreSQL: {db_version}")
    
    # Check if vector extension is enabled
    cur.execute("SELECT extname FROM pg_extension WHERE extname = 'vector';")
    ext_row = cur.fetchone()
    ext_name = ext_row.get("extname") if isinstance(ext_row, dict) else (ext_row[0] if ext_row else None)
    if ext_name == 'vector':
        print("pgvector extension verified: Enabled (OK)")
    else:
        print("pgvector extension is NOT installed/enabled. Check init.sql execution.")
        
    conn.close()
except Exception as e:
    import traceback
    print(f"Database Connection Failed: {e}")
    traceback.print_exc()
    print("Ensure you started the database with 'docker-compose up -d' in the rag_dev folder.")

# %% [markdown]
# ## Step 1.5: Preview Serialisation Formats (RAG Data Prep)
# To prepare our database records for text embeddings in Phase 2, we must serialise the structured JSON invoices into a text format.
# Let's inspect the two serialisation options:
# 1. **Markdown Format** (generic recursive markdown parser)
# 2. **Plain Text Format** (flat key-value strings)

# %%
# Cell 6: Preview Markdown vs Plain Text Serialisation
from src.serialise import json_to_markdown, json_to_text

sample_invoice = invoices[0]

print("=== OPTION 1: Serialised to Markdown (Recommended) ===")
markdown_out = json_to_markdown(sample_invoice, title=f"Invoice {sample_invoice['invoice_id']}")
print(markdown_out)

print("\n" + "="*50 + "\n")

print("=== OPTION 2: Serialised to Flat Plain Text ===")
text_out = json_to_text(sample_invoice)
print(text_out)
