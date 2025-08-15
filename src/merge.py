import re
from typing import Dict, Any, List, Tuple, Optional

METRIC_MAP = {
    "revenue": ["revenue", "sales", "top line"],
    "eps": ["eps", "earnings per share"],
    "gross margin": ["gross margin", "gross profit margin", "gpm"],
    "operating margin": ["operating margin", "op margin"],
    "op income": ["operating income", "op income"],
    "capex": ["capex", "capital expenditures"],
    "fcf": ["free cash flow", "fcf"],
    "arr": ["annual recurring revenue", "arr"],
}

def canon_metric(s: str) -> str:
    if not s:
        return ""
    t = s.lower().strip()
    for k, alts in METRIC_MAP.items():
        if any(a in t for a in alts):
            return k
    return t

def canon_period(period: str) -> Tuple[str, Optional[str], Optional[str]]:
    p = (period or "").strip()
    l = p.lower()
    period_type = "quarter"
    fy = None
    q = None
    m_fy = re.search(r"(?:fy\s*|full\s*year\s*)(\d{2,4})", l)
    if m_fy:
        yr = m_fy.group(1)
        fy = "20" + yr if len(yr) == 2 else yr
    m_q = re.search(r"(q[1-4])", l)
    if m_q:
        q = m_q.group(1).upper()
        period_type = "quarter"
    if "full year" in l and not q:
        period_type = "full year"
    if fy and not q:
        period_type = "full year"
    return period_type, fy, q

def canon_units(units: Optional[str]) -> str:
    if not units:
        return ""
    u = units.lower().strip()
    if u in ["percent", "%", "percentage", "pp"]:
        return "percent"
    if "eps" in u:
        return "eps"
    if any(x in u for x in ["usd", "$", "dollar", "bn", "billion", "m", "million"]):
        return "usd"
    return u

def to_base(value: Optional[float], units: str) -> Optional[float]:
    if value is None:
        return None
    return float(value)

def close_enough(a: Optional[float], b: Optional[float], units: str) -> bool:
    if a is None or b is None:
        return False
    a, b = float(a), float(b)
    if units == "percent":
        return abs(a - b) <= 0.10
    if units == "eps":
        return abs(a - b) <= 0.01
    denom = max(1.0, abs((a + b) / 2.0))
    return abs(a - b) / denom <= 0.01

def merge_items(items_by_source: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    source_rank = {"press_release": 3, "presentation": 2, "transcript": 1}
    buckets: Dict[Tuple, List[Tuple[str, Dict[str, Any]]]] = {}

    for src, lst in items_by_source.items():
        for it in (lst or []):
            metric = canon_metric(it.get("metric", ""))
            period = it.get("period") or ""
            ptype = (it.get("period_type") or "").lower().strip()
            if ptype not in ("quarter", "full year"):
                ptype, fy, q = canon_period(period)
            else:
                ptype2, fy, q = canon_period(period)
                if not it.get("period_type"):
                    ptype = ptype2
            key = (metric, ptype, fy, q)
            buckets.setdefault(key, []).append((src, it))

    merged: List[Dict[str, Any]] = []
    for key, candidates in buckets.items():
        candidates.sort(key=lambda x: source_rank.get(x[0], 0), reverse=True)
        kept: List[Tuple[str, Dict[str, Any]]] = []
        for src, it in candidates:
            units = canon_units(it.get("units"))
            low = to_base(it.get("low_end"), units)
            high = to_base(it.get("high_end"), units)
            if low is None and high is not None:
                low = high
            if high is None and low is not None:
                high = low

            merged_in = False
            for i, (ksrc, kitem) in enumerate(kept):
                kunits = canon_units(kitem.get("units"))
                klow = to_base(kitem.get("low_end"), kunits)
                khigh = to_base(kitem.get("high_end"), kunits)
                if kunits == units and close_enough(low, klow, units) and close_enough(high, khigh, units):
                    prov = set((kitem.get("provenance") or [])) | set((it.get("provenance") or []))
                    kitem["provenance"] = sorted(list(prov))
                    if source_rank.get(src, 0) > source_rank.get(ksrc, 0):
                        kitem["guidance_value_text"] = it.get("guidance_value_text") or kitem.get("guidance_value_text")
                        kitem["filing_date"] = it.get("filing_date") or kitem.get("filing_date")
                    merged_in = True
                    break
            if not merged_in:
                it = dict(it)
                it["units"] = units
                it["low_end"] = low
                it["high_end"] = high
                it.setdefault("provenance", [])
                it["provenance"] = list(set(it["provenance"]))
                it["source"] = src
                kept.append((src, it))

        if len(kept) > 1:
            for _src, it in kept:
                it["note"] = "conflict"
        merged.extend([it for _src, it in kept])

    for it in merged:
        low = it.get("low_end")
        high = it.get("high_end")
        avg = None
        if isinstance(low, (int, float)) and isinstance(high, (int, float)):
            avg = (low + high) / 2.0
        it["average"] = avg
        if it.get("period_type") not in ("quarter", "full year"):
            pt, _, _ = canon_period(it.get("period") or "")
            it["period_type"] = pt
    return merged

def bucketize(items_by_source: Dict[str, List[Dict[str, Any]]]) -> Dict[Tuple, List[Dict[str, Any]]]:
    buckets: Dict[Tuple, List[Dict[str, Any]]] = {}
    for src, lst in items_by_source.items():
        for it in (lst or []):
            metric = canon_metric(it.get("metric", ""))
            period = it.get("period") or ""
            ptype = (it.get("period_type") or "").lower().strip()
            if ptype not in ("quarter", "full year"):
                ptype, fy, q = canon_period(period)
            else:
                ptype2, fy, q = canon_period(period)
                if not it.get("period_type"):
                    ptype = ptype2
            units = canon_units(it.get("units"))
            low = to_base(it.get("low_end"), units)
            high = to_base(it.get("high_end"), units)
            if low is None and high is not None:
                low = high
            if high is None and low is not None:
                high = low
            item = dict(it)
            item["source"] = it.get("source") or src
            item["units"] = units
            item["low_end"] = low
            item["high_end"] = high
            key = (metric, ptype, fy, q)
            buckets.setdefault(key, []).append(item)
    return buckets
