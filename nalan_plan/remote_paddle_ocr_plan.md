# Plan: Decoupling PaddleOCR-VL & Qwen Orchestration to a Unified Remote GPU Endpoint (Option A)

This plan details **Option A (Unified Remote Execution - Single Round-Trip)**, which shifts the entire IDP strategy pipeline (image rasterization, OCR layout extraction, text cleaning, Qwen LLM extraction, and mathematical validation) to the remote Lightning AI GPU space.

---

## 1. Architecture Overview

### Option A (Single Round-Trip)
Instead of back-and-forth network uploads, the local machine performs a single request. All computation, orchestration, and local GPU loopbacks are handled on the server.

```mermaid
graph TD
    subgraph Local Machine
        Backend[Local Backend / RQ Worker] -- 1. Uploads File + Schema + Prompt --> RemoteServer[FastAPI microservice]
        Backend <-- 4. Returns Final Validated JSON -- RemoteServer
    end
    subgraph Remote Lightning AI GPU
        RemoteServer -- 2. Runs OCR on GPU --> Paddle[PaddleOCRVL Pipeline]
        RemoteServer -- Cleans text & formats prompts --> RemoteServer
        RemoteServer -- 3. Runs LLM extraction via localhost --> Qwen[Qwen vLLM Server]
    end
```

### Key Benefits
1. **Latency Reduction**: Cuts network round-trips from $N+1$ (for $N$-page PDFs) down to exactly **1** unified POST request.
2. **Bandwidth Savings**: The document file is uploaded only once. 
3. **No Local Dependencies**: Zero machine learning packages (`paddlepaddle`, `paddleocr`, `torch`, `cuda`, `fitz`) are required on developers' local machines.
4. **Offloaded Computation**: Even CPU-heavy PDF page rasterization and text cleaning are offloaded to the GPU server.

---

## 2. Remote Component: `remote_paddle_server.py`

This standalone FastAPI microservice runs on the Lightning AI GPU space. It receives the document file, handles page rasterization (if PDF), extracts text, runs the Qwen extraction, validates results, and returns schema JSON.

```python
# remote_paddle_server.py
import os
import re
import json
import tempfile
import logging
from typing import Dict, Any, Tuple
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import JSONResponse
from bs4 import BeautifulSoup
from openai import OpenAI

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("remote-idp-orchestrator")

app = FastAPI(
    title="Remote Paddle-Qwen IDP Orchestrator", 
    description="Unified API doing both OCR and LLM extraction on GPU"
)

# Configuration settings (can be overridden via environment variables)
QWEN_LLM_URL = os.environ.get("QWEN_LLM_URL", "http://localhost:8001/v1")
QWEN_LLM_MODEL = os.environ.get("QWEN_LLM_MODEL", "Qwen2.5-1.5B")
PADDLE_OCR_MODEL = os.environ.get("PADDLE_OCR_MODEL", "PaddlePaddle/PaddleOCR-VL")
VLM_MAX_PAGES = int(os.environ.get("VLM_MAX_PAGES", "3"))

# Lazy loaded singleton
_paddle_pipeline = None

def get_paddle_pipeline():
    global _paddle_pipeline
    if _paddle_pipeline is None:
        from paddleocr import PaddleOCRVL
        logger.info("Initializing PaddleOCRVL (Model: %s)", PADDLE_OCR_MODEL)
        _paddle_pipeline = PaddleOCRVL(
            vl_rec_backend="vllm-server",
            vl_rec_server_url="http://localhost:8000/v1",  # Local port on Lightning AI Studio
            vl_rec_api_model_name=PADDLE_OCR_MODEL
        )
    return _paddle_pipeline

# --- Helper Utilities ---

def html_table_to_markdown(html_content: str) -> str:
    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        tables = soup.find_all('table')
        markdown_tables = []
        for table in tables:
            rows = table.find_all('tr')
            if not rows: continue
            md_rows = []
            for i, row in enumerate(rows):
                cols = row.find_all(['td', 'th'])
                cols_text = [c.get_text(strip=True) for c in cols]
                md_rows.append("| " + " | ".join(cols_text) + " |")
                if i == 0:
                    md_rows.append("| " + " | ".join(["---"] * len(cols)) + " |")
            markdown_tables.append("\n".join(md_rows))
        return "\n\n".join(markdown_tables) if markdown_tables else html_content
    except Exception as e:
        logger.warning("Failed to convert table: %s", e)
        return html_content

def clean_ocr_text(text: str) -> str:
    text = re.sub(r'<img[^>]*>', '', text)
    def table_replacer(match):
        return html_table_to_markdown(match.group(0))
    cleaned_text = re.sub(r'<table>.*?</table>', table_replacer, text, flags=re.DOTALL)
    cleaned_text = re.sub(r'\n\s*\n', '\n\n', cleaned_text)
    return cleaned_text.strip()

def attempt_json_recovery(truncated_json_str: str) -> Dict[str, Any]:
    temp_str = truncated_json_str.strip()
    for _ in range(5):
        try:
            return json.loads(temp_str)
        except json.JSONDecodeError:
            if temp_str.endswith('"'): temp_str += ' }'
            elif temp_str.endswith(','): temp_str = temp_str[:-1] + ' }'
            else: temp_str += ' }'
    return {"requires_human_review": True, "error": "JSON Truncated"}

def validate_extraction(data: Dict[str, Any]) -> Dict[str, Any]:
    # Ensure standard schema structure is present
    defaults = {
        "document_details": {}, "vendor_details": {}, "client_details": {},
        "line_items": [], "financials": {}, "requires_human_review": False,
        "validation_errors": []
    }
    for key, value in defaults.items():
        if key not in data:
            data[key] = value
            
    issues = []
    financials = data.get("financials", {})
    subtotal = financials.get("subtotal") or 0.0
    tax = financials.get("tax_amount") or 0.0
    total = financials.get("total_amount") or 0.0
    
    if abs((subtotal + tax) - total) > 0.02:
        issues.append(f"Math mismatch: Subtotal({subtotal}) + Tax({tax}) != Total({total})")
    if not data.get("vendor_details", {}).get("company_name"):
        issues.append("Missing Vendor Name")
        
    if issues:
        data["requires_human_review"] = True
        data["validation_errors"] = issues
    return data

# --- Endpoint Routing ---

@app.post("/v1/extract")
async def extract(
    file: UploadFile = File(...),
    json_schema: str = Form(...),
    custom_prompt: str = Form(None)
):
    """Unified endpoint to parse PDF/images, run OCR, clean text, query Qwen, and validate results."""
    logger.info("Starting processing for file: %s", file.filename)
    
    # 1. Save uploaded file
    file_suffix = os.path.splitext(file.filename)[1].lower()
    with tempfile.NamedTemporaryFile(suffix=file_suffix, delete=False) as temp_file:
        temp_file.write(await file.read())
        temp_path = temp_file.name

    try:
        ocr_texts = []
        pipeline = get_paddle_pipeline()

        # 2. Extract OCR depending on file format
        if file_suffix == ".pdf":
            import fitz  # PyMuPDF (make sure it's installed on the GPU machine)
            doc = fitz.open(temp_path)
            try:
                pages_to_process = min(doc.page_count, max(1, VLM_MAX_PAGES))
                for idx in range(pages_to_process):
                    page = doc[idx]
                    # Render page to high-res PNG for OCR accuracy
                    pix = page.get_pixmap(dpi=150)
                    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as page_file:
                        pix.save(page_file.name)
                        page_path = page_file.name
                    try:
                        results = pipeline.predict(page_path)
                        # Extract parsed content text
                        page_text = ""
                        if results and 'parsing_res_list' in results[0]:
                            page_text = "\n".join(
                                item.get('content', '') if isinstance(item, dict) else getattr(item, 'content', '')
                                for item in results[0]['parsing_res_list']
                            )
                        ocr_texts.append(page_text)
                    finally:
                        if os.path.exists(page_path):
                            os.unlink(page_path)
            finally:
                doc.close()
        else:
            # Image formats
            results = pipeline.predict(temp_path)
            doc_text = ""
            if results and 'parsing_res_list' in results[0]:
                doc_text = "\n".join(
                    item.get('content', '') if isinstance(item, dict) else getattr(item, 'content', '')
                    for item in results[0]['parsing_res_list']
                )
            ocr_texts.append(doc_text)

        # 3. Clean OCR outputs
        full_ocr_text = "\n\n".join(ocr_texts)
        cleaned_text = clean_ocr_text(full_ocr_text)

        # 4. Prompt Qwen LLM
        client = OpenAI(base_url=QWEN_LLM_URL, api_key="EMPTY")
        
        system_instructions = (
            "You are a precise data extraction assistant specialized in financial documents.\n"
            "Extract information from the provided text and return it strictly as a JSON object matching the target structure.\n"
            "Be as concise as possible to avoid truncation.\n\n"
            f"TARGET JSON SCHEMA:\n{json_schema}"
        )
        if custom_prompt:
            system_instructions += f"\n\nAdditional Instructions:\n{custom_prompt}"

        logger.info("Calling Qwen model: %s", QWEN_LLM_MODEL)
        response = client.chat.completions.create(
            model=QWEN_LLM_MODEL,
            messages=[
                {"role": "system", "content": system_instructions},
                {"role": "user", "content": f"Text to process:\n{cleaned_text}"}
            ],
            temperature=0.1,
            response_format={"type": "json_object"}
        )

        raw_json_str = (response.choices[0].message.content or "").strip()
        try:
            extracted_json = json.loads(raw_json_str)
        except json.JSONDecodeError:
            extracted_json = attempt_json_recovery(raw_json_str)
            extracted_json["requires_human_review"] = True
            extracted_json.setdefault("validation_errors", []).append("LLM output was truncated/incomplete")

        # 5. Run Mathematical Audits
        validated_json = validate_extraction(extracted_json)

        return JSONResponse(content={
            "status": "success",
            "data": validated_json,
            "raw_content": raw_json_str,
            "ocr_text": cleaned_text,
            "page_count": len(ocr_texts)
        })

    except Exception as e:
        logger.exception("Error processing document extraction: %s", e)
        return JSONResponse(status_code=500, content={
            "status": "error",
            "detail": str(e)
        })
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)
```

---

## 3. Local Refactoring Changes

We modify the local files to consume this endpoint.

### File 1: [paddle_qwen.py](file:///c:/Users/pnala/Desktop/IDP_Archive/idp_codebase/Digital_Archive_Research/backend/app/modules/idp/paddle_qwen.py)
Replace all local extraction logic with a clean API client call:

```python
# backend/app/modules/idp/paddle_qwen.py
import os
import json
import logging
import httpx
from typing import Tuple, Dict, Any
from app.core.config import settings

logger = logging.getLogger(__name__)

def run_remote_paddle_qwen_extraction(
    file_bytes: bytes, 
    filename: str, 
    json_schema: Dict[str, Any], 
    custom_prompt: str | None
) -> Tuple[Dict[str, Any], str, str, int]:
    """Uploads the raw document file, prompt hints, and target schema to the remote GPU service
    to extract fields. Fallbacks to mock values in offline/localhost settings.
    """
    
    # Check if mock mode should trigger in development
    is_localhost = "localhost" in settings.paddle_ocr_url or "127.0.0.1" in settings.paddle_ocr_url
    if is_localhost and settings.env == "development":
        logger.info("[MOCK] Returning mock data extraction.")
        mock_output = {
            "document_details": {
                "document_type": "invoice",
                "invoice_number": "INV-2026-PADDLE",
                "invoice_date": "2026-06-22",
                "due_date": "2026-07-22"
            },
            "vendor_details": {
                "company_name": "ACME Corp Ltd",
                "address": "123 Industrial Way, Tech City"
            },
            "client_details": {"company_name": "DataWiz Corp"},
            "line_items": [
                {"description": "Server Hosting", "quantity": 1, "unit_price": 800, "line_total": 800},
                {"description": "Database Support", "quantity": 1, "unit_price": 150, "line_total": 150}
            ],
            "financials": {
                "subtotal": 950.0,
                "tax_amount": 50.0,
                "total_amount": 1000.0
            },
            "requires_human_review": False,
            "validation_errors": []
        }
        return mock_output, json.dumps(mock_output), "mock ocr text", 1

    # Prepare multipart data
    url = f"{settings.paddle_ocr_url}/v1/extract"
    logger.info("Uploading file to unified extraction endpoint: %s", url)
    
    try:
        files = {"file": (filename, file_bytes, "application/octet-stream")}
        data = {
            "json_schema": json.dumps(json_schema),
            "custom_prompt": custom_prompt or ""
        }
        
        # 120s timeout to accommodate cold-starts on GPUs
        with httpx.Client() as client:
            response = client.post(url, files=files, data=data, timeout=120.0)
            
        response.raise_for_status()
        res_json = response.json()
        
        if res_json.get("status") == "success":
            return (
                res_json["data"], 
                res_json["raw_content"], 
                res_json.get("ocr_text", ""), 
                res_json.get("page_count", 1)
            )
        else:
            detail = res_json.get("detail", "Unknown remote API error")
            raise RuntimeError(f"Remote extraction failed: {detail}")
            
    except Exception as e:
        logger.exception("HTTP call to remote PaddleOCR-Qwen pipeline failed: %s", e)
        raise RuntimeError(f"IDP remote extraction failed: {e}")
```

### File 2: [pipeline.py](file:///c:/Users/pnala/Desktop/IDP_Archive/idp_codebase/Digital_Archive_Research/backend/app/modules/idp/pipeline.py)
We change `run_ai_extraction` so it skips local page rendering and files creation. It directly invokes `run_remote_paddle_qwen_extraction`:

```python
    # Inside pipeline.py: run_ai_extraction()
    if strategy == "paddle_qwen":
        logger.info("Executing custom remote Paddle-Qwen strategy for document %s", doc.id)
        from app.modules.idp.paddle_qwen import run_remote_paddle_qwen_extraction
        from app.modules.idp.extraction import VlmExtraction, VlmOutcome
        
        try:
            # 1. Resolve schemas & targets
            target_schema = {}
            if doc.template_id:
                template = db.get(DocumentTemplate, doc.template_id)
                if template:
                    target_schema = template.field_mappings
            elif doc.document_type_id:
                doc_type = db.get(DocumentType, doc.document_type_id)
                if doc_type:
                    target_schema = doc_type.json_schema

            # Default fallback schema matching standard format
            if not target_schema:
                target_schema = {
                    "document_details": {"document_type": "invoice", "invoice_number": "string"},
                    "vendor_details": {"company_name": "string"},
                    "financials": {"subtotal": "float", "tax_amount": "float", "total_amount": "float"}
                }

            # 2. Call unified remote server
            filename = doc.filename or "document"
            validated_json, raw_content = run_remote_paddle_qwen_extraction(
                file_bytes=file_bytes,
                filename=filename,
                json_schema=target_schema,
                custom_prompt=custom_prompt
            )

            # Heuristic check for human review flag
            confidence = 0.9 if not validated_json.get("requires_human_review", False) else 0.4

            extraction = VlmExtraction(
                document_type=validated_json.get("document_details", {}).get("document_type", "other"),
                fields=validated_json,
                confidence=confidence,
                model_name=settings.qwen_llm_model,
                raw=raw_content
            )
            return VlmOutcome(extraction, "text_via_paddle", None)

        except Exception as exc:
            logger.exception("Unified remote Paddle-Qwen strategy errored: %s", exc)
            return VlmOutcome(None, "text_via_paddle", str(exc))
```

---

## 4. Verification & Testing Actions

1. **Deploy script on Lightning AI**: Run `python remote_paddle_server.py` on the GPU server.
2. **Expose port**: Keep port `8002` open.
3. **Change env variable**: Add `PADDLE_OCR_URL=https://<lightning-url>-8002.cloudspaces.litng.ai` to local `backend/.env`.
4. **Test run**: Trigger extraction on a document.
