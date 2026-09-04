"""
ai_agent.py
-----------
AI Reasoning Agent for ReconAI using Google Gemini.

Key architectural responsibilities:
  1. Isolates all Gemini-specific logic in this file.
  2. Resolves ONLY unresolved/ambiguous cases escalated from deterministic matching.
  3. Uses structured payload (only candidate records, not entire dataset).
  4. Enforces structured JSON output with strict schema validation via Pydantic.
  5. Model configuration with transparent fallback:
     - Uses GEMINI_MODEL exactly as configured without silent substitution.
     - If the configured model fails (e.g. 404/deprecated), logs a clear, explicit
       message and falls back to verified model gemini-3.6-flash.
  6. Adheres to strict financial controller rules:
     - Never force-matches without sufficient evidence.
     - Prefers EXCEPTION over MATCH when ambiguous.
     - Validates confidence, decision, and exception_type.
  7. Resilient failure degradation:
     - Missing API key, API timeout, network error, malformed JSON, or schema failure
       degrades safely to EXCEPTION with exception_type="LLM_PARSE_FAILURE".
     - Never crashes the caller pipeline.
     - Never logs or exposes the API key.
"""

import os
import json
import logging
from typing import Optional, Literal, Dict, Any, List
from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator

# Configure module logger
logger = logging.getLogger("reconai.ai_agent")
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("[%(levelname)s] %(name)s: %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

# Load environment variables
load_dotenv(override=True)

# Verified fallback model confirmed working with project API key on 2026-09-04
VERIFIED_FALLBACK_MODEL = "gemini-3.6-flash"

# ---------------------------------------------------------------------------
# Structured Output Schema
# ---------------------------------------------------------------------------

class ReconciliationDecision(BaseModel):
    decision: Literal["MATCH", "EXCEPTION"]
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str
    exception_type: Optional[Literal[
        "AMOUNT_MISMATCH",
        "DUPLICATE_SETTLEMENT",
        "MISSING_RECORD",
        "UNEXPLAINED",
        "LLM_PARSE_FAILURE"
    ]] = None

    @field_validator("confidence")
    @classmethod
    def check_confidence_range(cls, v: float) -> float:
        if not (0.0 <= v <= 1.0):
            raise ValueError("Confidence must be between 0.0 and 1.0")
        return round(float(v), 4)

    @field_validator("exception_type")
    @classmethod
    def check_exception_type_consistency(cls, v: Optional[str], info) -> Optional[str]:
        # If decision is MATCH, exception_type should normally be None
        decision = info.data.get("decision")
        if decision == "MATCH" and v is not None:
            return None
        return v


# ---------------------------------------------------------------------------
# Gemini Client & Configuration Management
# ---------------------------------------------------------------------------

def get_gemini_model_name() -> str:
    """
    Retrieve configured Gemini model from GEMINI_MODEL env var.
    Returns the exact string configured, with default to gemini-3.6-flash.
    No silent rewriting is performed here.
    """
    model = os.getenv("GEMINI_MODEL", "").strip()
    if not model:
        model = VERIFIED_FALLBACK_MODEL
    return model


def get_gemini_client():
    """
    Initializes and returns google.genai Client.
    Raises ValueError if GEMINI_API_KEY is not configured.
    """
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not set in environment or .env file.")
    
    from google import genai
    return genai.Client(api_key=api_key)


# ---------------------------------------------------------------------------
# Prompt Construction (Minimal relevant payload only)
# ---------------------------------------------------------------------------

def build_reasoning_prompt(
    payment_record: Dict[str, Any],
    bank_candidates: List[Dict[str, Any]],
    ledger_record: Optional[Dict[str, Any]],
    gateway_fee_pct: float = 0.02,
    settlement_window_days: int = 3,
) -> str:
    """
    Builds a concise, structured prompt containing only the payment and its
    immediate candidate records and business rules.
    """
    # Clean representation of payment
    pay_data = {
        "transaction_id": payment_record.get("transaction_id"),
        "date": str(payment_record.get("payment_date")),
        "amount": payment_record.get("payment_amount"),
        "customer_name": payment_record.get("customer_name"),
        "reference": payment_record.get("payment_reference"),
        "status": payment_record.get("status"),
    }

    # Clean representation of bank candidates
    bank_data = []
    for b in bank_candidates:
        bank_data.append({
            "bank_id": b.get("bank_id"),
            "settlement_date": str(b.get("settlement_date")),
            "settlement_amount": b.get("settlement_amount"),
            "description": b.get("description"),
            "bank_reference": b.get("bank_reference"),
        })

    # Clean representation of ledger
    ledger_data = None
    if ledger_record:
        ledger_data = {
            "ledger_id": ledger_record.get("ledger_id"),
            "date": str(ledger_record.get("ledger_date")),
            "amount": ledger_record.get("ledger_amount"),
            "customer_name": ledger_record.get("customer_name"),
            "reference": ledger_record.get("ledger_reference"),
        }

    expected_fee_amt = round(float(payment_record.get("payment_amount", 0)) * (1.0 - gateway_fee_pct), 2)

    prompt = f"""You are ReconAI, an expert AI finance controller for a high-volume merchant.
Your job is to analyze an ambiguous transaction that could not be matched by deterministic rules.

BUSINESS RULES & TOLERANCES:
- Standard Gateway Fee: {gateway_fee_pct * 100:.1f}% deduction. Expected bank amount if fee was deducted: {expected_fee_amt}.
- Allowable Settlement Window: Up to {settlement_window_days} days after payment date.
- DUPLICATES: If multiple bank entries appear to represent the same payment, DO NOT match. Mark EXCEPTION (DUPLICATE_SETTLEMENT).
- MISSING: If no plausible bank candidate matches, mark EXCEPTION (MISSING_RECORD).
- AMOUNT MISMATCH: If amount differs from payment AND cannot be explained by the {gateway_fee_pct * 100:.1f}% fee, mark EXCEPTION (AMOUNT_MISMATCH).
- STRICT CONSERVATISM: Do NOT force-match. Never guess or hallucinate. Prefer EXCEPTION over MATCH when in doubt.

DATA TO RECONCILE:
Payment Record:
{json.dumps(pay_data, indent=2)}

Plausible Bank Candidate Records:
{json.dumps(bank_data, indent=2)}

Merchant Internal Ledger Record:
{json.dumps(ledger_data, indent=2)}

TASK:
Analyze the records above against the business rules. Return a structured JSON object strictly matching the schema:
- decision: "MATCH" or "EXCEPTION"
- confidence: numeric float between 0.0 and 1.0
- reason: concise explanation of your findings
- exception_type: if decision is EXCEPTION, choose one of ["AMOUNT_MISMATCH", "DUPLICATE_SETTLEMENT", "MISSING_RECORD", "UNEXPLAINED"]. If MATCH, set to null.
"""
    return prompt


# ---------------------------------------------------------------------------
# Fallback / Error Handling
# ---------------------------------------------------------------------------

def make_fallback_decision(reason: str, exception_type: str = "LLM_PARSE_FAILURE") -> Dict[str, Any]:
    """
    Returns a safe, standardized failure record that adheres to the contract.
    """
    return {
        "decision": "EXCEPTION",
        "confidence": 0.0,
        "reason": reason,
        "exception_type": exception_type,
    }


# ---------------------------------------------------------------------------
# Core Interface: resolve_ambiguous_case
# ---------------------------------------------------------------------------

def resolve_ambiguous_case(
    payment_record: Dict[str, Any],
    bank_candidates: List[Dict[str, Any]],
    ledger_record: Optional[Dict[str, Any]],
    gateway_fee_pct: float = 0.02,
    settlement_window_days: int = 3,
    client: Optional[Any] = None,
    model_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Public provider-isolated function to resolve an ambiguous transaction.
    
    1. Attempts the call with the exact model configured (or passed in).
    2. If that call fails and it was different from VERIFIED_FALLBACK_MODEL,
       logs an explicit message and retries using VERIFIED_FALLBACK_MODEL.
    3. Gracefully catches JSON parsing errors, Pydantic validation errors,
       timeouts, and API errors, returning a standardized EXCEPTION fallback.
    """
    try:
        if client is None:
            client = get_gemini_client()
        if model_name is None:
            model_name = get_gemini_model_name()
    except Exception as e:
        return make_fallback_decision(f"Gemini client initialization failed: {type(e).__name__} - {str(e)}")

    prompt = build_reasoning_prompt(
        payment_record=payment_record,
        bank_candidates=bank_candidates,
        ledger_record=ledger_record,
        gateway_fee_pct=gateway_fee_pct,
        settlement_window_days=settlement_window_days,
    )

    from google.genai import types

    response = None
    # 1. Attempt with configured model
    try:
        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=ReconciliationDecision,
                temperature=0.0,
            )
        )
    except Exception as e:
        # Check if we should attempt fallback to VERIFIED_FALLBACK_MODEL
        if model_name != VERIFIED_FALLBACK_MODEL:
            err_str = str(e)
            api_key = os.getenv("GEMINI_API_KEY", "")
            if api_key and api_key in err_str:
                err_str = err_str.replace(api_key, "[REDACTED_API_KEY]")
            logger.warning(
                f"Configured model '{model_name}' failed with error: {err_str}. "
                f"Falling back to verified working model '{VERIFIED_FALLBACK_MODEL}'."
            )
            try:
                model_name = VERIFIED_FALLBACK_MODEL
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=ReconciliationDecision,
                        temperature=0.0,
                    )
                )
            except Exception as e_fallback:
                err_msg = f"{type(e_fallback).__name__}: {str(e_fallback)}"
                if api_key and api_key in err_msg:
                    err_msg = err_msg.replace(api_key, "[REDACTED_API_KEY]")
                return make_fallback_decision(f"AI reasoning failed after fallback: {err_msg}")
        else:
            err_msg = f"{type(e).__name__}: {str(e)}"
            api_key = os.getenv("GEMINI_API_KEY", "")
            if api_key and api_key in err_msg:
                err_msg = err_msg.replace(api_key, "[REDACTED_API_KEY]")
            return make_fallback_decision(f"AI reasoning failed: {err_msg}")

    # 2. Parse & Validate Response
    try:
        raw_text = getattr(response, "text", None)
        if not raw_text or not raw_text.strip():
            return make_fallback_decision("Gemini returned empty response text")

        # Pydantic schema validation (catches JSONDecodeError, ValidationError)
        decision_obj = ReconciliationDecision.model_validate_json(raw_text)
        result = decision_obj.model_dump()
        
        matched_bank_id = None
        if result["decision"] == "MATCH" and bank_candidates:
            matched_bank_id = bank_candidates[0].get("bank_id")
        result["matched_bank_id"] = matched_bank_id

        return result

    except Exception as parse_err:
        err_msg = f"{type(parse_err).__name__}: {str(parse_err)}"
        logger.error(f"Failed to validate Gemini response: {err_msg}")
        return make_fallback_decision(f"Malformed or invalid response: {err_msg}", exception_type="LLM_PARSE_FAILURE")


# ---------------------------------------------------------------------------
# Batch Helper for Unresolved Pipeline Cases
# ---------------------------------------------------------------------------

def resolve_unresolved_batch(
    unresolved_results: List[Dict[str, Any]],
    gateway_fee_pct: float = 0.02,
    settlement_window_days: int = 3,
) -> List[Dict[str, Any]]:
    """
    Iterates through UNRESOLVED items, calling Gemini for each one.
    Updates each record in-place with final_decision, confidence, reason,
    exception_type, and resolution_method='AI_RESOLVED'.
    Includes a 3.5s delay between calls to respect API rate limits.
    """
    import time
    try:
        client = get_gemini_client()
        model_name = get_gemini_model_name()
    except Exception as e:
        client = None
        model_name = None

    resolved_list = []
    for idx, item in enumerate(unresolved_results):
        if item.get("final_decision") not in ("UNRESOLVED", None):
            resolved_list.append(item)
            continue

        if idx > 0:
            time.sleep(3.5)

        ai_out = resolve_ambiguous_case(
            payment_record=item.get("payment_record", {}),
            bank_candidates=item.get("bank_candidates", []),
            ledger_record=item.get("ledger_record"),
            gateway_fee_pct=gateway_fee_pct,
            settlement_window_days=settlement_window_days,
            client=client,
            model_name=model_name,
        )

        item["final_decision"] = ai_out["decision"]
        item["confidence"] = ai_out["confidence"]
        item["reason"] = ai_out["reason"]
        item["exception_type"] = ai_out.get("exception_type")
        if ai_out.get("exception_type") == "LLM_PARSE_FAILURE":
            item["resolution_method"] = "AI_FAILED"
        else:
            item["resolution_method"] = "AI_RESOLVED"
        if ai_out.get("matched_bank_id"):
            item["matched_bank_id"] = ai_out["matched_bank_id"]

        resolved_list.append(item)

    return resolved_list
