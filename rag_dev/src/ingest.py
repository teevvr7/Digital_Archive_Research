"""Ingestion logic: embeds serialised document chunks and stores them in the PostgreSQL database."""

import json
from sentence_transformers import SentenceTransformer
from src.serialise import json_to_markdown

def ingest_invoices(invoices: list[dict], db_conn, model_name: str = "all-MiniLM-L6-v2"):
    """Serialise, embed, and insert invoice JSON objects into database.
    
    Uses SentenceTransformer to compute 384-dimensional dense vectors from markdown text.
    Inserts records into the `invoice_chunks` table, updating on conflict.
    """
    print(f"Loading embedding model '{model_name}'...")
    model = SentenceTransformer(model_name)
    print("Embedding model loaded successfully.")

    cursor = db_conn.cursor()
    success_count = 0

    for idx, inv in enumerate(invoices, 1):
        invoice_id = inv.get("invoice_id")
        if not invoice_id:
            print(f"Warning: Skipping invoice index {idx} due to missing 'invoice_id'")
            continue

        # 1. Serialise JSON structured invoice into Markdown text
        text_content = json_to_markdown(inv, title=f"Invoice {invoice_id}")

        # 2. Compute 384-dimensional dense vector embeddings
        embedding_vector = model.encode(text_content).tolist()

        # 3. Insert/Upsert into pgvector database
        # ON CONFLICT updates the data so that any format/serialisation tweaks reflect immediately
        cursor.execute("""
            INSERT INTO invoice_chunks (invoice_id, content_text, content_json, embedding)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (invoice_id) 
            DO UPDATE SET 
                content_text = EXCLUDED.content_text,
                content_json = EXCLUDED.content_json,
                embedding = EXCLUDED.embedding;
        """, (invoice_id, text_content, json.dumps(inv), embedding_vector))
        
        success_count += 1
        if idx % 20 == 0 or idx == len(invoices):
            print(f"Embedded and stored {idx}/{len(invoices)} invoices...")

    db_conn.commit()
    cursor.close()
    print(f"Successfully ingested {success_count} invoices into the database.")
