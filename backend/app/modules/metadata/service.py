"""Metadata module — custom field CRUD + document field value upsert/delete."""

import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.custom_field import VALID_FIELD_TYPES, CustomField, DocumentFieldValue
from app.models.document import Document
from app.models.document_type_field import VALID_DOCUMENT_TYPES, DocumentTypeField
from app.modules.metadata.schemas import (
    CustomFieldIn,
    CustomFieldOut,
    CustomFieldPatchIn,
    FieldValueIn,
    FieldValueOut,
    PredefinedFieldIn,
    PredefinedFieldOut,
    PredefinedFieldPatchIn,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _field_to_out(field: CustomField) -> CustomFieldOut:
    return CustomFieldOut(
        id=field.id,
        name=field.name,
        field_type=field.field_type,
        options=field.options or [],
        position=field.position,
        created_at=field.created_at,
    )


# ---------------------------------------------------------------------------
# Custom field catalog
# ---------------------------------------------------------------------------


def list_custom_fields(db: Session) -> list[CustomFieldOut]:
    """List all custom fields for the current tenant, ordered by position then name."""
    fields = db.scalars(
        select(CustomField).order_by(CustomField.position, CustomField.name)
    ).all()
    return [_field_to_out(f) for f in fields]


def create_custom_field(
    db: Session, tenant_id: uuid.UUID, data: CustomFieldIn
) -> CustomFieldOut:
    """Create a custom field definition. 422 on invalid type. 409 on duplicate name."""
    if data.field_type not in VALID_FIELD_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Invalid field_type '{data.field_type}'. "
                f"Must be one of: {sorted(VALID_FIELD_TYPES)}"
            ),
        )
    existing = db.scalars(
        select(CustomField).where(
            CustomField.tenant_id == tenant_id, CustomField.name == data.name
        )
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Custom field '{data.name}' already exists.",
        )
    field = CustomField(
        tenant_id=tenant_id,
        name=data.name,
        field_type=data.field_type,
        options=data.options,
        position=data.position,
    )
    db.add(field)
    db.flush()
    return _field_to_out(field)


def patch_custom_field(
    db: Session, field_id: uuid.UUID, patch: CustomFieldPatchIn
) -> CustomFieldOut:
    """Update a custom field. Only fields present in the request are written."""
    field = db.get(CustomField, field_id)
    if field is None:
        raise HTTPException(status_code=404, detail="Custom field not found.")
    updated = patch.model_fields_set
    if "name" in updated and patch.name is not None:
        field.name = patch.name
    if "options" in updated and patch.options is not None:
        field.options = patch.options
    if "position" in updated and patch.position is not None:
        field.position = patch.position
    db.flush()
    return _field_to_out(field)


def delete_custom_field(db: Session, field_id: uuid.UUID) -> None:
    """Delete a custom field (cascades document_field_values). 404 if not found."""
    field = db.get(CustomField, field_id)
    if field is None:
        raise HTTPException(status_code=404, detail="Custom field not found.")
    db.delete(field)
    db.flush()


# ---------------------------------------------------------------------------
# Document field values
# ---------------------------------------------------------------------------


def set_field_value(
    db: Session,
    tenant_id: uuid.UUID,
    doc_id: uuid.UUID,
    field_id: uuid.UUID,
    data: FieldValueIn,
) -> FieldValueOut:
    """Upsert a custom field value for a document. 404 if doc or field not found."""
    doc = db.get(Document, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    field = db.get(CustomField, field_id)
    if field is None:
        raise HTTPException(status_code=404, detail="Custom field not found.")

    db.execute(
        pg_insert(DocumentFieldValue)
        .values(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            document_id=doc_id,
            field_id=field_id,
            value=data.value,
        )
        .on_conflict_do_update(
            index_elements=["document_id", "field_id"],
            set_={"value": data.value},
        )
    )
    db.flush()

    return FieldValueOut(
        field_id=field.id,
        field_name=field.name,
        field_type=field.field_type,
        value=data.value,
    )


def delete_field_value(
    db: Session, doc_id: uuid.UUID, field_id: uuid.UUID
) -> None:
    """Clear a custom field value. 404 if no value is currently set."""
    row = db.scalars(
        select(DocumentFieldValue).where(
            DocumentFieldValue.document_id == doc_id,
            DocumentFieldValue.field_id == field_id,
        )
    ).first()
    if row is None:
        raise HTTPException(
            status_code=404,
            detail="No value is set for this field on this document.",
        )
    db.delete(row)
    db.flush()


def fetch_field_values_for_docs(
    db: Session, doc_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[FieldValueOut]]:
    """Batch-fetch all custom field values for a list of doc IDs (single query).

    Called by ``files.service`` to avoid N+1 queries when building a page of
    ``DocumentOut`` objects. Returns a mapping from ``document_id`` to the
    (possibly empty) list of ``FieldValueOut`` for that document.
    """
    if not doc_ids:
        return {}
    rows = db.execute(
        select(
            DocumentFieldValue.document_id,
            DocumentFieldValue.field_id,
            DocumentFieldValue.value,
            CustomField.name,
            CustomField.field_type,
        )
        .join(CustomField, CustomField.id == DocumentFieldValue.field_id)
        .where(DocumentFieldValue.document_id.in_(doc_ids))
        .order_by(CustomField.position, CustomField.name)
    ).all()
    result: dict[uuid.UUID, list[FieldValueOut]] = {}
    for row in rows:
        result.setdefault(row.document_id, []).append(
            FieldValueOut(
                field_id=row.field_id,
                field_name=row.name,
                field_type=row.field_type,
                value=row.value,
            )
        )
    return result


# ---------------------------------------------------------------------------
# Predefined fields per document type
# ---------------------------------------------------------------------------


def _predefined_to_out(link: DocumentTypeField, field: CustomField) -> PredefinedFieldOut:
    return PredefinedFieldOut(
        id=link.id,
        document_type=link.document_type,
        field_id=field.id,
        field_name=field.name,
        field_type=field.field_type,
        options=field.options or [],
        required=link.required,
        position=link.position,
    )


def _validate_document_type(document_type: str) -> None:
    if document_type not in VALID_DOCUMENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Invalid document_type '{document_type}'. "
                f"Must be one of: {sorted(VALID_DOCUMENT_TYPES)}"
            ),
        )


def list_predefined_fields(db: Session) -> dict[str, list[PredefinedFieldOut]]:
    """All predefined-field attachments for the current tenant, grouped by document_type.

    One joined query covers every type — used by both the upload popup and the
    Custom Fields management page's "predefined fields by type" section.
    """
    rows = db.execute(
        select(DocumentTypeField, CustomField)
        .join(CustomField, CustomField.id == DocumentTypeField.field_id)
        .order_by(DocumentTypeField.document_type, DocumentTypeField.position, CustomField.name)
    ).all()
    result: dict[str, list[PredefinedFieldOut]] = {t: [] for t in VALID_DOCUMENT_TYPES}
    for link, field in rows:
        result.setdefault(link.document_type, []).append(_predefined_to_out(link, field))
    return result


def add_predefined_field(
    db: Session, tenant_id: uuid.UUID, document_type: str, data: PredefinedFieldIn
) -> PredefinedFieldOut:
    """Attach an existing custom field as predefined for a document type.

    422 on invalid document_type, 404 if the field doesn't exist, 409 if
    already attached.
    """
    _validate_document_type(document_type)
    field = db.get(CustomField, data.field_id)
    if field is None:
        raise HTTPException(status_code=404, detail="Custom field not found.")
    existing = db.scalars(
        select(DocumentTypeField).where(
            DocumentTypeField.tenant_id == tenant_id,
            DocumentTypeField.document_type == document_type,
            DocumentTypeField.field_id == data.field_id,
        )
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"'{field.name}' is already predefined for document type '{document_type}'.",
        )
    link = DocumentTypeField(
        tenant_id=tenant_id,
        document_type=document_type,
        field_id=data.field_id,
        required=data.required,
        position=data.position,
    )
    db.add(link)
    db.flush()
    return _predefined_to_out(link, field)


def patch_predefined_field(
    db: Session, document_type: str, field_id: uuid.UUID, patch: PredefinedFieldPatchIn
) -> PredefinedFieldOut:
    """Toggle required/reorder a predefined-field attachment without detach+reattach."""
    link = db.scalars(
        select(DocumentTypeField).where(
            DocumentTypeField.document_type == document_type,
            DocumentTypeField.field_id == field_id,
        )
    ).first()
    if link is None:
        raise HTTPException(
            status_code=404,
            detail=f"No predefined-field attachment for '{document_type}'/{field_id}.",
        )
    updated = patch.model_fields_set
    if "required" in updated and patch.required is not None:
        link.required = patch.required
    if "position" in updated and patch.position is not None:
        link.position = patch.position
    db.flush()
    field = db.get(CustomField, field_id)
    return _predefined_to_out(link, field)


def remove_predefined_field(db: Session, document_type: str, field_id: uuid.UUID) -> None:
    """Detach a predefined field from a document type. 404 if not attached."""
    link = db.scalars(
        select(DocumentTypeField).where(
            DocumentTypeField.document_type == document_type,
            DocumentTypeField.field_id == field_id,
        )
    ).first()
    if link is None:
        raise HTTPException(
            status_code=404,
            detail=f"No predefined-field attachment for '{document_type}'/{field_id}.",
        )
    db.delete(link)
    db.flush()
