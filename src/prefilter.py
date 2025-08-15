import re
from typing import List, Dict, Any

GUIDANCE_RGX = re.compile(
    r"(guidance|outlook|forecast|expect|expects|we\s+expect|we\s+forecast|"
    r"full\s+year|FY\d{2,4}|Q[1-4]\s*(?:FY)?\d{2,4}|quarterly\s+outlook)",
    re.I,
)
NUMBER_SPAN = re.compile(
    r"(\$?\s?\d[\d,]*(?:\.\d+)?\s*(?:billion|bn|million|m|percent|%|bps|basis points|eps|dollars)?)",
    re.I,
)
PERIOD_RGX = re.compile(
    r"(Q[1-4]\s*(?:FY)?\d{2,4}|FY\s?\d{2,4}|FY\d{2}|full\s+year\s+\d{4}|full\s+year)",
    re.I,
)

METRIC_DICT = {
    "revenue": ["revenue", "sales", "top line"],
    "eps": ["eps", "earnings per share"],
    "gross margin": ["gross margin", "gpm", "gross profit margin"],
    "operating margin": ["operating margin", "op margin"],
    "op income": ["operating income", "op income"],
    "capex": ["capex", "capital expenditures"],
    "fcf": ["free cash flow", "fcf"],
    "arr": ["arr", "annual recurring revenue"],
}

def guess_metric(text: str) -> str:
    t = text.lower()
    for k, alts in METRIC_DICT.items():
        if any(a in t for a in alts):
            return k
    return ""

def normalize_value_span(s: str):
    t = s.lower().replace(",", "").strip()
    units = None
    if "eps" in t:
        units = "EPS"
    elif "billion" in t or "bn" in t or "$" in t or "million" in t or " m" in t:
        units = "USD"
    elif "%" in t or "percent" in t:
        units = "percent"
    rng = re.split(r"\s*(?:to|-|–|—|~)\s*", t)
    def as_num(x):
        x = x.replace("about", "").replace("approx", "").replace("$", "").strip()
        mult = 1.0
        if "billion" in x or "bn" in x: mult = 1e9
        elif "million" in x or re.search(r"\bm\b", x): mult = 1e6
        x = re.sub(r"[^\d.]", "", x)
        return float(x) * mult if x else None
    if len(rng) == 2:
        low, high = as_num(rng[0]), as_num(rng[1])
    else:
        low = as_num(t)
        high = None
    return units, low, high

def split_paragraphs(text: str) -> List[str]:
    parts = re.split(r"\n{2,}", text)
    return [re.sub(r"\s+", " ", p).strip() for p in parts if p.strip()]

def prefilter(text: str) -> List[str]:
    paras = split_paragraphs(text)
    kept = []
    for p in paras:
        if GUIDANCE_RGX.search(p) or NUMBER_SPAN.search(p):
            if "safe harbor" in p.lower() or "forward-looking statements" in p.lower():
                continue
            kept.append(p)
    return kept

def mine_candidates(text: str) -> List[Dict[str, Any]]:
    kept = prefilter(text)
    cands = []
    for p in kept:
        metric = guess_metric(p)
        period_m = PERIOD_RGX.search(p)
        num_m = NUMBER_SPAN.search(p)
        if not (period_m or num_m):
            continue
        guidance_value_text = num_m.group(1) if num_m else ""
        units, low, high = normalize_value_span(guidance_value_text) if guidance_value_text else (None, None, None)
        cands.append({
            "metric": metric,
            "guidance_value_text": guidance_value_text.strip(),
            "low_end": low,
            "high_end": high,
            "units": units,
            "period": period_m.group(0) if period_m else "",
            "context": p[:800],
        })
    return cands
