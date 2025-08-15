import os
import json
import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from .cloud_store import (
    fetch_rows,
    download_pdf,
    path_for,
    file_exists,
    upload_pdf,
    upsert_row,
    save_resolution,
    fetch_resolutions,
    make_metric_key,
)
from .quartr_loader import load_company_years
from .guidance import extract_for_ticker
from .merge import merge_items, canon_period, canon_metric, bucketize

def _inject_secrets_to_env():
    load_dotenv()
    if hasattr(st, "secrets"):
        for key, val in st.secrets.items():
            if isinstance(val, str) and not os.getenv(key):
                os.environ[key] = val

def ensure_playwright():
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
        return True
    except Exception:
        try:
            import subprocess
            import sys
            subprocess.run([sys.executable, "-m", "playwright", "install", "chromium", "--with-deps"], check=True)
            return True
        except Exception as e:
            st.warning(f"Playwright install may be incomplete: {e}")
            return False

def main():
    _inject_secrets_to_env()
    st.set_page_config(page_title="Earnings Guidance Extractor (Supabase)", layout="wide")
    st.title("📈 Earnings Guidance Extractor — Supabase storage (organized & idempotent)")

    tab1, tab2 = st.tabs(["Load data", "Guidance (extract, merge, resolve)"])

    with tab1:
        ensure_playwright()
        st.subheader("Backfill from Quartr → Supabase")
        tickers = st.text_input("Tickers (comma-separated)", "AAPL, MSFT")
        col1, col2 = st.columns(2)
        with col1:
            start_year = st.number_input("Start year", min_value=2000, max_value=2100, value=2023, step=1)
        with col2:
            end_year = st.number_input("End year", min_value=2000, max_value=2100, value=2024, step=1)
        headless = st.checkbox("Run headless", value=True, help="Uncheck to debug with a visible browser")
        if st.button("Run backfill"):
            os.environ["HEADLESS"] = "1" if headless else "0"
            for t in [t.strip().upper() for t in tickers.split(",") if t.strip()]:
                with st.spinner(f"Loading {t} {start_year}-{end_year}..."):
                    try:
                        load_company_years(t, start_year, end_year)
                        st.success(f"Loaded {t}")
                    except Exception as e:
                        st.error(f"Failed {t}: {e}")

    with tab2:
        st.subheader("Extract & Merge")
        tg = st.text_input("Ticker", "AAPL")
        mdl = st.text_input("OpenAI model", "gpt-4o-mini")
        if st.button("Run extraction for ticker"):
            with st.spinner("Extracting guidance from press releases, presentations, and transcripts..."):
                extract_for_ticker(tg.upper(), mdl)
            st.success("Extraction completed.")

        st.divider()
        st.subheader("Build merged table")
        t = st.text_input("Ticker to view", "")
        if st.button("Build merged view"):
            ticker = (t or tg).strip().upper()
            rows = fetch_rows(ticker, file_type="guidance_json", file_format="json")
            by_src = {"press_release": [], "presentation": [], "transcript": []}
            for r in rows:
                try:
                    items = json.loads(r.get("text_content") or "[]")
                except Exception:
                    items = []
                for it in items:
                    src = it.get("source") or "transcript"
                    it.setdefault("provenance", [])
                    it["provenance"].append(r.get("source_url"))
                    by_src.setdefault(src, []).append(it)

            merged = merge_items(by_src)
            data = [{
                "Metric": m.get("metric"),
                "Value of guide": m.get("guidance_value_text"),
                "Period": m.get("period"),
                "Period type": m.get("period_type"),
                "Low end of guidance": m.get("low_end"),
                "High end of guidance": m.get("high_end"),
                "Average": m.get("average"),
                "Filing date": m.get("filing_date"),
            } for m in merged]

            df = pd.DataFrame(data, columns=[
                "Metric", "Value of guide", "Period", "Period type",
                "Low end of guidance", "High end of guidance", "Average", "Filing date"
            ])
            if df.empty:
                st.info("No structured guidance yet. Try extracting or a different ticker.")
            else:
                st.dataframe(df, use_container_width=True)

            st.divider()
            st.subheader("Resolve conflicts (if any)")

            merged_for_conf = merge_items(by_src)

            from collections import defaultdict
            def key_label(k):
                metric, ptype, fy, q = k
                per = f"{q} FY{fy}" if ptype == "quarter" and fy else (f"Full Year {fy}" if fy else "Period")
                return f"{metric} — {per} ({ptype})"

            merged_by_key = defaultdict(list)
            for m in merged_for_conf:
                _pt, _fy, _q = canon_period(m.get("period") or "")
                pt = m.get("period_type") if m.get("period_type") in ("quarter", "full year") else _pt
                k = (canon_metric(m.get("metric", "")), pt, _fy, _q)
                merged_by_key[k].append(m)

            # Load previous resolutions for preselect
            prev = fetch_resolutions(ticker)
            prev_map = {r.get("metric_key"): r.get("chosen_json") for r in (prev or [])}

            def preselect_index_for_key(k, items):
                chosen = prev_map.get(str(k))
                if not chosen:
                    return 0
                try:
                    chosen_obj = json.loads(chosen)
                except Exception:
                    return 0
                for idx, it in enumerate(items):
                    if (
                        it.get("source") == chosen_obj.get("source") and
                        (it.get("guidance_value_text") or "") == (chosen_obj.get("guidance_value_text") or "") and
                        it.get("low_end") == chosen_obj.get("low_end") and
                        it.get("high_end") == chosen_obj.get("high_end")
                    ):
                        return idx
                return 0

            conflict_keys = [k for k, items in merged_by_key.items() if len(items) > 1]
            if conflict_keys:
                st.warning(f"Found {len(conflict_keys)} conflict group(s). Choose the correct option for each before exporting.")
                if "conflict_choices" not in st.session_state:
                    st.session_state.conflict_choices = {}

                for k in conflict_keys:
                    items = merged_by_key[k]
                    st.write("---")
                    st.write(f"**{key_label(k)}**")
                    options = []
                    for idx, it in enumerate(items):
                        lo = it.get("low_end")
                        hi = it.get("high_end")
                        rng = f"{lo}–{hi}" if (lo is not None and hi is not None and lo != hi) else (f"{lo}" if lo is not None else "")
                        label = f"[{it.get('source', '?')}] {it.get('guidance_value_text', '')}  {('(' + rng + ')') if rng else ''}"
                        options.append(label)
                    default_idx = preselect_index_for_key(k, items)
                    choice = st.radio("Select the correct guidance for this group:", options, index=default_idx, key=f"choice_{k}")
                    st.session_state.conflict_choices[str(k)] = options.index(choice)

                st.info("When you're ready, click **Finalize & Download CSV** below to apply your choices.")
            else:
                st.success("No conflicts detected. You can download the CSV directly.")

            st.divider()
            st.subheader("Finalize & Download")

            if st.button("Finalize & Download CSV"):
                kept = []
                for k, items in merged_by_key.items():
                    if len(items) <= 1:
                        kept.extend(items)
                    else:
                        key_str = str(k)
                        idx = st.session_state.conflict_choices.get(key_str, 0)
                        kept.append(items[idx])

                # Persist chosen resolutions
                for m in kept:
                    fy, q, pt = canon_period(m.get("period") or "")
                    key = make_metric_key(m.get("metric") or "", m.get("period_type") or pt, fy, q)
                    try:
                        save_resolution(ticker, int(fy) if (fy and str(fy).isdigit()) else 0, q or "", key, json.dumps(m, ensure_ascii=False))
                    except Exception:
                        save_resolution(ticker, 0, q or "", key, json.dumps(m, ensure_ascii=False))

                final_rows = [{
                    "Metric": m.get("metric"),
                    "Value of guide": m.get("guidance_value_text"),
                    "Period": m.get("period"),
                    "Period type": m.get("period_type"),
                    "Low end of guidance": m.get("low_end"),
                    "High end of guidance": m.get("high_end"),
                    "Average": m.get("average"),
                    "Filing date": m.get("filing_date"),
                } for m in kept]

                final_df = pd.DataFrame(final_rows, columns=[
                    "Metric", "Value of guide", "Period", "Period type",
                    "Low end of guidance", "High end of guidance", "Average", "Filing date"
                ])
                if final_df.empty:
                    st.info("Nothing to export. Try extracting guidance first.")
                else:
                    st.dataframe(final_df, use_container_width=True)
                    st.download_button("Download CSV", final_df.to_csv(index=False).encode("utf-8"),
                                       file_name=f"{ticker}_guidance_FINAL.csv", mime="text/csv")
