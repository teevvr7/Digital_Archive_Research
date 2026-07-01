import sys
import os

# Add parent directory to path so we can import app
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.db import SessionLocal
from app.models.document_type import DocumentType
from app.models.document_template import DocumentTemplate

def run():
    db = SessionLocal()
    try:
        # Update DocumentType
        types = db.query(DocumentType).filter(DocumentType.extraction_method == "default").all()
        print(f"Found {len(types)} DocumentTypes with extraction_method='default'. Updating to 'paddle_qwen'...")
        for t in types:
            t.extraction_method = "paddle_qwen"
            
        # Update DocumentTemplate
        templates = db.query(DocumentTemplate).filter(DocumentTemplate.extraction_method == "default").all()
        print(f"Found {len(templates)} DocumentTemplates with extraction_method='default'. Updating to 'paddle_qwen'...")
        for temp in templates:
            temp.extraction_method = "paddle_qwen"
            
        db.commit()
        print("Successfully updated all strategies to 'paddle_qwen' in the database.")
    except Exception as e:
        db.rollback()
        print(f"Error updating strategies: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    run()
