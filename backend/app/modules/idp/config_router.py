from uuid import UUID
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from app.core.camel import CamelModel
from sqlalchemy.orm import Session

from app.core.deps import get_tenant_db
from app.core.security import TokenData
from app.models.document_type import DocumentType
from app.models.document_template import DocumentTemplate

router = APIRouter(prefix="/idp/config", tags=["IDP Configuration"])

DEFAULT_INSTRUCTION = (
    "You are a precise data extraction assistant specialized in financial documents.\n"
    "Extract information from the provided text and return it strictly as a JSON object matching the target structure.\n"
    "Be as concise as possible to avoid truncation."
)

DEFAULT_RULES = (
    "RULES:\n"
    "1. DATES: All dates MUST be converted to YYYY-MM-DD format.\n"
    "2. NUMBERS: Convert currency and quantities to float numbers (e.g., 1,200.50 -> 1200.50).\n"
    "3. NULLS: If a field is not present in the text, use null.\n"
    "4. NESTING: Follow the exact nested structure provided below to separate Vendor vs Client details.\n"
    "5. LINE ITEMS: Extract every row from tables into the line_items array."
)


class IDPConfigResponse(CamelModel):
    document_type_id: UUID
    name: str
    extraction_method: str
    json_schema: Optional[Dict[str, Any]] = None
    instruction: str
    rules: str
    is_customized: bool
    is_system: bool


class DocumentTypeCreateRequest(CamelModel):
    name: str
    description: Optional[str] = None
    extraction_method: str = "paddle_qwen"


class IDPConfigUpdateRequest(CamelModel):
    extraction_method: str  # "default" or "paddle_qwen"
    json_schema: Optional[Dict[str, Any]] = None
    instruction: Optional[str] = None
    rules: Optional[str] = None


class IDPConfigListResponse(CamelModel):
    configs: List[IDPConfigResponse]


def split_schema_payload(payload: Optional[Dict[str, Any]]) -> tuple[Optional[Dict[str, Any]], str, str]:
    """Helper to separate instruction and rules from the target JSON schema dictionary."""
    if not payload:
        return None, DEFAULT_INSTRUCTION, DEFAULT_RULES
    
    import json
    clean_schema = dict(payload)
    instruction = clean_schema.pop("_instruction", DEFAULT_INSTRUCTION)
    rules = clean_schema.pop("_rules", DEFAULT_RULES)
    
    # Restore original user-defined key order if present in metadata
    original_schema_str = clean_schema.pop("_original_schema_str", None)
    if original_schema_str:
        try:
            clean_schema = json.loads(original_schema_str)
        except Exception as e:
            logger.warning("Failed to parse _original_schema_str: %s", e)
            
    # Clean up any legacy metadata keys if present
    clean_schema.pop("_hints", None)
    clean_schema.pop("_prompt", None)
    
    return clean_schema, instruction, rules


@router.get("", response_model=IDPConfigListResponse)
def list_idp_configurations(
    ctx: tuple[Session, TokenData] = Depends(get_tenant_db)
):
    """
    Lists all document types (system-wide and tenant-specific) and their active IDP configurations.
    """
    db, user = ctx
    tenant_uuid = UUID(user.tenant_id)
    
    # Fetch all system-wide and tenant-specific document types
    doc_types = db.query(DocumentType).filter(
        (DocumentType.tenant_id == tenant_uuid) | (DocumentType.tenant_id.is_(None))
    ).all()
    
    configs = []
    for doc_type in doc_types:
        template = db.query(DocumentTemplate).filter(
            DocumentTemplate.document_type_id == doc_type.id,
            DocumentTemplate.tenant_id == tenant_uuid,
            DocumentTemplate.status == "promoted"
        ).first()
        
        is_sys = (doc_type.tenant_id is None)
        
        if template:
            clean_schema, instruction, rules = split_schema_payload(template.field_mappings)
            configs.append(IDPConfigResponse(
                document_type_id=doc_type.id,
                name=doc_type.name,
                extraction_method=template.extraction_method,
                json_schema=clean_schema,
                instruction=instruction,
                rules=rules,
                is_customized=True,
                is_system=is_sys
            ))
        else:
            clean_schema, instruction, rules = split_schema_payload(doc_type.json_schema)
            configs.append(IDPConfigResponse(
                document_type_id=doc_type.id,
                name=doc_type.name,
                extraction_method=doc_type.extraction_method,
                json_schema=clean_schema,
                instruction=instruction,
                rules=rules,
                is_customized=False,
                is_system=is_sys
            ))
            
    return IDPConfigListResponse(configs=configs)


# --- Multi-Template CRUD Support ---

import logging
logger = logging.getLogger(__name__)
import uuid

class TemplateResponse(CamelModel):
    id: UUID
    document_type_id: UUID
    name: str
    is_default: bool
    use_image: bool
    use_ocr: bool
    extraction_method: str
    json_schema: Optional[Dict[str, Any]] = None
    instruction: str
    rules: str
    status: str


class TemplateCreateRequest(CamelModel):
    document_type_id: UUID
    name: str
    extraction_method: str = "paddle_qwen"
    json_schema: Dict[str, Any]
    instruction: Optional[str] = None
    rules: Optional[str] = None
    use_image: bool = False
    use_ocr: bool = True


class TemplateUpdateRequest(CamelModel):
    name: str
    extraction_method: str
    json_schema: Dict[str, Any]
    instruction: Optional[str] = None
    rules: Optional[str] = None
    use_image: bool
    use_ocr: bool


@router.get("/templates", response_model=List[TemplateResponse])
def list_templates(
    ctx: tuple[Session, TokenData] = Depends(get_tenant_db)
):
    """Lists all configured layouts/templates for the tenant."""
    db, user = ctx
    tenant_uuid = UUID(user.tenant_id)
    templates = db.query(DocumentTemplate).filter(
        DocumentTemplate.tenant_id == tenant_uuid
    ).order_by(DocumentTemplate.name).all()
    
    res = []
    for t in templates:
        clean_schema, instruction, rules = split_schema_payload(t.field_mappings)
        res.append(TemplateResponse(
            id=t.id,
            document_type_id=t.document_type_id,
            name=t.name,
            is_default=t.is_default,
            use_image=t.use_image,
            use_ocr=t.use_ocr,
            extraction_method=t.extraction_method,
            json_schema=clean_schema,
            instruction=instruction,
            rules=rules,
            status=t.status
        ))
    return res


@router.post("/templates", response_model=TemplateResponse)
def create_template(
    request: TemplateCreateRequest,
    ctx: tuple[Session, TokenData] = Depends(get_tenant_db)
):
    """Creates a new extraction template/layout configuration under a document type."""
    db, user = ctx
    tenant_uuid = UUID(user.tenant_id)
    
    doc_type = db.get(DocumentType, request.document_type_id)
    if not doc_type:
        raise HTTPException(status_code=404, detail="Document type not found.")
        
    schema_payload = dict(request.json_schema) if request.json_schema else {}
    schema_payload["_instruction"] = request.instruction if request.instruction is not None else DEFAULT_INSTRUCTION
    schema_payload["_rules"] = request.rules if request.rules is not None else DEFAULT_RULES
    import json
    schema_payload["_original_schema_str"] = json.dumps(request.json_schema)
    
    # Auto-set first template as default for its type
    existing_count = db.query(DocumentTemplate).filter(
        DocumentTemplate.document_type_id == request.document_type_id,
        DocumentTemplate.tenant_id == tenant_uuid
    ).count()
    is_default = (existing_count == 0)
    
    template = DocumentTemplate(
        tenant_id=tenant_uuid,
        document_type_id=request.document_type_id,
        name=request.name,
        fingerprint=f"custom_{uuid.uuid4().hex[:8]}",
        field_mappings=schema_payload,
        status="promoted",
        extraction_method=request.extraction_method,
        is_default=is_default,
        use_image=request.use_image,
        use_ocr=request.use_ocr
    )
    db.add(template)
    db.flush()
    db.refresh(template)
    
    clean_schema, instruction, rules = split_schema_payload(template.field_mappings)
    return TemplateResponse(
        id=template.id,
        document_type_id=template.document_type_id,
        name=template.name,
        is_default=template.is_default,
        use_image=template.use_image,
        use_ocr=template.use_ocr,
        extraction_method=template.extraction_method,
        json_schema=clean_schema,
        instruction=instruction,
        rules=rules,
        status=template.status
    )


@router.put("/templates/{template_id}", response_model=TemplateResponse)
def update_template(
    template_id: UUID,
    request: TemplateUpdateRequest,
    ctx: tuple[Session, TokenData] = Depends(get_tenant_db)
):
    """Updates settings, schema, instructions, rules, and modalities for a template."""
    db, user = ctx
    tenant_uuid = UUID(user.tenant_id)
    
    template = db.query(DocumentTemplate).filter(
        DocumentTemplate.id == template_id,
        DocumentTemplate.tenant_id == tenant_uuid
    ).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found.")
        
    schema_payload = dict(request.json_schema) if request.json_schema else {}
    schema_payload["_instruction"] = request.instruction if request.instruction is not None else DEFAULT_INSTRUCTION
    schema_payload["_rules"] = request.rules if request.rules is not None else DEFAULT_RULES
    import json
    schema_payload["_original_schema_str"] = json.dumps(request.json_schema)
    
    template.name = request.name
    template.extraction_method = request.extraction_method
    template.field_mappings = schema_payload
    template.use_image = request.use_image
    template.use_ocr = request.use_ocr
    
    db.flush()
    db.refresh(template)
    
    clean_schema, instruction, rules = split_schema_payload(template.field_mappings)
    return TemplateResponse(
        id=template.id,
        document_type_id=template.document_type_id,
        name=template.name,
        is_default=template.is_default,
        use_image=template.use_image,
        use_ocr=template.use_ocr,
        extraction_method=template.extraction_method,
        json_schema=clean_schema,
        instruction=instruction,
        rules=rules,
        status=template.status
    )


@router.post("/templates/{template_id}/set-default", response_model=TemplateResponse)
def set_default_template(
    template_id: UUID,
    ctx: tuple[Session, TokenData] = Depends(get_tenant_db)
):
    """Sets a template as the default configuration for its document type."""
    db, user = ctx
    tenant_uuid = UUID(user.tenant_id)
    
    template = db.query(DocumentTemplate).filter(
        DocumentTemplate.id == template_id,
        DocumentTemplate.tenant_id == tenant_uuid
    ).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found.")
        
    # Unset default on previous default template under this document type
    db.query(DocumentTemplate).filter(
        DocumentTemplate.document_type_id == template.document_type_id,
        DocumentTemplate.tenant_id == tenant_uuid,
        DocumentTemplate.is_default == True
    ).update({DocumentTemplate.is_default: False})
    
    template.is_default = True
    db.flush()
    db.refresh(template)
    
    clean_schema, instruction, rules = split_schema_payload(template.field_mappings)
    return TemplateResponse(
        id=template.id,
        document_type_id=template.document_type_id,
        name=template.name,
        is_default=template.is_default,
        use_image=template.use_image,
        use_ocr=template.use_ocr,
        extraction_method=template.extraction_method,
        json_schema=clean_schema,
        instruction=instruction,
        rules=rules,
        status=template.status
    )


@router.delete("/templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_template(
    template_id: UUID,
    ctx: tuple[Session, TokenData] = Depends(get_tenant_db)
):
    """Deletes a template. Promotes another default template if the deleted template was default."""
    db, user = ctx
    tenant_uuid = UUID(user.tenant_id)
    
    template = db.query(DocumentTemplate).filter(
        DocumentTemplate.id == template_id,
        DocumentTemplate.tenant_id == tenant_uuid
    ).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found.")
        
    was_default = template.is_default
    doc_type_id = template.document_type_id
    
    db.delete(template)
    db.flush()
    
    if was_default:
        next_template = db.query(DocumentTemplate).filter(
            DocumentTemplate.document_type_id == doc_type_id,
            DocumentTemplate.tenant_id == tenant_uuid
        ).first()
        if next_template:
            next_template.is_default = True
            db.flush()
            
    return None


@router.post("/document-types", response_model=IDPConfigResponse)
def create_document_type(
    request: DocumentTypeCreateRequest,
    ctx: tuple[Session, TokenData] = Depends(get_tenant_db)
):
    """Creates a custom tenant-specific document type."""
    db, user = ctx
    tenant_uuid = UUID(user.tenant_id)
    
    # Check if a document type with the same name already exists for this tenant
    existing = db.query(DocumentType).filter(
        DocumentType.name.ilike(request.name),
        DocumentType.tenant_id == tenant_uuid
    ).first()
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"A document type named '{request.name}' already exists."
        )
        
    # Default schema template for a new document type
    default_schema = {
        "document_details": {
            "document_type": request.name.lower(),
            "document_number": "string",
            "document_date": "YYYY-MM-DD"
        }
    }
    
    import json
    schema_payload = dict(default_schema)
    schema_payload["_instruction"] = DEFAULT_INSTRUCTION
    schema_payload["_rules"] = DEFAULT_RULES
    schema_payload["_original_schema_str"] = json.dumps(default_schema)
    
    doc_type = DocumentType(
        tenant_id=tenant_uuid,
        name=request.name,
        description=request.description,
        is_system=False,
        extraction_method=request.extraction_method,
        json_schema=schema_payload
    )
    db.add(doc_type)
    db.flush()
    db.refresh(doc_type)
    
    clean_schema, instruction, rules = split_schema_payload(doc_type.json_schema)
    return IDPConfigResponse(
        document_type_id=doc_type.id,
        name=doc_type.name,
        extraction_method=doc_type.extraction_method,
        json_schema=clean_schema,
        instruction=instruction,
        rules=rules,
        is_customized=False,
        is_system=False
    )


@router.delete("/document-types/{document_type_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document_type(
    document_type_id: UUID,
    ctx: tuple[Session, TokenData] = Depends(get_tenant_db)
):
    """Deletes a custom document type. System/global types cannot be deleted."""
    db, user = ctx
    tenant_uuid = UUID(user.tenant_id)
    
    doc_type = db.get(DocumentType, document_type_id)
    if not doc_type:
        raise HTTPException(
            status_code=404,
            detail="Document type not found."
        )
        
    if doc_type.tenant_id != tenant_uuid:
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to delete this system-default document type."
        )
        
    # Cascade delete any document templates associated with this document type
    db.query(DocumentTemplate).filter(
        DocumentTemplate.document_type_id == document_type_id,
        DocumentTemplate.tenant_id == tenant_uuid
    ).delete()
    
    db.delete(doc_type)
    db.flush()
    return None


@router.get("/{document_type_id}", response_model=IDPConfigResponse)
def get_idp_configuration(
    document_type_id: UUID,
    ctx: tuple[Session, TokenData] = Depends(get_tenant_db)
):
    """
    Retrieves the active IDP configuration for the given document type.
    Checks for a tenant-customized template first, falling back to the global document type definition.
    """
    db, user = ctx
    tenant_uuid = UUID(user.tenant_id)
    
    # 1. Look up the document type to make sure it exists
    doc_type = db.get(DocumentType, document_type_id)
    if not doc_type:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document type {document_type_id} not found."
        )
        
    # 2. Check if a promoted template exists for this tenant
    template = db.query(DocumentTemplate).filter(
        DocumentTemplate.document_type_id == document_type_id,
        DocumentTemplate.tenant_id == tenant_uuid,
        DocumentTemplate.status == "promoted"
    ).first()
    
    is_sys = (doc_type.tenant_id is None)
    if template:
        clean_schema, instruction, rules = split_schema_payload(template.field_mappings)
        return IDPConfigResponse(
            document_type_id=document_type_id,
            name=doc_type.name,
            extraction_method=template.extraction_method,
            json_schema=clean_schema,
            instruction=instruction,
            rules=rules,
            is_customized=True,
            is_system=is_sys
        )
        
    # 3. Fall back to the system default DocumentType definition
    clean_schema, instruction, rules = split_schema_payload(doc_type.json_schema)
    return IDPConfigResponse(
        document_type_id=document_type_id,
        name=doc_type.name,
        extraction_method=doc_type.extraction_method,
        json_schema=clean_schema,
        instruction=instruction,
        rules=rules,
        is_customized=False,
        is_system=is_sys
    )


@router.post("/{document_type_id}", response_model=IDPConfigResponse)
def update_idp_configuration(
    document_type_id: UUID,
    request: IDPConfigUpdateRequest,
    ctx: tuple[Session, TokenData] = Depends(get_tenant_db)
):
    """
    Upserts a promoted DocumentTemplate for the tenant to override default extraction schemas and strategy.
    This isolates customization per tenant without modifying system global schemas.
    """
    db, user = ctx
    tenant_uuid = UUID(user.tenant_id)
    
    doc_type = db.get(DocumentType, document_type_id)
    if not doc_type:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document type {document_type_id} not found."
        )
        
    if request.extraction_method not in ("default", "paddle_qwen"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Extraction method must be 'default' or 'paddle_qwen'."
        )
        
    # Look up existing template
    template = db.query(DocumentTemplate).filter(
        DocumentTemplate.document_type_id == document_type_id,
        DocumentTemplate.tenant_id == tenant_uuid,
        DocumentTemplate.status == "promoted"
    ).first()
    
    schema_payload = dict(request.json_schema) if request.json_schema else {}
    schema_payload["_instruction"] = request.instruction if request.instruction is not None else DEFAULT_INSTRUCTION
    schema_payload["_rules"] = request.rules if request.rules is not None else DEFAULT_RULES
    
    # Store the exact ordered schema string as metadata to bypass PostgreSQL JSONB key sorting
    if request.json_schema:
        import json
        schema_payload["_original_schema_str"] = json.dumps(request.json_schema)
        
    if template:
        # Update existing customization
        template.extraction_method = request.extraction_method
        template.field_mappings = schema_payload
    else:
        # Create a new custom template
        template = DocumentTemplate(
            tenant_id=tenant_uuid,
            document_type_id=document_type_id,
            name=f"Customized {doc_type.name} Template",
            fingerprint=f"custom_{document_type_id}",
            field_mappings=schema_payload,
            status="promoted",
            extraction_method=request.extraction_method
        )
        db.add(template)
        
    db.flush()
    db.refresh(template)
    
    clean_schema, instruction, rules = split_schema_payload(template.field_mappings)
    return IDPConfigResponse(
        document_type_id=document_type_id,
        name=doc_type.name,
        extraction_method=template.extraction_method,
        json_schema=clean_schema,
        instruction=instruction,
        rules=rules,
        is_customized=True,
        is_system=(doc_type.tenant_id is None)
    )



