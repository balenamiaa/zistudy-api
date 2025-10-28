from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from zistudy_api.domain.schemas.ai import AiGeneratedStudyCardSet
from zistudy_api.services.ai.clients import (
    GeminiClientError,
    GeminiGenerativeClient,
    GeminiInlineDataPart,
    GeminiMessage,
    GeminiTextPart,
)


def _build_response(payload: dict[str, Any]) -> httpx.Response:
    return httpx.Response(200, json=payload)


@pytest.mark.asyncio
async def test_generate_json_prefers_json_parts() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/models/test:generateContent"
        body = json.loads(request.content.decode("utf-8"))
        assert body["system_instruction"]["parts"][0]["text"] == "system prompt"
        assert body["generationConfig"]["responseMimeType"] == "application/json"
        assert "responseJsonSchema" in body["generationConfig"]
        return _build_response(
            {
                "candidates": [
                    {
                        "content": {"parts": [{"json": {"cards": []}}]},
                        "finishReason": "STOP",
                    }
                ]
            }
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://example.com"
    ) as async_client:
        client = GeminiGenerativeClient(api_key="secret", model="test", http_client=async_client)
        message = GeminiMessage(role="user", parts=[GeminiTextPart("Hello")])
        result = await client.generate_json(
            system_instruction="system prompt",
            messages=[message],
            response_schema={"type": "object"},
        )
        assert result == {"cards": []}


@pytest.mark.asyncio
async def test_generate_json_parses_text_payload() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return _build_response(
            {
                "candidates": [
                    {
                        "content": {"parts": [{"text": '{"foo": "bar"}'}]},
                        "finishReason": "STOP",
                    }
                ]
            }
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://example.com"
    ) as async_client:
        client = GeminiGenerativeClient(api_key="secret", model="test", http_client=async_client)
        message = GeminiMessage(
            role="user",
            parts=[
                GeminiTextPart("Explain this."),
                GeminiInlineDataPart(mime_type="image/png", data="abc"),
            ],
        )
        result = await client.generate_json(
            system_instruction="sys",
            messages=[message],
            response_schema={"type": "object"},
        )
        assert result == {"foo": "bar"}


@pytest.mark.asyncio
async def test_generate_json_raises_on_finish_reason() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return _build_response(
            {
                "candidates": [
                    {
                        "content": {"parts": []},
                        "finishReason": "SAFETY",
                    }
                ]
            }
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://example.com"
    ) as async_client:
        client = GeminiGenerativeClient(api_key="secret", model="test", http_client=async_client)
        message = GeminiMessage(role="user", parts=[GeminiTextPart("Hi")])
        with pytest.raises(GeminiClientError):
            await client.generate_json(
                system_instruction="sys",
                messages=[message],
                response_schema={"type": "object"},
            )


@pytest.mark.asyncio
async def test_generate_json_raises_on_non_object_payload() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return _build_response(
            {
                "candidates": [
                    {
                        "content": {"parts": [{"text": '"not-an-object"'}]},
                        "finishReason": "STOP",
                    }
                ]
            }
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://example.com"
    ) as async_client:
        client = GeminiGenerativeClient(api_key="secret", model="test", http_client=async_client)
        message = GeminiMessage(role="user", parts=[GeminiTextPart("Hi")])
        with pytest.raises(GeminiClientError):
            await client.generate_json(
                system_instruction="sys",
                messages=[message],
                response_schema={"type": "object"},
            )


@pytest.mark.asyncio
async def test_generate_json_accepts_prefixed_models() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/models/prefixed:generateContent"
        return _build_response(
            {
                "candidates": [
                    {
                        "content": {"parts": [{"json": {"cards": []}}]},
                        "finishReason": "STOP",
                    }
                ]
            }
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://example.com"
    ) as async_client:
        client = GeminiGenerativeClient(
            api_key="secret", model="models/prefixed", http_client=async_client
        )
        message = GeminiMessage(role="user", parts=[GeminiTextPart("Hello")])
        result = await client.generate_json(
            system_instruction="system prompt",
            messages=[message],
            response_schema={"type": "object"},
        )
        assert result == {"cards": []}


def _has_ref(node: Any) -> bool:
    if isinstance(node, dict):
        if "$ref" in node:
            return True
        return any(_has_ref(value) for value in node.values())
    if isinstance(node, list):
        return any(_has_ref(item) for item in node)
    return False


def _has_key(node: Any, target: str) -> bool:
    if isinstance(node, dict):
        if target in node:
            return True
        return any(_has_key(value, target) for value in node.values())
    if isinstance(node, list):
        return any(_has_key(item, target) for item in node)
    return False


@pytest.mark.asyncio
async def test_generate_json_resolves_schema_references() -> None:
    captured_schema: dict[str, Any] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        captured_schema["schema"] = body["generationConfig"]["responseJsonSchema"]
        captured_schema["config"] = body["generationConfig"]
        return _build_response(
            {
                "candidates": [
                    {
                        "content": {"parts": [{"json": {"cards": []}}]},
                        "finishReason": "STOP",
                    }
                ]
            }
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://example.com"
    ) as async_client:
        client = GeminiGenerativeClient(api_key="secret", model="test", http_client=async_client)
        schema = AiGeneratedStudyCardSet.model_json_schema()
        message = GeminiMessage(role="user", parts=[GeminiTextPart("Context")])
        await client.generate_json(
            system_instruction="system prompt",
            messages=[message],
            response_schema=schema,
        )

    resolved = captured_schema["schema"]
    config = captured_schema["config"]
    assert "$defs" not in resolved
    assert not _has_ref(resolved)
    assert _has_key(resolved, "additionalProperties")
    assert config.get("responseMimeType") == "application/json"


@pytest.mark.asyncio
async def test_generate_json_raises_client_error_on_http_failure() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={"error": {"status": "INVALID_ARGUMENT", "message": "schema mismatch"}},
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://example.com"
    ) as async_client:
        client = GeminiGenerativeClient(api_key="secret", model="test", http_client=async_client)
        message = GeminiMessage(role="user", parts=[GeminiTextPart("Hello")])
        with pytest.raises(GeminiClientError) as exc_info:
            await client.generate_json(
                system_instruction="sys",
                messages=[message],
                response_schema={"type": "object"},
            )
        error_text = str(exc_info.value)
        assert "400" in error_text
        assert "INVALID_ARGUMENT" in error_text


@pytest.mark.asyncio
async def test_upload_file_raises_client_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/upload/v1beta/files"):
            return httpx.Response(
                500,
                json={"error": {"status": "INTERNAL", "message": "capacity exceeded"}},
            )
        return httpx.Response(500)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://example.com"
    ) as async_client:
        client = GeminiGenerativeClient(api_key="secret", model="test", http_client=async_client)
        with pytest.raises(GeminiClientError):
            await client.upload_file(data=b"pdf-bytes", mime_type="application/pdf")
