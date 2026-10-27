"""
tests/test_pipeline.py
----------------------
Automated test suite verifying the multi-source reconciliation pipeline logic
in-memory without disk side-effects.
"""

import os
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from reconai import pipeline


def test_in_memory_deterministic_rules():
    """
    Verifies that pipeline.reconcile_records successfully handles:
      - Rule 1: Exact Reference & Amount Match
      - Rule 2: Fee-Adjusted Net Settlement Match (2% fee)
      - Rule 4: Missing Bank Record in Settlement Window
    """
    payments = [
        {
            "transaction_id": "TXN_TEST_1",
            "payment_date": "2024-05-01",
            "payment_amount": "1000.00",
            "customer_name": "Alice Smith",
            "payment_reference": "PAY111111",
            "status": "captured",
        },
        {
            "transaction_id": "TXN_TEST_2",
            "payment_date": "2024-05-01",
            "payment_amount": "2000.00",
            "customer_name": "Bob Jones",
            "payment_reference": "PAY222222",
            "status": "captured",
        },
        {
            "transaction_id": "TXN_TEST_3",
            "payment_date": "2024-05-01",
            "payment_amount": "3000.00",
            "customer_name": "Charlie Brown",
            "payment_reference": "PAY333333",
            "status": "captured",
        },
    ]

    banks = [
        {
            "bank_id": "BNK_1",
            "settlement_date": "2024-05-02",
            "settlement_amount": "1000.00",
            "description": "Settlement PAY111111 Alice Smith",
            "bank_reference": "PAY111111",
        },
        {
            "bank_id": "BNK_2",
            "settlement_date": "2024-05-02",
            "settlement_amount": "1960.00",  # 2000 - 2% gateway fee = 1960.00
            "description": "Settlement PAY222222 Bob Jones",
            "bank_reference": "PAY222222",
        },
    ]

    ledgers = [
        {
            "ledger_id": "LED_1",
            "ledger_date": "2024-05-01",
            "ledger_amount": "1000.00",
            "customer_name": "Alice Smith",
            "ledger_reference": "PAY111111",
        },
        {
            "ledger_id": "LED_2",
            "ledger_date": "2024-05-01",
            "ledger_amount": "2000.00",
            "customer_name": "Bob Jones",
            "ledger_reference": "PAY222222",
        },
        {
            "ledger_id": "LED_3",
            "ledger_date": "2024-05-01",
            "ledger_amount": "3000.00",
            "customer_name": "Charlie Brown",
            "ledger_reference": "PAY333333",
        },
    ]

    res = pipeline.reconcile_records(payments, banks, ledgers)
    summary = res["summary"]
    results_map = {r["transaction_id"]: r for r in res["final_results"]}

    # Verify Summary counts
    assert summary["total_records"] == 3
    assert summary["total_deterministic_matches"] == 2
    assert summary["matched_by_rule"] == 1
    assert summary["matched_with_fee"] == 1
    assert summary["rule_exceptions"] == 1
    assert summary["final_matches"] == 2
    assert summary["final_exceptions"] == 1

    # Verify Transaction 1: Rule 1 Exact Match
    r1 = results_map["TXN_TEST_1"]
    assert r1["final_decision"] == "MATCH"
    assert r1["resolution_method"] == "MATCHED_BY_RULE"
    assert r1["matched_bank_id"] == "BNK_1"

    # Verify Transaction 2: Rule 2 Fee Adjusted Match
    r2 = results_map["TXN_TEST_2"]
    assert r2["final_decision"] == "MATCH"
    assert r2["resolution_method"] == "MATCHED_WITH_FEE"
    assert r2["matched_bank_id"] == "BNK_2"

    # Verify Transaction 3: Rule 4 Missing Record Exception
    r3 = results_map["TXN_TEST_3"]
    assert r3["final_decision"] == "EXCEPTION"
    assert r3["exception_type"] == "MISSING_RECORD"
    assert r3["resolution_method"] == "NO_BANK_RECORD"

    print("[PASS] test_in_memory_deterministic_rules passed.")


def test_duplicate_settlement_detection():
    """
    Verifies that Rule 3 correctly isolates duplicate settlement candidates as an EXCEPTION.
    """
    payments = [
        {
            "transaction_id": "TXN_DUP",
            "payment_date": "2024-05-01",
            "payment_amount": "1500.00",
            "customer_name": "Dave Miller",
            "payment_reference": "PAY444444",
            "status": "captured",
        }
    ]

    # Two bank records with the same reference
    banks = [
        {
            "bank_id": "BNK_DUP_A",
            "settlement_date": "2024-05-02",
            "settlement_amount": "1500.00",
            "description": "Settlement PAY444444 Dave",
            "bank_reference": "PAY444444",
        },
        {
            "bank_id": "BNK_DUP_B",
            "settlement_date": "2024-05-02",
            "settlement_amount": "1500.00",
            "description": "Duplicate PAY444444 Dave",
            "bank_reference": "PAY444444",
        },
    ]

    ledgers = [
        {
            "ledger_id": "LED_DUP",
            "ledger_date": "2024-05-01",
            "ledger_amount": "1500.00",
            "customer_name": "Dave Miller",
            "ledger_reference": "PAY444444",
        }
    ]

    res = pipeline.reconcile_records(payments, banks, ledgers)
    r = res["final_results"][0]
    assert r["final_decision"] == "EXCEPTION"
    assert r["exception_type"] == "DUPLICATE_SETTLEMENT"
    assert r["resolution_method"] == "DUPLICATE_CANDIDATE"
    print("[PASS] test_duplicate_settlement_detection passed.")


if __name__ == "__main__":
    print("=== Running ReconAI Pipeline Tests ===")
    test_in_memory_deterministic_rules()
    test_duplicate_settlement_detection()
    print("=== All Pipeline Tests Passed Successfully! ===")
