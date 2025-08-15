# Guidance from Quartr — Supabase Storage (Organized & Idempotent)

This version stores files in **Supabase** so you can run Streamlit from any computer.
- **Storage layout** (object storage): `pdfs/{TICKER}/{YEAR}-{QUARTER}/{file_type}.pdf`
- **Idempotent loader**: checks if a file already exists in the folder and **skips re-downloading**.
- Structured guidance extraction, aggregation, conflict resolution — all retained.

## 1) Supabase setup
1. Create a Supabase project → copy **Project URL** and **Anon Key**.
2. Create a bucket named `earnings` (or another name).
3. Run this SQL (Database → SQL Editor):
```sql
create table if not exists earnings_files (
  id bigserial primary key,
  ticker text not null,
  year int not null,
  quarter text not null,                 -- 'Q1'..'Q4'
  file_type text not null,               -- 'press_release' | 'presentation' | 'transcript' | 'guidance_json'
  file_format text not null,             -- 'pdf' | 'text' | 'json'
  storage_path text,                     -- e.g., 'pdfs/AAPL/2025-Q2/press_release.pdf'
  source_url text,
  text_content text,                     -- extracted text or JSON text
  created_at timestamptz default now(),
  updated_at timestamptz default now(),
  unique (ticker, year, quarter, file_type, file_format)
);
create index if not exists ix_lookup on earnings_files(ticker, file_type, file_format, year desc, quarter);
```

## 2) Secrets (Streamlit Cloud → App → Settings → Secrets)
```toml
QUARTR_EMAIL="you@example.com"
QUARTR_PASSWORD="yourpassword"
OPENAI_API_KEY="sk-..."
SUPABASE_URL="https://<your-project>.supabase.co"
SUPABASE_ANON_KEY="<your-anon-key>"
SUPABASE_BUCKET="earnings"
HEADLESS="1"
SLOW_MO_MS="150"
```

## 3) Deploy (GitHub → Streamlit Cloud)
- Entry file: `streamlit_app.py`
- `apt.txt` contains Chromium deps
- `requirements.txt` includes `supabase` client

## 4) How the loader is idempotent
- Before attempting a Quartr download for a given **(ticker, year, quarter, file_type)**,
  it checks Supabase for `pdfs/{TICKER}/{YEAR}-{QUARTER}/{file_type}.pdf`.
- If the file **exists**, it **skips** the browser download and also skips text extraction for that file_type
  **unless** the text row is missing (in which case it reads the PDF from Supabase and extracts text).

## 5) Output columns (unchanged)
Metric | Value of guide | Period | Period type | Low end of guidance | High end of guidance | Average | Filing date


## Conflict resolutions (persistence)
If you create the optional `guidance_resolved` table (see SETUP_INSTRUCTIONS.txt), the app will:
- Auto-preselect prior choices in the conflict viewer.
- Save your new choices on "Finalize & Download CSV".
