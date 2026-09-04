"""
evaluate.py
-----------
Evaluation module for ReconAI.

Compares final reconciliation pipeline results against data/ground_truth.csv.

IMPORTANT ARCHITECTURAL CONSTRAINTS:
  - Ground truth is strictly the evaluation oracle / answer key.
  - This module alone is permitted to read ground_truth.csv.
  - Matching logic, normalization, deterministic rules, and the AI agent
    must NEVER import, read, or reference ground_truth.csv.
  - Metrics are calculated purely post-hoc from actual execution data.
  - No synthetic or hardcoded metrics.
"""

import os
import csv
from typing import List, Dict, Any


def load_ground_truth(ground_truth_path: str = "data/ground_truth.csv") -> Dict[str, Dict[str, Any]]:
    """
    Loads ground_truth.csv into a dictionary keyed by transaction_id.
    """
    if not os.path.exists(ground_truth_path):
        raise FileNotFoundError(f"Ground truth file not found at: {ground_truth_path}")

    with open(ground_truth_path, mode="r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        return {row["transaction_id"]: row for row in reader}


def evaluate_results(
    pipeline_results: List[Dict[str, Any]],
    ground_truth_path: str = "data/ground_truth.csv"
) -> Dict[str, Any]:
    """
    Evaluates final pipeline decisions against the ground truth answer key.

    Definitions:
      - Actual Positive (P): Ground truth decision == "MATCH"
      - Actual Negative (N): Ground truth decision == "EXCEPTION"
      - True Positive (TP): System says "MATCH", Ground truth says "MATCH"
      - True Negative (TN): System says "EXCEPTION", Ground truth says "EXCEPTION"
      - False Positive (FP): System says "MATCH", Ground truth says "EXCEPTION"
      - False Negative (FN): System says "EXCEPTION", Ground truth says "MATCH"

      - Accuracy: (TP + TN) / Total
      - False-Positive Rate (FPR): FP / (FP + TN) = FP / Actual Exceptions
      - False-Negative Rate (FNR): FN / (FN + TP) = FN / Actual Matches

    Per-Exception-Type Metrics:
      - Precision: TP_type / (Predicted as type)
      - Recall: TP_type / (Actual ground-truth cases of type)
    """
    gt_map = load_ground_truth(ground_truth_path)

    total_transactions = len(pipeline_results)
    tp = 0
    tn = 0
    fp = 0
    fn = 0

    discrepancies = []
    
    # Track per-exception-type counts:
    # We map ground-truth edge_case_type to standardized exception categories:
    # DUPLICATE_BANK -> DUPLICATE_SETTLEMENT
    # MISSING_BANK   -> MISSING_RECORD
    # AMOUNT_MISMATCH -> AMOUNT_MISMATCH
    gt_category_map = {
        "DUPLICATE_BANK": "DUPLICATE_SETTLEMENT",
        "MISSING_BANK": "MISSING_RECORD",
        "AMOUNT_MISMATCH": "AMOUNT_MISMATCH",
    }

    business_exception_categories = [
        "AMOUNT_MISMATCH",
        "DUPLICATE_SETTLEMENT",
        "MISSING_RECORD",
        "UNEXPLAINED"
    ]

    # {category: {"actual": 0, "predicted": 0, "correct": 0}}
    cat_stats = {cat: {"actual": 0, "predicted": 0, "correct": 0} for cat in business_exception_categories}

    system_failures = []
    ai_successful_resolutions = []

    for item in pipeline_results:
        txn_id = item["transaction_id"]
        pred_decision = item.get("final_decision")
        pred_exc_type = item.get("exception_type")
        res_method = item.get("resolution_method")

        gt_row = gt_map.get(txn_id)
        if not gt_row:
            raise KeyError(f"Transaction ID '{txn_id}' not found in ground truth oracle.")

        gt_decision = gt_row["ground_truth_decision"]
        gt_edge_type = gt_row.get("edge_case_type", "")
        gt_standard_exc = gt_category_map.get(gt_edge_type, gt_edge_type)

        # Track system/AI failures vs successful AI resolutions
        if pred_exc_type == "LLM_PARSE_FAILURE":
            system_failures.append({
                "transaction_id": txn_id,
                "reason": item.get("reason"),
                "bank_candidates": [b.get("bank_id") for b in item.get("bank_candidates", [])],
            })
        elif res_method == "AI_RESOLVED":
            ai_successful_resolutions.append(txn_id)

        # Count actual ground truth exception occurrences for business categories
        if gt_decision == "EXCEPTION" and gt_standard_exc in cat_stats:
            cat_stats[gt_standard_exc]["actual"] += 1

        # Count system predictions for business categories (LLM_PARSE_FAILURE is NEVER counted as a business exception prediction)
        if pred_decision == "EXCEPTION" and pred_exc_type in cat_stats:
            cat_stats[pred_exc_type]["predicted"] += 1

        # Binary Decision Confusion Matrix
        if pred_decision == "MATCH" and gt_decision == "MATCH":
            tp += 1
        elif pred_decision == "EXCEPTION" and gt_decision == "EXCEPTION":
            tn += 1
            # Check if exception type was correctly classified into a business category
            if pred_exc_type == gt_standard_exc and pred_exc_type in cat_stats:
                cat_stats[pred_exc_type]["correct"] += 1
        elif pred_decision == "MATCH" and gt_decision == "EXCEPTION":
            fp += 1
            discrepancies.append({
                "transaction_id": txn_id,
                "type": "FALSE_POSITIVE",
                "predicted": pred_decision,
                "ground_truth": gt_decision,
                "reason": item.get("reason"),
            })
        elif pred_decision == "EXCEPTION" and gt_decision == "MATCH":
            fn += 1
            discrepancies.append({
                "transaction_id": txn_id,
                "type": "FALSE_NEGATIVE",
                "predicted": pred_decision,
                "ground_truth": gt_decision,
                "reason": item.get("reason"),
            })

    correct = tp + tn
    incorrect = fp + fn
    accuracy = (correct / total_transactions) if total_transactions else 0.0

    actual_exceptions = tn + fp
    actual_matches = tp + fn

    fp_rate = (fp / actual_exceptions) if actual_exceptions else 0.0
    fn_rate = (fn / actual_matches) if actual_matches else 0.0

    # Calculate per-category precision & recall
    per_exception_metrics = {}
    for cat in business_exception_categories:
        c_actual = cat_stats[cat]["actual"]
        c_pred = cat_stats[cat]["predicted"]
        c_correct = cat_stats[cat]["correct"]

        if c_actual == 0 and c_pred == 0:
            precision_val = None
            recall_val = None
            display_str = f"N/A — no {cat} cases in this dataset"
        else:
            precision_val = round((c_correct / c_pred), 4) if c_pred > 0 else 0.0
            recall_val = round((c_correct / c_actual), 4) if c_actual > 0 else 0.0
            display_str = None

        per_exception_metrics[cat] = {
            "actual": c_actual,
            "predicted": c_pred,
            "correct": c_correct,
            "precision": precision_val,
            "recall": recall_val,
            "display": display_str,
        }

    return {
        "total_transactions": total_transactions,
        "correct_classifications": correct,
        "incorrect_classifications": incorrect,
        "overall_accuracy": round(accuracy, 4),
        "true_positives": tp,
        "true_negatives": tn,
        "false_positives": fp,
        "false_negatives": fn,
        "actual_matches": actual_matches,
        "actual_exceptions": actual_exceptions,
        "false_positive_rate": round(fp_rate, 4),
        "false_negative_rate": round(fn_rate, 4),
        "per_exception_metrics": per_exception_metrics,
        "discrepancies": discrepancies,
        "system_failures": system_failures,
        "ai_successful_resolutions": ai_successful_resolutions,
    }


def format_evaluation_report(
    eval_metrics: Dict[str, Any],
    pipeline_summary: Dict[str, Any],
    processing_time_sec: float
) -> str:
    """
    Formats the evaluation results into the required clean, human-readable report.
    """
    pem = eval_metrics["per_exception_metrics"]

    report_lines = [
        "=" * 60,
        "RECONAI FINAL EVALUATION",
        "=" * 60,
        f"Total transactions:         {eval_metrics['total_transactions']}",
        "",
        f"Deterministic matches:      {pipeline_summary.get('total_deterministic_matches', 0)}",
        f"  - Matched by rule:        {pipeline_summary.get('matched_by_rule', 0)}",
        f"  - Matched with fee:       {pipeline_summary.get('matched_with_fee', 0)}",
        f"AI-resolved cases:          {pipeline_summary.get('ai_resolved_count', 0)}",
        f"  - AI Successful:          {len(eval_metrics.get('ai_successful_resolutions', []))}",
        f"  - AI/System Failures:     {len(eval_metrics.get('system_failures', []))}",
        f"Final matches:              {pipeline_summary.get('final_matches', 0)}",
        f"Final exceptions:           {pipeline_summary.get('final_exceptions', 0)}",
        "",
        f"Binary decision accuracy:   {eval_metrics['overall_accuracy'] * 100:.2f}%",
        f"False-positive rate:        {eval_metrics['false_positive_rate'] * 100:.2f}% (FP={eval_metrics['false_positives']}/{eval_metrics['actual_exceptions']})",
        f"False-negative rate:        {eval_metrics['false_negative_rate'] * 100:.2f}% (FN={eval_metrics['false_negatives']}/{eval_metrics['actual_matches']})",
        "",
        "Business Exception-Type Metrics:",
    ]

    for cat in ["AMOUNT_MISMATCH", "DUPLICATE_SETTLEMENT", "MISSING_RECORD", "UNEXPLAINED"]:
        m = pem[cat]
        report_lines.append(f"  {cat}:")
        report_lines.append(f"    Actual:    {m['actual']}")
        report_lines.append(f"    Predicted: {m['predicted']}")
        if m["display"]:
            report_lines.append(f"    Precision: {m['display']}")
            report_lines.append(f"    Recall:    {m['display']}")
        else:
            report_lines.append(f"    Precision: {m['precision'] * 100:.2f}%")
            report_lines.append(f"    Recall:    {m['recall'] * 100:.2f}%")

    report_lines.extend([
        "",
        f"AI / System Failure Count:  {len(eval_metrics.get('system_failures', []))}",
    ])

    if eval_metrics.get("system_failures"):
        report_lines.append("  Failed Transactions:")
        for sf in eval_metrics["system_failures"]:
            report_lines.append(f"    - {sf['transaction_id']}: {sf['reason'][:80]}...")

    report_lines.extend([
        "",
        f"Processing time:            {processing_time_sec:.2f} seconds",
        "=" * 60,
    ])

    return "\n".join(report_lines)
