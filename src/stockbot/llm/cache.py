from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from sqlalchemy import select

from stockbot.llm.base import LLMClient, LLMRequest, LLMResponse
from stockbot.models import LLMCall


def cache_key(provider: str, model: str, req: LLMRequest) -> str:
    img = hashlib.sha256(req.image_png).hexdigest() if req.image_png else ""
    raw = "\x1f".join([provider, model, req.system, req.user, img, str(req.max_tokens)])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class CachedClient:
    """Wraps a client; identical requests are answered from the llm_calls table (cost 0)."""

    def __init__(self, inner: LLMClient, session_factory):
        self.inner = inner
        self._sf = session_factory
        self.provider, self.model = inner.provider, inner.model
        self.is_free, self.supports_image = inner.is_free, inner.supports_image

    def complete(self, req: LLMRequest) -> LLMResponse:
        key = cache_key(self.provider, self.model, req)
        with self._sf() as s:
            row = s.execute(select(LLMCall).where(LLMCall.cache_key == key)).scalar_one_or_none()
            if row is not None:
                return LLMResponse(text=row.response_text, provider=row.provider, model=row.model,
                                   input_tokens=row.input_tokens, output_tokens=row.output_tokens,
                                   cost_usd=0.0, cached=True)
        resp = self.inner.complete(req)
        with self._sf() as s:
            if s.execute(select(LLMCall.id).where(LLMCall.cache_key == key)).first() is None:
                s.add(LLMCall(cache_key=key, provider=resp.provider, model=resp.model,
                              input_tokens=resp.input_tokens, output_tokens=resp.output_tokens,
                              cost_usd=resp.cost_usd, response_text=resp.text,
                              created_at=datetime.now(timezone.utc).replace(tzinfo=None)))
                s.commit()
        return resp
