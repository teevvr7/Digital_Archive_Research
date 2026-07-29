import json
import csv
import os
import random
from datetime import datetime

# Set seed for reproducibility
random.seed(42)

def main():
    input_path = "data/invoices.json"
    output_path = "data/ground_truth.csv"
    
    if not os.path.exists(input_path):
        print(f"Error: {input_path} does not exist. Run generate_invoices.py first.")
        return
        
    with open(input_path, "r", encoding="utf-8") as f:
        invoices = json.load(f)
        
    # Calculate aggregation values globally
    vendor_invoice_counts = {}
    for inv in invoices:
        v = inv["vendor"]
        vendor_invoice_counts[v] = vendor_invoice_counts.get(v, 0) + 1

    qa_pairs = []
    fuzzy_qa_pairs = []
    
    for inv in invoices:
        inv_id = inv["invoice_id"]
        vendor = inv["vendor"]
        buyer = inv["buyer"]
        total = f"{inv['currency']} {inv['grand_total']:.2f}"
        subtotal = f"{inv['currency']} {inv['subtotal']:.2f}"
        date = inv["date"]
        
        # 1. Vendor Lookup (Structured)
        qa_pairs.append({
            "question": f"Which vendor issued invoice {inv_id}?",
            "expected_answer": vendor,
            "source_invoice_id": inv_id,
            "question_type": "vendor_lookup"
        })
        
        # 2. Grand Total Lookup (Structured)
        qa_pairs.append({
            "question": f"What is the grand total for invoice {inv_id}?",
            "expected_answer": total,
            "source_invoice_id": inv_id,
            "question_type": "total_lookup"
        })
        
        # 3. Subtotal Lookup (Structured)
        qa_pairs.append({
            "question": f"What was the subtotal amount on invoice {inv_id}?",
            "expected_answer": subtotal,
            "source_invoice_id": inv_id,
            "question_type": "subtotal_lookup"
        })

        # 4. Date Lookup (Structured)
        qa_pairs.append({
            "question": f"What is the billing date for invoice {inv_id}?",
            "expected_answer": date,
            "source_invoice_id": inv_id,
            "question_type": "date_lookup"
        })

        # 5. Line items details (Structured)
        items = inv["line_items"]
        if items:
            item = random.choice(items)
            desc = item["description"]
            qty = str(item["qty"])
            uprice = f"{inv['currency']} {item['unit_price']:.2f}"
            
            qa_pairs.append({
                "question": f"How many {desc} items were purchased in invoice {inv_id}?",
                "expected_answer": qty,
                "source_invoice_id": inv_id,
                "question_type": "line_item_qty"
            })
            
            qa_pairs.append({
                "question": f"What was the unit price of {desc} on invoice {inv_id}?",
                "expected_answer": uprice,
                "source_invoice_id": inv_id,
                "question_type": "line_item_price"
            })

            # 6. Fuzzy / Discovery Questions WITHOUT invoice IDs (RAG Path)
            fuzzy_qa_pairs.append({
                "question": f"Find the invoice document where we purchased {desc}.",
                "expected_answer": inv_id,
                "source_invoice_id": inv_id,
                "question_type": "fuzzy_item_discovery"
            })
            
            fuzzy_qa_pairs.append({
                "question": f"I remember placing an order with {vendor}, can you locate the matching invoice record?",
                "expected_answer": inv_id,
                "source_invoice_id": inv_id,
                "question_type": "fuzzy_vendor_discovery"
            })

            fuzzy_qa_pairs.append({
                "question": f"Which invoice record covers supplies delivered to {buyer}?",
                "expected_answer": inv_id,
                "source_invoice_id": inv_id,
                "question_type": "fuzzy_buyer_discovery"
            })

    # Shuffle QA pairs
    random.shuffle(qa_pairs)
    random.shuffle(fuzzy_qa_pairs)
    
    # Select 150 structured questions + 30 fuzzy RAG discovery questions = 180 total
    structured_selected = qa_pairs[:150]
    fuzzy_selected = fuzzy_qa_pairs[:30]
    
    final_ground_truth = structured_selected + fuzzy_selected
    random.shuffle(final_ground_truth)
    
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["question", "expected_answer", "source_invoice_id", "question_type"])
        writer.writeheader()
        writer.writerows(final_ground_truth)
        
    print(f"Successfully generated {len(final_ground_truth)} ground truth Q&A pairs (150 Structured + 30 Fuzzy RAG) at {output_path}")

if __name__ == "__main__":
    main()
