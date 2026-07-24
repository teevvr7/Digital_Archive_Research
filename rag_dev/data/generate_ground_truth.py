import json
import csv
import os
import random

# Set seed for reproducibility
random.seed(42)

def main():
    input_path = "data/invoices.json"
    output_path = "data/ground_truth.csv"
    
    if not os.path.exists(input_path):
        print(f"Error: {input_path} does not exist. Run generate_invoices.py first.")
        return
        
    with open(input_path, "r") as f:
        invoices = json.load(f)
        
    # Calculate aggregation values globally
    vendor_invoice_counts = {}
    for inv in invoices:
        v = inv["vendor"]
        vendor_invoice_counts[v] = vendor_invoice_counts.get(v, 0) + 1

    qa_pairs = []
    
    for inv in invoices:
        inv_id = inv["invoice_id"]
        vendor = inv["vendor"]
        total = f"{inv['currency']} {inv['grand_total']:.2f}"
        subtotal = f"{inv['currency']} {inv['subtotal']:.2f}"
        date = inv["date"]
        
        # 1. Vendor Lookup
        qa_pairs.append({
            "question": f"Which vendor issued invoice {inv_id}?",
            "expected_answer": vendor,
            "source_invoice_id": inv_id,
            "question_type": "vendor_lookup"
        })
        
        # 2. Grand Total Lookup
        qa_pairs.append({
            "question": f"What is the grand total for invoice {inv_id}?",
            "expected_answer": total,
            "source_invoice_id": inv_id,
            "question_type": "total_lookup"
        })
        
        # 3. Subtotal Lookup
        qa_pairs.append({
            "question": f"What was the subtotal amount on invoice {inv_id}?",
            "expected_answer": subtotal,
            "source_invoice_id": inv_id,
            "question_type": "subtotal_lookup"
        })

        # 4. Date Lookup
        qa_pairs.append({
            "question": f"What is the billing date for invoice {inv_id}?",
            "expected_answer": date,
            "source_invoice_id": inv_id,
            "question_type": "date_lookup"
        })

        # 5. Line items details
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
            
    # Add aggregation queries for vendors
    for v in list(vendor_invoice_counts.keys())[:10]: # Top 10 vendors
        count = str(vendor_invoice_counts[v])
        qa_pairs.append({
            "question": f"How many invoices are in the database from {v}?",
            "expected_answer": count,
            "source_invoice_id": "multiple",
            "question_type": "count_aggregation"
        })

    # Shuffle the QA pairs and select exactly 150 for our test set
    random.shuffle(qa_pairs)
    qa_selected = qa_pairs[:150]
    
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["question", "expected_answer", "source_invoice_id", "question_type"])
        writer.writeheader()
        writer.writerows(qa_selected)
        
    print(f"Successfully generated {len(qa_selected)} ground truth Q&A pairs at {output_path}")

if __name__ == "__main__":
    main()
