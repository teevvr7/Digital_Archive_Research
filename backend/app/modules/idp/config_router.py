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
        
        if template:
            clean_schema, instruction, rules = split_schema_payload(template.field_mappings)
            configs.append(IDPConfigResponse(
                document_type_id=doc_type.id,
                name=doc_type.name,
                extraction_method=template.extraction_method,
                json_schema=clean_schema,
                instruction=instruction,
                rules=rules,
                is_customized=True
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
                is_customized=False
            ))
            
    return IDPConfigListResponse(configs=configs)


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
    
    if template:
        clean_schema, instruction, rules = split_schema_payload(template.field_mappings)
        return IDPConfigResponse(
            document_type_id=document_type_id,
            name=doc_type.name,
            extraction_method=template.extraction_method,
            json_schema=clean_schema,
            instruction=instruction,
            rules=rules,
            is_customized=True
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
        is_customized=False
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
        
    db.commit()
    db.refresh(template)
    
    clean_schema, instruction, rules = split_schema_payload(template.field_mappings)
    return IDPConfigResponse(
        document_type_id=document_type_id,
        name=doc_type.name,
        extraction_method=template.extraction_method,
        json_schema=clean_schema,
        instruction=instruction,
        rules=rules,
        is_customized=True
    )

