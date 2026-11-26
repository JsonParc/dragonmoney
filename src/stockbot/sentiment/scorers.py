"""Sentiment scorers in [-1, 1]. FinBERT when installed (free, local CPU); keyword fallback otherwise."""
from __future__ import annotations

import re
from typing import Protocol


class SentimentScorer(Protocol):
    def score(self, texts: list[str]) -> list[float]: ...


_NEG = ["war", "attack", "invasion", "missile", "plunge", "plunges", "crash", "crashes", "tumble", "tumbles",
        "slump", "ban", "banned", "sanction", "sanctions", "lawsuit", "sued", "miss", "misses", "downgrade",
        "downgraded", "recession", "default", "bankrupt", "bankruptcy", "fraud", "probe", "investigation",
        "layoffs", "halt", "halted", "recall", "shortage", "fears", "selloff", "sell-off", "collapse",
        "crisis", "cut guidance", "warning", "warns", "fall", "falls", "drop", "drops", "loss", "losses",
        "rejects", "rejected", "charges", "chapter 11", "indicted"]
_POS = ["beat", "beats", "upgrade", "upgraded", "record", "rally", "rallies", "approve", "approved",
        "approval", "partnership", "raises guidance", "buyback", "soars on", "gain", "gains", "profit",
        "growth", "strong", "rebound", "rebounds", "outperform"]


def _count(words: list[str], text: str) -> int:
    return sum(len(re.findall(rf"\b{re.escape(w)}\b", text)) for w in words)


class KeywordScorer:
    def score(self, texts: list[str]) -> list[float]:
        out = []
        for t in texts:
            low = t.lower()
            n, p = _count(_NEG, low), _count(_POS, low)
            out.append(0.0 if n + p == 0 else (p - n) / (p + n))
        return out


class FinBertScorer:
    MODEL = "ProsusAI/finbert"

    def __init__(self):
        from transformers import pipeline

        self._pipe = pipeline("text-classification", model=self.MODEL, top_k=None, truncation=True)

    def score(self, texts: list[str]) -> list[float]:
        if not texts:
            return []
        out = []
        for res in self._pipe(texts, batch_size=16):
            probs = {r["label"].lower(): r["score"] for r in res}
            out.append(float(probs.get("positive", 0) - probs.get("negative", 0)))
        return out


def get_scorer() -> SentimentScorer:
    try:
        return FinBertScorer()
    except Exception:  # transformers/torch missing or model download failed
        return KeywordScorer()
