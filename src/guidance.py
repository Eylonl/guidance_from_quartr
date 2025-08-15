import os, json, re
from typing import Optional
from dotenv import load_dotenv
from openai import OpenAI
from tenacity import retry, wait_exponential, stop_after_attempt
from .cloud_store import fetch_rows, upsert_row
from .prefilter import mine_candidates

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
DEFAULT_MODEL = "gpt-4o-mini"

SYSTEM = """Return ONLY JSON array called items. For each candidate item provided,
emit a validated guidance object with keys:
- metric (string)
- guidance_value_text (string, verbatim)
- period (string)
- period_type ("quarter" or "full year")
- low_end (number or null)
- high_end (number or null)
- units (string or null: 'USD' | 'percent' | 'EPS' | etc.)
- filing_date (YYYY-MM-DD or null)
Discard any candidate that is not forward-looking guidance. Use the short 'context' string if needed to confirm.
"""

def try_iso_date_from_text(text: str) -> Optional[str]:
    m = re.search(r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+([12]?\d|3[01]),\s+(20\d{2})', text)
    if not m:
        return None
    month_map = {m: i for i, m in enumerate([
        "January","February","March","April","May","June",
        "July","August","September","October","November","December"
    ], start=1)}
    month = month_map[m.group(1)]
    day = int(m.group(2))
    year = int(m.group(3))
    return f"{year:04d}-{month:02d}-{day:02d}"

@retry(wait=wait_exponential(multiplier=1, min=2, max=30), stop=stop_after_attempt(5))
def call_openai(messages, model: str):
    client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else OpenAI()
    resp = client.chat.completions.create(
        model=model,
        temperature=0,
        messages=messages,
        response_format={"type": "json_object"},
    )
    txt = resp.choices[0].message.content.strip()
    data = json.loads(txt)
    if isinstance(data, dict) and "items" in data:
        return data["items"]
    if isinstance(data, list):
        return data
    return []

def extract_for_ticker(ticker: str, model: Optional[str] = None):
    model = model or DEFAULT_MODEL
    sources = ["press_release", "presentation", "transcript"]
    for src in sources:
        rows = fetch_rows(ticker, file_type=src, file_format="text")
        if not rows:
            continue
        for r in rows:
            text = r.get("text_content") or ""
            if not text.strip():
                continue
            year = r["year"]
            quarter = r["quarter"]
            url = r.get("source_url")
            filing_date = try_iso_date_from_text(text[:2000])
            candidates = mine_candidates(text)
            if not candidates:
                continue
            messages = [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": json.dumps({"candidates": candidates})},
            ]
            items = call_openai(messages, model=model)
            for it in items:
                it.setdefault("source", src)
                it.setdefault("filing_date", filing_date)
            blob = json.dumps(items, ensure_ascii=False)
            upsert_row(ticker, year, quarter, "guidance_json", "json", None, url, blob)
