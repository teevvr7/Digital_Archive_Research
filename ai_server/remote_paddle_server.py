# remote_paddle_server.py
import os
import re
import json
import tempfile
import logging
from typing import Dict, Any
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import JSONResponse
from bs4 import BeautifulSoup
from openai import OpenAI

# Standard production-grade logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("remote-idp-orchestrator")

app = FastAPI(
    title="Remote Paddle-Qwen IDP Orchestrator", 
    description="Unified API doing both OCR and LLM extraction on GPU"
)

@app.on_event("startup")
def startup_event():
    logger.info("Pre-loading PaddleOCRVL pipeline on server startup...")
    try:
        get_paddle_pipeline()
        logger.info("PaddleOCRVL pipeline preloaded successfully on startup.")
    except Exception as e:
        logger.error("Failed to preload PaddleOCRVL pipeline on startup: %s", e)

# --- Configuration & Debug Toggles (via Environment Variables) ---
QWEN_LLM_URL = os.environ.get("QWEN_LLM_URL", "http://localhost:8001/v1")
QWEN_LLM_MODEL = os.environ.get("QWEN_LLM_MODEL", "qwen3-vl-4b-instruct")
PADDLE_OCR_MODEL = os.environ.get("PADDLE_OCR_MODEL", "PaddlePaddle/PaddleOCR-VL")
VLM_MAX_PAGES = int(os.environ.get("VLM_MAX_PAGES", "10"))

# Debug toggles (case-insensitive string matching to support docker/env systems)
def _get_bool_env(var_name: str) -> bool:
    val = os.environ.get(var_name, "False").lower()
    return val in ("true", "1", "yes", "on")

DEBUG_RAW_OCR = _get_bool_env("DEBUG_RAW_OCR")
DEBUG_CLEANED_OCR = _get_bool_env("DEBUG_CLEANED_OCR")
DEBUG_FULL_PROMPT = _get_bool_env("DEBUG_FULL_PROMPT")
DEBUG_RAW_RESPONSE = _get_bool_env("DEBUG_RAW_RESPONSE")

# Lazy-loaded Paddle singleton
_paddle_pipeline = None

def get_paddle_pipeline():
    global _paddle_pipeline
    if _paddle_pipeline is None:
        from paddleocr import PaddleOCRVL
        logger.info("Initializing PaddleOCRVL (Model: %s)", PADDLE_OCR_MODEL)
        _paddle_pipeline = PaddleOCRVL(
            vl_rec_backend="vllm-server",
            vl_rec_server_url="http://localhost:8000/v1",
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

def validate_extraction(data: Dict[str, Any], json_schema: Dict[str, Any] = None) -> Dict[str, Any]:
    if "requires_human_review" not in data:
        data["requires_human_review"] = False
    if "validation_errors" not in data:
        data["validation_errors"] = []
        
    issues = []
    
    # Try dynamic math validation if keys are present
    def find_val(d, keys):
        if not isinstance(d, dict):
            return None
        for k, v in d.items():
            if k.lower() in keys:
                try:
                    return float(v)
                except (ValueError, TypeError):
                    pass
            if isinstance(v, dict):
                res = find_val(v, keys)
                if res is not None:
                    return res
        return None

    subtotal = find_val(data, ("subtotal", "sub_total"))
    tax = find_val(data, ("tax", "tax_amount", "tax_total", "vat"))
    total = find_val(data, ("total_amount", "grand_total", "total", "amount_due"))

    if subtotal is not None and tax is not None and total is not None:
        if abs((subtotal + tax) - total) > 0.02:
            issues.append(f"Math mismatch: Subtotal({subtotal}) + Tax({tax}) != Total({total})")
            
    # Dynamic vendor name check
    vendor_name = None
    for parent in ("vendor_details", "invoice_metadata", "metadata", "header"):
        if isinstance(data.get(parent), dict):
            vendor_name = data[parent].get("company_name") or data[parent].get("vendor_name")
            if vendor_name:
                break
    if not vendor_name:
        vendor_name = data.get("vendor_name") or data.get("company_name")

    schema_has_vendor = False
    if json_schema:
        def has_key(s, keys):
            if not isinstance(s, dict):
                return False
            for k, v in s.items():
                if k in keys:
                    return True
                if isinstance(v, dict) and has_key(v, keys):
                    return True
            return False
        schema_has_vendor = has_key(json_schema, ("company_name", "vendor_name"))
    else:
        schema_has_vendor = True

    if schema_has_vendor and not vendor_name:
        issues.append("Missing Vendor Name")
        
    if issues:
        data["requires_human_review"] = True
        for issue in issues:
            if issue not in data["validation_errors"]:
                data["validation_errors"].append(issue)
    return data

def merge_dicts(dict_a: dict, dict_b: dict) -> dict:
    res = dict(dict_a)
    for key, val in dict_b.items():
        if key not in res:
            res[key] = val
            continue
            
        # If both are lists, concatenate
        if isinstance(res[key], list) and isinstance(val, list):
            res[key] = res[key] + val
        # If both are dicts, recursively merge
        elif isinstance(res[key], dict) and isinstance(val, dict):
            res[key] = merge_dicts(res[key], val)
        # If scalar, apply rule: total-related keys take last, others take first
        else:
            is_empty_a = (res[key] is None or res[key] == "")
            is_empty_b = (val is None or val == "")
            
            _TOTAL_KEYS = ("total", "amount_due", "grand_total", "balance_due", "amount_payable")
            is_total = any(t in key.lower() for t in _TOTAL_KEYS)
            
            if is_total:
                if not is_empty_b:
                    res[key] = val
            else:
                if is_empty_a and not is_empty_b:
                    res[key] = val
    return res

def process_single_page(
    page_num: int,
    path: str,
    use_ocr: bool,
    use_image: bool,
    system_instructions: str,
    qwen_llm_url: str,
    qwen_llm_model: str,
    debug_raw_response: bool,
    debug_full_prompt: bool
) -> Dict[str, Any]:
    try:
        # 1. OCR Extraction (if enabled)
        cleaned_text = ""
        if use_ocr:
            pipeline = get_paddle_pipeline()
            results = pipeline.predict(path)
            page_text = ""
            if results and 'parsing_res_list' in results[0]:
                page_text = "\n".join(
                    item.get('content', '') if isinstance(item, dict) else getattr(item, 'content', '')
                    for item in results[0]['parsing_res_list']
                )
            cleaned_text = clean_ocr_text(page_text) if page_text else ""

            # Print page-level OCR logs if debug is enabled
            if DEBUG_RAW_OCR and page_text:
                logger.info("\n\n=== [DEBUG: Page %d RAW OCR OUTPUT] ===\n%s\n=======================================", page_num, page_text)
            if DEBUG_CLEANED_OCR and cleaned_text:
                logger.info("\n\n=== [DEBUG: Page %d CLEANED OCR TEXT] ===\n%s\n========================================", page_num, cleaned_text)

        # 2. Base64 Image Processing (if enabled)
        b64_image = None
        if use_image:
            import base64
            with open(path, "rb") as img_file:
                b64_image = base64.b64encode(img_file.read()).decode("utf-8")

        # 3. Construct message contents
        user_content = []
        if cleaned_text:
            user_content.append({
                "type": "text",
                "text": f"Use the following OCR text extraction of Page {page_num} as a guide for text accuracy:\n{cleaned_text}"
            })
        else:
            user_content.append({
                "type": "text",
                "text": f"Extract structured data from Page {page_num} of the provided document."
            })

        if b64_image:
            user_content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{b64_image}"
                }
            })

        if debug_full_prompt:
            logger.info("\n\n=== [DEBUG: PAGE %d SYSTEM INSTRUCTIONS] ===\n%s\n===========================================", page_num, system_instructions)
            txt_content = next((c["text"] for c in user_content if c["type"] == "text"), "")
            logger.info("\n\n=== [DEBUG: PAGE %d USER PROMPT TEXT] ===\n%s\n=======================================", page_num, txt_content)

        # 4. LLM/VLM Call
        client = OpenAI(base_url=qwen_llm_url, api_key="EMPTY")
        response = client.chat.completions.create(
            model=qwen_llm_model,
            messages=[
                {"role": "system", "content": system_instructions},
                {"role": "user", "content": user_content}
            ],
            temperature=0.1,
            response_format={"type": "json_object"}
        )

        raw_json_str = (response.choices[0].message.content or "").strip()
        
        if debug_raw_response:
            logger.info("\n\n=== [DEBUG: RAW QWEN RESPONSE FOR PAGE %d] ===\n%s\n==================================", page_num, raw_json_str)

        try:
            extracted_json = json.loads(raw_json_str)
        except json.JSONDecodeError:
            extracted_json = attempt_json_recovery(raw_json_str)
            extracted_json["requires_human_review"] = True
            extracted_json.setdefault("validation_errors", []).append(f"Page {page_num} LLM output was truncated/incomplete")

        return {
            "page_number": page_num,
            "success": True,
            "data": extracted_json,
            "raw_content": raw_json_str,
            "ocr_text": cleaned_text
        }

    except Exception as e:
        logger.exception("Error processing Page %d: %s", page_num, e)
        return {
            "page_number": page_num,
            "success": False,
            "error": str(e),
            "data": {},
            "raw_content": "",
            "ocr_text": ""
        }

# --- Endpoint Routing ---

@app.post("/v1/extract")
async def extract(
    file: UploadFile = File(...),
    json_schema: str = Form(...),
    custom_prompt: str = Form(None),
    use_image: str = Form("false"),
    use_ocr: str = Form("true")
):
    logger.info("--------------------------------------------------")
    logger.info("PROCESSING REQUEST: %s (use_image: %s, use_ocr: %s)", file.filename, use_image, use_ocr)
    
    file_suffix = os.path.splitext(file.filename)[1].lower()
    with tempfile.NamedTemporaryFile(suffix=file_suffix, delete=False) as temp_file:
        temp_file.write(await file.read())
        temp_path = temp_file.name

    page_paths = []
    try:
        # Rasterize PDF pages if applicable
        if file_suffix == ".pdf":
            import fitz
            doc = fitz.open(temp_path)
            try:
                pages_to_process = min(doc.page_count, max(1, VLM_MAX_PAGES))
                for idx in range(pages_to_process):
                    page = doc[idx]
                    pix = page.get_pixmap(dpi=150)
                    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as page_file:
                        pix.save(page_file.name)
                        page_path = page_file.name
                    page_paths.append(page_path)
            finally:
                doc.close()
        else:
            page_paths.append(temp_path)

        # 1. Construct System Instructions
        system_instructions = (
            "You are a precise data extraction assistant specialized in financial documents.\n"
            "Your task is to extract structured data from the provided document and return it as a JSON object matching the target schema.\n\n"
            "=== CRITICAL EXTRACTION INSTRUCTIONS ===\n"
            f"{custom_prompt or 'Extract all fields present in the text.'}\n"
            "========================================\n\n"
            f"TARGET JSON SCHEMA:\n{json_schema}\n\n"
            "You must output a single, valid JSON object matching the schema. Do not include any explanation or markdown formatting outside the JSON."
        )

        # 2. Run Page Extractions in Parallel via ThreadPoolExecutor
        from concurrent.futures import ThreadPoolExecutor
        results = []
        u_image = (use_image.lower() == "true")
        u_ocr = (use_ocr.lower() == "true")
        
        with ThreadPoolExecutor(max_workers=len(page_paths)) as executor:
            futures = [
                executor.submit(
                    process_single_page,
                    idx + 1,
                    path,
                    u_ocr,
                    u_image,
                    system_instructions,
                    QWEN_LLM_URL,
                    QWEN_LLM_MODEL,
                    DEBUG_RAW_RESPONSE,
                    DEBUG_FULL_PROMPT
                )
                for idx, path in enumerate(page_paths)
            ]
            for future in futures:
                results.append(future.result())

        # Check if any pages failed completely
        failed_pages = [r for r in results if not r["success"]]
        if len(failed_pages) == len(results) and len(results) > 0:
            raise RuntimeError(f"All page extractions failed. First error: {failed_pages[0]['error']}")

        # 3. Merge Page JSON Outputs
        merged_json = {}
        all_ocr_texts = []
        all_raw_contents = []
        validation_errors = []

        for r in sorted(results, key=lambda x: x["page_number"]):
            if r["success"]:
                page_data = r["data"]
                # Filter out standard validation key list so we can compile them cleanly at the end
                page_validation_errors = page_data.pop("validation_errors", [])
                if isinstance(page_validation_errors, list):
                    validation_errors.extend(page_validation_errors)
                
                merged_json = merge_dicts(merged_json, page_data)
                
                if r["ocr_text"]:
                    all_ocr_texts.append(f"--- Page {r['page_number']} ---\n{r['ocr_text']}")
                if r["raw_content"]:
                    all_raw_contents.append(f"--- Page {r['page_number']} ---\n{r['raw_content']}")
            else:
                validation_errors.append(f"Page {r['page_number']} failed to process: {r['error']}")

        # Append collected validation errors
        if validation_errors:
            merged_json["validation_errors"] = list(set(validation_errors))
            merged_json["requires_human_review"] = True

        # Parse target schema for dynamic math/validation checks
        parsed_schema = None
        try:
            parsed_schema = json.loads(json_schema)
        except Exception:
            pass

        # Validate the merged payload
        validated_json = validate_extraction(merged_json, parsed_schema)

        logger.info("REQUEST COMPLETED SUCCESSFULLY")
        return JSONResponse(content={
            "status": "success",
            "data": validated_json,
            "raw_content": "\n\n".join(all_raw_contents),
            "ocr_text": "\n\n".join(all_ocr_texts),
            "page_count": len(page_paths)
        })

    except Exception as e:
        logger.exception("Error processing document extraction: %s", e)
        return JSONResponse(status_code=500, content={
            "status": "error",
            "detail": str(e)
        })
    finally:
        # Clean up temporary PDF page files
        if file_suffix == ".pdf":
            for path in page_paths:
                if os.path.exists(path):
                    try:
                        os.unlink(path)
                    except Exception as e:
                        logger.warning("Failed to clean up temp page %s: %s", path, e)
        # Clean up temporary base file
        if os.path.exists(temp_path):
            os.unlink(temp_path)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)
