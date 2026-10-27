"""
tests/test_app_modes.py
-----------------------
End-to-end integration test suite using Streamlit AppTest.
Verifies Demo Mode metrics, Upload Mode interactions, in-memory reconciliation,
and guarantees zero mutation of benchmark data files on disk.
"""

import os
import sys
import hashlib
from streamlit.testing.v1 import AppTest

# Determine repo root dynamically
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

APP_PATH = os.path.join(REPO_ROOT, "app.py")

# Benchmark files to check for immutability
CANONICAL_FILES = [
    "data/payments.csv",
    "data/bank.csv",
    "data/ledger.csv",
    "data/ground_truth.csv",
    "data/reconciliation_cache.pkl",
]


def test_full_app_modes():
    print("=== Starting ReconAI AppTest Integration Suite ===")

    # 1. Snapshot SHA256 hashes of canonical files
    hashes_before = {}
    for cf in CANONICAL_FILES:
        full_path = os.path.join(REPO_ROOT, cf)
        if os.path.exists(full_path):
            with open(full_path, "rb") as f:
                hashes_before[cf] = hashlib.sha256(f.read()).hexdigest()

    # 2. Test Demo Mode (Default)
    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.run()

    assert not at.exception, f"Demo mode encountered exception: {at.exception}"

    # Verify default radio mode
    radio = at.sidebar.radio[0]
    assert radio.value == "Demo Mode (Cached Final Run)", f"Expected default Demo Mode, got {radio.value}"

    # Verify benchmark metrics
    metrics = {m.label: m.value for m in at.metric}
    print("Demo Mode Metrics:", metrics)

    assert str(metrics["Total Transactions"]) == "90"
    assert str(metrics["Deterministic Matches"]) == "68"
    assert str(metrics["Rule-Based Exceptions"]) == "10"
    assert str(metrics["AI Escalated"]) == "12"
    assert str(metrics["AI Successful"]) == "8"
    assert str(metrics["AI/System Failures"]) == "4"
    assert str(metrics["Binary Accuracy"]) == "97.8%"
    assert str(metrics["False Positives (FP)"]) == "0"
    assert str(metrics["False Negatives (FN)"]) == "2"
    assert str(metrics["Match Rate"]) == "82.2%"

    print("[PASS] Step 1: Demo Mode correctly displays all 9 canonical benchmark metrics.")

    # 3. Test Mode Toggle to Upload Mode
    at_toggle = AppTest.from_file(APP_PATH, default_timeout=30)
    at_toggle.run()
    assert at_toggle.sidebar.radio[0].value == "Demo Mode (Cached Final Run)"

    at_toggle.sidebar.radio[0].set_value("Upload CSV Data").run()
    assert at_toggle.sidebar.radio[0].value == "Upload CSV Data"
    assert len(at_toggle.file_uploader) == 3
    assert at_toggle.button[0].disabled == True

    print("[PASS] Step 2: Mode switching toggle cleanly transitions to Upload UI.")

    # 4. Test In-Memory Reconciliation on Uploaded Data
    at_up = AppTest.from_file(APP_PATH, default_timeout=30)
    at_up.run()
    at_up.sidebar.radio[0].set_value("Upload CSV Data").run()

    pay_csv = (
        b"transaction_id,payment_date,payment_amount,customer_name,payment_reference,status\n"
        b"TXN_UP_1,2024-05-01,1000.00,Alice Smith,PAY111111,captured\n"
        b"TXN_UP_2,2024-05-01,2000.00,Bob Jones,PAY222222,captured\n"
        b"TXN_UP_3,2024-05-01,3000.00,Charlie Brown,PAY333333,captured\n"
    )

    bank_csv = (
        b"bank_id,settlement_date,settlement_amount,description,bank_reference\n"
        b"BNK_UP_1,2024-05-02,1000.00,Settlement PAY111111 Alice Smith,PAY111111\n"
        b"BNK_UP_2,2024-05-02,1960.00,Settlement PAY222222 Bob Jones,PAY222222\n"
    )

    ledger_csv = (
        b"ledger_id,ledger_date,ledger_amount,customer_name,ledger_reference\n"
        b"LED_UP_1,2024-05-01,1000.00,Alice Smith,PAY111111\n"
        b"LED_UP_2,2024-05-01,2000.00,Bob Jones,PAY222222\n"
        b"LED_UP_3,2024-05-01,3000.00,Charlie Brown,PAY333333\n"
    )

    at_up.file_uploader[0].upload("payments.csv", pay_csv)
    at_up.file_uploader[1].upload("bank.csv", bank_csv)
    at_up.file_uploader[2].upload("ledger.csv", ledger_csv)
    at_up.run()

    # Verify Run button is enabled
    run_btn = at_up.button[0]
    assert run_btn.disabled == False, "Expected Run button to be enabled"

    # Click Run Reconciliation
    run_btn.click().run()
    assert not at_up.exception, f"Running reconciliation threw exception: {at_up.exception}"

    # Verify operational metrics for uploaded dataset
    up_metrics = {m.label: m.value for m in at_up.metric}
    print("Upload Mode Metrics:", up_metrics)

    assert str(up_metrics["Total Transactions"]) == "3"
    assert str(up_metrics["Deterministic Matches"]) == "2"
    assert str(up_metrics["Rule-Based Exceptions"]) == "1"
    assert str(up_metrics["Match Rate"]) == "66.7%"
    assert str(up_metrics["AI Escalated"]) == "0"
    assert str(up_metrics["AI Successful"]) == "0"
    assert str(up_metrics["AI/System Failures"]) == "0"

    # Verify absence of Ground Truth metrics in Upload Mode
    assert "Binary Accuracy" not in up_metrics, "Binary Accuracy should not appear without ground truth"
    assert "False Positives (FP)" not in up_metrics, "FP metric should not appear without ground truth"
    assert "False Negatives (FN)" not in up_metrics, "FN metric should not appear without ground truth"

    # Verify tables rendered
    assert len(at_up.dataframe) >= 2, f"Expected tables rendered, found {len(at_up.dataframe)}"

    print("[PASS] Step 3: In-memory reconciliation on uploaded CSVs succeeded with accurate metrics.")

    # 5. Verify Disk Immutability (zero file modifications)
    for cf, orig_hash in hashes_before.items():
        full_path = os.path.join(REPO_ROOT, cf)
        with open(full_path, "rb") as f:
            new_hash = hashlib.sha256(f.read()).hexdigest()
        assert new_hash == orig_hash, f"CRITICAL: {cf} was modified! Hash before {orig_hash} != {new_hash}"

    print("[PASS] Step 4: All canonical data files remain 100% untouched and identical.")
    print("\n=== ALL APP TESTS PASSED SUCCESSFULLY! ===")


if __name__ == "__main__":
    test_full_app_modes()
