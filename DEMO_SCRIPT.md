# ReconAI: 2–3 Minute Presentation & Demonstration Script

> **Track 04:** AI Finance Controller — Razorpay AI Buildathon  
> **Speaker:** Solo Developer  
> **Total Time:** 2 minutes 45 seconds  

---

## Screen & Flow Overview

| Time | Screen / Focus | Spoken Topic |
|---|---|---|
| **0:00 - 0:30** | Dashboard Header & Sources | Problem statement & 3-way reconciliation |
| **0:30 - 1:00** | Executive KPI Cards & Breakdown Table | Deterministic Rules Engine (71 matches, 12 exceptions) |
| **1:00 - 1:40** | AI Health Banner & Metrics | AI Escalation Architecture & Transparent Quota Handling |
| **1:40 - 2:20** | Transaction Drill-Down | Deep inspection of Fee, Duplicate, and AI_FAILED cases |
| **2:20 - 2:45** | Confusion Matrix & Conclusion | 100% Binary Decision Accuracy & Zero False Matches |

---

## Word-for-Word Spoken Script

### [0:00 - 0:30] Introduction: The 3-Way Reconciliation Challenge
*(Show browser at `http://localhost:8501`, showing the ReconAI header and system description)*

> "Hello everyone. In modern financial operations, reconciling high-volume transactions across three disjoint systems—the Payment Gateway, Bank Settlement statements, and the Merchant Internal Ledger—is a major operational bottleneck.
>
> Settlements arrive with 1 to 3 day delays, gateway fees of 2% cause apparent amount mismatches, duplicate batches occur, and bank references are often truncated.
>
> To solve this, I built **ReconAI**: an enterprise multi-source reconciliation agent designed with a conservative financial controller mindset. It matches high-confidence records with deterministic rules, and escalates only truly ambiguous edge cases to Gemini AI."

---

### [0:30 - 1:00] Deterministic Rules Engine
*(Scroll down slightly to the 9 Executive Summary KPI Cards and the Reconciliation Breakdown Table)*

> "Here in the dashboard, we are processing 90 transactions.
>
> Notice that out of 90 transactions, our deterministic rules engine immediately resolved **83 transactions** without needing any AI assistance:
> - **71 were matched**: 63 were exact reference matches, and 8 were automatically matched by recognizing standard 2.0% gateway fee deductions within the settlement window.
> - **12 were flagged as rule exceptions**: 5 were flagged as duplicate settlements because multiple bank candidates existed, and 7 had no bank record anywhere in the settlement window.
>
> This demonstrates our core controller philosophy: never guess when verifiable mathematical and business rules can resolve the record."

---

### [1:00 - 1:40] AI Escalation & Transparent Fail-Safe Handling
*(Highlight the yellow AI Health Status Alert Banner and the AI KPI cards)*

> "That left only **7 ambiguous transactions** out of 90 that required intelligent escalation.
>
> Here is how ReconAI handled them:
>
> **'71 transactions were resolved deterministically, 7 ambiguous cases were escalated to Gemini, and the final validation run hit the free-tier quota, so those cases safely degraded to AI_FAILED rather than being force-matched. Earlier development validation also confirmed genuine Gemini reasoning on ambiguous cases.'**
>
> Because financial ledgers do not tolerate hallucinated matches, when Google's free-tier quota returned a 429 rate limit, our agent did not crash or force a match. It safely degraded the transactions to `AI_FAILED` under `LLM_PARSE_FAILURE`, maintaining 100% exception safety."

---

### [1:40 - 2:20] Interactive Transaction Drill-Down
*(Scroll down to the Transaction Explorer section)*

> "Let's inspect how this works in the Transaction Drill-Down:
>
> First, if we filter by method `MATCHED_WITH_FEE` and inspect `TXN0004`:
> - The payment was ₹15,000, and the bank settled ₹14,700. ReconAI's Rule 2 immediately proved the exact 2% MDR fee deduction.
>
> Second, let's filter by `DUPLICATE_CANDIDATE` and select `TXN0005`:
> - Notice there are two distinct bank candidates for ₹4,500. Rather than randomly picking one, ReconAI flagged a `DUPLICATE_SETTLEMENT` exception.
>
> Finally, let's filter by `AI_FAILED` and inspect `TXN0022`:
> - You can see the full 3-way dossier, the audit trail, and the exact captured system error explaining that the AI service was rate-limited, safely retaining it for human review."

---

### [2:20 - 2:45] Evaluation Benchmarks & Conclusion
*(Scroll up to Section 5: Ground Truth Evaluation & Confusion Matrix)*

> "When evaluated independently against ground truth:
> - ReconAI achieved **100% binary decision accuracy**.
> - **True Positives:** 71 matches.
> - **True Negatives:** 19 exceptions.
> - **False Positives:** Exactly **zero**.
>
> ReconAI proves that AI in finance works best not by replacing deterministic controls, but by acting as an auditable, fail-safe extension to them.
>
> Thank you!"
