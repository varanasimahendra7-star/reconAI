"""
match_rules.py
--------------
Deterministic reconciliation engine for ReconAI.

Applies rules in a strict priority order BEFORE any AI is consulted.

Rules (applied in order):
  Rule 1 — EXACT REFERENCE MATCH
    Payment reference == bank reference (normalized) AND
    amount matches exactly AND
    settlement date within settlement window.
    => MATCHED_BY_RULE

  Rule 2 — FEE-ADJUSTED MATCH
    Payment reference == bank reference (normalized) AND
    bank amount == payment amount * (1 - gateway_fee_pct) within tolerance AND
    settlement date within settlement window.
    => MATCHED_WITH_FEE

  Rule 3 — DUPLICATE CANDIDATE DETECTION
    After rules 1+2, if a payment has MULTIPLE plausible bank candidates
    (same/similar amount within the settlement window, same reference OR
    similar description-derived name) that could all represent the same
    payment, flag ALL of them without choosing.
    => DUPLICATE_CANDIDATE  (escalate for manual/AI review)

  Rule 4 — UNRESOLVED
    No high-confidence deterministic match exists.
    => UNRESOLVED  (escalate to AI agent)

IMPORTANT:
  - Never force a match to improve the match rate.
  - A match requires sufficient evidence, not just plausibility.
  - Ground truth is NEVER read by this module.

Result schema (per payment):
  {
    "transaction_id":      str,
    "final_decision":      "MATCH" | "EXCEPTION" | "UNRESOLVED" | "DUPLICATE_CANDIDATE",
    "resolution_method":   "MATCHED_BY_RULE" | "MATCHED_WITH_FEE" | "DUPLICATE_CANDIDATE"
                           | "UNRESOLVED" | "NO_BANK_RECORD",
    "confidence":          float,        # 1.0 for rule matches, 0.0 otherwise
    "reason":              str,
    "exception_type":      str | None,   # set for definitive EXCEPTION outcomes
    "matched_bank_id":     str | None,
    "matched_ledger_id":   str | None,
    "bank_candidates":     list[dict],   # all plausible bank rows (for AI escalation)
    "ledger_record":       dict | None,
    "payment_record":      dict,         # normalized payment
  }
"""

import os
from datetime import timedelta
from normalize import (
    load_normalized_payments,
    load_normalized_bank,
    load_normalized_ledger,
)

# ---------------------------------------------------------------------------
# Configuration (can be overridden by caller)
# ---------------------------------------------------------------------------

DEFAULT_GATEWAY_FEE_PCT    = 0.02   # 2%
DEFAULT_SETTLEMENT_WINDOW  = 3      # days
DEFAULT_AMOUNT_TOLERANCE   = 0.01   # absolute tolerance for floating-point comparison (1 paisa)
DEFAULT_FEE_TOLERANCE      = 0.50   # accept fee-adjusted amount if within Rs 0.50 (rounding)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _amounts_exact(a: float, b: float, tol: float = DEFAULT_AMOUNT_TOLERANCE) -> bool:
    """True if two normalized amounts are within floating-point tolerance."""
    return abs(a - b) <= tol


def _amounts_fee_adjusted(
    payment_amount: float,
    bank_amount: float,
    fee_pct: float,
    tol: float = DEFAULT_FEE_TOLERANCE,
) -> bool:
    """
    True if bank_amount == payment_amount * (1 - fee_pct) within tolerance.
    Also accepts partial-fee scenarios where the bank deducted less than the full fee
    (e.g. rounded down to the nearest rupee).
    """
    expected = round(payment_amount * (1.0 - fee_pct), 2)
    return abs(bank_amount - expected) <= tol


def _date_within_window(
    payment_date,
    settlement_date,
    window_days: int,
) -> bool:
    """
    True if settlement_date is within [payment_date - 1, payment_date + window_days].
    The -1 allows for one day of back-dating (e.g. timezone differences).
    """
    if payment_date is None or settlement_date is None:
        return False
    diff = (settlement_date - payment_date).days
    return -1 <= diff <= window_days


def _reference_match(pay_ref: str, bank_ref: str, bank_ref_from_desc: str) -> bool:
    """
    True if the payment reference matches the bank's stored reference OR
    the reference extracted from the bank description.
    All values must already be normalized (uppercased).
    """
    if not pay_ref:
        return False
    return pay_ref == bank_ref or (bank_ref_from_desc and pay_ref == bank_ref_from_desc)


def _name_compatible(pay_norm_name: str, bank_norm_name_from_desc: str) -> bool:
    """
    Rough name compatibility check.
    Returns True if either name is a substring of the other OR they share
    both words of a two-word name.
    We do NOT require exact equality because normalization may have diverged.
    """
    if not pay_norm_name or not bank_norm_name_from_desc:
        return False
    # Exact match
    if pay_norm_name == bank_norm_name_from_desc:
        return True
    # One is contained within the other (handles abbreviated names)
    if pay_norm_name in bank_norm_name_from_desc or bank_norm_name_from_desc in pay_norm_name:
        return True
    # Both words of a two-word name appear
    pay_words  = set(pay_norm_name.split())
    bank_words = set(bank_norm_name_from_desc.split())
    if len(pay_words) >= 2 and len(pay_words & bank_words) >= 2:
        return True
    return False


# ---------------------------------------------------------------------------
# Plausible candidate finder
# Used by:
#  - Duplicate detection (Rule 3)
#  - AI escalation payload builder (pipeline.py)
# ---------------------------------------------------------------------------


def find_plausible_bank_candidates(
    payment: dict,
    bank_records: list,
    gateway_fee_pct: float = DEFAULT_GATEWAY_FEE_PCT,
    settlement_window: int = DEFAULT_SETTLEMENT_WINDOW,
    amount_tolerance: float = DEFAULT_AMOUNT_TOLERANCE,
    fee_tolerance: float = DEFAULT_FEE_TOLERANCE,
) -> list:
    """
    Return a list of bank records that are plausible candidates for this payment.

    A bank record is plausible if:
      (a) reference matches (exact or via description extraction), OR
      (b) amount is compatible (exact OR fee-adjusted) AND date is within window
          AND name is partially compatible.

    This is deliberately broad — the caller (rule engine or AI) decides what to do.
    """
    pay_ref    = payment.get("norm_reference", "")
    pay_amount = payment.get("norm_amount", 0.0)
    pay_date   = payment.get("norm_date")
    pay_name   = payment.get("norm_name", "")

    candidates = []
    for b in bank_records:
        bank_ref       = b.get("norm_reference", "")
        bank_ref_desc  = b.get("norm_ref_from_desc", "")
        bank_name_desc = b.get("norm_name_from_desc", "")
        bank_amount    = b.get("norm_amount", 0.0)
        bank_date      = b.get("norm_date")

        ref_ok    = _reference_match(pay_ref, bank_ref, bank_ref_desc)
        amount_ok = (
            _amounts_exact(pay_amount, bank_amount, amount_tolerance)
            or _amounts_fee_adjusted(pay_amount, bank_amount, gateway_fee_pct, fee_tolerance)
        )
        date_ok   = _date_within_window(pay_date, bank_date, settlement_window)
        name_ok   = _name_compatible(pay_name, bank_name_desc)

        if ref_ok or (amount_ok and date_ok and name_ok):
            candidates.append(b)

    return candidates


# ---------------------------------------------------------------------------
# Rule engine — applied per payment
# ---------------------------------------------------------------------------


def _apply_rules_to_payment(
    payment: dict,
    plausible_bank: list,
    ledger_record: dict | None,
    gateway_fee_pct: float,
    settlement_window: int,
    amount_tolerance: float,
    fee_tolerance: float,
) -> dict:
    """
    Apply Rules 1-4 to a single payment and return the result dict.
    """
    txn_id     = payment.get("transaction_id", "")
    pay_ref    = payment.get("norm_reference", "")
    pay_amount = payment.get("norm_amount", 0.0)
    pay_date   = payment.get("norm_date")

    base = {
        "transaction_id":   txn_id,
        "final_decision":   None,
        "resolution_method": None,
        "confidence":       0.0,
        "reason":           "",
        "exception_type":   None,
        "matched_bank_id":  None,
        "matched_ledger_id": ledger_record.get("ledger_id") if ledger_record else None,
        "bank_candidates":  plausible_bank,
        "ledger_record":    ledger_record,
        "payment_record":   payment,
    }

    # -----------------------------------------------------------------------
    # Special case: no bank candidates at all
    # -----------------------------------------------------------------------
    if not plausible_bank:
        base.update({
            "final_decision":    "EXCEPTION",
            "resolution_method": "NO_BANK_RECORD",
            "confidence":        1.0,
            "reason":            "No bank settlement record found for this payment reference or amount/date/name combination.",
            "exception_type":    "MISSING_RECORD",
        })
        return base

    # -----------------------------------------------------------------------
    # Separate candidates: exact-ref match vs amount-only match
    # -----------------------------------------------------------------------
    exact_ref_candidates = [
        b for b in plausible_bank
        if _reference_match(pay_ref, b.get("norm_reference", ""), b.get("norm_ref_from_desc", ""))
    ]

    # -----------------------------------------------------------------------
    # Rule 3 — DUPLICATE CANDIDATE DETECTION
    # Must run BEFORE rules 1+2 to avoid silently selecting one of two duplicates.
    #
    # Trigger: multiple bank candidates ALL share the same payment reference AND
    # each individually would pass Rule 1 or Rule 2 criteria.
    # We check within the settlement window so we don't flag unrelated
    # same-amount coincidences.
    # -----------------------------------------------------------------------
    if len(exact_ref_candidates) > 1:
        # All share the same reference — this is the duplicate scenario
        within_window = [
            b for b in exact_ref_candidates
            if _date_within_window(pay_date, b.get("norm_date"), settlement_window)
        ]
        if len(within_window) > 1:
            bank_ids = ", ".join(b.get("bank_id", "") for b in within_window)
            base.update({
                "final_decision":    "EXCEPTION",
                "resolution_method": "DUPLICATE_CANDIDATE",
                "confidence":        0.0,
                "reason":            (
                    f"Multiple bank records ({bank_ids}) share reference {pay_ref!r} "
                    f"with compatible amounts within the {settlement_window}-day settlement window. "
                    "Cannot auto-match — manual or AI review required."
                ),
                "exception_type":    "DUPLICATE_SETTLEMENT",
                "bank_candidates":   within_window,
            })
            return base

    # -----------------------------------------------------------------------
    # If exactly one ref-matched candidate, try Rule 1 then Rule 2 on it.
    # If zero ref-matched candidates (amount+name match only), try Rule 1/2
    # on those candidates.
    # -----------------------------------------------------------------------
    primary_candidates = exact_ref_candidates if exact_ref_candidates else plausible_bank

    # We need exactly one strong candidate to make a deterministic match.
    # If there are multiple non-ref candidates, escalate to UNRESOLVED.
    if len(primary_candidates) > 1 and not exact_ref_candidates:
        bank_ids = ", ".join(b.get("bank_id", "") for b in primary_candidates)
        base.update({
            "final_decision":    "UNRESOLVED",
            "resolution_method": "UNRESOLVED",
            "confidence":        0.0,
            "reason":            (
                f"Multiple bank candidates ({bank_ids}) are plausible by amount/date/name "
                "but no reference match narrows them to one. Escalating to AI review."
            ),
        })
        return base

    candidate = primary_candidates[0]
    bank_amount = candidate.get("norm_amount", 0.0)
    bank_date   = candidate.get("norm_date")
    bank_id     = candidate.get("bank_id", "")

    # -----------------------------------------------------------------------
    # Rule 1 — EXACT AMOUNT + DATE WITHIN WINDOW
    # -----------------------------------------------------------------------
    if (
        _amounts_exact(pay_amount, bank_amount, amount_tolerance)
        and _date_within_window(pay_date, bank_date, settlement_window)
    ):
        drift = (bank_date - pay_date).days if bank_date and pay_date else 0
        drift_note = f" (settlement {drift} day(s) after payment)" if drift > 0 else ""
        base.update({
            "final_decision":    "MATCH",
            "resolution_method": "MATCHED_BY_RULE",
            "confidence":        1.0,
            "reason":            (
                f"Exact amount match (payment={pay_amount}, bank={bank_amount})"
                f"{drift_note}. Reference: {pay_ref!r}."
            ),
            "matched_bank_id":   bank_id,
        })
        return base

    # -----------------------------------------------------------------------
    # Rule 2 — FEE-ADJUSTED AMOUNT + DATE WITHIN WINDOW
    # -----------------------------------------------------------------------
    if (
        _amounts_fee_adjusted(pay_amount, bank_amount, gateway_fee_pct, fee_tolerance)
        and _date_within_window(pay_date, bank_date, settlement_window)
    ):
        expected_after_fee = round(pay_amount * (1.0 - gateway_fee_pct), 2)
        actual_diff        = round(pay_amount - bank_amount, 2)
        base.update({
            "final_decision":    "MATCH",
            "resolution_method": "MATCHED_WITH_FEE",
            "confidence":        1.0,
            "reason":            (
                f"Fee-adjusted match: payment={pay_amount}, "
                f"expected after {gateway_fee_pct*100:.0f}% fee={expected_after_fee}, "
                f"bank settled={bank_amount} (diff={actual_diff}). "
                f"Reference: {pay_ref!r}."
            ),
            "matched_bank_id":   bank_id,
        })
        return base

    # -----------------------------------------------------------------------
    # Rule 4 — UNRESOLVED (plausible candidate exists but insufficient evidence)
    # -----------------------------------------------------------------------
    diff        = round(abs(pay_amount - bank_amount), 2)
    diff_pct    = round(diff / pay_amount * 100, 1) if pay_amount else 0.0
    date_diff   = (bank_date - pay_date).days if bank_date and pay_date else None
    date_note   = f"; settlement date {date_diff} day(s) from payment" if date_diff is not None else ""

    base.update({
        "final_decision":    "UNRESOLVED",
        "resolution_method": "UNRESOLVED",
        "confidence":        0.0,
        "reason":            (
            f"Plausible bank candidate {bank_id!r} found but cannot confirm deterministically. "
            f"Amount difference: {diff} ({diff_pct}%){date_note}. "
            "Escalating to AI agent."
        ),
    })
    return base


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run_deterministic_matching(
    payments:          list,
    bank_records:      list,
    ledger_records:    list,
    gateway_fee_pct:   float = DEFAULT_GATEWAY_FEE_PCT,
    settlement_window: int   = DEFAULT_SETTLEMENT_WINDOW,
    amount_tolerance:  float = DEFAULT_AMOUNT_TOLERANCE,
    fee_tolerance:     float = DEFAULT_FEE_TOLERANCE,
) -> list:
    """
    Run the full deterministic matching pipeline on pre-normalized records.

    Args:
        payments:       Output of load_normalized_payments()
        bank_records:   Output of load_normalized_bank()
        ledger_records: Output of load_normalized_ledger()

    Returns:
        List of result dicts, one per payment. See module docstring for schema.
    """
    # Build lookup: ledger by normalized reference
    ledger_by_ref = {}
    for l in ledger_records:
        ref = l.get("norm_reference", "")
        if ref:
            ledger_by_ref[ref] = l

    results = []
    for payment in payments:
        # Find plausible bank candidates (deliberately broad)
        plausible = find_plausible_bank_candidates(
            payment, bank_records,
            gateway_fee_pct, settlement_window,
            amount_tolerance, fee_tolerance,
        )

        # Find the ledger record for this payment
        pay_ref       = payment.get("norm_reference", "")
        ledger_record = ledger_by_ref.get(pay_ref)

        result = _apply_rules_to_payment(
            payment, plausible, ledger_record,
            gateway_fee_pct, settlement_window,
            amount_tolerance, fee_tolerance,
        )
        results.append(result)

    return results


def summarize_results(results: list) -> dict:
    """Return a summary dict of matching outcomes."""
    total             = len(results)
    matched_by_rule   = sum(1 for r in results if r["resolution_method"] == "MATCHED_BY_RULE")
    matched_with_fee  = sum(1 for r in results if r["resolution_method"] == "MATCHED_WITH_FEE")
    duplicates        = sum(1 for r in results if r["resolution_method"] == "DUPLICATE_CANDIDATE")
    missing_bank      = sum(1 for r in results if r["resolution_method"] == "NO_BANK_RECORD")
    unresolved        = sum(1 for r in results if r["resolution_method"] == "UNRESOLVED")
    total_matched     = matched_by_rule + matched_with_fee
    total_exceptions  = sum(1 for r in results if r["final_decision"] == "EXCEPTION")

    return {
        "total":            total,
        "matched_by_rule":  matched_by_rule,
        "matched_with_fee": matched_with_fee,
        "total_matched":    total_matched,
        "duplicates":       duplicates,
        "missing_bank":     missing_bank,
        "unresolved":       unresolved,
        "total_exceptions": total_exceptions,
        "match_rate":       round(total_matched / total * 100, 1) if total else 0.0,
    }


# ---------------------------------------------------------------------------
# CLI / quick test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import os

    DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

    print("=" * 65)
    print("ReconAI -- Deterministic Matching Engine")
    print("=" * 65)

    payments  = load_normalized_payments(os.path.join(DATA_DIR, "payments.csv"))
    banks     = load_normalized_bank(os.path.join(DATA_DIR, "bank.csv"))
    ledgers   = load_normalized_ledger(os.path.join(DATA_DIR, "ledger.csv"))

    print(f"Loaded: {len(payments)} payments, {len(banks)} bank rows, {len(ledgers)} ledger rows")
    print()

    results = run_deterministic_matching(payments, banks, ledgers)
    summary = summarize_results(results)

    print("-" * 65)
    print("MATCHING RESULTS SUMMARY")
    print("-" * 65)
    print(f"  Total payments processed:     {summary['total']}")
    print(f"  Matched by rule (exact):      {summary['matched_by_rule']}")
    print(f"  Matched with fee adjustment:  {summary['matched_with_fee']}")
    print(f"  Total deterministic matches:  {summary['total_matched']}")
    print(f"  Duplicate candidates:         {summary['duplicates']}")
    print(f"  Missing bank record:          {summary['missing_bank']}")
    print(f"  Unresolved (-> AI):           {summary['unresolved']}")
    print(f"  Total exceptions so far:      {summary['total_exceptions']}")
    print(f"  Deterministic match rate:     {summary['match_rate']}%")

    # Per-resolution-method breakdown
    from collections import Counter
    method_counts = Counter(r["resolution_method"] for r in results)
    print()
    print("-" * 65)
    print("BY RESOLUTION METHOD")
    print("-" * 65)
    for method, count in sorted(method_counts.items()):
        print(f"  {method:<26}  {count:>3}")

    # Representative examples
    print()
    print("-" * 65)
    print("REPRESENTATIVE EXAMPLES")
    print("-" * 65)

    shown = set()
    for r in results:
        method = r["resolution_method"]
        if method not in shown:
            shown.add(method)
            pay = r["payment_record"]
            print(f"\n  [{method}] TXN={r['transaction_id']}")
            print(f"    payment_ref    = {pay.get('payment_reference')}")
            print(f"    payment_amount = {pay.get('payment_amount')}")
            print(f"    payment_date   = {pay.get('payment_date')}")
            bank_cands = r.get('bank_candidates', [])
            for b in bank_cands[:2]:
                print(f"    bank_id        = {b.get('bank_id')}  amount={b.get('settlement_amount')}  date={b.get('settlement_date')}")
            print(f"    reason         = {r['reason'][:120]}")
            print(f"    decision       = {r['final_decision']}  confidence={r['confidence']}")

    # Verify specific cases
    print()
    print("-" * 65)
    print("VERIFICATION CHECKS")
    print("-" * 65)

    result_map = {r["transaction_id"]: r for r in results}
    import csv

    gt_rows = list(csv.DictReader(open(os.path.join(DATA_DIR, "ground_truth.csv"))))
    gt_map  = {g["transaction_id"]: g for g in gt_rows}

    checks = {
        "EXACT_MATCH":    ("MATCHED_BY_RULE",     "MATCH"),
        "DATE_DRIFT":     ("MATCHED_BY_RULE",     "MATCH"),
        "FEE_DEDUCTION":  ("MATCHED_WITH_FEE",    "MATCH"),
        "DUPLICATE_BANK": ("DUPLICATE_CANDIDATE", "EXCEPTION"),
        "MISSING_BANK":   ("NO_BANK_RECORD",      "EXCEPTION"),
        "AMOUNT_MISMATCH":("UNRESOLVED",          "UNRESOLVED"),
        "NAME_VARIATION": ("MATCHED_BY_RULE",     "MATCH"),
    }

    all_passed = True
    for edge_type, (expected_method, expected_decision) in checks.items():
        samples = [g for g in gt_rows if g["edge_case_type"] == edge_type]
        passed_method = 0
        passed_decision = 0
        for g in samples:
            txn = g["transaction_id"]
            r   = result_map.get(txn, {})
            if r.get("resolution_method") == expected_method:
                passed_method += 1
            if r.get("final_decision") == expected_decision:
                passed_decision += 1

        total_s = len(samples)
        ok = passed_method == total_s
        status = "OK" if ok else "PARTIAL/FAIL"
        if not ok:
            all_passed = False
        print(f"  {edge_type:<22}  method={passed_method}/{total_s}  decision={passed_decision}/{total_s}  [{status}]")

    print()
    if all_passed:
        print("  All verification checks passed.")
    else:
        print("  Some checks did not fully pass -- review above.")
        # Show failing transactions in detail
        for edge_type, (expected_method, expected_decision) in checks.items():
            samples = [g for g in gt_rows if g["edge_case_type"] == edge_type]
            for g in samples:
                txn = g["transaction_id"]
                r   = result_map.get(txn, {})
                if r.get("resolution_method") != expected_method:
                    print()
                    print(f"  FAIL: {txn} ({edge_type})")
                    print(f"    Expected method:   {expected_method}")
                    print(f"    Got method:        {r.get('resolution_method')}")
                    print(f"    Got decision:      {r.get('final_decision')}")
                    print(f"    Reason:            {r.get('reason','')[:150]}")
                    bank_cands = r.get('bank_candidates', [])
                    for b in bank_cands[:3]:
                        print(f"    Bank cand:         {b.get('bank_id')}  ref={b.get('bank_reference')}  norm_ref={b.get('norm_reference')}  amount={b.get('settlement_amount')}")
                    pay = r.get('payment_record', {})
                    print(f"    Pay ref:           {pay.get('payment_reference')}  norm_ref={pay.get('norm_reference')}")
