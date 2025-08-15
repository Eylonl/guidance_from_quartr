import os
from typing import Optional, List, Dict, Any
from supabase import create_client, Client

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_ANON_KEY")
BUCKET = os.getenv("SUPABASE_BUCKET", "earnings")

sb: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def path_for(ticker: str, year: int, quarter: str, file_type: str) -> str:
    return f"pdfs/{ticker.upper()}/{year}-{quarter}/{file_type}.pdf"

def file_exists(storage_path: str) -> bool:
    if not storage_path:
        return False
    parent, name = storage_path.rsplit("/", 1)
    try:
        entries = sb.storage.from_(BUCKET).list(path=parent)
        return any(e.get("name") == name for e in entries)
    except Exception:
        return False

def upload_pdf(ticker: str, year: int, quarter: str, file_type: str, pdf_bytes: bytes) -> str:
    key = path_for(ticker, year, quarter, file_type)
    sb.storage.from_(BUCKET).upload(key, pdf_bytes, {"content-type": "application/pdf", "upsert": True})
    return key

def download_pdf(storage_path: str) -> Optional[bytes]:
    try:
        return sb.storage.from_(BUCKET).download(storage_path)
    except Exception:
        return None

def upsert_row(ticker: str, year: int, quarter: str,
               file_type: str, file_format: str,
               storage_path: Optional[str], source_url: Optional[str],
               text_content: Optional[str]) -> None:
    sb.table("earnings_files").upsert({
        "ticker": ticker.upper(),
        "year": year,
        "quarter": quarter,
        "file_type": file_type,
        "file_format": file_format,
        "storage_path": storage_path,
        "source_url": source_url,
        "text_content": text_content
    }, on_conflict="ticker,year,quarter,file_type,file_format").execute()

def fetch_rows(ticker: str, file_type: Optional[str] = None, file_format: Optional[str] = None) -> List[Dict[str, Any]]:
    q = sb.table("earnings_files").select("*").eq("ticker", ticker.upper())
    if file_type:
        q = q.eq("file_type", file_type)
    if file_format:
        q = q.eq("file_format", file_format)
    q = q.order("year", desc=True).order("quarter", desc=True)
    return q.execute().data

# Conflict resolution persistence
def make_metric_key(metric: str, period_type: str, fy: Optional[str], q: Optional[str]) -> str:
    m = (metric or "").strip().lower()
    pt = (period_type or "").strip().lower()
    return f"{m}|{pt}|{fy or ''}|{q or ''}"

def save_resolution(ticker: str, year: int, quarter: str, metric_key: str, chosen_json_text: str):
    sb.table("guidance_resolved").upsert({
        "ticker": ticker.upper(),
        "year": year,
        "quarter": quarter,
        "metric_key": metric_key,
        "chosen_json": chosen_json_text
    }, on_conflict="ticker,year,quarter,metric_key").execute()

def fetch_resolutions(ticker: str, year: Optional[int] = None, quarter: Optional[str] = None):
    q = sb.table("guidance_resolved").select("*").eq("ticker", ticker.upper())
    if year is not None:
        q = q.eq("year", year)
    if quarter is not None:
        q = q.eq("quarter", quarter)
    return q.execute().data
