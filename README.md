# Guidance from Quartr — Supabase Storage + Conflict Viewer + Persistence (Clean Build)

This app:
- Logs into Quartr via Playwright
- Downloads press releases, presentations, and transcripts (idempotent)
- Stores PDFs in Supabase Storage and text/metadata in a Supabase table
- Extracts guidance using a token-efficient pipeline
- Aggregates + de-duplicates across sources
- Provides a **conflict viewer** to resolve disagreements
- Saves your conflict choices for future runs
