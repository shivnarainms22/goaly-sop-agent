from typing import Protocol

import anthropic
from pydantic import ValidationError

from sop_agent.config import Settings
from sop_agent.sop.extraction import TurnExtraction

MAX_TOKENS = 1024
EXTRACT_ATTEMPTS = 2


class LLMError(Exception):
    pass


class LLMAuthError(LLMError):
    """The API key was rejected."""


class LLMUnavailableError(LLMError):
    """Rate limit, outage, connection failure, refusal or empty output."""


class LLMClient(Protocol):
    def extract(self, *, system: str, messages: list[dict]) -> TurnExtraction: ...

    def phrase(self, *, system: str, messages: list[dict]) -> str: ...


class AnthropicLLM:
    def __init__(self, api_key: str, settings: Settings, client: anthropic.Anthropic | None = None):
        self._settings = settings
        self._client = client or anthropic.Anthropic(api_key=api_key, max_retries=2, timeout=30.0)

    def _call(self, fn, **kwargs):
        try:
            response = fn(max_tokens=MAX_TOKENS, output_config={"effort": "low"}, **kwargs)
        except anthropic.AuthenticationError as e:
            raise LLMAuthError("Anthropic rejected the API key") from e
        except (anthropic.RateLimitError, anthropic.APIStatusError, anthropic.APIConnectionError) as e:
            raise LLMUnavailableError(type(e).__name__) from e
        if response.stop_reason == "refusal":
            raise LLMUnavailableError("model refusal")
        return response

    def extract(self, *, system: str, messages: list[dict]) -> TurnExtraction:
        """Invalid structured output is retried once, then replaced by an empty (safe) extraction."""
        for _ in range(EXTRACT_ATTEMPTS):
            try:
                response = self._call(
                    self._client.messages.parse,
                    model=self._settings.extractor_model,
                    system=system,
                    messages=messages,
                    output_format=TurnExtraction,
                )
            except ValidationError:
                continue
            if response.parsed_output is not None:
                return response.parsed_output
        return TurnExtraction()

    def phrase(self, *, system: str, messages: list[dict]) -> str:
        response = self._call(
            self._client.messages.create,
            model=self._settings.responder_model,
            system=system,
            messages=messages,
        )
        text = "".join(b.text for b in response.content if b.type == "text").strip()
        if not text:
            raise LLMUnavailableError("empty reply")
        return text
