from __future__ import annotations

from openakita.core.stream_accumulator import StreamAccumulator
from openakita.llm.providers.openai_responses import OpenAIResponsesProvider
from openakita.llm.types import EndpointConfig, LLMRequest, Message


def _provider() -> OpenAIResponsesProvider:
    cfg = EndpointConfig(
        name="test-openai-responses",
        provider="openai",
        api_type="openai_responses",
        base_url="https://api.openai.com/v1",
        api_key_env="TEST_OPENAI_KEY",
        model="gpt-5.4",
        capabilities=["text", "tools"],
    )
    return OpenAIResponsesProvider(cfg)


def test_build_request_body_injects_prompt_cache_key_for_openai():
    provider = _provider()
    request = LLMRequest(
        messages=[Message(role="user", content="hello")],
        system="## System\n\n静态规则\n\n## Runtime\n\n## 运行环境\n- **当前时间**: 2026-04-05 10:00:00",
    )
    body = provider._build_request_body(request)
    assert body.get("prompt_cache_key", "").startswith("oak:v1:gpt-5-4:")


def test_prompt_cache_key_is_stable_across_runtime_and_session_changes():
    provider = _provider()
    system_a = (
        "## System\n\n静态规则A\n\n"
        "## Runtime\n\n"
        "## 运行环境\n- **当前时间**: 2026-04-05 10:00:00\n"
        "## 当前会话\n- **会话 ID**: s1\n- **已有消息**: 3 条\n"
        "## 系统概况\n你运行在 OpenAkita 多 Agent 系统中，powered by **gpt-5.4**。"
    )
    system_b = (
        "## System\n\n静态规则A\n\n"
        "## Runtime\n\n"
        "## 运行环境\n- **当前时间**: 2026-04-05 11:59:59\n"
        "## 当前会话\n- **会话 ID**: s2\n- **已有消息**: 99 条\n"
        "## 系统概况\n你运行在 OpenAkita 多 Agent 系统中，powered by **gpt-5.4**。"
    )
    req_a = LLMRequest(messages=[Message(role="user", content="hello")], system=system_a)
    req_b = LLMRequest(messages=[Message(role="user", content="hello")], system=system_b)
    body_a = provider._build_request_body(req_a)
    body_b = provider._build_request_body(req_b)
    assert body_a["prompt_cache_key"] == body_b["prompt_cache_key"]


def test_parse_response_reads_nested_cached_tokens():
    provider = _provider()
    response = provider._parse_response(
        {
            "id": "resp_123",
            "model": "gpt-5.4",
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "ok"}],
                }
            ],
            "usage": {
                "input_tokens": 2000,
                "output_tokens": 100,
                "input_tokens_details": {"cached_tokens": 1536},
            },
        }
    )
    assert response.usage.input_tokens == 2000
    assert response.usage.output_tokens == 100
    assert response.usage.cache_read_input_tokens == 1536


def test_convert_stream_event_includes_usage_on_completed():
    provider = _provider()
    event = provider._convert_stream_event(
        {
            "type": "response.completed",
            "response": {
                "usage": {
                    "input_tokens": 1200,
                    "output_tokens": 50,
                    "input_tokens_details": {"cached_tokens": 1024},
                }
            },
        }
    )
    assert event["type"] == "message_stop"
    assert event["usage"]["input_tokens"] == 1200
    assert event["usage"]["cache_read_input_tokens"] == 1024


def test_stream_accumulator_stores_usage_on_message_stop():
    acc = StreamAccumulator()
    acc.feed(
        {
            "type": "message_stop",
            "stop_reason": "stop",
            "usage": {
                "input_tokens": 1200,
                "output_tokens": 50,
                "cache_read_input_tokens": 1024,
            },
        }
    )
    assert acc.usage is not None
    assert acc.usage["cache_read_input_tokens"] == 1024
