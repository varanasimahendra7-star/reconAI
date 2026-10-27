"""
tests/test_validation.py
------------------------
Validates CSV schema parsing, missing column detection, empty file handling,
and boundary validation logic for user-uploaded CSVs.
"""

import os
import sys
import logging
import warnings

# Suppress Streamlit bare-mode context warnings when testing helper functions
logging.getLogger("streamlit").setLevel(logging.ERROR)
warnings.filterwarnings("ignore")

# Ensure repository root is in python search path
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import app


class MockUploadedFile:
    def __init__(self, name: str, content_bytes: bytes):
        self.name = name
        self._bytes = content_bytes

    def getvalue(self) -> bytes:
        return self._bytes


def test_empty_file_rejected():
    empty_file = MockUploadedFile("empty.csv", b"")
    ok, records, err = app.parse_and_validate_csv(
        empty_file, app.REQUIRED_PAYMENT_COLS, "Payment Gateway CSV"
    )
    assert not ok, "Empty file should not pass validation"
    assert "empty" in err.lower(), f"Expected 'empty' in error, got: {err}"


def test_missing_required_columns_rejected():
    bad_csv = MockUploadedFile(
        "bad.csv",
        b"transaction_id,payment_date,customer_name\nTXN1,2024-05-01,Alice",
    )
    ok, records, err = app.parse_and_validate_csv(
        bad_csv, app.REQUIRED_PAYMENT_COLS, "Payment Gateway CSV"
    )
    assert not ok, "File with missing columns should fail validation"
    assert "missing required column" in err.lower(), f"Unexpected error format: {err}"
    assert "payment_amount" in err
    assert "payment_reference" in err
    assert "status" in err


def test_header_only_zero_rows_rejected():
    header_only_csv = MockUploadedFile(
        "header_only.csv",
        b"transaction_id,payment_date,payment_amount,customer_name,payment_reference,status\n",
    )
    ok, records, err = app.parse_and_validate_csv(
        header_only_csv, app.REQUIRED_PAYMENT_COLS, "Payment Gateway CSV"
    )
    assert not ok, "Header-only CSV with zero data rows should fail"
    assert "zero data records" in err.lower(), f"Expected 'zero data records' error, got: {err}"


def test_valid_csv_with_extra_columns_accepted():
    valid_csv = MockUploadedFile(
        "valid.csv",
        b"transaction_id,payment_date,payment_amount,customer_name,payment_reference,status,notes\n"
        b"TXN1,2024-05-01,100.0,Alice,REF1,captured,test_note\n",
    )
    ok, records, err = app.parse_and_validate_csv(
        valid_csv, app.REQUIRED_PAYMENT_COLS, "Payment Gateway CSV"
    )
    assert ok, f"Valid CSV should pass, but failed with: {err}"
    assert len(records) == 1
    assert records[0]["transaction_id"] == "TXN1"
    assert records[0]["payment_amount"] == "100.0"
    assert records[0]["customer_name"] == "Alice"


if __name__ == "__main__":
    print("Running test_validation.py...")
    test_empty_file_rejected()
    test_missing_required_columns_rejected()
    test_header_only_zero_rows_rejected()
    test_valid_csv_with_extra_columns_accepted()
    print("[PASS] All CSV schema validation tests passed successfully!")
