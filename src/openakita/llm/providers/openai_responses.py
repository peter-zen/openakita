"""
OpenAI Responses API Provider

继承 OpenAIProvider，覆写请求构建和响应解析以适配 Responses API 格式。
共享 HTTP 客户端、认证、超时、健康检查等基础设施。

Responses API 与 Chat Completions 的核心差异：
- 端点: /v1/responses (非 /v1/chat/completions)
- 输入: input (items 数组) + instructions (系统提示)
- 输出: output (items 数组) 而非 choices[0].message
- 工具定义: internally-tagged, strict 默认开启
- 流式事件: 语义化事件名 (response.output_text.delta 等)
"""

import hashlib
import json
import logging
import re
from collections.abc import AsyncIterator

from ..converters.messages import convert_messages_to_responses
from ..converters.tools import (
    convert_tool_calls_from_responses,
    convert_tools_to_responses,
    has_text_tool_calls,
    parse_text_tool_calls,
)
from ..types import (
    AuthenticationError,
    EndpointConfig,
    LLMError,
    LLMRequest,
    LLMResponse,
    RateLimitError,
    StopReason,
    TextBlock,
    Usage,
)
from .openai import OpenAIProvider

logger = logging.getLogger(__name__)


class OpenAIResponsesProvider(OpenAIProvider):
    """OpenAI Responses API Provider

    覆写以下方法以适配 Responses API，其余全部继承自 OpenAIProvider：
    - _api_url: 端点路径 (/responses)
    - _estimate_request_timeout: 基于 input items 估算超时
    - _chat_non_stream: 非流式请求（验证 output 而非 choices）
    - _build_request_body: 请求体格式
    - _parse_response: 响应解析
    - _convert_stream_event: 流式事件解析
    - _iter_sse_events: SSE 传输（适配 named events 格式）

    chat() 和 _chat_via_stream() 继承自 OpenAIProvider（统一的 stream-only 检测逻辑）。
    """

    def __init__(self, config: EndpointConfig):
        super().__init__(config)
        self._prompt_cache_key_unsupported = False

    @property
    def _api_url(self) -> str:
        return f"{self.base_url}/responses"

    _CACHE_KEY_DYNAMIC_HEADINGS = (
        "## Runtime",
        "## User",
        "## 运行环境",
        "## 当前会话",
        "## 系统概况",
        "## 你的记忆系统",
        "## 用户设定的规则（必须遵守）",
        "## 核心记忆",
        "## 历史经验（执行任务前请参考）",
        "## 相关记忆（自动检索）",
        "## 关系型记忆（图检索）",
    )

    @classmethod
    def _strip_markdown_section(cls, text: str, heading: str) -> str:
        pattern = rf"(?ms)^{re.escape(heading)}\n.*?(?=^## |\Z)"
        return re.sub(pattern, "", text)

    @classmethod
    def _normalize_instructions_for_cache_key(cls, instructions: str) -> str:
        if not instructions:
            return ""

        normalized = instructions
        for heading in cls._CACHE_KEY_DYNAMIC_HEADINGS:
            normalized = cls._strip_markdown_section(normalized, heading)

        line_patterns = (
            r"(?m)^- \*\*当前时间\*\*:.*\n?",
            r"(?m)^- \*\*会话 ID\*\*:.*\n?",
            r"(?m)^- \*\*已有消息\*\*:.*\n?",
            r"(?m)^- \*\*子 Agent 协作记录\*\*:.*\n?",
            r"(?m)^- \*\*当前模型\*\*:.*\n?",
            r"(?m)^- \*\*当前工作目录\*\*:.*\n?",
            r"(?m)^- \*\*PATH 可用工具\*\*:.*\n?",
        )
        for pattern in line_patterns:
            normalized = re.sub(pattern, "", normalized)

        normalized = re.sub(r"\n{3,}", "\n\n", normalized)
        return normalized.strip()

    def _build_prompt_cache_key(self, body: dict) -> str | None:
        instructions = self._normalize_instructions_for_cache_key(
            str(body.get("instructions", "") or "")
        )
        tools = body.get("tools", []) or []

        if not instructions and not tools:
            return None

        basis = {
            "provider": self.config.provider,
            "model": self.config.model,
            "instructions": instructions[:12000],
            "tools": tools,
        }
        basis_json = json.dumps(
            basis,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(basis_json.encode("utf-8")).hexdigest()[:16]
        model_slug = re.sub(r"[^a-z0-9]+", "-", self.config.model.lower()).strip("-")[:32] or "unknown"
        return f"oak:v1:{model_slug}:{digest}"

    def _should_auto_inject_prompt_cache_key(self) -> bool:
        return not self._prompt_cache_key_unsupported

    @staticmethod
    def _is_prompt_cache_key_unsupported(error_text: str) -> bool:
        low = (error_text or "").lower()
        return (
            "prompt_cache_key" in low
            and any(
                marker in low
                for marker in (
                    "unsupported parameter",
                    "unknown parameter",
                    "extra_forbidden",
                    "extra inputs are not permitted",
                    "not supported",
                )
            )
        )

    @staticmethod
    def _parse_usage_data(usage_data: dict | None) -> Usage:
        usage_data = usage_data or {}
        input_details = usage_data.get("input_tokens_details", {}) or {}
        cache_read = usage_data.get("cache_read_input_tokens", 0)
        if not cache_read:
            cache_read = input_details.get("cached_tokens", 0)

        cache_creation = usage_data.get("cache_creation_input_tokens", 0)
        if not cache_creation:
            cache_creation = (
                input_details.get("cache_creation_tokens", 0)
                or input_details.get("cache_write_tokens", 0)
            )

        return Usage(
            input_tokens=usage_data.get("input_tokens", 0),
            output_tokens=usage_data.get("output_tokens", 0),
            cache_creation_input_tokens=cache_creation,
            cache_read_input_tokens=cache_read,
        )

    def _estimate_request_timeout(self, body: dict):  # -> httpx.Timeout | None
        """Responses API 使用 input 而非 messages，需适配 token 估算。"""
        input_items = body.get("input", [])
        body_chars = sum(
            len(str(item.get("content", "")))
            + len(str(item.get("arguments", "")))
            + len(str(item.get("output", "")))
            for item in input_items
            if isinstance(item, dict)
        )
        tools = body.get("tools", [])
        if tools:
            body_chars += sum(len(str(t)) for t in tools)

        est_tokens = body_chars // 2
        if est_tokens < 60_000:
            return None

        import httpx
        base_timeout = self.config.timeout or 180
        scale = min(est_tokens / 60_000, 3.0)
        new_read = min(base_timeout * scale, 540.0)
        if new_read <= base_timeout * 1.1:
            return None

        logger.info(
            f"[ResponsesAPI] '{self.name}': large context (~{est_tokens // 1000}k tokens est.), "
            f"scaling read timeout {base_timeout}s → {new_read:.0f}s"
        )
        return httpx.Timeout(
            connect=min(10.0, new_read),
            read=new_read,
            write=min(30.0, new_read),
            pool=min(30.0, new_read),
        )

    async def _chat_non_stream(self, request: LLMRequest) -> LLMResponse:
        """Responses API 非流式请求实现。调用方须已获取 rate limit。

        Responses API 返回 output 而非 choices，因此需要独立的响应验证逻辑。
        """
        client = await self._get_client()

        body = self._build_request_body(request)
        logger.debug(f"ResponsesAPI request to {self.base_url}: model={body.get('model')}")

        req_timeout = self._estimate_request_timeout(body)

        try:
            import httpx
            response = await client.post(
                self._api_url,
                headers=self._build_headers(),
                json=body,
                **({"timeout": req_timeout} if req_timeout else {}),
            )

            if response.status_code >= 400 and body.get("prompt_cache_key"):
                body_preview = (response.text or "")[:500]
                if self._is_prompt_cache_key_unsupported(body_preview):
                    self._prompt_cache_key_unsupported = True
                    retry_body = dict(body)
                    retry_body.pop("prompt_cache_key", None)
                    logger.info(
                        "[ResponsesAPI] endpoint '%s' rejected prompt_cache_key; "
                        "auto-disabling and retrying once",
                        self.name,
                    )
                    response = await client.post(
                        self._api_url,
                        headers=self._build_headers(),
                        json=retry_body,
                        **({"timeout": req_timeout} if req_timeout else {}),
                    )

            if response.status_code >= 400:
                body = (response.text or "")[:500]
                if response.status_code == 401:
                    raise AuthenticationError(f"Authentication failed: {body}")
                if response.status_code == 429:
                    raise RateLimitError(f"Rate limit exceeded: {body}")
                raise LLMError(f"API error ({response.status_code}): {body}")

            from json import JSONDecodeError
            try:
                data = response.json()
            except JSONDecodeError:
                content_type = response.headers.get("content-type", "")
                body_preview = (response.text or "")[:500]
                raise LLMError(
                    "Invalid JSON response from Responses API "
                    f"(status={response.status_code}, content-type={content_type}, "
                    f"body_preview={body_preview!r})"
                )

            if "error" in data and data["error"]:
                err_obj = data["error"] if isinstance(data["error"], dict) else {"message": str(data["error"])}
                err_msg = err_obj.get("message", str(err_obj))
                raise LLMError(f"API error in response body: {err_msg}")

            output = data.get("output")
            if not output:
                body_preview = json.dumps(data, ensure_ascii=False)[:500]
                logger.warning(
                    f"[ResponsesAPI] '{self.name}': API returned 200 but output is empty. "
                    f"Response preview: {body_preview}"
                )
                self.mark_unhealthy(
                    f"Empty output in 200 response (model={data.get('model', '?')})",
                    is_local=self._is_local_endpoint(),
                )
                raise LLMError(
                    f"API returned empty response (no output) from '{self.name}'. "
                    f"Response: {body_preview}"
                )

            self.mark_healthy()
            return self._parse_response(data)

        except Exception as e:
            import httpx
            if isinstance(e, (AuthenticationError, RateLimitError, LLMError)):
                raise
            if isinstance(e, httpx.TimeoutException):
                detail = f"{type(e).__name__}: {e}"
                self.mark_unhealthy(f"Timeout: {detail}", is_local=self._is_local_endpoint())
                raise LLMError(f"Request timeout: {detail}")
            if isinstance(e, httpx.RequestError):
                detail = f"{type(e).__name__}: {e}" if str(e) else f"{type(e).__name__}({repr(e)})"
                self.mark_unhealthy(f"Request error: {detail}", is_local=self._is_local_endpoint())
                raise LLMError(f"Request failed: {detail}")
            raise

    def _build_request_body(self, request: LLMRequest) -> dict:
        input_items, instructions = convert_messages_to_responses(
            request.messages, request.system,
            provider=self.config.provider,
            enable_thinking=request.enable_thinking,
        )

        body: dict = {
            "model": self.config.model,
            "input": input_items,
        }

        if instructions:
            body["instructions"] = instructions

        # max_tokens → max_output_tokens (Responses API 字段名)
        _max_tokens = request.max_tokens
        if _max_tokens and _max_tokens > 0:
            body["max_output_tokens"] = _max_tokens
        else:
            _fallback = self.config.max_tokens or 16384
            body["max_output_tokens"] = _fallback

        # 工具
        if request.tools:
            body["tools"] = convert_tools_to_responses(request.tools)

        # 温度
        if request.temperature != 1.0:
            body["temperature"] = request.temperature

        # 不使用服务端状态管理，每次发送完整上下文
        body["store"] = False

        # 思考模式 (reasoning)
        if request.enable_thinking and self.config.has_capability("thinking"):
            if request.thinking_depth:
                body["reasoning"] = {"effort": request.thinking_depth}
            else:
                body["reasoning"] = {"effort": "medium"}

        # 额外参数
        if self.config.extra_params:
            body.update(self.config.extra_params)
        if request.extra_params:
            body.update(request.extra_params)

        # 清理 Chat Completions 专有字段（可能经 extra_params 泄漏）
        for _cc_key in (
            "max_tokens", "max_completion_tokens", "tool_choice", "stop",
            "enable_thinking", "thinking", "thinking_budget", "reasoning_effort",
        ):
            body.pop(_cc_key, None)

        # 请求体卫生检查
        for key in ("max_output_tokens",):
            val = body.get(key)
            if val is not None and (not isinstance(val, int) or val <= 0):
                body.pop(key, None)

        if not body.get("prompt_cache_key") and self._should_auto_inject_prompt_cache_key():
            prompt_cache_key = self._build_prompt_cache_key(body)
            if prompt_cache_key:
                body["prompt_cache_key"] = prompt_cache_key
                logger.debug(
                    "[ResponsesAPI] prompt cache enabled: endpoint=%s key=%s input_items=%d tools=%d",
                    self.name,
                    prompt_cache_key,
                    len(body.get("input", []) or []),
                    len(body.get("tools", []) or []),
                )

        return body

    def _parse_response(self, data: dict) -> LLMResponse:
        output_items = data.get("output", [])
        content_blocks = []
        has_tool_calls = False

        text_content = ""
        for item in output_items:
            item_type = item.get("type", "")

            if item_type == "message":
                # 从 message item 中提取文本
                for part in item.get("content", []):
                    if part.get("type") in ("output_text", "text"):
                        text_content += part.get("text", "")

            elif item_type == "function_call":
                converted = convert_tool_calls_from_responses([item])
                if converted:
                    content_blocks.extend(converted)
                    has_tool_calls = True

        # 文本格式工具调用降级解析
        if not has_tool_calls and text_content and has_text_tool_calls(text_content):
            logger.info(f"[TEXT_TOOL_PARSE] Detected text-based tool calls from {self.name}")
            clean_text, text_tool_calls = parse_text_tool_calls(text_content)
            if text_tool_calls:
                text_content = clean_text
                content_blocks.extend(text_tool_calls)
                has_tool_calls = True

        if text_content:
            content_blocks.insert(0, TextBlock(text=text_content))

        # 停止原因
        status = data.get("status", "completed")
        if status == "failed":
            err_detail = data.get("last_error") or {}
            err_msg = err_detail.get("message", "unknown error") if isinstance(err_detail, dict) else str(err_detail)
            raise LLMError(f"Responses API returned failed status: {err_msg}")
        if has_tool_calls:
            stop_reason = StopReason.TOOL_USE
        elif status == "incomplete":
            stop_reason = StopReason.MAX_TOKENS
        else:
            stop_reason = StopReason.END_TURN

        # Usage
        usage = self._parse_usage_data(data.get("usage", {}))

        return LLMResponse(
            id=data.get("id", ""),
            content=content_blocks,
            stop_reason=stop_reason,
            usage=usage,
            model=data.get("model", self.config.model),
        )

    def _convert_stream_event(self, event: dict) -> dict:
        """将 Responses API 流式事件转换为内部统一格式。

        Responses API 流式事件结构：
        - response.output_text.delta: 文本增量
        - response.function_call_arguments.delta: 工具调用参数增量
        - response.output_item.added: 新 output item 开始
        - response.completed / response.done: 正常完成
        - response.incomplete: max_output_tokens 截断
        - response.failed / error: API 级别错误
        """
        event_type = event.get("type", "")

        # ── 错误事件 ──
        if event_type in ("error", "response.failed"):
            err_msg = event.get("message") or event.get("error", {}).get("message", "")
            return {
                "type": "error",
                "error": err_msg or f"Responses API stream error: {event_type}",
            }

        # ── 文本增量 ──
        if event_type == "response.output_text.delta":
            return {
                "type": "content_block_delta",
                "delta": {"type": "text", "text": event.get("delta", "")},
            }

        # ── 工具调用：参数增量 ──
        if event_type == "response.function_call_arguments.delta":
            return {
                "type": "content_block_delta",
                "delta": {
                    "type": "tool_use",
                    "id": event.get("call_id"),
                    "name": event.get("name"),
                    "arguments": event.get("delta", ""),
                },
            }

        # ── 工具调用：完成 ──
        if event_type == "response.function_call_arguments.done":
            return {
                "type": "content_block_delta",
                "delta": {
                    "type": "tool_use",
                    "id": event.get("call_id"),
                    "name": event.get("name"),
                    "arguments": "",
                },
            }

        # ── 正常完成 ──
        if event_type in ("response.completed", "response.done"):
            usage_data = event.get("response", {}).get("usage") or event.get("usage")
            return {
                "type": "message_stop",
                "stop_reason": "stop",
                "usage": self._parse_usage_data(usage_data).__dict__ if usage_data else None,
            }

        # ── 截断（max_output_tokens 达到上限）──
        if event_type == "response.incomplete":
            usage_data = event.get("response", {}).get("usage") or event.get("usage")
            return {
                "type": "message_stop",
                "stop_reason": "length",
                "usage": self._parse_usage_data(usage_data).__dict__ if usage_data else None,
            }

        # ── 新 output item（函数调用的首个事件，含 name 和 call_id）──
        if event_type == "response.output_item.added":
            item = event.get("item", {})
            if item.get("type") == "function_call":
                return {
                    "type": "content_block_delta",
                    "delta": {
                        "type": "tool_use",
                        "id": item.get("call_id"),
                        "name": item.get("name"),
                        "arguments": "",
                    },
                }

        # 其他事件（content_part.added 等）
        return {"type": "ping"}

    async def _iter_sse_events(self, body: dict) -> AsyncIterator[dict]:
        """Responses API SSE 传输层。

        适配 Responses API 的 named SSE events (event: + data:) 格式，
        并处理 Responses API 特有的流式错误事件。
        """
        client = await self._get_client()
        req_timeout = self._estimate_request_timeout(body)

        try:
            import httpx
            stream_body = dict(body)
            retry_without_cache_key = False
            while True:
                async with client.stream(
                    "POST",
                    self._api_url,
                    headers=self._build_headers(),
                    json=stream_body,
                    **({"timeout": req_timeout} if req_timeout else {}),
                ) as response:
                    if response.status_code >= 400:
                        error_body = await response.aread()
                        error_text = error_body.decode(errors="replace")[:500]
                        if (
                            stream_body.get("prompt_cache_key")
                            and not retry_without_cache_key
                            and self._is_prompt_cache_key_unsupported(error_text)
                        ):
                            self._prompt_cache_key_unsupported = True
                            retry_without_cache_key = True
                            stream_body = dict(stream_body)
                            stream_body.pop("prompt_cache_key", None)
                            logger.info(
                                "[ResponsesAPI] endpoint '%s' rejected prompt_cache_key "
                                "in stream mode; auto-disabling and retrying once",
                                self.name,
                            )
                            continue
                        if response.status_code == 401:
                            raise AuthenticationError(f"Authentication failed: {error_text}")
                        if response.status_code == 429:
                            raise RateLimitError(f"Rate limit exceeded: {error_text}")
                        raise LLMError(f"API error ({response.status_code}): {error_text}")

                    has_content = False
                    async for line in response.aiter_lines():
                        if not line.strip():
                            continue

                        if line.startswith("data: "):
                            data = line[6:]
                            if data.strip() and data != "[DONE]":
                                try:
                                    event = json.loads(data)
                                    converted = self._convert_stream_event(event)
                                    items = converted if isinstance(converted, list) else [converted]
                                    for item in items:
                                        if item.get("type") == "error":
                                            err_msg = item.get("error", "Unknown stream error")
                                            self.mark_unhealthy(
                                                f"Stream error: {err_msg}",
                                                is_local=self._is_local_endpoint(),
                                            )
                                            raise LLMError(
                                                f"Stream error from '{self.name}': {err_msg}"
                                            )
                                        has_content = True
                                        yield item
                                except json.JSONDecodeError:
                                    continue
                        elif line.startswith("event:"):
                            continue
                        elif not has_content and not line.startswith(":"):
                            try:
                                err_data = json.loads(line)
                                if "error" in err_data:
                                    err_obj = err_data["error"]
                                    err_msg = (
                                        err_obj.get("message", str(err_obj))
                                        if isinstance(err_obj, dict)
                                        else str(err_obj)
                                    )
                                    raise LLMError(f"Stream error from '{self.name}': {err_msg}")
                            except json.JSONDecodeError:
                                if "error" in line.lower():
                                    raise LLMError(
                                        f"Stream error from '{self.name}': {line[:500]}"
                                    )

                    if has_content:
                        self.mark_healthy()
                    else:
                        self.mark_unhealthy(
                            f"Empty stream response (model={stream_body.get('model', '?')})",
                            is_local=self._is_local_endpoint(),
                        )
                        raise LLMError(
                            f"Stream returned empty response from '{self.name}'. "
                            f"Model may be unavailable or rate-limited."
                        )
                    break

        except Exception as e:
            import httpx
            if isinstance(e, (AuthenticationError, RateLimitError, LLMError)):
                raise
            if isinstance(e, httpx.TimeoutException):
                detail = f"{type(e).__name__}: {e}"
                self.mark_unhealthy(
                    f"Timeout: {detail}", is_local=self._is_local_endpoint()
                )
                raise LLMError(f"Stream timeout: {detail}")
            if isinstance(e, httpx.RequestError):
                detail = (
                    f"{type(e).__name__}: {e}"
                    if str(e)
                    else f"{type(e).__name__}({repr(e)})"
                )
                self.mark_unhealthy(
                    f"Stream request error: {detail}",
                    is_local=self._is_local_endpoint(),
                )
                raise LLMError(f"Stream request failed: {detail}")
            raise

    async def chat_stream(self, request: LLMRequest) -> AsyncIterator[dict]:
        """流式聊天请求"""
        await self.acquire_rate_limit()
        body = self._build_request_body(request)
        body["stream"] = True
        async for event in self._iter_sse_events(body):
            yield event
