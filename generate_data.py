"""
generate_data.py
----------------
Generates synthetic financial records for ReconAI reconciliation demo.

Produces:
  data/payments.csv      -- Payment gateway records
  data/bank.csv          -- Bank settlement records
  data/ledger.csv        -- Merchant internal ledger records
  data/ground_truth.csv  -- Answer key for evaluation ONLY

IMPORTANT:
  ground_truth.csv is ONLY for the evaluator.
  The matching engine and AI agent must NEVER read or reference it.

Fixed random seed ensures full reproducibility.
"""

import os
import random
import string
import csv
from datetime import date, timedelta

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

RANDOM_SEED = 42
NUM_BASE_TRANSACTIONS = 90          # ~90 root payments; total rows differ
GATEWAY_FEE_PCT = 0.02              # 2 % gateway fee deduction
SETTLEMENT_WINDOW_DAYS = 3          # Bank may settle up to N days after payment

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "data")

# Edge-case counts (must sum to <= NUM_BASE_TRANSACTIONS)
EDGE_CASE_COUNTS = {
    "EXACT_MATCH":              45,   # Clean three-way match
    "NAME_VARIATION":           10,   # Name/description differs across sources
    "DATE_DRIFT":               8,    # Settlement date drifts 1-3 days
    "FEE_DEDUCTION":            8,    # Bank amount = payment minus gateway fee
    "DUPLICATE_BANK":           5,    # Two bank entries for one payment
    "MISSING_BANK":             7,    # No bank record at all
    "AMOUNT_MISMATCH":          7,    # Unexplained amount difference
}
assert sum(EDGE_CASE_COUNTS.values()) == NUM_BASE_TRANSACTIONS, (
    f"Edge case counts sum to {sum(EDGE_CASE_COUNTS.values())}, expected {NUM_BASE_TRANSACTIONS}"
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

random.seed(RANDOM_SEED)


def _rand_ref(prefix, length=8):
    """Generate a deterministic-looking reference code."""
    chars = string.ascii_uppercase + string.digits
    return prefix + "".join(random.choices(chars, k=length))


def _rand_amount(lo=500.0, hi=50000.0):
    """Random amount rounded to 2 dp."""
    return round(random.uniform(lo, hi), 2)


def _rand_date(start=date(2024, 1, 1), end=date(2024, 6, 30)):
    """Random date in a range."""
    delta = (end - start).days
    return start + timedelta(days=random.randint(0, delta))


FIRST_NAMES = [
    "Rahul", "Priya", "Amit", "Sneha", "Vikram", "Ananya", "Rohan",
    "Neha", "Arjun", "Kavya", "Siddharth", "Pooja", "Karan", "Meera",
    "Raj", "Divya", "Suresh", "Lakshmi", "Manish", "Aarti", "Deepak",
    "Sunita", "Nikhil", "Rashmi", "Gaurav", "Smita", "Arun", "Geeta",
]
LAST_NAMES = [
    "Sharma", "Verma", "Patel", "Mehta", "Gupta", "Reddy", "Nair",
    "Iyer", "Joshi", "Singh", "Kumar", "Rao", "Shah", "Kapoor",
    "Pillai", "Bose", "Chatterjee", "Malhotra", "Choudhary", "Mishra",
]


def _rand_name():
    return f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}"


def _name_variations(name):
    """Return plausible name variants for the same person."""
    parts = name.split()
    initial = f"{parts[0][0]}. {parts[-1]}" if len(parts) >= 2 else name
    return [
        name,
        name.lower(),
        name.upper(),
        f"RZP {name}",
        f"NEFT/{name.upper()}",
        initial,
    ]


def _bank_description(name, ref, variant_style="plain"):
    styles = {
        "plain":   f"Settlement for {name} Ref:{ref}",
        "rzp":     f"RZP Settlement {ref} {name.upper()}",
        "neft":    f"NEFT/{name.upper()}/{ref}",
        "abbrev":  f"Setl {name.split()[0]} {ref}",
        "refonly": f"BANK CREDIT {ref}",
    }
    return styles.get(variant_style, styles["plain"])


# ---------------------------------------------------------------------------
# Record builders
# ---------------------------------------------------------------------------

payment_counter = 0
bank_counter = 0
ledger_counter = 0


def _next_txn_id():
    global payment_counter
    payment_counter += 1
    return f"TXN{payment_counter:04d}"


def _next_bank_id():
    global bank_counter
    bank_counter += 1
    return f"BNK{bank_counter:04d}"


def _next_ledger_id():
    global ledger_counter
    ledger_counter += 1
    return f"LDG{ledger_counter:04d}"


# ---------------------------------------------------------------------------
# Scenario generators
# Each returns: (payment_row, [bank_rows], ledger_row, gt_row)
# ---------------------------------------------------------------------------

def make_exact_match():
    txn_id   = _next_txn_id()
    name     = _rand_name()
    amount   = _rand_amount()
    pay_date = _rand_date()
    pay_ref  = _rand_ref("PAY")

    payment = {
        "transaction_id":    txn_id,
        "payment_date":      str(pay_date),
        "payment_amount":    amount,
        "customer_name":     name,
        "payment_reference": pay_ref,
        "status":            "CAPTURED",
    }

    bank_id = _next_bank_id()
    bank = [{
        "bank_id":           bank_id,
        "settlement_date":   str(pay_date),
        "settlement_amount": amount,
        "description":       f"Settlement {pay_ref} {name}",
        "bank_reference":    pay_ref,
    }]

    ledger_id = _next_ledger_id()
    ledger = {
        "ledger_id":         ledger_id,
        "ledger_date":       str(pay_date),
        "ledger_amount":     amount,
        "customer_name":     name,
        "ledger_reference":  pay_ref,
    }

    gt = {
        "transaction_id":        txn_id,
        "ground_truth_decision": "MATCH",
        "ground_truth_reason":   "Exact three-way match on reference, amount, and date",
        "expected_bank_id":      bank_id,
        "expected_ledger_id":    ledger_id,
        "edge_case_type":        "EXACT_MATCH",
    }

    return payment, bank, ledger, gt


def make_name_variation():
    txn_id   = _next_txn_id()
    name     = _rand_name()
    amount   = _rand_amount()
    pay_date = _rand_date()
    pay_ref  = _rand_ref("PAY")

    payment = {
        "transaction_id":    txn_id,
        "payment_date":      str(pay_date),
        "payment_amount":    amount,
        "customer_name":     name,
        "payment_reference": pay_ref,
        "status":            "CAPTURED",
    }

    variants = _name_variations(name)
    bank_name_variant = random.choice(variants[1:])
    bank_desc_style   = random.choice(["rzp", "neft", "abbrev"])

    bank_id = _next_bank_id()
    bank = [{
        "bank_id":           bank_id,
        "settlement_date":   str(pay_date + timedelta(days=random.randint(0, 2))),
        "settlement_amount": amount,
        "description":       _bank_description(bank_name_variant, pay_ref, bank_desc_style),
        "bank_reference":    pay_ref,
    }]

    ledger_id = _next_ledger_id()
    ledger_name = random.choice(variants[:3])
    ledger = {
        "ledger_id":         ledger_id,
        "ledger_date":       str(pay_date),
        "ledger_amount":     amount,
        "customer_name":     ledger_name,
        "ledger_reference":  pay_ref,
    }

    gt = {
        "transaction_id":        txn_id,
        "ground_truth_decision": "MATCH",
        "ground_truth_reason":   (
            f"Name varies across sources but reference, amount, and date are consistent"
        ),
        "expected_bank_id":      bank_id,
        "expected_ledger_id":    ledger_id,
        "edge_case_type":        "NAME_VARIATION",
    }

    return payment, bank, ledger, gt


def make_date_drift():
    txn_id   = _next_txn_id()
    name     = _rand_name()
    amount   = _rand_amount()
    pay_date = _rand_date()
    pay_ref  = _rand_ref("PAY")
    drift    = random.randint(1, SETTLEMENT_WINDOW_DAYS)

    payment = {
        "transaction_id":    txn_id,
        "payment_date":      str(pay_date),
        "payment_amount":    amount,
        "customer_name":     name,
        "payment_reference": pay_ref,
        "status":            "CAPTURED",
    }

    bank_id = _next_bank_id()
    bank = [{
        "bank_id":           bank_id,
        "settlement_date":   str(pay_date + timedelta(days=drift)),
        "settlement_amount": amount,
        "description":       f"Settlement {pay_ref} {name}",
        "bank_reference":    pay_ref,
    }]

    ledger_id = _next_ledger_id()
    ledger = {
        "ledger_id":         ledger_id,
        "ledger_date":       str(pay_date),
        "ledger_amount":     amount,
        "customer_name":     name,
        "ledger_reference":  pay_ref,
    }

    gt = {
        "transaction_id":        txn_id,
        "ground_truth_decision": "MATCH",
        "ground_truth_reason":   (
            f"Settlement date drifted {drift} day(s) from payment date -- "
            f"within configured window of {SETTLEMENT_WINDOW_DAYS} days"
        ),
        "expected_bank_id":      bank_id,
        "expected_ledger_id":    ledger_id,
        "edge_case_type":        "DATE_DRIFT",
    }

    return payment, bank, ledger, gt


def make_fee_deduction():
    txn_id   = _next_txn_id()
    name     = _rand_name()
    amount   = _rand_amount()
    pay_date = _rand_date()
    pay_ref  = _rand_ref("PAY")
    fee      = round(amount * GATEWAY_FEE_PCT, 2)
    settled  = round(amount - fee, 2)
    drift    = random.randint(0, SETTLEMENT_WINDOW_DAYS)

    payment = {
        "transaction_id":    txn_id,
        "payment_date":      str(pay_date),
        "payment_amount":    amount,
        "customer_name":     name,
        "payment_reference": pay_ref,
        "status":            "CAPTURED",
    }

    bank_id = _next_bank_id()
    bank = [{
        "bank_id":           bank_id,
        "settlement_date":   str(pay_date + timedelta(days=drift)),
        "settlement_amount": settled,
        "description":       f"Settlement {pay_ref} {name} (net of fees)",
        "bank_reference":    pay_ref,
    }]

    ledger_id = _next_ledger_id()
    ledger = {
        "ledger_id":         ledger_id,
        "ledger_date":       str(pay_date),
        "ledger_amount":     amount,
        "customer_name":     name,
        "ledger_reference":  pay_ref,
    }

    gt = {
        "transaction_id":        txn_id,
        "ground_truth_decision": "MATCH",
        "ground_truth_reason":   (
            f"Bank settlement = payment minus {GATEWAY_FEE_PCT*100:.0f}% gateway fee"
        ),
        "expected_bank_id":      bank_id,
        "expected_ledger_id":    ledger_id,
        "edge_case_type":        "FEE_DEDUCTION",
    }

    return payment, bank, ledger, gt


def make_duplicate_bank():
    txn_id   = _next_txn_id()
    name     = _rand_name()
    amount   = _rand_amount()
    pay_date = _rand_date()
    pay_ref  = _rand_ref("PAY")

    payment = {
        "transaction_id":    txn_id,
        "payment_date":      str(pay_date),
        "payment_amount":    amount,
        "customer_name":     name,
        "payment_reference": pay_ref,
        "status":            "CAPTURED",
    }

    bank_id1 = _next_bank_id()
    bank_id2 = _next_bank_id()

    bank = [
        {
            "bank_id":           bank_id1,
            "settlement_date":   str(pay_date + timedelta(days=1)),
            "settlement_amount": amount,
            "description":       f"Settlement {pay_ref} {name}",
            "bank_reference":    pay_ref,
        },
        {
            "bank_id":           bank_id2,
            "settlement_date":   str(pay_date + timedelta(days=2)),
            "settlement_amount": amount,
            "description":       f"Settlement {pay_ref} {name} DUP",
            "bank_reference":    pay_ref,
        },
    ]

    ledger_id = _next_ledger_id()
    ledger = {
        "ledger_id":         ledger_id,
        "ledger_date":       str(pay_date),
        "ledger_amount":     amount,
        "customer_name":     name,
        "ledger_reference":  pay_ref,
    }

    gt = {
        "transaction_id":        txn_id,
        "ground_truth_decision": "EXCEPTION",
        "ground_truth_reason":   (
            f"Two bank entries ({bank_id1}, {bank_id2}) both reference {pay_ref} "
            "with same amount -- duplicate settlement must be investigated"
        ),
        "expected_bank_id":      f"{bank_id1}|{bank_id2}",
        "expected_ledger_id":    ledger_id,
        "edge_case_type":        "DUPLICATE_BANK",
    }

    return payment, bank, ledger, gt


def make_missing_bank():
    txn_id   = _next_txn_id()
    name     = _rand_name()
    amount   = _rand_amount()
    pay_date = _rand_date()
    pay_ref  = _rand_ref("PAY")

    payment = {
        "transaction_id":    txn_id,
        "payment_date":      str(pay_date),
        "payment_amount":    amount,
        "customer_name":     name,
        "payment_reference": pay_ref,
        "status":            "CAPTURED",
    }

    bank = []

    ledger_id = _next_ledger_id()
    ledger = {
        "ledger_id":         ledger_id,
        "ledger_date":       str(pay_date),
        "ledger_amount":     amount,
        "customer_name":     name,
        "ledger_reference":  pay_ref,
    }

    gt = {
        "transaction_id":        txn_id,
        "ground_truth_decision": "EXCEPTION",
        "ground_truth_reason":   "No bank settlement record found for this payment",
        "expected_bank_id":      "",
        "expected_ledger_id":    ledger_id,
        "edge_case_type":        "MISSING_BANK",
    }

    return payment, bank, ledger, gt


def make_amount_mismatch():
    txn_id   = _next_txn_id()
    name     = _rand_name()
    amount   = _rand_amount()
    pay_date = _rand_date()
    pay_ref  = _rand_ref("PAY")

    offset_pct = random.uniform(0.03, 0.15)
    if random.random() < 0.5:
        bank_amount = round(amount * (1 - offset_pct), 2)
    else:
        bank_amount = round(amount * (1 + offset_pct), 2)

    payment = {
        "transaction_id":    txn_id,
        "payment_date":      str(pay_date),
        "payment_amount":    amount,
        "customer_name":     name,
        "payment_reference": pay_ref,
        "status":            "CAPTURED",
    }

    bank_id = _next_bank_id()
    bank = [{
        "bank_id":           bank_id,
        "settlement_date":   str(pay_date + timedelta(days=random.randint(0, 2))),
        "settlement_amount": bank_amount,
        "description":       f"Settlement {pay_ref} {name}",
        "bank_reference":    pay_ref,
    }]

    ledger_id = _next_ledger_id()
    ledger = {
        "ledger_id":         ledger_id,
        "ledger_date":       str(pay_date),
        "ledger_amount":     amount,
        "customer_name":     name,
        "ledger_reference":  pay_ref,
    }

    diff_pct = round(abs(amount - bank_amount) / amount * 100, 1)

    gt = {
        "transaction_id":        txn_id,
        "ground_truth_decision": "EXCEPTION",
        "ground_truth_reason":   (
            f"Amount mismatch of {diff_pct}% between payment and bank -- "
            f"not explainable by {GATEWAY_FEE_PCT*100:.0f}% gateway fee"
        ),
        "expected_bank_id":      bank_id,
        "expected_ledger_id":    ledger_id,
        "edge_case_type":        "AMOUNT_MISMATCH",
    }

    return payment, bank, ledger, gt


# ---------------------------------------------------------------------------
# Main generation
# ---------------------------------------------------------------------------

SCENARIO_FUNCS = {
    "EXACT_MATCH":     make_exact_match,
    "NAME_VARIATION":  make_name_variation,
    "DATE_DRIFT":      make_date_drift,
    "FEE_DEDUCTION":   make_fee_deduction,
    "DUPLICATE_BANK":  make_duplicate_bank,
    "MISSING_BANK":    make_missing_bank,
    "AMOUNT_MISMATCH": make_amount_mismatch,
}


def generate_all():
    scenarios = []
    for edge_type, count in EDGE_CASE_COUNTS.items():
        scenarios.extend([edge_type] * count)
    random.shuffle(scenarios)

    all_payments   = []
    all_bank       = []
    all_ledger     = []
    all_gt         = []
    edge_case_dist = {}

    for edge_type in scenarios:
        func = SCENARIO_FUNCS[edge_type]
        payment, bank_rows, ledger, gt = func()

        all_payments.append(payment)
        all_bank.extend(bank_rows)
        all_ledger.append(ledger)
        all_gt.append(gt)

        edge_case_dist[edge_type] = edge_case_dist.get(edge_type, 0) + 1

    return all_payments, all_bank, all_ledger, all_gt, edge_case_dist


def write_csv(rows, filepath):
    if not rows:
        print(f"  [WARN] No rows to write for {filepath}")
        return
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    print(f"  Written: {filepath}  ({len(rows)} rows)")


def main():
    print("=" * 60)
    print("ReconAI -- Synthetic Data Generator")
    print("=" * 60)
    print(f"Seed: {RANDOM_SEED}")
    print(f"Base transactions: {NUM_BASE_TRANSACTIONS}")
    print(f"Gateway fee: {GATEWAY_FEE_PCT*100:.0f}%")
    print(f"Settlement window: {SETTLEMENT_WINDOW_DAYS} days")
    print()

    payments, banks, ledgers, ground_truth, dist = generate_all()

    print("Generating CSV files ...")
    write_csv(payments,     os.path.join(OUTPUT_DIR, "payments.csv"))
    write_csv(banks,        os.path.join(OUTPUT_DIR, "bank.csv"))
    write_csv(ledgers,      os.path.join(OUTPUT_DIR, "ledger.csv"))
    write_csv(ground_truth, os.path.join(OUTPUT_DIR, "ground_truth.csv"))

    print()
    print("-" * 60)
    print("RECORD COUNTS")
    print("-" * 60)
    print(f"  Payments (payment gateway records): {len(payments)}")
    print(f"  Bank entries (settlement records):  {len(banks)}")
    print(f"  Ledger entries:                     {len(ledgers)}")
    print(f"  Ground truth rows:                  {len(ground_truth)}")

    print()
    print("-" * 60)
    print("EDGE-CASE DISTRIBUTION")
    print("-" * 60)
    match_total     = 0
    exception_total = 0
    for edge_type, count in sorted(dist.items()):
        sample_gt = next(g for g in ground_truth if g["edge_case_type"] == edge_type)
        decision  = sample_gt["ground_truth_decision"]
        flag      = "MATCH    " if decision == "MATCH" else "EXCEPTION"
        print(f"  [{flag}]  {edge_type:<22}  {count:>3} records")
        if decision == "MATCH":
            match_total += count
        else:
            exception_total += count

    print(f"\n  Expected ground-truth MATCH count:      {match_total}")
    print(f"  Expected ground-truth EXCEPTION count:  {exception_total}")

    print()
    print("-" * 60)
    print("SAMPLE ROWS")
    print("-" * 60)

    def show_sample(label, rows, n=3):
        print(f"\n  [{label}] -- first {n} rows:")
        for row in rows[:n]:
            for k, v in row.items():
                print(f"    {k:<24}: {v}")
            print()

    show_sample("payments.csv", payments, 3)
    show_sample("bank.csv",     banks,    3)
    show_sample("ledger.csv",   ledgers,  3)

    print("-" * 60)
    print("GROUND TRUTH EXAMPLES (one per edge case type)")
    print("-" * 60)
    seen_types = set()
    for gt in ground_truth:
        et = gt["edge_case_type"]
        if et not in seen_types:
            seen_types.add(et)
            print(f"\n  Edge type: {et}")
            for k, v in gt.items():
                print(f"    {k:<26}: {v}")
        if len(seen_types) >= len(EDGE_CASE_COUNTS):
            break

    print()
    print("-" * 60)
    print("CROSS-SOURCE EXAMPLES")
    print("-" * 60)

    payments_map  = {p["transaction_id"]: p for p in payments}
    banks_by_ref  = {}
    for b in banks:
        banks_by_ref.setdefault(b["bank_reference"], []).append(b)
    ledger_by_ref = {l["ledger_reference"]: l for l in ledgers}

    def show_full(label, gt_row):
        print(f"\n  === {label} ===")
        txn_id = gt_row["transaction_id"]
        pay    = payments_map.get(txn_id, {})
        ref    = pay.get("payment_reference", "")
        bc     = banks_by_ref.get(ref, [])
        lr     = ledger_by_ref.get(ref, {})
        print(f"  PAYMENT : {pay}")
        for i, b in enumerate(bc):
            print(f"  BANK[{i}]  : {b}")
        if not bc:
            print("  BANK    : (none)")
        print(f"  LEDGER  : {lr}")
        print(f"  GT      : {gt_row}")

    match_gt     = next((g for g in ground_truth if g["ground_truth_decision"] == "MATCH"), None)
    exception_gt = next((g for g in ground_truth if g["ground_truth_decision"] == "EXCEPTION"), None)

    if match_gt:
        show_full("MATCH EXAMPLE", match_gt)
    if exception_gt:
        show_full("EXCEPTION EXAMPLE", exception_gt)

    print()
    print("=" * 60)
    print("Phase 1 complete. Data ready in ./data/")
    print("=" * 60)


if __name__ == "__main__":
    main()
