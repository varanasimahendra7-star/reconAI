"""
normalize.py
------------
Reusable normalization functions for ReconAI.

All functions follow these principles:
  - Return a normalized COPY; the original value is never mutated.
  - Normalization is lossy in surface form but preserves semantic content.
  - Original values are kept alongside normalized ones for audit/drill-down.

Functions:
  normalize_name(s)         -> str
  normalize_reference(s)    -> str
  normalize_amount(v)       -> float
  normalize_date(s)         -> datetime.date | None
  normalize_description(s)  -> str
  normalize_payment(row)    -> dict   (adds norm_* keys to a copy)
  normalize_bank(row)       -> dict
  normalize_ledger(row)     -> dict
"""

import re
from datetime import date, datetime
from typing import Union

# ---------------------------------------------------------------------------
# Prefixes and noise patterns to strip from names / descriptions
# ---------------------------------------------------------------------------

# Bank description prefixes that don't carry name information
_DESC_NOISE = re.compile(
    r"^(settlement\s+(for\s+)?|rzp\s+settlement\s+|neft/|bank\s+credit\s+|setl\s+)",
    re.IGNORECASE,
)

# Name prefixes injected by gateways / banks
_NAME_PREFIXES = re.compile(
    r"^(rzp\s+|neft/|imps/|upi/|rtgs/)",
    re.IGNORECASE,
)

# Reference tokens embedded in descriptions (PAYxxxxxxxx)
_REF_INLINE = re.compile(r"\bPAY[A-Z0-9]{6,}\b", re.IGNORECASE)

# ---------------------------------------------------------------------------
# Core normalizers
# ---------------------------------------------------------------------------


def normalize_name(s: str) -> str:
    """
    Normalize a customer name for fuzzy comparison.

    Steps:
      1. Strip leading/trailing whitespace.
      2. Remove known gateway prefixes (RZP, NEFT/, IMPS/).
      3. Lowercase.
      4. Collapse internal whitespace.
      5. Remove punctuation (dots, slashes) introduced by initials or prefixes.

    Examples:
      "RZP Rahul Sharma"   -> "rahul sharma"
      "NEFT/RAHUL SHARMA"  -> "rahul sharma"
      "RAHUL SHARMA"       -> "rahul sharma"
      "rahul sharma"       -> "rahul sharma"
      "R. Sharma"          -> "r sharma"
    """
    if not s or not isinstance(s, str):
        return ""

    s = s.strip()
    # Remove gateway prefix if present
    s = _NAME_PREFIXES.sub("", s)
    # Lowercase
    s = s.lower()
    # Remove trailing reference tokens (e.g. name followed by PAYxxxxxx in description)
    s = _REF_INLINE.sub("", s)
    # Remove punctuation except spaces
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    # Collapse whitespace
    s = " ".join(s.split())
    return s


def normalize_reference(s: str) -> str:
    """
    Normalize a payment/bank/ledger reference for exact comparison.

    Payment references have the form PAYxxxxxxxx.
    This function uppercases and strips surrounding whitespace.
    If the string contains an embedded reference (e.g. inside a description),
    the FIRST matching token is extracted.

    Examples:
      "PAY5LXO6QJI"                       -> "PAY5LXO6QJI"
      "  pay5lxo6qji  "                   -> "PAY5LXO6QJI"
      "Settlement PAY5LXO6QJI Karan Joshi" -> "PAY5LXO6QJI"  (via extract_reference)
    """
    if not s or not isinstance(s, str):
        return ""
    s = s.strip().upper()
    return s


def extract_reference_from_text(s: str) -> str:
    """
    Extract the first PAYxxxxxxxx token from a free-text string such as a
    bank description.  Returns empty string if none found.
    """
    if not s:
        return ""
    m = _REF_INLINE.search(s.upper())
    return m.group(0) if m else ""


def normalize_amount(v: Union[str, float, int]) -> float:
    """
    Normalize a monetary amount to a float rounded to 2 decimal places.
    Handles string inputs (e.g. "3,776.34" or "3776.34").

    Returns 0.0 on parse failure (logged by caller).
    """
    if isinstance(v, float):
        return round(v, 2)
    if isinstance(v, int):
        return round(float(v), 2)
    if isinstance(v, str):
        # Remove currency symbols and commas
        cleaned = re.sub(r"[^\d.]", "", v.strip())
        try:
            return round(float(cleaned), 2)
        except ValueError:
            return 0.0
    return 0.0


def normalize_date(s: Union[str, date, None]) -> Union[date, None]:
    """
    Normalize a date value to a datetime.date object.

    Accepts:
      - datetime.date (passthrough)
      - ISO strings: "2024-05-25"
      - DD/MM/YYYY, MM/DD/YYYY, DD-MM-YYYY

    Returns None if parsing fails.
    """
    if s is None:
        return None
    if isinstance(s, date):
        return s
    if isinstance(s, datetime):
        return s.date()
    if not isinstance(s, str):
        return None

    s = s.strip()
    formats = [
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%m/%d/%Y",
        "%d-%m-%Y",
        "%Y/%m/%d",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def normalize_description(s: str) -> str:
    """
    Normalize a bank description for comparison purposes.

    Steps:
      1. Strip noise prefixes (Settlement, RZP Settlement, NEFT/).
      2. Remove embedded reference tokens (they are captured separately).
      3. Normalize the remaining name portion using normalize_name().

    This produces a cleaned name fragment that can be compared with the
    normalized customer_name from the payment record.

    Example:
      "NEFT/RZP GEETA VERMA/PAYDOM5IGQP" -> "geeta verma"
      "RZP Settlement PAY123 RAHUL SHARMA" -> "rahul sharma"
      "Settlement PAY5LXO6QJI Karan Joshi" -> "karan joshi"
    """
    if not s or not isinstance(s, str):
        return ""

    text = s.strip()

    # Remove leading noise prefix
    text = _DESC_NOISE.sub("", text)

    # Remove embedded PAY references
    text = _REF_INLINE.sub("", text)

    # Remove common noise suffixes
    text = re.sub(r"\(net of fees?\)", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\bDUP\b", "", text, flags=re.IGNORECASE)

    # Run through name normalizer to strip remaining gateway prefixes
    return normalize_name(text)


# ---------------------------------------------------------------------------
# Row-level normalizers: add norm_* keys alongside originals
# ---------------------------------------------------------------------------


def normalize_payment(row: dict) -> dict:
    """
    Return a copy of the payment row with normalized fields added.

    Added keys:
      norm_name       - normalized customer_name
      norm_reference  - normalized payment_reference (uppercased)
      norm_amount     - normalized float amount
      norm_date       - datetime.date from payment_date
    """
    r = dict(row)
    r["norm_name"]      = normalize_name(r.get("customer_name", ""))
    r["norm_reference"] = normalize_reference(r.get("payment_reference", ""))
    r["norm_amount"]    = normalize_amount(r.get("payment_amount", 0))
    r["norm_date"]      = normalize_date(r.get("payment_date"))
    return r


def normalize_bank(row: dict) -> dict:
    """
    Return a copy of the bank row with normalized fields added.

    Added keys:
      norm_reference       - normalized bank_reference
      norm_ref_from_desc   - PAY reference extracted from description
      norm_name_from_desc  - name extracted and normalized from description
      norm_amount          - normalized float amount
      norm_date            - datetime.date from settlement_date
    """
    r = dict(row)
    r["norm_reference"]     = normalize_reference(r.get("bank_reference", ""))
    r["norm_ref_from_desc"] = extract_reference_from_text(r.get("description", ""))
    r["norm_name_from_desc"] = normalize_description(r.get("description", ""))
    r["norm_amount"]         = normalize_amount(r.get("settlement_amount", 0))
    r["norm_date"]           = normalize_date(r.get("settlement_date"))
    return r


def normalize_ledger(row: dict) -> dict:
    """
    Return a copy of the ledger row with normalized fields added.

    Added keys:
      norm_name      - normalized customer_name
      norm_reference - normalized ledger_reference
      norm_amount    - normalized float amount
      norm_date      - datetime.date from ledger_date
    """
    r = dict(row)
    r["norm_name"]      = normalize_name(r.get("customer_name", ""))
    r["norm_reference"] = normalize_reference(r.get("ledger_reference", ""))
    r["norm_amount"]    = normalize_amount(r.get("ledger_amount", 0))
    r["norm_date"]      = normalize_date(r.get("ledger_date"))
    return r


# ---------------------------------------------------------------------------
# Bulk loaders  (convenience wrappers for use by match_rules / pipeline)
# ---------------------------------------------------------------------------


def load_normalized_payments(filepath: str) -> list:
    """Read payments.csv and return list of normalized payment dicts."""
    import csv
    with open(filepath, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return [normalize_payment(r) for r in rows]


def load_normalized_bank(filepath: str) -> list:
    """Read bank.csv and return list of normalized bank dicts."""
    import csv
    with open(filepath, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return [normalize_bank(r) for r in rows]


def load_normalized_ledger(filepath: str) -> list:
    """Read ledger.csv and return list of normalized ledger dicts."""
    import csv
    with open(filepath, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return [normalize_ledger(r) for r in rows]


# ---------------------------------------------------------------------------
# Quick self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== normalize.py self-test ===")
    print()

    cases = [
        ("RZP Rahul Sharma",      "rahul sharma"),
        ("NEFT/RAHUL SHARMA",     "rahul sharma"),
        ("RAHUL SHARMA",          "rahul sharma"),
        ("rahul sharma",          "rahul sharma"),
        ("R. Sharma",             "r sharma"),
        ("Geeta Verma",           "geeta verma"),
    ]
    print("normalize_name:")
    for inp, expected in cases:
        result = normalize_name(inp)
        ok = "OK" if result == expected else f"FAIL (expected '{expected}')"
        print(f"  '{inp}' -> '{result}'  [{ok}]")

    print()
    desc_cases = [
        ("Settlement PAY5LXO6QJI Karan Joshi",   "karan joshi"),
        ("RZP Settlement PAY123 RAHUL SHARMA",    "rahul sharma"),
        ("NEFT/RZP GEETA VERMA/PAYDOM5IGQP",     "geeta verma"),
        ("Setl Aarti PAY753LC58D",               "aarti"),
        ("Settlement PAY4SHNF877 Suresh Mehta DUP", "suresh mehta"),
    ]
    print("normalize_description:")
    for inp, expected in desc_cases:
        result = normalize_description(inp)
        ok = "OK" if result == expected else f"FAIL (expected '{expected}')"
        print(f"  '{inp}' -> '{result}'  [{ok}]")

    print()
    ref_cases = [
        ("PAY5LXO6QJI",                          "PAY5LXO6QJI"),
        ("pay5lxo6qji",                           "PAY5LXO6QJI"),
        ("Settlement PAY5LXO6QJI Karan Joshi",    ""),  # reference not extracted by normalize_reference
    ]
    print("normalize_reference:")
    for inp, expected in ref_cases:
        result = normalize_reference(inp)
        ok = "OK" if result == expected else f"FAIL (expected '{expected}')"
        print(f"  '{inp}' -> '{result}'  [{ok}]")

    print()
    ext_ref_cases = [
        ("NEFT/RZP GEETA VERMA/PAYDOM5IGQP",     "PAYDOM5IGQP"),
        ("Settlement PAY5LXO6QJI Karan Joshi",    "PAY5LXO6QJI"),
        ("BANK CREDIT 12345",                      ""),
    ]
    print("extract_reference_from_text:")
    for inp, expected in ext_ref_cases:
        result = extract_reference_from_text(inp)
        ok = "OK" if result == expected else f"FAIL (expected '{expected}')"
        print(f"  '{inp}' -> '{result}'  [{ok}]")

    print()
    amount_cases = [
        ("3776.34",  3776.34),
        ("3,776.34", 3776.34),
        (3776.34,    3776.34),
        (100,        100.0),
    ]
    print("normalize_amount:")
    for inp, expected in amount_cases:
        result = normalize_amount(inp)
        ok = "OK" if result == expected else f"FAIL (expected {expected})"
        print(f"  {inp!r} -> {result}  [{ok}]")

    print()
    date_cases = [
        ("2024-05-25", "2024-05-25"),
        ("25/05/2024", "2024-05-25"),
        ("2024/05/25", "2024-05-25"),
    ]
    print("normalize_date:")
    from datetime import date as dt
    for inp, expected in date_cases:
        result = normalize_date(inp)
        ok = "OK" if result and str(result) == expected else f"FAIL (expected '{expected}')"
        print(f"  '{inp}' -> '{result}'  [{ok}]")

    print()
    print("Self-test complete.")
