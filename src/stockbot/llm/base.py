from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel


class LLMRequest(BaseModel):
    system: str
    user: str
    image_png: bytes | None = None
    max_tokens: int = 800
    temperature: float = 0.3
    want_json: bool = True


class LLMResponse(BaseModel):
    text: str
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    cached: bool = False


class LLMClient(Protocol):
    provider: str
    model: str
    is_free: bool
    supports_image: bool

    def complete(self, req: LLMRequest) -> LLMResponse: ...


class LLMError(Exception):
    pass


class RateLimited(LLMError):
    pass


class AllProvidersFailed(LLMError):
    pass
