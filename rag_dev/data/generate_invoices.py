import os
import json
import random
from faker import Faker

fake = Faker()
# Set seed for reproducibility
random.seed(42)
Faker.seed(42)

VENDORS = [
    "TechCorp Sdn Bhd", "GlobalSupply Pte Ltd", "OfficeMart Trading",
    "PrintPro Solutions", "CloudNet Services", "FreshFood Distribution",
    "Apex Engineering", "BuildMart Materials", "Swift Logistics",
    "SecureGuard Systems", "Optima Consultants", "Pinnacle Designs",
    "Prime Catering", "Elite Cleaners", "Zenith Software",
    "Aero Industries", "Delta Energy", "Nexus Utilities",
    "Stellar Media", "Quantum Labs", "Summit Hardware"
]

PRODUCTS = [
    ("Laptop", 800, 2500), ("Monitor", 200, 800), ("Keyboard", 20, 80),
    ("Office Chair", 100, 500), ("Printer Ink", 15, 60), ("A4 Paper (Box)", 8, 25),
    ("Consulting Hour", 150, 300), ("Software License", 50, 400),
    ("Desk Organizer", 15, 45), ("Whiteboard", 40, 120), ("Extension Cord", 10, 30),
    ("Coffee Beans (Bag)", 25, 60), ("Cleaning Supplies Kit", 30, 90),
    ("First Aid Kit", 20, 50), ("Network Cable (10m)", 12, 35),
    ("Server Rack", 500, 1500), ("UPS Backup Unit", 120, 450)
]

def generate_invoice(idx: int) -> dict:
    vendor = random.choice(VENDORS)
    num_items = random.randint(1, 6)
    
    # Pick unique products for this invoice to prevent duplicates in line items
    picked_products = random.sample(PRODUCTS, num_items)
    
    line_items = []
    for name, lo, hi in picked_products:
        qty = random.randint(1, 15)
        price = round(random.uniform(lo, hi), 2)
        line_items.append({
            "description": name,
            "qty": qty,
            "unit_price": price,
            "amount": round(qty * price, 2)
        })
        
    subtotal = round(sum(i["amount"] for i in line_items), 2)
    tax_rate = random.choice([0.06, 0.08, 0.10])
    tax = round(subtotal * tax_rate, 2)
    
    return {
        "invoice_id": f"INV-{2025 + idx // 100}-{idx:04d}",
        "vendor": vendor,
        "date": fake.date_between(start_date="-1y", end_date="today").isoformat(),
        "buyer": fake.company(),
        "buyer_address": fake.address().replace("\n", ", "),
        "line_items": line_items,
        "subtotal": subtotal,
        "tax_rate": f"{tax_rate*100:.0f}%",
        "tax": tax,
        "grand_total": round(subtotal + tax, 2),
        "currency": random.choice(["MYR", "USD", "SGD"]),
        "payment_terms": random.choice(["Net 30", "Net 60", "Due on Receipt"]),
    }

def main():
    os.makedirs("data", exist_ok=True)
    invoices = [generate_invoice(i) for i in range(1, 201)]
    
    output_path = "data/invoices.json"
    with open(output_path, "w") as f:
        json.dump(invoices, f, indent=2)
        
    print(f"Successfully generated {len(invoices)} invoices at {output_path}")

if __name__ == "__main__":
    main()
