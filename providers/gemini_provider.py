from __future__ import annotations

import json
from typing import Any

import google.generativeai as genai

import config
from providers.base import BaseLLMProvider, LLMResponse, ToolCall


class GeminiProvider(BaseLLMProvider):
    def __init__(self) -> None:
        genai.configure(api_key=config.GEMINI_API_KEY)
        self._model_name = config.GEMINI_MODEL

    @property
    def model_name(self) -> str:
        return self._model_name

    def _build_tools(self, tools: list[dict]) -> list[dict]:
        declarations: list[dict[str, Any]] = []
        for schema in tools:
            declarations.append(
                {
                    "function_declarations": [
                        {
                            "name": schema["name"],
                            "description": schema["description"],
                            "parameters": schema["parameters"],
                        }
                    ]
                }
            )
        return declarations

    def _neutral_to_native(self, messages: list[dict]) -> list[dict]:
        native_messages: list[dict[str, Any]] = []
        for message in messages:
            role = message["role"]
            if role in {"user", "assistant"} and "content" in message:
                native_messages.append(
                    {"role": "model" if role == "assistant" else "user", "parts": [message["content"]]}
                )
            elif role == "assistant" and "tool_calls" in message:
                parts = [
                    {
                        "function_call": {
                            "name": call["name"],
                            "args": call.get("params", {}),
                        }
                    }
                    for call in message["tool_calls"]
                ]
                native_messages.append({"role": "model", "parts": parts})
            elif role == "tool":
                payload = json.loads(message["content"])
                native_messages.append(
                    {
                        "role": "user",
                        "parts": [
                            {
                                "function_response": {
                                    "name": payload.get("tool_name", "tool_result"),
                                    "response": payload,
                                }
                            }
                        ],
                    }
                )
        return native_messages

    def chat(
        self,
        messages: list[dict],
        tools: list[dict],
        system_prompt: str,
        stream_callback=None,
    ) -> LLMResponse:
        model = genai.GenerativeModel(
            model_name=self._model_name,
            system_instruction=system_prompt,
            tools=self._build_tools(tools),
        )
        native_messages = self._neutral_to_native(messages)
        text_chunks: list[str] = []
        tool_calls: list[ToolCall] = []
        if stream_callback is not None:
            response = model.generate_content(native_messages, stream=True)
            raw_response = []
            for chunk in response:
                raw_response.append(chunk)
                for candidate in getattr(chunk, "candidates", []) or []:
                    content = getattr(candidate, "content", None)
                    for part in getattr(content, "parts", []) or []:
                        if getattr(part, "text", None):
                            text_chunks.append(part.text)
                            stream_callback(part.text)
                        function_call = getattr(part, "function_call", None)
                        if function_call:
                            tool_calls.append(
                                ToolCall(
                                    id=f"gemini_{len(tool_calls)+1}",
                                    name=function_call.name,
                                    params=dict(function_call.args),
                                )
                            )
            return LLMResponse(text="".join(text_chunks), tool_calls=tool_calls, raw=raw_response)

        response = model.generate_content(native_messages)
        candidate = response.candidates[0] if getattr(response, "candidates", None) else None
        content = getattr(candidate, "content", None)
        for part in getattr(content, "parts", []) or []:
            if getattr(part, "text", None):
                text_chunks.append(part.text)
            function_call = getattr(part, "function_call", None)
            if function_call:
                tool_calls.append(
                    ToolCall(
                        id=f"gemini_{len(tool_calls)+1}",
                        name=function_call.name,
                        params=dict(function_call.args),
                    )
                )
        return LLMResponse(text="".join(text_chunks), tool_calls=tool_calls, raw=response)

    def format_tool_result(
        self,
        tool_call_id: str,
        result: dict[str, Any],
        is_error: bool = False,
    ) -> dict:
        payload = {
            "tool_call_id": tool_call_id,
            "tool_name": result.get("tool_name", "tool_result"),
            "is_error": is_error,
            **result,
        }
        return {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": json.dumps(payload),
        }
