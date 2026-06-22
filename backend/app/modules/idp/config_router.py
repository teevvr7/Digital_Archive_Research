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

class IDPConfigResponse(CamelModel):
    document_type_id: UUID
    name: str
    extraction_method: str
    json_schema: Optional[Dict[str, Any]] = None
    prompt_hints: Optional[Dict[str, Any]] = None
    is_customized: bool

class IDPConfigUpdateRequest(CamelModel):
    extraction_method: str  # "default" or "paddle_qwen"
    json_schema: Optional[Dict[str, Any]] = None
    prompt_hints: Optional[Dict[str, Any]] = None

class IDPConfigListResponse(CamelModel):
    configs: List[IDPConfigResponse]


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
            configs.append(IDPConfigResponse(
                document_type_id=doc_type.id,
                name=doc_type.name,
                extraction_method=template.extraction_method,
                json_schema=template.field_mappings,
                prompt_hints=template.field_mappings.get("_hints") if isinstance(template.field_mappings, dict) else None,
                is_customized=True
            ))
        else:
            configs.append(IDPConfigResponse(
                document_type_id=doc_type.id,
                name=doc_type.name,
                extraction_method=doc_type.extraction_method,
                json_schema=doc_type.json_schema,
                prompt_hints=None,
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
        return IDPConfigResponse(
            document_type_id=document_type_id,
            name=doc_type.name,
            extraction_method=template.extraction_method,
            json_schema=template.field_mappings,
            prompt_hints=template.field_mappings.get("_hints") if isinstance(template.field_mappings, dict) else None,
            is_customized=True
        )
        
    # 3. Fall back to the system default DocumentType definition
    return IDPConfigResponse(
        document_type_id=document_type_id,
        name=doc_type.name,
        extraction_method=doc_type.extraction_method,
        json_schema=doc_type.json_schema,
        prompt_hints=None,
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
    
    schema_payload = request.json_schema or {}
    if request.prompt_hints:
        schema_payload["_hints"] = request.prompt_hints
        
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
    
    return IDPConfigResponse(
        document_type_id=document_type_id,
        name=doc_type.name,
        extraction_method=template.extraction_method,
        json_schema=template.field_mappings,
        prompt_hints=request.prompt_hints,
        is_customized=True
    )
