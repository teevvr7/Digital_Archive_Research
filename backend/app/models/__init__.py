"""SQLAlchemy models. Importing this package registers every table on Base.metadata."""

from app.models.activity_event import ActivityEvent
from app.models.ai_usage import AiUsage
from app.models.api_key import ApiKey
from app.models.base import Base
from app.models.correspondent import Correspondent
from app.models.document import Document
from app.models.document_template import DocumentTemplate
from app.models.document_type import DocumentType
from app.models.extraction import Extraction
from app.models.processing_job import ProcessingJob
from app.models.tag import DocumentTag, Tag
from app.models.tenant import Tenant
from app.models.user import User

__all__ = [
    "Base",
    "Tenant",
    "User",
    "Document",
    "DocumentType",
    "DocumentTemplate",
    "Extraction",
    "ProcessingJob",
    "ActivityEvent",
    "ApiKey",
    "AiUsage",
    "Tag",
    "DocumentTag",
    "Correspondent",
]
