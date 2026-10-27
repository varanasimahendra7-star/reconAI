"""
ReconAI: Multi-Source Financial Reconciliation Engine
=====================================================

A modular enterprise-grade 3-way reconciliation package combining:
  - High-confidence deterministic rules (exact matches, fee deduction, duplicates, time windows)
  - Selective Gemini AI escalation for ambiguous edge cases
  - Conservative financial controller fail-safe policies (zero false-positive tolerance)
"""

from .pipeline import reconcile_records, run_pipeline
from .evaluate import evaluate_results, load_ground_truth, format_evaluation_report
from .normalize import normalize_payment, normalize_bank, normalize_ledger
from .match_rules import run_deterministic_matching, summarize_results
from .ai_agent import (
    resolve_ambiguous_case,
    resolve_unresolved_batch,
    get_gemini_model_name,
)

__version__ = "1.0.0"
__all__ = [
    "reconcile_records",
    "run_pipeline",
    "evaluate_results",
    "load_ground_truth",
    "format_evaluation_report",
    "normalize_payment",
    "normalize_bank",
    "normalize_ledger",
    "run_deterministic_matching",
    "summarize_results",
    "resolve_ambiguous_case",
    "resolve_unresolved_batch",
    "get_gemini_model_name",
]
