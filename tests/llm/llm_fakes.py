from stockbot.llm.base import LLMResponse


class ScriptedClient:
    """Returns scripted texts (or raises scripted exceptions) in order; repeats the last item."""

    def __init__(self, responses, is_free=True, supports_image=True, provider="fake", model="fake-1", cost=0.0):
        self.responses = list(responses)
        self.is_free = is_free
        self.supports_image = supports_image
        self.provider = provider
        self.model = model
        self.cost = cost
        self.calls = []

    def complete(self, req):
        self.calls.append(req)
        r = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(r, Exception):
            raise r
        return LLMResponse(text=r, provider=self.provider, model=self.model, input_tokens=10, output_tokens=5,
                           cost_usd=self.cost)
