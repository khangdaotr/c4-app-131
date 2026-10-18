"""Raw Chat Completions boundary for v2; events are internal, never SSE.

Recorded files are ordered HTTP exchanges, exercised through the same SDK as live
calls. Assistant messages remain provider dictionaries, never LangChain messages.
"""

import asyncio
import copy
import json
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.config import Settings, get_settings
from src.services.privacy.types import MaskingError
from src.services.providers.gateway import (
    GatewayError,
    GatewayTimeoutError,
    PreparedPayload,
    RawChatTransport,
    _finish,
    _retryable,
    _start,
    close_model_stream,
    egress_scan,
    provider_error_status,
    provider_scope,
    validate_chat_message,
)


@dataclass(frozen=True)
class ContentDelta:
    text: str


@dataclass(frozen=True)
class ReasoningDelta:
    text: str = field(repr=False)


@dataclass(frozen=True)
class ToolCallDelta:
    index: int
    arguments: str = field(default="", repr=False)
    id: str | None = None
    name: str | None = None


@dataclass(frozen=True)
class Done:
    message: dict[str, Any] = field(repr=False)


class LlmProviderError(GatewayError):
    """Only status and a fixed diagnostic code survive provider exceptions."""

    def __init__(self, status_code: int | None, *, reasoning_contract: bool = False) -> None:
        super().__init__(
            "Provider reasoning replay contract failed" if reasoning_contract else "Provider request failed"
        )
        self.status_code = status_code
        self.reasoning_contract = reasoning_contract


class LlmClient:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        recorded: str | Path | None = None,
        http_client: Any = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.recorded = recorded is not None
        self._transport = RawChatTransport(self.settings, recorded=recorded, http_client=http_client)
        self.recorded_requests = self._transport.recorded_requests

    async def aclose(self) -> None:
        await self._transport.close()

    def assert_recording_consumed(self) -> None:
        self._transport.assert_recording_consumed()

    @staticmethod
    def parse_tool_arguments(message: dict[str, Any]) -> dict[str, dict[str, Any]]:
        """Call only on Done/chat results. Keep original argument strings intact."""
        parsed: dict[str, dict[str, Any]] = {}
        try:
            for call in message.get("tool_calls", []):
                arguments = json.loads(call["function"]["arguments"])
                if not isinstance(arguments, dict):
                    raise ValueError
                parsed[call["id"]] = arguments
        except (ValueError, KeyError, TypeError):
            raise GatewayError("Invalid tool arguments", stage="validation") from None
        return parsed

    @staticmethod
    def _check_tool_results(messages: list[dict[str, Any]]) -> None:
        pending: set[str] = set()
        for message in messages:
            if pending:
                if message.get("role") != "tool" or message.get("tool_call_id") not in pending:
                    raise GatewayError("Reconcile dangling tool calls before dispatch", stage="validation")
                pending.remove(message["tool_call_id"])
            elif message.get("role") == "tool":
                raise GatewayError("Tool result has no provider-issued call", stage="validation")
            for call in message.get("tool_calls", []):
                call_id = call.get("id")
                if not call_id or call_id in pending:
                    raise GatewayError("Invalid provider tool call ids", stage="validation")
                pending.add(call_id)
        if pending:
            raise GatewayError("Reconcile dangling tool calls before dispatch", stage="validation")

    def _payload(
        self,
        messages: list[dict[str, Any]] | PreparedPayload,
        *,
        tools: list[dict[str, Any]] | None,
        thinking: bool | None,
        model: str | None,
        stream: bool,
        max_tokens: int | None,
        temperature: float | None,
    ) -> dict[str, Any]:
        with provider_scope() as scope:
            if not self.settings.pii_masking_enabled:
                raise MaskingError("Local privacy protection unavailable; please try again later")
            if isinstance(messages, PreparedPayload):
                if messages.scope is not scope:
                    raise MaskingError("Prepared messages belong to another scope")
                log = copy.deepcopy(messages.value)
                scope._detector()  # Fail closed even for caller-masked messages.
            else:
                log = [
                    scope.mask_payload(
                        copy.deepcopy(message),
                        wire=not scope.mask_only and message.get("role") in {"assistant", "tool"},
                    )
                    for message in messages
                ]
                log = scope._mask_dictionary(log)
                # Rewriting reasoning invalidates the replay contract. Callers
                # must checkpoint masked messages; unsafe replay fails closed.
                for original, masked in zip(messages, log, strict=True):
                    if not scope.mask_only and original.get("role") == "assistant" and original != masked:
                        raise MaskingError("Assistant replay must already be masked")
            self._check_tool_results(log)
            enabled = self.settings.llm_thinking_agent == "enabled" if thinking is None else thinking
            if scope.mask_only:
                if thinking is True:
                    raise GatewayError("Thinking mode is unavailable for the assistant", stage="validation")
                enabled = False
                for message in log:
                    message.pop("reasoning_content", None)
            payload: dict[str, Any] = {
                "model": model or self.settings.llm_model_agent,
                "messages": log,
                "stream": stream,
            }
            if "deepseek" in (self.settings.llm_base_url or "").lower() or self.settings.llm_provider == "deepseek":
                payload["extra_body"] = {"thinking": {"type": "enabled" if enabled else "disabled"}}
            if enabled:
                payload["reasoning_effort"] = self.settings.llm_reasoning_effort
            elif temperature is not None or scope.mask_only:
                payload["temperature"] = 0 if scope.mask_only else temperature
            if tools is not None:
                # Definitions are server-owned protocol, not user prose. Keep
                # regex, identity and dictionary checks without NER inventing
                # people from schema titles such as Message or ToolCall.
                payload["tools"] = scope.mask_payload(tools, detect_names=not scope.mask_only)
            if max_tokens is not None:
                payload["max_tokens"] = max_tokens
            if stream:
                payload["stream_options"] = {"include_usage": True}
            egress_scan(payload, scope)
            return payload

    async def chat(
        self,
        messages: list[dict[str, Any]] | PreparedPayload,
        *,
        tools: list[dict[str, Any]] | None = None,
        thinking: bool | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        iterator = self._run(
            messages,
            tools=tools,
            thinking=thinking,
            model=model,
            stream=False,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        try:
            async for event in iterator:
                if isinstance(event, Done):
                    return event.message
        finally:
            await iterator.aclose()
        raise GatewayError("Provider returned no message")

    async def chat_stream(
        self,
        messages: list[dict[str, Any]] | PreparedPayload,
        *,
        tools: list[dict[str, Any]] | None = None,
        thinking: bool | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        stream_text: bool = False,
        output_detect_names: bool = True,
    ) -> AsyncIterator[ContentDelta | ReasoningDelta | ToolCallDelta | Done]:
        """output_detect_names=False skips NER on model text for prompts built only from
        server-authored guides plus an already-masked question; regex, identity and
        dictionary masking still apply."""
        if stream_text and tools:
            raise GatewayError("Text streaming cannot use tools", stage="validation")
        iterator = self._run(
            messages,
            stream_text=stream_text,
            output_detect_names=output_detect_names,
            tools=tools,
            thinking=thinking,
            model=model,
            stream=True,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        try:
            async for event in iterator:
                yield event
        finally:
            await iterator.aclose()

    async def _run(
        self, messages: list[dict[str, Any]] | PreparedPayload, **options: Any
    ) -> AsyncIterator[ContentDelta | ReasoningDelta | ToolCallDelta | Done]:
        with provider_scope() as scope:
            stream_text = options.pop("stream_text", False)
            names = options.pop("output_detect_names", True)
            payload = self._payload(messages, **options)
            if not self.recorded and not self.settings.llm_api_key.get_secret_value():
                raise GatewayError("LLM_API_KEY is required")
            for attempt in range(self.settings.llm_max_retries + 1):
                egress_scan(payload, scope)
                call_id = _start("recorded_chat" if self.recorded else "chat", scope)
                status, usage, emitted, upstream = "failed", None, False, None
                retry = False
                sanitized_error: GatewayError | None = None
                try:
                    async with asyncio.timeout(self.settings.llm_timeout_s):
                        upstream = await self._transport.create(payload)
                        if not options["stream"]:
                            usage = upstream.usage.model_dump(exclude_none=True) if upstream.usage else None
                            message = upstream.choices[0].message.model_dump(exclude_none=True)
                        else:
                            accumulated: dict[str, Any] = {}
                            private_pending = ""
                            public_text = ""
                            calls: dict[int, dict[str, Any]] = {}
                            finished = False
                            async for chunk in upstream:
                                if chunk.usage:
                                    usage = chunk.usage.model_dump(exclude_none=True)
                                for choice in chunk.choices:
                                    if choice.index != 0:
                                        raise GatewayError("Only one completion is supported")
                                    delta = choice.delta.model_dump(exclude_none=True)
                                    for key, value in delta.items():
                                        if key == "tool_calls":
                                            for fragment in value:
                                                index = fragment["index"]
                                                call = calls.setdefault(index, {})
                                                for call_key, call_value in fragment.items():
                                                    if call_key == "index":
                                                        continue
                                                    if call_key == "function":
                                                        function = call.setdefault("function", {})
                                                        for name, part in call_value.items():
                                                            function[name] = function.get(name, "") + part
                                                    else:
                                                        call[call_key] = call.get(call_key, "") + call_value
                                                function = fragment.get("function", {})
                                                if not scope.mask_only:
                                                    emitted = True
                                                    yield ToolCallDelta(
                                                        index,
                                                        function.get("arguments", ""),
                                                        fragment.get("id"),
                                                        function.get("name"),
                                                    )
                                        elif key in {"content", "reasoning_content", "refusal"}:
                                            accumulated[key] = accumulated.get(key, "") + value
                                            if value and key == "content" and scope.mask_only and stream_text:
                                                private_pending += value
                                                # Preserve cross-chunk identifiers for the existing masker.
                                                # Flush complete sentences only; never mask individual tokens.
                                                boundary = list(re.finditer(r"[.!?](?=\s)|\n", private_pending))
                                                if boundary:
                                                    end = boundary[-1].end()
                                                    unit, private_pending = private_pending[:end], private_pending[end:]
                                                    safe = scope.sanitize_output(
                                                        scope.mask_payload(unit, wire=True, detect_names=names)
                                                    )
                                                    egress_scan(safe, scope)
                                                    public_text += safe
                                                    for token in re.findall(r"\S+\s*|\s+", safe):
                                                        emitted = True
                                                        yield ContentDelta(token)
                                            if value and key != "refusal" and not scope.mask_only:
                                                emitted = True
                                                yield ContentDelta(value) if key == "content" else ReasoningDelta(value)
                                        else:
                                            accumulated[key] = value
                                    if choice.finish_reason is not None:
                                        finished = True
                            if not finished:
                                raise GatewayError("Provider stream ended without a finish marker")
                            if scope.mask_only and stream_text:
                                if calls:
                                    raise GatewayError("Unexpected tool call in text stream")
                                safe = scope.sanitize_output(
                                    scope.mask_payload(private_pending, wire=True, detect_names=names)
                                )
                                egress_scan(safe, scope)
                                public_text += safe
                                for token in re.findall(r"\S+\s*|\s+", safe):
                                    emitted = True
                                    yield ContentDelta(token)
                                accumulated["content"] = public_text
                            if calls:
                                accumulated["tool_calls"] = [calls[index] for index in sorted(calls)]
                            message = validate_chat_message(accumulated)
                        if scope.mask_only:
                            message.pop("reasoning_content", None)
                            # Default callers retain complete-response validation.
                            # Opt-in text streams already masked each complete
                            # sentence and still validate the assembled response.
                            message = scope.sanitize_output(scope.mask_payload(message, wire=True, detect_names=names))
                        egress_scan(message, scope)
                        status = "success"
                    # Finish accounting and close transport BEFORE publishing Done.
                except (asyncio.CancelledError, GeneratorExit):
                    status = "cancelled"
                    raise
                except TimeoutError:
                    status = "timeout"
                    retry = not emitted and attempt < self.settings.llm_max_retries
                    if not retry:
                        sanitized_error = GatewayTimeoutError("Provider request timed out")
                except (GatewayError, MaskingError):
                    raise
                except Exception as error:
                    retry = not emitted and _retryable(error) and attempt < self.settings.llm_max_retries
                    if not retry:
                        code = provider_error_status(error)
                        reasoning = code == 400 and "reasoning" in str(error).lower()
                        sanitized_error = LlmProviderError(code, reasoning_contract=reasoning)
                finally:
                    try:
                        if options["stream"] and upstream is not None:
                            await close_model_stream(upstream)
                    finally:
                        _finish(
                            call_id, status, {"usage": usage or {}}, local=self.recorded, model_name=payload["model"]
                        )
                if sanitized_error is not None:
                    # Raise after the provider handler has exited: no raw error
                    # body is retained in __context__, even for error exporters.
                    raise sanitized_error
                if retry:
                    await asyncio.sleep(min(0.5 * 2**attempt, 8.0))
                    continue
                if scope.mask_only and options["stream"] and not stream_text:
                    if message.get("content"):
                        yield ContentDelta(message["content"])
                    for index, call in enumerate(message.get("tool_calls", [])):
                        function = call["function"]
                        yield ToolCallDelta(index, function.get("arguments", ""), call.get("id"), function.get("name"))
                yield Done(message)
                return
