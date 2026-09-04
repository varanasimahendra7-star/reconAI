"""
pipeline.py
-----------
Main orchestration pipeline for ReconAI.

End-to-end execution flow:
  1. Generate synthetic data (if not existing or when requested).
  2. Load & normalize data from all 3 sources (payments, bank, ledger).
  3. Execute deterministic rules (Rules 1-4).
  4. Identify UNRESOLVED cases (and ONLY unresolved cases).
  5. Escalate unresolved cases to Gemini AI agent with minimal candidate payload.
  6. Combine deterministic and AI results into final reconciliation table.
  7. Run independent evaluation against ground truth answer key (via evaluate.py).
  8. Return structured results, exception list, and metrics to caller / CLI.
"""

import os
import sys
import time
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv

# Load env variables (including GEMINI_MODEL, GEMINI_API_KEY)
load_dotenv(override=True)

import normalize
import match_rules
import ai_agent
import evaluate


def reconcile_records(
    raw_payments: List[Dict[str, Any]],
    raw_banks: List[Dict[str, Any]],
    raw_ledgers: List[Dict[str, Any]],
    ground_truth_path: Optional[str] = None,
    gateway_fee_pct: float = 0.02,
    settlement_window_days: int = 3,
) -> Dict[str, Any]:
    """
    Executes the complete reconciliation pipeline on in-memory lists of raw records.
    Normalizes sources, executes deterministic rules, escalates unresolved cases to
    Gemini, and optionally evaluates against ground truth if path is provided.
    Does NOT read from or write to disk.
    """
    start_time = time.time()

    # Step 1: Normalize sources in-memory
    norm_payments = [normalize.normalize_payment(r) for r in raw_payments]
    norm_banks = [normalize.normalize_bank(r) for r in raw_banks]
    norm_ledgers = [normalize.normalize_ledger(r) for r in raw_ledgers]

    # Step 2: Deterministic Matching (Pre-AI)
    # Rules applied: Exact match, Fee-adjusted match, Duplicate candidate, Unresolved
    initial_results = match_rules.run_deterministic_matching(
        payments=norm_payments,
        bank_records=norm_banks,
        ledger_records=norm_ledgers,
        gateway_fee_pct=gateway_fee_pct,
        settlement_window=settlement_window_days,
    )

    # Step 3: Identify ONLY unresolved cases
    unresolved_cases = [r for r in initial_results if r.get("final_decision") == "UNRESOLVED"]
    resolved_deterministic = [r for r in initial_results if r.get("final_decision") != "UNRESOLVED"]

    matched_by_rule = sum(1 for r in resolved_deterministic if r.get("resolution_method") == "MATCHED_BY_RULE")
    matched_with_fee = sum(1 for r in resolved_deterministic if r.get("resolution_method") == "MATCHED_WITH_FEE")
    total_deterministic_matches = matched_by_rule + matched_with_fee
    rule_exceptions = sum(1 for r in resolved_deterministic if r.get("final_decision") == "EXCEPTION")

    # Step 4: Send strictly UNRESOLVED cases to Gemini AI agent
    ai_resolved_cases = []
    if unresolved_cases:
        ai_resolved_cases = ai_agent.resolve_unresolved_batch(
            unresolved_results=unresolved_cases,
            gateway_fee_pct=gateway_fee_pct,
            settlement_window_days=settlement_window_days,
        )

    # Step 5: Combine all records into final reconciliation
    all_final_results: List[Dict[str, Any]] = []
    all_final_results.extend(resolved_deterministic)
    all_final_results.extend(ai_resolved_cases)

    # Sort deterministically by transaction_id
    all_final_results.sort(key=lambda x: str(x.get("transaction_id", "")))

    # Build Exception List
    exception_list = [
        {
            "transaction_id": r["transaction_id"],
            "exception_type": r.get("exception_type"),
            "reason": r.get("reason"),
            "confidence": r.get("confidence", 0.0),
            "resolution_method": r.get("resolution_method"),
            "bank_candidates": [b.get("bank_id") for b in r.get("bank_candidates", [])],
        }
        for r in all_final_results
        if r.get("final_decision") == "EXCEPTION"
    ]

    final_matches = sum(1 for r in all_final_results if r.get("final_decision") == "MATCH")
    final_exceptions = sum(1 for r in all_final_results if r.get("final_decision") == "EXCEPTION")
    ai_matches = sum(1 for r in ai_resolved_cases if r.get("final_decision") == "MATCH")
    ai_exceptions = sum(1 for r in ai_resolved_cases if r.get("final_decision") == "EXCEPTION")
    ai_successful_count = sum(1 for r in ai_resolved_cases if r.get("resolution_method") == "AI_RESOLVED")
    ai_failed_count = sum(1 for r in ai_resolved_cases if r.get("resolution_method") == "AI_FAILED")

    pipeline_summary = {
        "total_records": len(all_final_results),
        "total_deterministic_matches": total_deterministic_matches,
        "matched_by_rule": matched_by_rule,
        "matched_with_fee": matched_with_fee,
        "rule_exceptions": rule_exceptions,
        "unresolved_sent_to_ai": len(unresolved_cases),
        "ai_resolved_count": len(ai_resolved_cases),
        "ai_successful_count": ai_successful_count,
        "ai_failed_count": ai_failed_count,
        "ai_matches": ai_matches,
        "ai_exceptions": ai_exceptions,
        "final_matches": final_matches,
        "final_exceptions": final_exceptions,
        "match_rate": round(final_matches / len(all_final_results) * 100, 2) if all_final_results else 0.0,
    }

    elapsed_time = time.time() - start_time
    pipeline_summary["processing_time_sec"] = round(elapsed_time, 2)

    # Step 6: Independent Evaluation against Ground Truth (if provided and exists)
    eval_metrics = None
    report_text = ""
    if ground_truth_path and os.path.exists(ground_truth_path):
        eval_metrics = evaluate.evaluate_results(
            pipeline_results=all_final_results,
            ground_truth_path=ground_truth_path,
        )
        report_text = evaluate.format_evaluation_report(
            eval_metrics=eval_metrics,
            pipeline_summary=pipeline_summary,
            processing_time_sec=elapsed_time,
        )

    return {
        "final_results": all_final_results,
        "exception_list": exception_list,
        "summary": pipeline_summary,
        "evaluation": eval_metrics,
        "report_text": report_text,
    }


def run_pipeline(
    data_dir: str = "data",
    gateway_fee_pct: float = 0.02,
    settlement_window_days: int = 3,
    regenerate_data: bool = False,
    ground_truth_path: Optional[str] = None
) -> Dict[str, Any]:
    """
    Executes the complete reconciliation pipeline from disk files and returns all results,
    metadata, exceptions, and evaluation metrics.
    """
    import csv

    if ground_truth_path is None:
        ground_truth_path = os.path.join(data_dir, "ground_truth.csv")

    # Ensure dataset exists (or regenerate if requested)
    payments_path = os.path.join(data_dir, "payments.csv")
    bank_path = os.path.join(data_dir, "bank.csv")
    ledger_path = os.path.join(data_dir, "ledger.csv")

    if regenerate_data or not (
        os.path.exists(payments_path) and os.path.exists(bank_path) and os.path.exists(ledger_path)
    ):
        import generate_data
        generate_data.main()

    # Load raw records from disk
    with open(payments_path, newline="", encoding="utf-8") as f:
        raw_payments = list(csv.DictReader(f))
    with open(bank_path, newline="", encoding="utf-8") as f:
        raw_banks = list(csv.DictReader(f))
    with open(ledger_path, newline="", encoding="utf-8") as f:
        raw_ledgers = list(csv.DictReader(f))

    return reconcile_records(
        raw_payments=raw_payments,
        raw_banks=raw_banks,
        raw_ledgers=raw_ledgers,
        ground_truth_path=ground_truth_path,
        gateway_fee_pct=gateway_fee_pct,
        settlement_window_days=settlement_window_days,
    )


def main():
    print("=" * 60)
    print("ReconAI -- Multi-Source Reconciliation Pipeline")
    print("=" * 60)

    # Verify active model before running
    model = ai_agent.get_gemini_model_name()
    print(f"Configured Gemini Model: {model}")
    print("Running pipeline...")
    print()

    results = run_pipeline()

    print(results["report_text"])

    print("\n--- SAMPLE EXCEPTIONS (from exception list) ---")
    for exc in results["exception_list"][:5]:
        print(f"TXN: {exc['transaction_id']} | Type: {exc['exception_type']} | Method: {exc['resolution_method']}")
        print(f"  Candidates: {exc['bank_candidates']}")
        print(f"  Reason: {exc['reason'][:110]}...")
        print()


if __name__ == "__main__":
    main()
