"""
app.py
------
Streamlit Interactive Dashboard for ReconAI: Multi-Source Finance Reconciliation Agent.

Modes:
  1. Demo Mode (Cached Final Run) [Default]:
     - Visualizes the canonical 90-record multi-source reconciliation benchmark.
     - Loads from data/reconciliation_cache.pkl with zero Gemini API calls or quota consumption.
     - Complete evaluation oracle metrics (Binary Accuracy, FP, FN, Confusion Matrix, Per-Exception Metrics).
  2. Upload CSV Data:
     - Allows users to upload Payment Gateway, Bank Settlement, and Merchant Ledger CSVs.
     - Reconciles records completely in-memory without overwriting canonical benchmark files.
     - Validates schemas, empty files, and encodings gracefully with informative error messages.
     - Displays operational metrics, AI health status, reconciliation breakdown, and full drill-down explorer.
"""

import os
import io
import csv
import pickle
from typing import Set, Tuple, List, Dict, Any
import pandas as pd
import streamlit as st

import pipeline

# Configure Streamlit page
st.set_page_config(
    page_title="ReconAI -- Finance Reconciliation Agent",
    page_icon="⚖️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ---------------------------------------------------------------------------
# Constants & Schemas
# ---------------------------------------------------------------------------

REQUIRED_PAYMENT_COLS: Set[str] = {
    "transaction_id", "payment_date", "payment_amount",
    "customer_name", "payment_reference", "status"
}

REQUIRED_BANK_COLS: Set[str] = {
    "bank_id", "settlement_date", "settlement_amount",
    "description", "bank_reference"
}

REQUIRED_LEDGER_COLS: Set[str] = {
    "ledger_id", "ledger_date", "ledger_amount",
    "customer_name", "ledger_reference"
}


# ---------------------------------------------------------------------------
# CSV Parsing & Validation Helper (In-Memory)
# ---------------------------------------------------------------------------

def parse_and_validate_csv(file_obj, required_columns: Set[str], file_label: str) -> Tuple[bool, List[Dict[str, Any]], str]:
    """
    Parses an uploaded CSV file into a list of dicts and validates required columns.
    Returns (success: bool, records: list, error_message: str)
    Handles empty files, encodings, and missing columns without throwing unhandled exceptions.
    """
    if file_obj is None:
        return False, [], f"No file uploaded for {file_label}."

    try:
        content_bytes = file_obj.getvalue()
        if not content_bytes or len(content_bytes.strip()) == 0:
            return False, [], f"**{file_label}** is empty."

        # Decode utf-8 with fallback to latin-1
        try:
            content_str = content_bytes.decode("utf-8")
        except UnicodeDecodeError:
            try:
                content_str = content_bytes.decode("latin-1")
            except Exception as decode_err:
                return False, [], f"**{file_label}** could not be decoded: {decode_err}"

        reader = csv.DictReader(io.StringIO(content_str))
        if not reader.fieldnames:
            return False, [], f"**{file_label}** has no header row or columns."

        fieldnames_set = set(reader.fieldnames)
        missing_columns = required_columns - fieldnames_set
        if missing_columns:
            missing_sorted = sorted(list(missing_columns))
            return False, [], f"**{file_label}** is missing required column(s): `{', '.join(missing_sorted)}`"

        records = list(reader)
        if not records:
            return False, [], f"**{file_label}** contains a header row but zero data records."

        return True, records, ""
    except Exception as e:
        return False, [], f"Error reading **{file_label}**: {str(e)}"


# ---------------------------------------------------------------------------
# Data Loading for Demo Mode (Cached Benchmark Run)
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner=False)
def get_demo_pipeline_data() -> Dict[str, Any]:
    """
    Loads reconciliation results for Demo Mode. Uses local cached run
    (data/reconciliation_cache.pkl) to avoid consuming external Gemini quota.
    """
    cache_path = os.path.join("data", "reconciliation_cache.pkl")
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "rb") as f:
                return pickle.load(f)
        except Exception:
            pass

    data = pipeline.run_pipeline()
    try:
        with open(cache_path, "wb") as f:
            pickle.dump(data, f)
    except Exception:
        pass
    return data


# ---------------------------------------------------------------------------
# Reusable UI Component: Reconciliation Breakdown Table
# ---------------------------------------------------------------------------

def render_reconciliation_breakdown(summary: Dict[str, Any], final_results: List[Dict[str, Any]], section_num: str = "3"):
    st.subheader(f"{section_num}. Reconciliation Breakdown")
    total = summary.get("total_records", 0)

    dup_count = sum(1 for r in final_results if r.get("resolution_method") == "DUPLICATE_CANDIDATE")
    no_bank_count = sum(1 for r in final_results if r.get("resolution_method") == "NO_BANK_RECORD")
    ai_failed_count = summary.get("ai_failed_count", 0)
    ai_succ_count = summary.get("ai_successful_count", 0)

    breakdown_data = [
        {
            "Category": "Deterministic Match (Exact)",
            "Resolution Method": "MATCHED_BY_RULE",
            "Type": "MATCH",
            "Count": summary["matched_by_rule"],
            "Share": f"{(summary['matched_by_rule'] / total * 100):.1f}%" if total else "0.0%",
            "Description": "Exact amount + reference + date within 3-day window"
        },
        {
            "Category": "Deterministic Match (Fee-adjusted)",
            "Resolution Method": "MATCHED_WITH_FEE",
            "Type": "MATCH",
            "Count": summary["matched_with_fee"],
            "Share": f"{(summary['matched_with_fee'] / total * 100):.1f}%" if total else "0.0%",
            "Description": "Settlement amount equals payment minus 2.0% gateway fee"
        },
        {
            "Category": "Duplicate Bank Candidates",
            "Resolution Method": "DUPLICATE_CANDIDATE",
            "Type": "BUSINESS EXCEPTION",
            "Count": dup_count,
            "Share": f"{(dup_count / total * 100):.1f}%" if total else "0.0%",
            "Description": "Multiple bank credits sharing reference within settlement window"
        },
        {
            "Category": "Missing Bank Settlement",
            "Resolution Method": "NO_BANK_RECORD",
            "Type": "BUSINESS EXCEPTION",
            "Count": no_bank_count,
            "Share": f"{(no_bank_count / total * 100):.1f}%" if total else "0.0%",
            "Description": "Payment captured but no bank credit received"
        }
    ]

    if ai_succ_count > 0:
        breakdown_data.append({
            "Category": "AI Resolved Cases",
            "Resolution Method": "AI_RESOLVED",
            "Type": "AI RESOLUTION",
            "Count": ai_succ_count,
            "Share": f"{(ai_succ_count / total * 100):.1f}%" if total else "0.0%",
            "Description": "Ambiguous case successfully reconciled by Gemini reasoning"
        })

    if ai_failed_count > 0:
        breakdown_data.append({
            "Category": "AI Escalated / Quota Fallback",
            "Resolution Method": "AI_FAILED",
            "Type": "AI SYSTEM FAILURE",
            "Count": ai_failed_count,
            "Share": f"{(ai_failed_count / total * 100):.1f}%" if total else "0.0%",
            "Description": "Ambiguous amount mismatch where Gemini hit free-tier daily quota"
        })

    df_breakdown = pd.DataFrame(breakdown_data)
    st.dataframe(df_breakdown, width="stretch", hide_index=True)
    st.divider()


# ---------------------------------------------------------------------------
# Reusable UI Component: Transaction Drill-Down Explorer
# ---------------------------------------------------------------------------

def render_drill_down_explorer(final_results: List[Dict[str, Any]], section_num: str = "5"):
    st.subheader(f"{section_num}. Transaction Drill-Down Explorer")
    st.markdown("Inspect individual transactions, payment details, candidate bank records, and controller decisions.")

    if not final_results:
        st.info("No transaction records to display.")
        return

    # Filter Bar
    f_col1, f_col2, f_col3 = st.columns([1, 1, 2])
    with f_col1:
        decision_filter = st.selectbox(
            "Filter by Decision",
            ["ALL", "MATCH", "EXCEPTION"]
        )
    with f_col2:
        available_methods = ["ALL"] + sorted(list({r.get("resolution_method", "") for r in final_results if r.get("resolution_method")}))
        method_filter = st.selectbox(
            "Filter by Method",
            available_methods
        )
    with f_col3:
        search_query = st.text_input(
            "🔍 Search Transaction ID, Reference, or Name",
            ""
        )

    # Apply Filters
    filtered_results = final_results
    if decision_filter != "ALL":
        filtered_results = [r for r in filtered_results if r["final_decision"] == decision_filter]
    if method_filter != "ALL":
        filtered_results = [r for r in filtered_results if r.get("resolution_method") == method_filter]
    if search_query.strip():
        q = search_query.strip().lower()
        filtered_results = [
            r for r in filtered_results
            if q in str(r.get("transaction_id", "")).lower()
            or q in str(r.get("payment_record", {}).get("payment_reference", "")).lower()
            or q in str(r.get("payment_record", {}).get("customer_name", "")).lower()
        ]

    # Summary Table of Filtered Transactions
    table_rows = []
    for r in filtered_results:
        p = r.get("payment_record", {})
        try:
            amt_float = float(p.get("payment_amount", 0))
            amt_str = f"{amt_float:,.2f}"
        except (ValueError, TypeError):
            amt_str = str(p.get("payment_amount", "0.00"))

        table_rows.append({
            "Txn ID": r.get("transaction_id"),
            "Customer": p.get("customer_name", "N/A"),
            "Payment Amt (₹)": amt_str,
            "Payment Date": str(p.get("payment_date", "")),
            "Decision": r.get("final_decision"),
            "Resolution Method": r.get("resolution_method", "N/A"),
            "Exception Type": r.get("exception_type") or "-",
            "Matched Bank ID": r.get("matched_bank_id") or "-",
        })

    df_table = pd.DataFrame(table_rows)
    st.dataframe(df_table, width="stretch", height=280)
    st.caption(f"Showing {len(filtered_results)} of {len(final_results)} transactions.")

    # Transaction Details Card
    st.markdown("#### Detailed Transaction Inspection")

    txn_options = [r["transaction_id"] for r in filtered_results] if filtered_results else [r["transaction_id"] for r in final_results]
    selected_txn_id = st.selectbox(
        "Select Transaction to Inspect in Depth",
        txn_options
    )

    selected_record = next((r for r in final_results if r["transaction_id"] == selected_txn_id), None)

    if selected_record:
        pay = selected_record.get("payment_record", {})
        bank_cands = selected_record.get("bank_candidates", [])
        ledger = selected_record.get("ledger_record")
        dec = selected_record.get("final_decision")
        meth = selected_record.get("resolution_method")
        exc_type = selected_record.get("exception_type")
        conf = selected_record.get("confidence", 0.0)
        reason = selected_record.get("reason", "N/A")

        # Banner for AI_FAILED
        if meth == "AI_FAILED":
            st.error(
                f"""
                🚨 **AI SYSTEM FAILURE — QUOTA EXHAUSTION (`LLM_PARSE_FAILURE`)**  
                **Plain-Language Explanation:**  
                The AI layer was rate-limited by Gemini's free-tier daily quota (`RESOURCE_EXHAUSTED`). 
                This does **NOT** mean the underlying financial records were proven to be invalid. 
                ReconAI safely left the case held as an exception rather than risk force-matching.
                
                **Actual Controller Error / Reason:** `{reason}`
                """
            )
        elif dec == "EXCEPTION":
            st.warning(f"⚠️ **Business Exception Flagged:** `{exc_type}` via method `{meth}` (Confidence: {conf})")
        else:
            st.success(f"✅ **Reconciliation Match Confirmed:** via `{meth}` (Confidence: {conf})")

        # 3-Way Record Comparison Columns
        det_c1, det_c2, det_c3 = st.columns(3)

        with det_c1:
            st.markdown("##### 💳 Payment Gateway Record")
            st.write(f"**Txn ID:** `{pay.get('transaction_id')}`")
            st.write(f"**Customer:** {pay.get('customer_name')}")
            try:
                p_amt = float(pay.get("payment_amount", 0))
                st.write(f"**Amount:** ₹{p_amt:,.2f}")
            except (ValueError, TypeError):
                st.write(f"**Amount:** ₹{pay.get('payment_amount', 0)}")
            st.write(f"**Date:** {pay.get('payment_date')}")
            st.write(f"**Reference:** `{pay.get('payment_reference')}`")
            st.write(f"**Status:** `{pay.get('status')}`")

        with det_c2:
            st.markdown(f"##### 🏦 Bank Settlement Records ({len(bank_cands)} candidate{'s' if len(bank_cands) != 1 else ''})")
            if bank_cands:
                for i, b in enumerate(bank_cands, 1):
                    st.markdown(f"**Candidate #{i}: `{b.get('bank_id')}`**")
                    try:
                        b_amt = float(b.get("settlement_amount", 0))
                        st.write(f"- **Settlement Amt:** ₹{b_amt:,.2f}")
                    except (ValueError, TypeError):
                        st.write(f"- **Settlement Amt:** ₹{b.get('settlement_amount', 0)}")
                    st.write(f"- **Settlement Date:** {b.get('settlement_date')}")
                    st.write(f"- **Bank Ref:** `{b.get('bank_reference')}`")
                    st.write(f"- **Description:** `{b.get('description')}`")
            else:
                st.info("No bank settlement candidates found for this transaction.")

        with det_c3:
            st.markdown("##### 📖 Merchant Internal Ledger")
            if ledger:
                st.write(f"**Ledger ID:** `{ledger.get('ledger_id')}`")
                st.write(f"**Customer:** {ledger.get('customer_name')}")
                try:
                    l_amt = float(ledger.get("ledger_amount", 0))
                    st.write(f"**Amount:** ₹{l_amt:,.2f}")
                except (ValueError, TypeError):
                    st.write(f"**Amount:** ₹{ledger.get('ledger_amount', 0)}")
                st.write(f"**Date:** {ledger.get('ledger_date')}")
                st.write(f"**Reference:** `{ledger.get('ledger_reference')}`")
            else:
                st.info("No internal ledger record attached.")

        # Audit Trail & Rationale
        st.markdown("##### 📝 Controller Rationale & Audit Trail")
        st.code(reason, language="text")


# ---------------------------------------------------------------------------
# Sidebar Controls & Engine Configuration
# ---------------------------------------------------------------------------

st.sidebar.title("⚖️ ReconAI Controller")
st.sidebar.markdown("**Track 04: AI Finance Controller**")
st.sidebar.markdown("*Solo Submission -- Razorpay AI Buildathon*")
st.sidebar.divider()

# Mode Selector (Demo Mode is default)
app_mode = st.sidebar.radio(
    "Select Mode",
    ["Demo Mode (Cached Final Run)", "Upload CSV Data"],
    index=0
)

st.sidebar.divider()
st.sidebar.subheader("⚙️ Engine Configuration")
st.sidebar.write(f"**Gateway Fee:** 2.0% (₹0.50 tol.)")
st.sidebar.write(f"**Settlement Window:** 3 Days")
st.sidebar.write(f"**AI Model:** `gemini-3.6-flash`")


# ===========================================================================
# MODE 1: DEMO MODE (CACHED BENCHMARK RUN)
# ===========================================================================

if app_mode == "Demo Mode (Cached Final Run)":
    # Load cached data
    pipeline_output = get_demo_pipeline_data()
    summary = pipeline_output["summary"]
    evaluation = pipeline_output["evaluation"]
    final_results = pipeline_output["final_results"]
    exception_list = pipeline_output["exception_list"]
    pem = evaluation["per_exception_metrics"]

    st.sidebar.write(f"**Total Records:** {summary['total_records']}")

    # Section 1: Header & System Status / Validation Note
    st.title("⚖️ ReconAI — Multi-Source Reconciliation Dashboard")
    st.caption("Automated financial reconciliation across Payment Gateway, Bank Settlements, and Merchant Ledger.")

    st.info(
        """
        ℹ️ **System Status / Validation Note:**  
        **Final validation run:** Gemini free-tier daily quota was exhausted (`RESOURCE_EXHAUSTED: 20 reqs/day cap`), 
        so all 7 AI-escalated cases safely degraded to `AI_FAILED`. During earlier development validation, 
        the Gemini AI layer successfully produced structured reasoning for ambiguous cases. The final run 
        does not claim those 7 cases were successfully AI-resolved.
        """
    )

    # Section 2: Executive Summary (9 Distinct Metrics)
    st.subheader("1. Executive Summary")

    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.metric(
            label="Total Transactions",
            value=summary["total_records"]
        )
    with col2:
        st.metric(
            label="Deterministic Matches",
            value=f"{summary['total_deterministic_matches']}",
            help="63 Matched by Rule (Exact) + 8 Matched with Fee (2%)"
        )
    with col3:
        st.metric(
            label="Rule-Based Exceptions",
            value=f"{summary['rule_exceptions']}",
            help="5 Duplicate Settlements + 7 Missing Bank Records"
        )
    with col4:
        st.metric(
            label="AI Escalated",
            value=f"{summary['unresolved_sent_to_ai']}",
            help="Ambiguous cases with unexplained amount gap escalated to Gemini"
        )
    with col5:
        st.metric(
            label="AI Successful",
            value=f"{summary.get('ai_successful_count', 0)}",
            help="Ambiguous cases successfully resolved by Gemini reasoning"
        )

    col6, col7, col8, col9, col10 = st.columns(5)
    with col6:
        st.metric(
            label="AI/System Failures",
            value=f"{summary.get('ai_failed_count', 7)}",
            help="Cases where Gemini was unavailable (rate-limited / quota exhausted)"
        )
    with col7:
        st.metric(
            label="Binary Accuracy",
            value=f"{evaluation['overall_accuracy'] * 100:.1f}%",
            help="Correct Binary Decisions (MATCH vs EXCEPTION): 90 / 90"
        )
    with col8:
        st.metric(
            label="False Positives (FP)",
            value=f"{evaluation['false_positives']}",
            help="System matched an invalid exception (Target: 0)"
        )
    with col9:
        st.metric(
            label="False Negatives (FN)",
            value=f"{evaluation['false_negatives']}",
            help="System flagged a valid match as exception (Target: 0)"
        )
    with col10:
        st.metric(
            label="Match Rate",
            value=f"{summary['match_rate']:.1f}%",
            help="Final matched transactions / Total transactions"
        )

    st.divider()

    # Section 3: AI Status & Controller Health
    st.subheader("2. AI Status & Controller Health")
    ai_alert_col, ai_stat_col = st.columns([2, 1])

    with ai_alert_col:
        st.warning(
            """
            ⚠️ **AI Health Status: Gemini unavailable due to free-tier daily quota exhaustion**  
            **Controller Safety Guarantee:** The reconciliation engine continued safely without force-matching when Gemini was unavailable.
            
            - **Ambiguous Transactions Escalated:** 7 (Amount gaps of 3%–15% beyond standard 2% gateway fee)
            - **AI Successful:** 0 (Quota limit hit during batch inference)
            - **AI / System Failures:** 7 (`LLM_PARSE_FAILURE` / `AI_FAILED`)
            - **Fail-Safe Action:** Conservative controller degradation — all 7 transactions safely held as **`EXCEPTION`** rather than risking financial leakage through unauthorized matching.
            """
        )

    with ai_stat_col:
        st.markdown("##### AI Health Telemetry")
        st.write(f"- **Active Model:** `gemini-3.6-flash`")
        st.write(f"- **Escalated Cases:** `{summary['unresolved_sent_to_ai']}`")
        st.write(f"- **AI Successful:** `{summary.get('ai_successful_count', 0)}`")
        st.write(f"- **AI / System Failures:** `{summary.get('ai_failed_count', 7)}`")
        st.write(f"- **Daily Free Quota Limit:** `20 requests/day`")

    st.divider()

    # Section 4: Reconciliation Breakdown
    render_reconciliation_breakdown(summary, final_results, section_num="3")

    # Section 5: Evaluation & Ground-Truth Verification
    st.subheader("4. Evaluation & Ground-Truth Oracle Performance")
    st.markdown("*Ground truth (`data/ground_truth.csv`) is strictly used as the evaluation oracle and is never seen by matching logic.*")

    eval_col1, eval_col2 = st.columns([1, 1])

    with eval_col1:
        st.markdown("##### Binary Decision Confusion Matrix")
        act_match = evaluation['true_positives'] + evaluation['false_negatives']
        act_exc = evaluation['true_negatives'] + evaluation['false_positives']
        pred_match = evaluation['true_positives'] + evaluation['false_positives']
        pred_exc = evaluation['true_negatives'] + evaluation['false_negatives']
        conf_matrix = pd.DataFrame(
            [
                [f"True Positive (TP): {evaluation['true_positives']}", f"False Negative (FN): {evaluation['false_negatives']}"],
                [f"False Positive (FP): {evaluation['false_positives']}", f"True Negative (TN): {evaluation['true_negatives']}"]
            ],
            index=[f"Actual MATCH ({act_match})", f"Actual EXCEPTION ({act_exc})"],
            columns=[f"Predicted MATCH ({pred_match})", f"Predicted EXCEPTION ({pred_exc})"]
        )
        st.table(conf_matrix)
        st.caption(
            f"**Accuracy:** {evaluation['overall_accuracy']*100:.2f}% | "
            f"**False-Positive Rate:** {evaluation['false_positive_rate']*100:.2f}% | "
            f"**False-Negative Rate:** {evaluation['false_negative_rate']*100:.2f}%"
        )

    with eval_col2:
        st.markdown("##### Business Exception-Type Metrics")
        exc_rows = []
        for cat in ["AMOUNT_MISMATCH", "DUPLICATE_SETTLEMENT", "MISSING_RECORD", "UNEXPLAINED"]:
            m = pem[cat]
            prec_str = m["display"] if m["display"] else f"{m['precision']*100:.1f}%"
            rec_str = m["display"] if m["display"] else f"{m['recall']*100:.1f}%"
            exc_rows.append({
                "Exception Category": cat,
                "Actual (Ground Truth)": m["actual"],
                "Predicted by Engine": m["predicted"],
                "Precision": prec_str,
                "Recall": rec_str,
            })
        df_exc = pd.DataFrame(exc_rows)
        st.dataframe(df_exc, width='stretch', hide_index=True)

    st.divider()

    # Section 6: Transaction Drill-Down Explorer
    render_drill_down_explorer(final_results, section_num="5")


# ===========================================================================
# MODE 2: UPLOAD CSV DATA
# ===========================================================================

else:
    st.title("⚖️ ReconAI — Upload CSV Data Reconciliation")
    st.caption("Upload multi-source transaction data (Payment Gateway, Bank Settlement, Merchant Ledger) for real-time reconciliation.")

    st.info(
        """
        ℹ️ **Ground Truth Notice:**  
        `ground_truth.csv` is **not required** for production reconciliation — ground truth is strictly an evaluation oracle.  
        ReconAI executes deterministic matching, candidate validation, and AI escalation directly from the three uploaded operational feeds.
        """
    )

    st.markdown("### 📤 Upload Operational Data Feeds")
    up_c1, up_c2, up_c3 = st.columns(3)

    with up_c1:
        st.markdown("#### 1. Payment Gateway")
        pay_file = st.file_uploader(
            "Upload payments.csv",
            type=["csv"],
            key="csv_upload_payments",
            help="Required columns: transaction_id, payment_date, payment_amount, customer_name, payment_reference, status"
        )
        st.caption("Required: `transaction_id`, `payment_date`, `payment_amount`, `customer_name`, `payment_reference`, `status`")

    with up_c2:
        st.markdown("#### 2. Bank Settlement")
        bank_file = st.file_uploader(
            "Upload bank.csv",
            type=["csv"],
            key="csv_upload_bank",
            help="Required columns: bank_id, settlement_date, settlement_amount, description, bank_reference"
        )
        st.caption("Required: `bank_id`, `settlement_date`, `settlement_amount`, `description`, `bank_reference`")

    with up_c3:
        st.markdown("#### 3. Merchant Ledger")
        ledger_file = st.file_uploader(
            "Upload ledger.csv",
            type=["csv"],
            key="csv_upload_ledger",
            help="Required columns: ledger_id, ledger_date, ledger_amount, customer_name, ledger_reference"
        )
        st.caption("Required: `ledger_id`, `ledger_date`, `ledger_amount`, `customer_name`, `ledger_reference`")

    all_uploaded = pay_file is not None and bank_file is not None and ledger_file is not None

    btn_col1, btn_col2 = st.columns([2, 8])
    with btn_col1:
        run_clicked = st.button(
            "🚀 Run Reconciliation",
            disabled=not all_uploaded,
            type="primary",
            help="Upload all 3 CSV files to enable reconciliation." if not all_uploaded else "Execute multi-source reconciliation in-memory."
        )

    with btn_col2:
        if "uploaded_recon_data" in st.session_state:
            if st.button("🗑️ Reset Uploaded Results", key="reset_uploaded_btn"):
                del st.session_state["uploaded_recon_data"]
                if "uploaded_file_info" in st.session_state:
                    del st.session_state["uploaded_file_info"]
                st.rerun()

    # Handle Run Reconciliation Action
    if run_clicked and all_uploaded:
        # Step 1: Validate and parse each file in-memory
        p_ok, raw_payments, p_err = parse_and_validate_csv(pay_file, REQUIRED_PAYMENT_COLS, "Payment Gateway CSV")
        b_ok, raw_banks, b_err = parse_and_validate_csv(bank_file, REQUIRED_BANK_COLS, "Bank Settlement CSV")
        l_ok, raw_ledgers, l_err = parse_and_validate_csv(ledger_file, REQUIRED_LEDGER_COLS, "Merchant Ledger CSV")

        if not p_ok:
            st.error(p_err)
        elif not b_ok:
            st.error(b_err)
        elif not l_ok:
            st.error(l_err)
        else:
            with st.spinner("Reconciling uploaded records across deterministic rules and AI controller..."):
                try:
                    # In-memory execution: zero files written to disk!
                    recon_output = pipeline.reconcile_records(
                        raw_payments=raw_payments,
                        raw_banks=raw_banks,
                        raw_ledgers=raw_ledgers,
                        ground_truth_path=None
                    )
                    st.session_state["uploaded_recon_data"] = recon_output
                    st.session_state["uploaded_file_info"] = {
                        "pay": (pay_file.name, len(raw_payments)),
                        "bank": (bank_file.name, len(raw_banks)),
                        "ledger": (ledger_file.name, len(raw_ledgers)),
                    }
                    st.success(f"✅ Successfully reconciled {len(raw_payments)} transactions in-memory!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Reconciliation failed during execution: {str(e)}")

    st.divider()

    # Display Uploaded Reconciliation Results (if available in session state)
    if "uploaded_recon_data" in st.session_state:
        uploaded_data = st.session_state["uploaded_recon_data"]
        up_summary = uploaded_data["summary"]
        up_final_results = uploaded_data["final_results"]
        up_info = st.session_state.get("uploaded_file_info", {})

        pay_meta = up_info.get("pay", ("payments.csv", up_summary["total_records"]))
        bank_meta = up_info.get("bank", ("bank.csv", "-"))
        ledger_meta = up_info.get("ledger", ("ledger.csv", "-"))

        st.sidebar.write(f"**Total Uploaded Records:** {up_summary['total_records']}")

        st.subheader("1. Operational Summary — Uploaded Data Reconciliation")
        st.caption(
            f"Sources: **{pay_meta[0]}** ({pay_meta[1]} payments) • "
            f"**{bank_meta[0]}** ({bank_meta[1]} bank credits) • "
            f"**{ledger_meta[0]}** ({ledger_meta[1]} ledger entries) • "
            f"Processing Time: {up_summary.get('processing_time_sec', 0.0)}s"
        )

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric(
                label="Total Transactions",
                value=up_summary["total_records"]
            )
        with col2:
            st.metric(
                label="Deterministic Matches",
                value=f"{up_summary['total_deterministic_matches']}",
                help=f"{up_summary['matched_by_rule']} Exact + {up_summary['matched_with_fee']} Fee-adjusted"
            )
        with col3:
            st.metric(
                label="Rule-Based Exceptions",
                value=f"{up_summary['rule_exceptions']}",
                help="Duplicate settlements and missing bank records"
            )
        with col4:
            st.metric(
                label="Match Rate",
                value=f"{up_summary['match_rate']:.1f}%",
                help="Final matched transactions / Total transactions"
            )

        col5, col6, col7 = st.columns(3)
        with col5:
            st.metric(
                label="AI Escalated",
                value=f"{up_summary['unresolved_sent_to_ai']}",
                help="Ambiguous cases with unexplained amount gap escalated to Gemini"
            )
        with col6:
            st.metric(
                label="AI Successful",
                value=f"{up_summary.get('ai_successful_count', 0)}",
                help="Ambiguous cases successfully resolved by Gemini reasoning"
            )
        with col7:
            st.metric(
                label="AI/System Failures",
                value=f"{up_summary.get('ai_failed_count', 0)}",
                help="Cases where Gemini was unavailable (rate-limited / quota exhausted)"
            )

        st.info(
            """
            ℹ️ **Evaluation Oracle Notice:**  
            Ground-truth evaluation metrics (binary accuracy, false positives, false negatives, confusion matrix) 
            require an answer key (`ground_truth.csv`) and are displayed in **Demo Mode**. 
            Operational reconciliation metrics, candidate analysis, and individual transaction audit trails are shown below.
            """
        )

        st.divider()

        # Section 2: AI Status & Controller Health
        st.subheader("2. AI Status & Controller Health")
        ai_up1, ai_up2 = st.columns([2, 1])

        with ai_up1:
            if up_summary["unresolved_sent_to_ai"] == 0:
                st.success(
                    "✅ **All transactions resolved deterministically.**  \n"
                    "Every transaction was matched or categorized via deterministic business rules (exact match, "
                    "2.0% fee tolerance, duplicate candidates, or missing bank records). Zero Gemini calls were required."
                )
            elif up_summary.get("ai_failed_count", 0) > 0 and up_summary.get("ai_successful_count", 0) == 0:
                st.warning(
                    f"""
                    ⚠️ **AI Health Status: Gemini rate limit / quota encountered**  
                    {up_summary.get('ai_failed_count', 0)} cases were escalated to Gemini due to ambiguous amount gaps, 
                    and safely fell back to `AI_FAILED` exceptions without financial leakage.
                    """
                )
            else:
                st.success(
                    f"""
                    ✅ **AI Resolution Layer Active**  
                    {up_summary.get('ai_successful_count', 0)} of {up_summary['unresolved_sent_to_ai']} escalated cases 
                    were successfully resolved with structured LLM reasoning.
                    """
                )

        with ai_up2:
            st.markdown("##### AI Health Telemetry")
            st.write(f"- **Active Model:** `gemini-3.6-flash`")
            st.write(f"- **Escalated Cases:** `{up_summary['unresolved_sent_to_ai']}`")
            st.write(f"- **AI Successful:** `{up_summary.get('ai_successful_count', 0)}`")
            st.write(f"- **AI / System Failures:** `{up_summary.get('ai_failed_count', 0)}`")

        st.divider()

        # Section 3: Reconciliation Breakdown
        render_reconciliation_breakdown(up_summary, up_final_results, section_num="3")

        # Section 4: Transaction Drill-Down Explorer
        render_drill_down_explorer(up_final_results, section_num="4")

    else:
        st.info(
            "👆 Please upload all three CSV files above and click **Run Reconciliation** to process multi-source reconciliation in real time."
        )

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------
st.divider()
st.caption("ReconAI • Built for Razorpay AI Buildathon 2026 (Track 04: AI Finance Controller) • Python + Streamlit")
