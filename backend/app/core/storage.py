"""Supabase Storage adapter.

File bytes live ONLY in object storage. This module is the single place the
rest of the app interacts with storage — swap the implementation here to change
providers without touching any other module.
"""

# The official Supabase Python client — gives us `.storage` for file
# upload/download/delete/signed-URL operations.
from supabase import Client, create_client

from app.core.config import settings


def _client() -> Client:
    # A new client is created on every call rather than cached as a module
    # singleton — Supabase clients are cheap to construct and this keeps the
    # module stateless and simple. Uses the SERVICE ROLE key (full access),
    # since only the backend/worker ever calls this module, never the browser.
    return create_client(settings.supabase_url, settings.supabase_service_role_key)


def upload_file(storage_key: str, data: bytes, content_type: str) -> None:
    """Upload bytes to the documents bucket at ``storage_key``."""
    _client().storage.from_(settings.supabase_storage_bucket).upload(
        path=storage_key,  # where in the bucket to store it, e.g. "tenants/{id}/{sha256}"
        file=data,  # the raw file bytes
        file_options={"content-type": content_type, "upsert": "false"},  # never silently overwrite
    )


def create_signed_url(storage_key: str, expires_in: int = 300) -> str:
    """Return a short-lived signed URL for downloading a file (default 5 min)."""
    # A signed URL lets the BROWSER download the file directly from storage
    # (bypassing our API entirely) for a limited time — the API never has to
    # stream file bytes itself.
    result = (
        _client()
        .storage.from_(settings.supabase_storage_bucket)
        .create_signed_url(
            path=storage_key,
            expires_in=expires_in,  # how many seconds the URL stays valid
        )
    )
    return result["signedURL"]


def delete_file(storage_key: str) -> None:
    """Remove a file from object storage (used when emptying trash)."""
    # remove() takes a LIST of keys (supports batch deletes) — we always pass
    # a single-item list since this function deletes one file at a time.
    _client().storage.from_(settings.supabase_storage_bucket).remove([storage_key])


def download_file(storage_key: str) -> bytes:
    """Download a file's bytes (used by the worker to retrieve documents for parsing)."""
    # Only the worker calls this — it needs the actual bytes in memory to run
    # OCR/parsing on them, unlike the API which only ever hands out signed URLs.
    return _client().storage.from_(settings.supabase_storage_bucket).download(storage_key)
