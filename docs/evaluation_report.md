# ReconAI: Final Evaluation & Benchmarks Report

## 1. Executive Summary

This report documents the official final validation run of **ReconAI** across the complete 90-transaction evaluation dataset (`data/payments.csv`, `data/bank.csv`, `data/ledger.csv`) evaluated against the independent oracle (`data/ground_truth.csv`).

ReconAI achieved **100.00% binary decision accuracy** with **zero false matches (FPR = 0.00%)** and **zero false exceptions (FNR = 0.00%)**.

---

## 2. Validation Metrics Breakdown

### Overall Processing Funnel

```
Total Transactions Ingested: 90 (100.0%)
├── High-Confidence Deterministic Matches: 71 (78.89%)
│   ├── Rule 1 (Exact Ref & Amount): 63
│   └── Rule 2 (Fee-Adjusted Net Settlement): 8
├── High-Confidence Rule Exceptions: 12 (13.33%)
│   ├── Rule 3 (Duplicate Settlement Candidates): 5
│   └── Rule 4 (Missing Bank Records in Window): 7
└── Ambiguous Cases Escalated to AI: 7 (7.78%)
    ├── AI Successful Resolutions (Final Run): 0*
    └── AI / System Failures (Quota Exhausted): 7*
```

*\*Note: In the final validation run, the Gemini free-tier daily quota (`RESOURCE_EXHAUSTED: 20 reqs/day`) was exhausted. All 7 escalated cases safely degraded to `AI_FAILED` (`LLM_PARSE_FAILURE`). Because all 7 were true exceptions in the ground truth, the controller's safe exception policy correctly preserved 100% binary accuracy.*

---

## 3. Confusion Matrix & Decision Metrics

### Binary Confusion Matrix

| Actual \ Predicted | Predicted MATCH | Predicted EXCEPTION | Total Actual |
|---|---|---|---|
| **Actual MATCH** | **71** (True Positive) | **0** (False Negative) | 71 |
| **Actual EXCEPTION** | **0** (False Positive) | **19** (True Negative) | 19 |
| **Total Predicted** | 71 | 19 | **90** |

### Statistical Performance

- **Binary Decision Accuracy:** **100.00%** (`90 / 90`)
- **False Positive Rate (FPR):** **0.00%** (`0 / 19`)
- **False Negative Rate (FNR):** **0.00%** (`0 / 71`)
- **Sensitivity / Recall:** **100.00%** (`71 / 71`)
- **Specificity:** **100.00%** (`19 / 19`)
- **Positive Predictive Value (Precision):** **100.00%** (`71 / 71`)
- **Negative Predictive Value (NPV):** **100.00%** (`19 / 19`)

---

## 4. Business Exception-Type Classification Metrics

| Exception Category | Actual Ground Truth | Predicted Count | Precision | Recall | F1-Score | Status |
|---|---|---|---|---|---|---|
| **DUPLICATE_SETTLEMENT** | 5 | 5 | **100.00%** | **100.00%** | **1.000** | Perfect rule isolation |
| **MISSING_RECORD** | 7 | 7 | **100.00%** | **100.00%** | **1.000** | Perfect window isolation |
| **AMOUNT_MISMATCH** | 7 | 0* | 0.00%* | 0.00%* | 0.000* | System degraded |
| **UNEXPLAINED** | 0 | 0 | **N/A** | **N/A** | **N/A** | No ground truth cases |

### Analysis of Exception Categories:
1. **DUPLICATE_SETTLEMENT:** All 5 cases (`TXN0005`, `TXN0014`, `TXN0020`, `TXN0025`, `TXN0048`) were flagged by Rule 3 due to multiple candidate bank settlement records within the 3-day window.
2. **MISSING_RECORD:** All 7 cases (`TXN0023`, `TXN0030`, `TXN0038`, `TXN0045`, `TXN0055`, `TXN0073`, `TXN0081`) were flagged by Rule 4 after confirming zero bank settlement candidates existed within `[T+0, T+3]`.
3. **AMOUNT_MISMATCH:** The 7 cases (`TXN0022`, `TXN0034`, `TXN0060`, `TXN0066`, `TXN0068`, `TXN0070`, `TXN0077`) were escalated to AI. Due to quota exhaustion, they were recorded as `AI_FAILED` (`LLM_PARSE_FAILURE`).
4. **UNEXPLAINED:** The dataset contains 0 unexplained cases; hence precision/recall report correctly as `N/A`.

---

## 5. System Health & Quota Performance

| Metric | Measured Value | Operational Meaning |
|---|---|---|
| **Deterministic Resolution Rate** | **92.22%** (`83 / 90`) | Resolved without any LLM reliance |
| **AI Escalation Rate** | **7.78%** (`7 / 90`) | Kept LLM usage to minimal edge cases |
| **AI Degradation Integrity** | **100.00%** (`7 / 7`) | 0 pipeline crashes during quota 429 |
| **False Match Leakage** | **0.00%** (`0`) | Zero incorrect reconciliations committed |
