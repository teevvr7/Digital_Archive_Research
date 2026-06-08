"""Supabase Storage adapter.

File bytes live ONLY in object storage. This module is the single place the
rest of the app interacts with storage — swap the implementation here to change
providers without touching any other module.
"""

from supabase import Client, create_client

from app.core.config import settings


def _client() -> Client:
    return create_client(settings.supabase_url, settings.supabase_service_role_key)


def upload_file(storage_key: str, data: bytes, content_type: str) -> None:
    """Upload bytes to the documents bucket at ``storage_key``."""
    _client().storage.from_(settings.supabase_storage_bucket).upload(
        path=storage_key,
        file=data,
        file_options={"content-type": content_type, "upsert": "false"},
    )


def create_signed_url(storage_key: str, expires_in: int = 300) -> str:
    """Return a short-lived signed URL for downloading a file (default 5 min)."""
    result = _client().storage.from_(settings.supabase_storage_bucket).create_signed_url(
        path=storage_key,
        expires_in=expires_in,
    )
    return result["signedURL"]


def download_file(storage_key: str) -> bytes:
    """Download a file's bytes (used by the worker to retrieve documents for parsing)."""
    return _client().storage.from_(settings.supabase_storage_bucket).download(storage_key)
