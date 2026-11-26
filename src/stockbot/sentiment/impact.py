"""Event tags, severity (0-5) and sector relevance for news items."""
from __future__ import annotations

import re

from stockbot.data.news import NewsItem

EVENT_TAGS: dict[str, list[str]] = {
    "geopolitical": [r"\bwar\b", r"\binvasion\b", r"\binvades?\b", r"\bmissiles?\b", r"\bairstrikes?\b",
                     r"\bmilitary (strike|attack)\b", r"\bconflict\b", r"\bterror", r"\bcoup\b", r"\bsanctions?\b"],
    "oil_shock": [r"\b(oil|crude|brent)\b.{0,30}\b(surges?|soars?|jumps?|spikes?|skyrockets?|plunges?|tumbles?)\b",
                  r"\bopec\b.{0,30}\bcut", r"\brefinery\b.{0,20}\b(attack|strike|fire)"],
    "rate_hike": [r"\brate hikes?\b", r"\braises? (interest )?rates?\b", r"\bhawkish\b"],
    "rate_cut": [r"\brate cuts?\b", r"\bcuts? (interest )?rates?\b", r"\bdovish\b"],
    "inflation": [r"\binflation\b", r"\bcpi\b", r"\bconsumer prices\b"],
    "pandemic": [r"\bpandemic\b", r"\boutbreak\b", r"\blockdowns?\b", r"\bcovid\b"],
    "bank_crisis": [r"\bbank (run|failure|collapse)s?\b", r"\bbank(s)? collapse\b", r"\bbailout\b", r"\bcontagion\b"],
    "tariff": [r"\btariffs?\b", r"\btrade war\b", r"\bexport (curbs|controls|ban)\b"],
    "regulation": [r"\bantitrust\b", r"\bregulators?\b", r"\bfine[ds]?\b", r"\bban(s|ned)?\b"],
    "supply_chain": [r"\bsupply chain\b", r"\bshortages?\b", r"\bport (strike|closure)\b"],
    "earnings_miss": [r"\bmiss(es|ed)? (estimates|expectations)\b", r"\bcuts? (guidance|outlook)\b",
                      r"\bprofit warning\b"],
    "earnings_beat": [r"\bbeats? (estimates|expectations|earnings)?\b", r"\braises? (guidance|outlook)\b",
                      r"\brecord (profit|revenue)\b"],
    "lawsuit": [r"\blawsuit\b", r"\bsued\b", r"\bsues\b", r"\bclass action\b"],
    "bankruptcy": [r"\bbankrupt", r"\bchapter 11\b", r"\binsolven", r"\bdefaults? on\b"],
    "fraud": [r"\bfraud\b", r"\baccounting (irregularit|scandal)", r"\bsec charges\b", r"\bindicted\b",
              r"\bshort seller report\b"],
    "regulatory_rejection": [r"\bfda (rejects|denies|declines)\b", r"\bcomplete response letter\b",
                             r"\b(rejects|denies|denied|rejected) approval\b", r"\bblocks? (the )?(deal|merger)\b"],
}

TAG_BASE_SEVERITY = {"geopolitical": 3, "oil_shock": 2, "rate_hike": 2, "rate_cut": 2, "inflation": 1,
                     "pandemic": 3, "bank_crisis": 3, "tariff": 2, "regulation": 1, "supply_chain": 1,
                     "earnings_miss": 2, "earnings_beat": 1, "lawsuit": 1, "bankruptcy": 5, "fraud": 4,
                     "regulatory_rejection": 3}

_ALL_SECTORS = ["Information Technology", "Communication Services", "Consumer Discretionary", "Consumer Staples",
                "Energy", "Financials", "Health Care", "Industrials", "Materials", "Real Estate", "Utilities"]

TAG_SECTOR_IMPACT: dict[str, dict[str, int]] = {
    "geopolitical": {**{s: -1 for s in _ALL_SECTORS}, "Energy": 1, "Industrials": 0},
    "oil_shock": {"Information Technology": -1, "Consumer Discretionary": -1, "Industrials": -1,
                  "Communication Services": -1, "Energy": 2, "Materials": 1},
    "rate_hike": {"Information Technology": -2, "Real Estate": -2, "Utilities": -1, "Consumer Discretionary": -1,
                  "Communication Services": -1, "Financials": 1},
    "rate_cut": {"Information Technology": 2, "Real Estate": 2, "Utilities": 1, "Consumer Discretionary": 1,
                 "Communication Services": 1, "Financials": -1},
    "inflation": {"Consumer Discretionary": -1, "Information Technology": -1, "Real Estate": -1, "Energy": 1,
                  "Materials": 1},
    "pandemic": {**{s: -1 for s in _ALL_SECTORS}, "Health Care": 1, "Communication Services": 0},
    "bank_crisis": {"Financials": -2, "Real Estate": -1, "Consumer Discretionary": -1},
    "tariff": {"Information Technology": -1, "Consumer Discretionary": -1, "Industrials": -1, "Materials": -1},
    "supply_chain": {"Information Technology": -1, "Consumer Discretionary": -1, "Industrials": -1},
}


def tags_for(text: str) -> list[str]:
    low = text.lower()
    return [tag for tag, pats in EVENT_TAGS.items() if any(re.search(p, low) for p in pats)]


def assess(item: NewsItem, sentiment: float) -> NewsItem:
    tags = tags_for(f"{item.title} {item.summary}")
    severity = 0
    if tags:
        severity = max(TAG_BASE_SEVERITY[t] for t in tags) + (len(tags) - 1)
        if abs(sentiment) >= 0.6:
            severity += 1
    elif abs(sentiment) >= 0.6:
        severity = 1
    return item.model_copy(update={"tags": tags, "sentiment": sentiment, "severity": min(5, severity)})


def relevance(item: NewsItem, ticker: str, sector: str) -> int:
    if ticker in item.tickers:
        return 2
    if any(TAG_SECTOR_IMPACT.get(t, {}).get(sector, 0) != 0 for t in item.tags):
        return 1
    return 0
