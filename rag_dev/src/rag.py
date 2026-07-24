"""RAG pipeline: context retrieval, query rewriting, and LLM answer generation."""

from src.config import get_llm_client, LLM_MODEL
from src.search import hybrid_search

PROMPT_VARIANTS = {
    "concise": (
        "You are InvoiceInsight, an expert financial assistant.\n"
        "Answer the user's question concisely using ONLY the provided invoice context.\n"
        "If the information is not present in the context, say 'I could not find this in the available invoices.'\n"
        "Always cite the invoice ID in your response."
    ),
    "detailed": (
        "You are InvoiceInsight, an expert financial assistant.\n"
        "Provide a detailed breakdown answering the user's question based strictly on the retrieved invoice context.\n"
        "Include exact currency, amounts, unit prices, dates, and vendor details wherever applicable.\n"
        "Cite the invoice ID prominently."
    ),
    "structured": (
        "You are InvoiceInsight, an expert financial assistant.\n"
        "Answer in the following structured format:\n"
        "ANSWER: <Direct short answer>\n"
        "SOURCE: <Invoice ID>\n"
        "CONFIDENCE: <High/Medium/Low>"
    )
}

def rewrite_query(original_query: str, client=None) -> str:
    """Rewrite query to improve semantic search clarity (Bonus feature)."""
    if client is None:
        client = get_llm_client()
    try:
        resp = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": "Rewrite the user query to be concise, clear, and focused on invoice attributes for document search."},
                {"role": "user", "content": f"Original query: {original_query}\nRewritten query:"}
            ],
            temperature=0,
            max_tokens=100
        )
        return resp.choices[0].message.content.strip()
    except Exception:
        return original_query

def generate_answer(query: str, retrieved_chunks: list[dict], client=None, prompt_variant: str = "concise") -> str:
    """Send retrieved context and user query to LLM endpoint."""
    if client is None:
        client = get_llm_client()

    context_blocks = [f"--- Document {i+1} ---\n{chunk['content_text']}" for i, chunk in enumerate(retrieved_chunks)]
    context_str = "\n\n".join(context_blocks)
    
    system_prompt = PROMPT_VARIANTS.get(prompt_variant, PROMPT_VARIANTS["concise"])

    response = client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Invoice Context:\n{context_str}\n\nQuestion: {query}"}
        ],
        temperature=0,
        max_tokens=400
    )
    return response.choices[0].message.content.strip()

def rag_answer(query: str, model, db_conn, top_k: int = 5, client=None, prompt_variant: str = "concise", use_rewriting: bool = False) -> dict:
    """Execute complete RAG flow: [Optional Rewrite] → Retrieve Context → Generate LLM Answer."""
    search_query = rewrite_query(query, client) if use_rewriting else query
    chunks = hybrid_search(search_query, model, db_conn, top_k=top_k)
    
    if not chunks:
        return {
            "answer": "I could not find any relevant invoices in the database.",
            "retrieved_chunks": [],
            "method": "rag"
        }

    try:
        answer = generate_answer(query, chunks, client=client, prompt_variant=prompt_variant)
    except Exception as e:
        answer = f"Error generating answer from LLM: {str(e)}"

    return {
        "answer": answer,
        "retrieved_chunks": chunks,
        "method": "rag"
    }
