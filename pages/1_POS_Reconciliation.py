from __future__ import annotations

import hashlib
import inspect

import pandas as pd
import streamlit as st

import auth, theme, core, db
import report_export

# Universal POS import is an IMPORT-LAYER extension only.
# It does NOT replace or change core.reconcile().
try:
    import pos_auto_mapper
except Exception:
    pos_auto_mapper = None


st.set_page_config(
    page_title="POS Reconciliation - Retail Control Tower",
    layout="wide",
    page_icon="🧾",
)
auth.require_login({"Admin", "Finance Manager", "Finance Maker", "Finance Checker"})
auth.render_user_sidebar()
st.markdown(theme.global_css(), unsafe_allow_html=True)
st.markdown(
    theme.top_banner(
        "RETAIL CONTROL TOWER",
        "POS Reconciliation – Universal POS Import + Frozen Reconciliation Engine",
    ),
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------
# DEPLOYMENT DIAGNOSTIC
# ---------------------------------------------------------------------
DEPLOYMENT_BUILD = "POS_RECON_UNIVERSAL_IMPORT_2026_08_28_V1"

try:
    _core_source = inspect.getsource(core.read_upload)
except Exception as _diag_err:
    _core_source = f"Unable to inspect core.read_upload: {_diag_err}"

_core_file = getattr(core, "__file__", "Unknown")
_core_hash = hashlib.sha1(
    _core_source.encode("utf-8", errors="ignore")
).hexdigest()[:12]
_uses_old_parser = "pd.read_csv" in _core_source

with st.expander("🛠️ Deployment Diagnostic", expanded=False):
    d1, d2, d3, d4 = st.columns(4)
    d1.metric("Page Build", DEPLOYMENT_BUILD)
    d2.metric("core.py Hash", _core_hash)
    d3.metric("Old pd.read_csv Path", "YES ❌" if _uses_old_parser else "NO ✅")
    d4.metric("Universal POS Mapper", "LOADED ✅" if pos_auto_mapper else "MISSING ❌")

    st.write("**Loaded core.py:**")
    st.code(str(_core_file))

    if _uses_old_parser:
        st.error(
            "This Streamlit process is still running an OLD core.read_upload() "
            "that contains pd.read_csv. Replace/redeploy core.py before testing uploads."
        )
    else:
        st.success("The loaded core.read_upload() is the corrected parser.")

    if pos_auto_mapper is None:
        st.warning(
            "pos_auto_mapper.py is not available. Existing POS formats will still run, "
            "but Universal POS fallback and ADCB/NBK/ANB HIVE adapters are unavailable."
        )


# ---------------------------------------------------------------------
# Universal POS import helpers
# ---------------------------------------------------------------------
def _normalized_pos_is_usable(n: pd.DataFrame) -> bool:
    """Existing parser remains authoritative when it produces usable POS data."""
    if n is None or n.empty:
        return False
    if "POS Amount" not in n.columns:
        return False
    amt = pd.to_numeric(n["POS Amount"], errors="coerce")
    return bool(amt.notna().any())


def _normalize_pos_universal(df, source_file: str, forced=None):
    """
    IMPORT ORDER / SAFETY CONTRACT
    ------------------------------
    1) Existing core.normalize_pos() runs FIRST.
    2) If that fails / produces no usable amount, try explicit confirmed
       adapters (ADCB_CHAIN_DAILY, NBK_MERCHANT_STATEMENT, ANB_HIVE_POS).
    3) Only then use the learned/inferred auto-mapper fallback.
    4) Unknown-layout fallback requires:
         - Auth mapping present
         - Amount mapping present
         - Auth confidence >= 70
         - Amount confidence >= 70
         - Overall confidence >= 70
    5) core.reconcile() is never changed by this helper.

    Returns: (normalized_df, audit_dict)
    """
    legacy_error = ""

    # 1. Existing parser first.
    try:
        n = core.normalize_pos(df, source_file, forced)
        if _normalized_pos_is_usable(n):
            return n, {
                "Import Mode": "EXISTING PARSER",
                "Detected Format": forced or "LEGACY / EXISTING",
                "Confidence": 100.0,
                "Rows": len(n),
                "Safety": "Existing supported format",
            }
    except Exception as e:
        legacy_error = str(e)

    if pos_auto_mapper is None:
        raise ValueError(
            "Existing POS parser could not normalize this sheet and "
            "pos_auto_mapper.py is not available."
            + (f" Existing parser error: {legacy_error}" if legacy_error else "")
        )

    # 2. Explicit confirmed format adapters.
    try:
        adapted, fmt, confidence = pos_auto_mapper.adapt_known_format(df)
    except Exception as e:
        adapted, fmt, confidence = None, None, 0.0
        known_err = str(e)
    else:
        known_err = ""

    if adapted is not None and fmt:
        try:
            n = core.normalize_pos(adapted, source_file, None)
        except Exception as e:
            raise ValueError(f"{fmt} adapter succeeded but normalization failed: {e}")

        if not _normalized_pos_is_usable(n):
            raise ValueError(f"{fmt} adapter produced no usable POS Amount rows.")

        safety = "Confirmed explicit adapter"
        if fmt == "ANB_HIVE_POS":
            safety += (
                "; tr_arf is preserved as transaction reference / normalization auth "
                "because the source has no separate 6-digit approval code. "
                "No approval code is invented."
            )

        return n, {
            "Import Mode": "EXPLICIT UNIVERSAL ADAPTER",
            "Detected Format": fmt,
            "Confidence": float(confidence or 0.0),
            "Rows": len(n),
            "Safety": safety,
        }

    # 3. Generic learned/inferred fallback.
    try:
        adapted, mapping, conf, overall = pos_auto_mapper.adapt_dataframe(df)
    except Exception as e:
        raise ValueError(
            f"Universal POS auto-mapper could not analyze this layout: {e}"
        )

    auth_ok = "auth" in mapping and float(conf.get("auth", 0.0)) >= 70.0
    amount_ok = "amount" in mapping and float(conf.get("amount", 0.0)) >= 70.0
    overall_ok = float(overall or 0.0) >= 70.0

    if not (auth_ok and amount_ok and overall_ok):
        raise ValueError(
            "Unknown POS layout rejected by Universal POS safety gate. "
            f"Required: Auth + Amount mappings and >=70% confidence. "
            f"Observed: auth={conf.get('auth', 0)}%, "
            f"amount={conf.get('amount', 0)}%, overall={overall}%."
        )

    try:
        n = core.normalize_pos(adapted, source_file, None)
    except Exception as e:
        raise ValueError(
            f"Universal POS mapping passed the safety gate but normalization failed: {e}"
        )

    if not _normalized_pos_is_usable(n):
        raise ValueError(
            "Universal POS mapping passed the safety gate but produced no usable POS rows."
        )

    return n, {
        "Import Mode": "AUTO-MAPPER FALLBACK",
        "Detected Format": "LEARNED / INFERRED",
        "Confidence": float(overall or 0.0),
        "Rows": len(n),
        "Safety": (
            f"Auth {conf.get('auth', 0)}% | Amount {conf.get('amount', 0)}% | "
            f"Overall {overall}%"
        ),
    }


# ---------------------------------------------------------------------
# Navigation / control center
# ---------------------------------------------------------------------
st.markdown(
    theme.section_title(1, "POS-TO-GL CONTROL CENTER"),
    unsafe_allow_html=True,
)
st.caption(
    "One operating hub for the full lifecycle: Reconcile → Validate → Settle → "
    "Correct → Close → Configure GL → Create JV → Approve → Post to D365 → "
    "Verify → Adjust Late Transactions."
)
st.markdown(
    '<div class="ct-flow">POS Reconciliation → Commission / Bank / Refund Controls '
    '→ Exceptions & Close → GL Configuration → JV Creation → Approval → '
    'D365 Posting → Verification → Adjustment JV</div>',
    unsafe_allow_html=True,
)


def card(col, title, desc, page, icon):
    with col:
        st.markdown('<div class="ct-card">', unsafe_allow_html=True)
        st.markdown(f"**{icon} {title}**")
        st.caption(desc)
        st.page_link(page, label=f"Open {title}", icon="➡️")
        st.markdown("</div>", unsafe_allow_html=True)


st.subheader("1. Reconciliation & Treasury Controls")
a, b, c = st.columns(3)
card(
    a, "Commission Validation",
    "Validate settled POS/provider commission and VAT against signed contract rates.",
    "pages/10_Commission_Validation.py", "🧾",
)
card(
    b, "Bank Settlement Audit",
    "Match POS batches to real bank credits and measure actual settlement delay.",
    "pages/11_Bank_Settlement_Audit.py", "🏦",
)
card(
    c, "Refund Reconciliation",
    "Control refunds, reversals and provider/bank refund settlement.",
    "pages/12_Refund_Reconciliation.py", "↩️",
)

a, b, c = st.columns(3)
card(
    a, "POS Auto Mapper",
    "Learn and map new POS/provider layouts without replacing proven reconciliation rules.",
    "pages/13_POS_Auto_Mapper.py", "🧩",
)
card(
    b, "Store Mapping Master",
    "Upload/change Provider Store Name → D365 Store Code mappings.",
    "pages/14_Store_Mapping_Master.py", "🏬",
)
card(
    c, "POS Terminal Master",
    "Upload/change Terminal ID → Store Code mappings without changing code.",
    "pages/16_POS_Terminal_Master.py", "🖥️",
)

a, b, c = st.columns(3)
card(
    a, "Merchant ID Master",
    "Upload/change Merchant ID → Store Code mappings for provider files with no Terminal ID.",
    "pages/17_Merchant_ID_Master.py", "🏷️",
)
card(
    b, "Bank Claim Follow Up",
    "Track missing/delayed settlements, claims, ownership, aging and follow-up.",
    "pages/15_Bank_Claim_Follow_Up.py", "📨",
)

st.subheader("2. Close, Configuration & Exception Control")
a, b, c = st.columns(3)
card(
    a, "Month End Close Calendar",
    "Finance close ownership, due dates, status and completion control.",
    "pages/21_Month_End_Close_Calendar.py", "🗓️",
)
card(
    b, "GL Configuration",
    "Maintain country, store, provider and accounting GL mappings used by JV creation.",
    "pages/22_GL_Configuration.py", "⚙️",
)
card(
    c, "Exception Correction Center",
    "Investigate exceptions and apply controlled corrections with reason and audit history.",
    "pages/23_Exception_Correction_Center.py", "🛠️",
)

st.subheader("3. JV, D365 Posting & Verification")
a, b, c = st.columns(3)
card(
    a, "JV Creation",
    "Create weekly store-wise balanced JVs from approved, bank-settled matched transactions.",
    "pages/24_JV_Creation.py", "🧾",
)
card(
    b, "JV Approval Center",
    "Maker-checker finance approval before posting.",
    "pages/25_JV_Approval_Center.py", "✅",
)
card(
    c, "D365 Posting Center",
    "Controlled posting queue with duplicate protection.",
    "pages/26_D365_Posting_Center.py", "🚀",
)
a, b, c = st.columns(3)
card(
    a, "D365 Posting Verification",
    "Capture voucher/status and verify successful posting.",
    "pages/27_D365_Posting_Verification.py", "🔎",
)
card(
    b, "Late Transaction Adjustment JV",
    "Create controlled adjustment/reversal JV for late transactions after close.",
    "pages/28_Late_Transaction_Adjustment_JV.py", "🔁",
)


# ---------------------------------------------------------------------
# Main reconciliation
# ---------------------------------------------------------------------
st.divider()
st.markdown(
    theme.section_title(4, "POS Reconciliation Functions"),
    unsafe_allow_html=True,
)

with st.sidebar:
    st.header("Reconciliation Settings")
    tolerance = st.number_input(
        "Tolerance (SAR)", 0.0, 10.0, 1.0, 0.25
    )
    st.caption(
        "Matched within approved tolerance can proceed only after bank settlement "
        "and Finance approval."
    )

st.info(
    "Universal POS Import is active on this page. Existing formats run through "
    "the proven parser first. Confirmed ADCB / NBK / ANB HIVE adapters are additive "
    "fallbacks. Unknown layouts are processed only when Auth + Amount are mapped "
    "and confidence is at least 70%. The reconciliation engine itself is unchanged."
)

uploads = st.file_uploader(
    "Upload D365 Store Tender + POS/AMEX/Tabby/Tamara/Tap/Universal POS files",
    type=["xlsx", "xls", "csv"],
    accept_multiple_files=True,
)
bank_uploads = st.file_uploader(
    "Upload Bank Statements (ANB / Al Rajhi)",
    type=["xlsx", "xls", "csv"],
    accept_multiple_files=True,
)
prev_cf = st.file_uploader(
    "Previous Carry Forward (optional)",
    type=["xlsx", "xls", "csv"],
    key="cf",
)

if st.button("RUN RECONCILIATION", type="primary", use_container_width=True):
    try:
        tender_parts = []
        pos_parts = []
        quarantine = []
        import_audit = []

        for f in uploads or []:
            try:
                _sheets = core.read_upload(f)
            except Exception:
                st.error(
                    f"Upload parser failed for {f.name}. Loaded core.py: {_core_file} | "
                    f"core hash: {_core_hash} | old pd.read_csv path: {_uses_old_parser}"
                )
                raise

            for sheet, df in _sheets.items():
                typ = core.classify(f"{f.name}-{sheet}", df)

                if typ == "D365 STORE TENDER":
                    tender_parts.append(core.normalize_tender(df))
                    import_audit.append({
                        "File": f.name,
                        "Sheet": sheet,
                        "Classified As": typ,
                        "Import Mode": "D365 TENDER PARSER",
                        "Detected Format": "D365 STORE TENDER",
                        "Confidence": 100.0,
                        "Rows": len(df),
                        "Safety": "Tender source",
                    })
                    continue

                # Existing recognized POS/provider types.
                if typ in {"POS", "AMEX", "TABBY", "TAMARA", "TAP"}:
                    forced = typ if typ in {"AMEX", "TABBY", "TAMARA", "TAP"} else None
                    try:
                        n, audit = _normalize_pos_universal(df, f.name, forced)
                        pos_parts.append(n)
                        import_audit.append({
                            "File": f.name,
                            "Sheet": sheet,
                            "Classified As": typ,
                            **audit,
                        })
                    except Exception as e:
                        quarantine.append({
                            "File": f.name,
                            "Sheet": sheet,
                            "Type": "POS_IMPORT_REJECTED",
                            "Reason": str(e),
                        })
                    continue

                # Unknown classification: still give Universal POS import a
                # controlled chance. This is the critical additive fallback.
                try:
                    n, audit = _normalize_pos_universal(df, f.name, None)
                    pos_parts.append(n)
                    import_audit.append({
                        "File": f.name,
                        "Sheet": sheet,
                        "Classified As": typ,
                        **audit,
                    })
                except Exception as e:
                    quarantine.append({
                        "File": f.name,
                        "Sheet": sheet,
                        "Type": "UNRECOGNIZED_OR_UNSAFE_LAYOUT",
                        "Reason": (
                            f"Classified as {typ}. Universal POS fallback rejected it: {e}"
                        ),
                    })

        # Safety fallback for tender detection only.
        if not tender_parts:
            for f in uploads or []:
                _sheets = core.read_upload(f)
                for sheet, df in _sheets.items():
                    d = core.norm_cols(df)
                    has_store = core.find(d, ["store", "store code", "store name"])
                    has_date = core.find(
                        d, ["transdate", "transaction date", "sales date", "date"]
                    )
                    has_receipt = core.find(
                        d, ["receiptid", "receipt id", "receipt", "receipt number", "receipt no"]
                    )
                    has_auth = core.find(
                        d, [
                            "auth code", "authorization code", "auth",
                            "authorization", "approval code",
                        ]
                    )
                    if has_store and has_date and has_receipt and has_auth:
                        tender_parts.append(core.normalize_tender(df))

        if not tender_parts:
            detected = []
            for f in uploads or []:
                _sheets = core.read_upload(f)
                for sheet, df in _sheets.items():
                    detected.append(
                        f"{f.name} / {sheet}: {core.classify(f.name, df)} | "
                        f"Columns: {', '.join(map(str, list(df.columns)[:12]))}"
                    )
            detail = "\n".join(detected) if detected else "No upload files found."
            raise ValueError(
                "No D365 Store Tender detected. The Store Tender must contain Store, "
                "Transaction Date/Transdate, Receipt ID/Receiptid and Auth Code.\n\n"
                "Detected files:\n" + detail
            )

        tender = pd.concat(tender_parts, ignore_index=True)
        pos = pd.concat(pos_parts, ignore_index=True) if pos_parts else pd.DataFrame()

        # Existing store-resolution priority remains unchanged.
        store_master = db.load_store_mapping_master()
        if not pos.empty and not store_master.empty:
            pos = core.apply_store_mapping_master(pos, store_master)

        merchant_master = db.load_merchant_master()
        if not pos.empty:
            pos = core.apply_merchant_master(pos, merchant_master)

        terminal_master = db.load_terminal_master()
        if not pos.empty:
            pos = core.apply_terminal_master(pos, terminal_master)

        # FROZEN ACCOUNTING MATCH ENGINE.
        matched, us, up = core.reconcile(tender, pos, tolerance)

        banks = []
        bank_skipped = []
        for f in bank_uploads or []:
            try:
                _sheets = core.read_upload(f)
            except Exception:
                st.error(
                    f"Bank parser failed for {f.name}. Loaded core.py: {_core_file} | "
                    f"core hash: {_core_hash}"
                )
                raise

            for sheet, df in _sheets.items():
                bank = "Al Rajhi Bank" if "rajhi" in f.name.lower() else "ANB Bank"
                try:
                    b = core.normalize_bank(df, bank)
                    if b is not None and not b.empty:
                        b["Bank Source File"] = f.name
                        b["Bank Source Sheet"] = sheet
                        banks.append(b)
                    else:
                        bank_skipped.append({
                            "File": f.name,
                            "Sheet": sheet,
                            "Reason": "No usable bank transaction rows",
                        })
                except Exception as e:
                    bank_skipped.append({
                        "File": f.name,
                        "Sheet": sheet,
                        "Reason": str(e),
                    })

        bank = pd.concat(banks, ignore_index=True) if banks else pd.DataFrame()
        matched = core.apply_bank_settlement(matched, bank, tolerance)

        previous = None
        if prev_cf:
            previous = list(core.read_upload(prev_cf).values())[0]
        cf = core.make_carry_forward(us, up, previous)

        qdf = pd.DataFrame(quarantine)
        bqdf = pd.DataFrame(bank_skipped)
        if not bqdf.empty:
            bqdf["Type"] = "BANK_SHEET_SKIPPED"
            qdf = pd.concat([qdf, bqdf], ignore_index=True, sort=False)

        import_audit_df = pd.DataFrame(import_audit)

        st.session_state.ct_result = {
            "matched": matched,
            "unmatched_sales": us,
            "unmatched_pos": up,
            "carry_forward": cf,
            "tender": tender,
            "pos": pos,
            "bank": bank,
            "quarantine": qdf,
            "pos_import_audit": import_audit_df,
        }
        st.success(
            "Reconciliation completed. Universal POS import audit is available below."
        )

    except Exception as e:
        st.exception(e)


r = st.session_state.get("ct_result")
if r:
    m = r["matched"]
    us = r["unmatched_sales"]
    up = r["unmatched_pos"]
    ia = r.get("pos_import_audit", pd.DataFrame())

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Matched / Review", len(m))
    k2.metric("Unmatched D365", len(us))
    k3.metric("Unmatched POS", len(up))
    k4.metric("Bank Settled", int(m["Bank Settled"].sum()) if not m.empty else 0)
    k5.metric(
        "Max Diff",
        f"SAR {m['Difference'].abs().max():,.2f}" if not m.empty else "SAR 0.00",
    )

    if not ia.empty:
        st.subheader("Universal POS Import Audit")
        a, b, c = st.columns(3)
        a.metric("Imported Sheets", len(ia))
        b.metric(
            "Universal / Fallback Sheets",
            int(ia["Import Mode"].astype(str).str.contains("UNIVERSAL|AUTO", regex=True).sum())
            if "Import Mode" in ia.columns else 0,
        )
        c.metric(
            "Explicit Known Formats",
            int(ia["Detected Format"].isin(
                ["ADCB_CHAIN_DAILY", "NBK_MERCHANT_STATEMENT", "ANB_HIVE_POS"]
            ).sum())
            if "Detected Format" in ia.columns else 0,
        )

    tabs = st.tabs([
        "Matched",
        "Unmatched D365",
        "Unmatched POS",
        "Carry Forward",
        "Quarantine",
        "POS Import Audit",
    ])

    with tabs[0]:
        st.dataframe(m, use_container_width=True, hide_index=True)
    with tabs[1]:
        st.dataframe(us, use_container_width=True, hide_index=True)
    with tabs[2]:
        st.dataframe(up, use_container_width=True, hide_index=True)
    with tabs[3]:
        st.dataframe(r["carry_forward"], use_container_width=True, hide_index=True)
    with tabs[4]:
        st.dataframe(r["quarantine"], use_container_width=True, hide_index=True)
    with tabs[5]:
        st.dataframe(ia, use_container_width=True, hide_index=True)

    blob = report_export.create_reconciliation_pack(r, tolerance)
    st.download_button(
        "DOWNLOAD RECONCILIATION PACK",
        blob,
        "RetailReconAI_Reconciliation.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )
