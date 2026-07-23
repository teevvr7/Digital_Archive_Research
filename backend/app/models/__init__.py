"""SQLAlchemy models. Importing this package registers every table on Base.metadata."""

# Every model class is imported here even though most of the app imports
# them directly from their own module (e.g. `from app.models.tenant import
# Tenant`) — this exists so that simply `import app.models` (which Alembic's
# migration-autogenerate machinery does) is guaranteed to register every
# single table on Base.metadata, even ones no other code currently imports.
from app.models.activity_event import ActivityEvent
from app.models.ai_usage import AiUsage
from app.models.api_key import ApiKey
from app.models.base import Base
from app.models.correspondent import Correspondent
from app.models.custom_field import CustomField, DocumentFieldValue
from app.models.document import Document
from app.models.document_share import DocumentShare
from app.models.document_template import DocumentTemplate
from app.models.document_type import DocumentType
from app.models.document_type_field import DocumentTypeField
from app.models.extraction import Extraction
from app.models.processing_job import ProcessingJob
from app.models.saved_view import SavedView
from app.models.tag import DocumentTag, Tag
from app.models.tenant import Tenant
from app.models.user import User

# __all__ controls what "from app.models import *" would expose, and also
# documents at a glance every table that exists in the whole system.
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
    "CustomField",
    "DocumentFieldValue",
    "DocumentTypeField",
    "SavedView",
    "DocumentShare",
]
