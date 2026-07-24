# Daily Progress Report — 15 July 2026

## Overview
Organized the dedicated RAG development workspace (`rag_dev/`) and implemented **Phase 1: Foundations** of the sandbox. Built the configuration scaffolding, raw database connection layer, synthetic data generation pipeline (invoices + ground-truth Q&A), and containerized PostgreSQL database configurations with native pgvector and full-text search indexing.

---

## 1. Project Scaffolding & Environment Setup
* **Workspace Setup**: Moved the RAG development roadmap to the new `rag_dev/` directory for consolidated sandbox development and testing.
* **Scaffold Layout**: Created directory directories (`app/`, `data/`, `notebooks/`) and stubbed modules with docstrings for serialisation, ingestion, retrieval, and LLM generation.
* **Dependency Pinned requirements**: Pinned requirements versions (Streamlit, Faker, psycopg2, openai, sentence-transformers, python-dotenv) inside `requirements.txt` for clean installations.
* **Environment Configuration**: Created `.env` and `app/config.py` loading database URLs, model keys, and base URLs.

---

## 2. Invoices & Ground-Truth Dataset Generator
* **Invoice Generator (`generate_invoices.py`)**: Built a customizable Faker script with deterministic seed configurations. Generates 200 invoices varying vendors, buyer details, dates, items, quantities, prices, tax rates, currencies, and payment terms, saving output to `data/invoices.json`.
* **Ground-Truth Generator (`generate_ground_truth.py`)**: Built a Q&A script to parse generated invoices and construct 150 diverse Q&A test cases (vendor lookup, subtotal/total query, billing dates, line items, and multi-document count aggregations) into `data/ground_truth.csv`.

---

## 3. PostgreSQL pgvector & Full-Text Search Schema
* **Initialization Schema (`init.sql`)**: Defined database tables, enabling the `vector(384)` extension for SentenceTransformer embeddings. Included:
  * *HNSW Vector Index*: Fast cosine-distance matching.
  * *Postgres Full-Text Search*: GIN-indexed `tsvector` generated column (`search_tsv`) for keyword matching.
  * *Feedback Persistence*: Logging user ratings, query details, relevance scores, and latency.
* **Orchestration Configuration (`docker-compose.yml`)**: Configured a lightweight pgvector Postgres database service container mapping data volumes and initializing tables on startup.

---

## 4. Next Session Plans
* Implement Phase 2 parser to serialize invoice JSON objects into Markdown and verify outputs.
* Write and run the embedding ingestion task to populate PostgreSQL tables.
