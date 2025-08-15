import os
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError
import fitz  # PyMuPDF
from .cloud_store import path_for, file_exists, upload_pdf, upsert_row, fetch_rows, download_pdf

load_dotenv()

EMAIL = os.getenv("QUARTR_EMAIL")
PASSWORD = os.getenv("QUARTR_PASSWORD")
HEADLESS = os.getenv("HEADLESS", "1") == "1"
SLOW_MO_MS = int(os.getenv("SLOW_MO_MS", "0"))

def is_cloud_headless():
    # If no X server (no DISPLAY), force headless to avoid runtime crash on Streamlit Cloud
    return not os.environ.get("DISPLAY")


QMAP = {'Q1':1,'Q2':2,'Q3':3,'Q4':4}

LABELS = [
    ("Transcript", "transcript"),
    ("Press Release", "press_release"),
    ("Presentation", "presentation"),
]

def pdf_bytes_to_text(pdf_bytes: bytes) -> str:
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        return "\n".join(page.get_text() for page in doc).strip()

def login(page):
    page.goto("https://quartr.com/login", wait_until="networkidle")
    page.wait_for_timeout(500)
    page.get_by_placeholder("Email").fill(EMAIL)
    page.get_by_placeholder("Password").fill(PASSWORD)
    page.get_by_role("button", name="Log in").click()
    page.wait_for_load_state("networkidle")

def open_company(page, ticker: str):
    page.get_by_placeholder("Search").click()
    page.get_by_placeholder("Search").fill(ticker)
    page.keyboard.press("Enter")
    page.wait_for_timeout(1200)
    page.get_by_text(ticker.upper(), exact=False).first.click()
    page.wait_for_load_state("networkidle")

def open_quarter(page, year: int, quarter: str) -> bool:
    patterns = [f"{quarter} {year}", f"{quarter} FY{year}", f"{quarter} {str(year)[-2:]}"]
    for pat in patterns:
        loc = page.get_by_text(pat, exact=False)
        if loc.count():
            loc.first.click()
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(600)
            return True
    return False

def download_label(page, label_text: str):
    locator = page.get_by_text(label_text, exact=False).first
    if not locator or not locator.count():
        return None, None
    try:
        with page.expect_download() as dl_info:
            locator.click()
        dl = dl_info.value
        return dl.read(), dl.url
    except PWTimeoutError:
        return None, None

def ensure_text_row_from_existing_pdf(ticker: str, year: int, quarter: str, ftype: str):
    rows = fetch_rows(ticker, file_type=ftype, file_format="text")
    has_text = any(r["year"] == year and r["quarter"] == quarter for r in rows)
    if has_text:
        return
    key = path_for(ticker, year, quarter, ftype)
    if file_exists(key):
        pdf_bytes = download_pdf(key)
        if pdf_bytes:
            text = pdf_bytes_to_text(pdf_bytes)
            upsert_row(ticker, year, quarter, ftype, "text", None, None, text)

def load_company_years(ticker: str, start_year: int, end_year: int, start_q: str = 'Q1', end_q: str = 'Q4'):
    with sync_playwright() as p:
        args = ["--no-sandbox", "--disable-dev-shm-usage"]
        headless_flag = True if is_cloud_headless() else HEADLESS
        browser = p.chromium.launch(headless=headless_flag, slow_mo=SLOW_MO_MS, args=args)
        ctx = browser.new_context(accept_downloads=True)
        page = ctx.new_page()
        login(page)
        open_company(page, ticker)

        for year in range(start_year, end_year + 1):
            q_start = QMAP[start_q] if year == start_year else 1
            q_end = QMAP[end_q] if year == end_year else 4
            for qi in range(q_start, q_end + 1):
                quarter = f"Q{qi}"
                if not open_quarter(page, year, quarter):
                    print(f"[{ticker}] Skip: could not open {quarter} {year}")
                    continue
                for label, ftype in LABELS:
                    storage_path = path_for(ticker, year, quarter, ftype)
                    if file_exists(storage_path):
                        print(f"[{ticker}] {quarter} {year} — {label}: already exists, skipping download")
                        ensure_text_row_from_existing_pdf(ticker, year, quarter, ftype)
                        continue
                    b, url = download_label(page, label)
                    if not b:
                        print(f"[{ticker}] {quarter} {year} — {label}: not available")
                        continue
                    key = upload_pdf(ticker, year, quarter, ftype, b)
                    text = pdf_bytes_to_text(b)
                    upsert_row(ticker, year, quarter, ftype, "pdf", key, url or None, None)
                    upsert_row(ticker, year, quarter, ftype, "text", None, url or None, text)
                    print(f"[{ticker}] Saved {label} PDF & TEXT ({quarter} {year})")

        ctx.close()
        browser.close()
