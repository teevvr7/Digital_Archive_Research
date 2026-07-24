import os
from dotenv import load_dotenv
from openai import OpenAI

# Load from .env file if it exists
load_dotenv()

LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1")
LLM_API_KEY = os.getenv("LLM_API_KEY", "none")
LLM_MODEL = os.getenv("LLM_MODEL", "openai/gpt-oss-20b")

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/invoice_insight")

def get_llm_client() -> OpenAI:
    """Return an OpenAI client configured for the specified API endpoint."""
    return OpenAI(
        base_url=LLM_BASE_URL,
        api_key=LLM_API_KEY if LLM_API_KEY != "none" else "placeholder"
    )
