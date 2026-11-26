"""Provider clients. OpenAI-compatible endpoints (OpenAI, Groq, Gemini) share one client;
Claude goes through the official Anthropic SDK."""
from __future__ import annotations

import base64

from stockbot.llm.base import LLMError, LLMRequest, LLMResponse, RateLimited
from stockbot.llm.pricing import cost

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/openai/"
GROQ_BASE = "https://api.groq.com/openai/v1"


class OpenAICompatClient:
    def __init__(self, provider: str, base_url: str | None, api_key: str, model: str, is_free: bool,
                 supports_image: bool, timeout: float = 60.0):
        import openai

        self.provider, self.model, self.is_free, self.supports_image = provider, model, is_free, supports_image
        self._client = openai.OpenAI(api_key=api_key, base_url=base_url, timeout=timeout, max_retries=1)

    def complete(self, req: LLMRequest) -> LLMResponse:
        import openai

        content: list | str = req.user
        if req.image_png is not None:
            b64 = base64.b64encode(req.image_png).decode()
            content = [{"type": "text", "text": req.user},
                       {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}]
        try:
            r = self._client.chat.completions.create(
                model=self.model, max_tokens=req.max_tokens, temperature=req.temperature,
                messages=[{"role": "system", "content": req.system}, {"role": "user", "content": content}],
            )
        except openai.RateLimitError as e:
            raise RateLimited(str(e)) from e
        except openai.APIError as e:
            raise LLMError(str(e)) from e
        text = (r.choices[0].message.content or "") if r.choices else ""
        tin = getattr(r.usage, "prompt_tokens", 0) or 0
        tout = getattr(r.usage, "completion_tokens", 0) or 0
        return LLMResponse(text=text, provider=self.provider, model=self.model, input_tokens=tin,
                           output_tokens=tout, cost_usd=cost(self.model, self.is_free, tin, tout))


class AnthropicClient:
    """Claude via the official SDK. Sampling params are not sent (rejected on current models);
    server-side refusal fallback is enabled by default."""

    provider = "anthropic"
    is_free = False
    supports_image = True

    def __init__(self, api_key: str, model: str, timeout: float = 120.0):
        import anthropic

        self.model = model
        self._client = anthropic.Anthropic(api_key=api_key, timeout=timeout, max_retries=1)

    def complete(self, req: LLMRequest) -> LLMResponse:
        import anthropic

        content: list = []
        if req.image_png is not None:
            content.append({"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                                        "data": base64.standard_b64encode(req.image_png).decode()}})
        content.append({"type": "text", "text": req.user})
        try:
            r = self._client.beta.messages.create(
                model=self.model, max_tokens=16000, system=req.system,
                messages=[{"role": "user", "content": content}],
                betas=["server-side-fallback-2026-07-01"], fallbacks="default",
            )
        except anthropic.RateLimitError as e:
            raise RateLimited(str(e)) from e
        except (anthropic.APIStatusError, anthropic.APIConnectionError) as e:
            raise LLMError(str(e)) from e
        if r.stop_reason == "refusal":
            raise LLMError("refusal")
        text = "".join(b.text for b in r.content if b.type == "text")
        tin, tout = r.usage.input_tokens, r.usage.output_tokens
        return LLMResponse(text=text, provider=self.provider, model=self.model, input_tokens=tin,
                           output_tokens=tout, cost_usd=cost(self.model, False, tin, tout))
