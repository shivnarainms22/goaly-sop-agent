from types import SimpleNamespace

import anthropic
import httpx
import pytest
from pydantic import ValidationError

from sop_agent.config import Settings
from sop_agent.llm.client import AnthropicLLM, LLMAuthError, LLMUnavailableError
from sop_agent.llm.fake import FakeLLM
from sop_agent.sop.extraction import PII, TurnExtraction

MSGS = [{"role": "user", "content": "hi"}]


class StubMessages:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.kwargs = []

    def _next(self, kwargs):
        self.kwargs.append(kwargs)
        out = self.outcomes.pop(0)
        if isinstance(out, Exception):
            raise out
        return out

    parse = create = lambda self, **kw: self._next(kw)  # noqa: E731


def llm_with(*outcomes):
    messages = StubMessages(outcomes)
    return AnthropicLLM("k", Settings(), client=SimpleNamespace(messages=messages)), messages


def parsed(ex, stop_reason="end_turn"):
    return SimpleNamespace(parsed_output=ex, stop_reason=stop_reason, content=[])


def text_reply(*blocks, stop_reason="end_turn"):
    return SimpleNamespace(
        stop_reason=stop_reason, content=[SimpleNamespace(type=t, **kw) for t, kw in blocks]
    )


def status_error(cls, code):
    req = httpx.Request("POST", "https://x")
    return cls(message="x", response=httpx.Response(code, request=req), body=None)


def test_extract_returns_parsed_output():
    ex = TurnExtraction(pii=PII(full_name="Margaret Chen"))
    llm, _ = llm_with(parsed(ex))
    assert llm.extract(system="s", messages=MSGS) == ex


def test_extract_retries_once_then_returns_empty_extraction():
    bad = ValidationError.from_exception_data("TurnExtraction", [])
    llm, stub = llm_with(bad, parsed(None))
    assert llm.extract(system="s", messages=MSGS) == TurnExtraction()
    assert len(stub.kwargs) == 2


def test_extract_retry_can_succeed():
    ex = TurnExtraction(intent="status_inquiry")
    llm, _ = llm_with(parsed(None), parsed(ex))
    assert llm.extract(system="s", messages=MSGS) == ex


def test_extract_request_kwargs():
    llm, stub = llm_with(parsed(TurnExtraction()))
    llm.extract(system="sys", messages=MSGS)
    kw = stub.kwargs[0]
    assert kw["model"] == "claude-haiku-5-5" and kw["output_format"] is TurnExtraction
    assert kw["output_config"] == {"effort": "low"} and kw["max_tokens"] == 1024
    assert "temperature" not in kw and "thinking" not in kw and "tools" not in kw


def test_phrase_joins_text_blocks_and_drops_thinking():
    llm, stub = llm_with(
        text_reply(
            ("thinking", {"thinking": "secret"}), ("text", {"text": "Hello "}), ("text", {"text": "there."})
        )
    )
    assert llm.phrase(system="s", messages=MSGS) == "Hello there."
    kw = stub.kwargs[0]
    assert kw["model"] == "claude-sonnet-5-5" and kw["output_config"] == {"effort": "low"}
    assert "temperature" not in kw and "thinking" not in kw


def test_authentication_error_becomes_llm_auth_error():
    llm, _ = llm_with(status_error(anthropic.AuthenticationError, 401))
    with pytest.raises(LLMAuthError):
        llm.phrase(system="s", messages=MSGS)
    llm, _ = llm_with(status_error(anthropic.AuthenticationError, 401))
    with pytest.raises(LLMAuthError):
        llm.extract(system="s", messages=MSGS)


@pytest.mark.parametrize(
    "error",
    [
        status_error(anthropic.RateLimitError, 429),
        status_error(anthropic.InternalServerError, 500),
        anthropic.APIConnectionError(request=httpx.Request("POST", "https://x")),
    ],
)
def test_api_failures_become_unavailable(error):
    llm, _ = llm_with(error)
    with pytest.raises(LLMUnavailableError):
        llm.phrase(system="s", messages=MSGS)


def test_refusal_is_unavailable():
    llm, _ = llm_with(text_reply(("text", {"text": "no"}), stop_reason="refusal"))
    with pytest.raises(LLMUnavailableError):
        llm.phrase(system="s", messages=MSGS)


def test_empty_phrase_is_unavailable():
    llm, _ = llm_with(text_reply(("thinking", {"thinking": "hmm"})))
    with pytest.raises(LLMUnavailableError):
        llm.phrase(system="s", messages=MSGS)


def test_fake_llm_pops_in_order_echoes_template_and_records_calls():
    a, b = TurnExtraction(intent="next_steps"), TurnExtraction()
    fake = FakeLLM([a, b], replies=["first"])
    assert fake.extract(system="s1", messages=MSGS) is a
    assert fake.extract(system="s2", messages=MSGS) is b
    assert fake.extract(system="s3", messages=MSGS) == TurnExtraction()
    assert fake.phrase(system="p", messages=MSGS) == "first"
    echo = [{"role": "user", "content": "TEMPLATE:\nhello\n\nFACTS:\n{}"}]
    assert fake.phrase(system="p", messages=echo) == "hello"
    assert [c["system"] for c in fake.calls] == ["s1", "s2", "s3", "p", "p"]
