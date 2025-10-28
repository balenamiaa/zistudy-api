"""Gemini client abstractions used by the study card generation pipeline."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import (
    Mapping,
    MutableMapping,
    Protocol,
    Sequence,
    TypeAlias,
    Union,
    cast,
)

import httpx

MAX_INLINE_BYTES = 20 * 1024 * 1024

logger = logging.getLogger(__name__)

JSONPrimitive: TypeAlias = str | int | float | bool | None
JSONValue: TypeAlias = JSONPrimitive | list["JSONValue"] | dict[str, "JSONValue"]
JSONObject: TypeAlias = dict[str, JSONValue]


class GeminiClientError(RuntimeError):
    """Raised when a Gemini response cannot be parsed or indicates failure."""


@dataclass(frozen=True, slots=True)
class GeminiMessage:
    """Single Gemini message consisting of role-tagged parts."""

    role: str
    parts: Sequence["GeminiContentPart"]


@dataclass(frozen=True, slots=True)
class GeminiTextPart:
    """Plain text content part."""

    text: str


@dataclass(frozen=True, slots=True)
class GeminiInlineDataPart:
    """Inline base64 encoded payload part."""

    mime_type: str
    data: str


@dataclass(frozen=True, slots=True)
class GeminiFilePart:
    """Reference to a Gemini uploaded file."""

    mime_type: str
    file_uri: str


GeminiContentPart = Union[GeminiTextPart, GeminiInlineDataPart, GeminiFilePart]


class GenerationConfig:
    """Typed container for Gemini generation configuration parameters."""

    __slots__ = (
        "_temperature",
        "_top_p",
        "_top_k",
        "_candidate_count",
        "_max_output_tokens",
        "_response_mime_type",
        "_additional_parameters",
    )

    def __init__(
        self,
        *,
        temperature: float | None = None,
        top_p: float | None = None,
        top_k: int | None = None,
        candidate_count: int | None = None,
        max_output_tokens: int | None = None,
        response_mime_type: str | None = "application/json",
        additional_parameters: Mapping[str, JSONValue] | None = None,
    ) -> None:
        self._temperature = temperature
        self._top_p = top_p
        self._top_k = top_k
        self._candidate_count = candidate_count
        self._max_output_tokens = max_output_tokens
        self._response_mime_type = response_mime_type
        self._additional_parameters = dict(additional_parameters or {})

    def as_payload(self) -> JSONObject:
        """Render the config as the JSON payload expected by Gemini."""
        payload: JSONObject = {}
        if self._temperature is not None:
            payload["temperature"] = self._temperature
        if self._top_p is not None:
            payload["topP"] = self._top_p
        if self._top_k is not None:
            payload["topK"] = self._top_k
        if self._candidate_count is not None:
            payload["candidateCount"] = self._candidate_count
        if self._max_output_tokens is not None:
            payload["maxOutputTokens"] = self._max_output_tokens
        if self._response_mime_type:
            payload["responseMimeType"] = self._response_mime_type
        if self._additional_parameters:
            payload.update(ensure_json_object(self._additional_parameters))
        return payload


class GenerativeClient(Protocol):
    """Protocol representing the subset of Gemini client behaviour we rely on."""

    @property
    def default_model(self) -> str: ...

    @property
    def supports_file_uploads(self) -> bool: ...

    async def generate_json(
        self,
        *,
        system_instruction: str,
        messages: Sequence[GeminiMessage],
        response_schema: Mapping[str, JSONValue] | None = None,
        generation_config: GenerationConfig | None = None,
        model: str | None = None,
    ) -> Mapping[str, JSONValue]: ...

    async def upload_file(
        self,
        *,
        data: bytes,
        mime_type: str,
        display_name: str | None = None,
    ) -> str: ...

    async def aclose(self) -> None: ...


class GeminiGenerativeClient:
    """Thin async client for Google Gemini models."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        endpoint: str = "https://generativelanguage.googleapis.com/v1beta",
        timeout: float = 60.0,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("A Gemini API key is required.")
        self._api_key = api_key
        self._model = model
        self._client = http_client or httpx.AsyncClient(
            base_url=endpoint,
            timeout=httpx.Timeout(timeout),
            headers={
                "Content-Type": "application/json",
            },
        )
        self._owns_client = http_client is None
        base_url = httpx.URL(self._client.base_url if http_client else endpoint)
        self._root_url = base_url.copy_with(path="/")

    @property
    def default_model(self) -> str:
        return self._model

    @property
    def supports_file_uploads(self) -> bool:
        return True

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def generate_json(
        self,
        *,
        system_instruction: str,
        messages: Sequence[GeminiMessage],
        response_schema: Mapping[str, JSONValue] | None = None,
        generation_config: GenerationConfig | None = None,
        model: str | None = None,
    ) -> Mapping[str, JSONValue]:
        """Send a structured JSON generation request and return the decoded payload."""
        target_model = model or self._model
        path_component = (
            target_model if target_model.startswith("models/") else f"models/{target_model}"
        )
        url = f"/{path_component}:generateContent"
        instruction_payload = ensure_json_object(
            {
                "parts": [{"text": system_instruction}],
            }
        )
        contents_payload: list[JSONValue] = []
        for message in messages:
            part_payloads = [
                ensure_json_object(dict(self._serialise_part(part))) for part in message.parts
            ]
            message_payload = ensure_json_object(
                {
                    "role": message.role,
                    "parts": part_payloads,
                }
            )
            contents_payload.append(message_payload)

        config_payload: JSONObject = ensure_json_object(
            generation_config.as_payload() if generation_config else {}
        )
        if "responseMimeType" not in config_payload:
            config_payload["responseMimeType"] = "application/json"
        if response_schema:
            config_payload["responseJsonSchema"] = _resolve_schema(
                ensure_json_object(response_schema)
            )

        payload_dict: dict[str, JSONValue] = {
            "system_instruction": instruction_payload,
            "contents": contents_payload,
        }
        if config_payload:
            payload_dict["generationConfig"] = config_payload
        payload: JSONObject = ensure_json_object(payload_dict)

        response = await self._client.post(
            url,
            headers={"x-goog-api-key": self._api_key},
            json=payload,
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:  # pragma: no cover - relies on remote service
            error_summary = _summarize_response_error(exc.response)
            error_body = _extract_error_body(exc.response)
            logger.error(
                "Gemini request failed",
                extra={
                    "status_code": exc.response.status_code,
                    "url": str(exc.request.url),
                    "model": target_model,
                    "error_summary": error_summary,
                    "error_body": error_body,
                    "request_id": exc.response.headers.get("x-request-id"),
                },
            )
            raise GeminiClientError(
                f"Gemini request failed ({exc.response.status_code}): {error_summary}"
            ) from exc
        data = response.json()
        feedback = data.get("promptFeedback")
        if feedback and feedback.get("blockReason"):
            raise GeminiClientError(f"Gemini blocked the request: {feedback['blockReason']}")

        candidates = data.get("candidates", [])
        if not candidates:
            raise GeminiClientError("Gemini response did not contain any candidates.")

        candidate = candidates[0]
        finish_reason = candidate.get("finishReason")
        if finish_reason and finish_reason not in {"STOP", "FINISH"}:
            raise GeminiClientError(
                f"Gemini did not finish successfully (finishReason={finish_reason})."
            )

        content = candidate.get("content", {})
        parts = content.get("parts", [])
        for part in parts:
            if "json" in part:
                json_payload = part["json"]
                if isinstance(json_payload, dict):
                    return json_payload
            if "text" in part and isinstance(part["text"], str):
                return self._parse_text_json(part["text"])

        raise GeminiClientError("Unable to locate JSON payload in Gemini response.")

    async def upload_file(
        self,
        *,
        data: bytes,
        mime_type: str,
        display_name: str | None = None,
    ) -> str:
        """Upload binary data to Gemini's file API and return the resulting URI."""
        start_headers = {
            "x-goog-api-key": self._api_key,
            "X-Goog-Upload-Protocol": "resumable",
            "X-Goog-Upload-Command": "start",
            "X-Goog-Upload-Header-Content-Length": str(len(data)),
            "X-Goog-Upload-Header-Content-Type": mime_type,
            "Content-Type": "application/json",
        }
        start_payload = {
            "file": {
                "display_name": display_name or "uploaded.pdf",
            }
        }
        start_url = str(self._root_url.join("upload/v1beta/files"))
        start_resp = await self._client.post(start_url, headers=start_headers, json=start_payload)
        try:
            start_resp.raise_for_status()
        except httpx.HTTPStatusError as exc:  # pragma: no cover - relies on remote service
            error_summary = _summarize_response_error(exc.response)
            logger.error(
                "Gemini upload initialisation failed",
                extra={
                    "status_code": exc.response.status_code,
                    "url": str(exc.request.url),
                    "mime_type": mime_type,
                    "display_name": display_name,
                    "request_id": exc.response.headers.get("x-request-id"),
                    "error_summary": error_summary,
                },
            )
            raise GeminiClientError(
                f"Gemini upload initialisation failed ({exc.response.status_code}): {error_summary}"
            ) from exc
        upload_url = start_resp.headers.get("x-goog-upload-url")
        if not upload_url:
            raise GeminiClientError("Gemini did not provide an upload URL.")

        upload_headers = {
            "x-goog-api-key": self._api_key,
            "Content-Length": str(len(data)),
            "Content-Type": mime_type,
            "X-Goog-Upload-Offset": "0",
            "X-Goog-Upload-Command": "upload, finalize",
        }
        upload_resp = await self._client.post(upload_url, headers=upload_headers, content=data)
        try:
            upload_resp.raise_for_status()
        except httpx.HTTPStatusError as exc:  # pragma: no cover - relies on remote service
            error_summary = _summarize_response_error(exc.response)
            logger.error(
                "Gemini upload failed",
                extra={
                    "status_code": exc.response.status_code,
                    "url": str(exc.request.url),
                    "mime_type": mime_type,
                    "display_name": display_name,
                    "request_id": exc.response.headers.get("x-request-id"),
                    "error_summary": error_summary,
                },
            )
            raise GeminiClientError(
                f"Gemini upload failed ({exc.response.status_code}): {error_summary}"
            ) from exc
        payload = upload_resp.json()
        file_info = payload.get("file")
        if not file_info or "uri" not in file_info:
            raise GeminiClientError("Gemini upload response missing file URI.")
        return cast(str, file_info["uri"])

    def _parse_text_json(self, payload: str) -> Mapping[str, JSONValue]:
        """Parse a JSON object embedded inside a Gemini text part."""
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError as exc:  # pragma: no cover - defensive guard
            raise GeminiClientError("Gemini response was not valid JSON.") from exc
        if not isinstance(parsed, MutableMapping):
            raise GeminiClientError("Gemini response did not contain a JSON object.")
        return ensure_json_object(parsed)

    @staticmethod
    def _serialise_part(part: GeminiContentPart) -> Mapping[str, JSONValue]:
        """Convert strongly typed part structures into Gemini payload dictionaries."""
        if isinstance(part, GeminiTextPart):
            return {"text": part.text}
        if isinstance(part, GeminiInlineDataPart):
            return {
                "inlineData": {
                    "mimeType": part.mime_type,
                    "data": part.data,
                }
            }
        if isinstance(part, GeminiFilePart):
            return {
                "fileData": {
                    "mimeType": part.mime_type,
                    "fileUri": part.file_uri,
                }
            }
        raise GeminiClientError(f"Unsupported part type: {type(part)!r}")


__all__ = [
    "GeminiClientError",
    "GeminiGenerativeClient",
    "GenerativeClient",
    "GenerationConfig",
    "JSONValue",
    "JSONObject",
    "GeminiContentPart",
    "GeminiFilePart",
    "GeminiInlineDataPart",
    "GeminiMessage",
    "GeminiTextPart",
    "MAX_INLINE_BYTES",
    "ensure_json_object",
]


def _ensure_json_value(value: JSONValue | object, *, path: str = "root") -> JSONValue:
    """Validate nested JSON content and raise descriptive errors when invalid."""
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        return [
            _ensure_json_value(item, path=f"{path}[{index}]") for index, item in enumerate(value)
        ]
    if isinstance(value, tuple):
        return [
            _ensure_json_value(item, path=f"{path}[{index}]") for index, item in enumerate(value)
        ]
    if isinstance(value, dict):
        return ensure_json_object(cast(Mapping[str, JSONValue | object], value), path=path)
    raise GeminiClientError(f"Unsupported JSON value at {path}: {type(value)!r}")


def ensure_json_object(
    payload: Mapping[str, JSONValue | object],
    *,
    path: str = "root",
) -> JSONObject:
    """Coerce mappings into JSON dictionaries while validating keys and values."""
    result: JSONObject = {}
    for key, value in payload.items():
        if not isinstance(key, str):
            raise GeminiClientError(f"JSON keys must be strings (found {type(key)!r} at {path})")
        result[key] = _ensure_json_value(value, path=f"{path}.{key}")
    return result


def _resolve_schema(schema: JSONObject) -> JSONObject:
    """Inline $ref references so Gemini receives a fully-expanded schema."""

    if "$defs" not in schema and "$ref" not in schema:
        return schema

    defs_obj: dict[str, JSONValue] | None = None
    raw_defs = schema.get("$defs")
    if raw_defs is not None:
        if not isinstance(raw_defs, dict):
            raise GeminiClientError("Invalid JSON schema: $defs must be an object.")
        defs_obj = ensure_json_object(raw_defs)

    def _resolve(obj: JSONValue, *, trail: tuple[str, ...] = ()) -> JSONValue:
        if isinstance(obj, dict):
            if "$ref" in obj:
                ref_value = obj["$ref"]
                if not isinstance(ref_value, str):
                    raise GeminiClientError("Invalid JSON schema: $ref must be a string.")
                if not ref_value.startswith("#/$defs/"):
                    raise GeminiClientError(f"Unsupported $ref target: {ref_value}")
                ref_key = ref_value.split("/")[-1]
                if defs_obj is None or ref_key not in defs_obj:
                    raise GeminiClientError(f"Missing $defs entry for {ref_value}")
                if ref_value in trail:
                    raise GeminiClientError(f"Circular $ref detected for {ref_value}")
                return _resolve(defs_obj[ref_key], trail=trail + (ref_value,))

            return {
                key: _resolve(value, trail=trail) for key, value in obj.items() if key != "$defs"
            }
        if isinstance(obj, list):
            return [_resolve(item, trail=trail) for item in obj]
        return obj

    resolved: JSONObject = {key: _resolve(value) for key, value in schema.items() if key != "$defs"}
    return resolved


def _summarize_response_error(response: httpx.Response) -> str:
    """Provide a concise textual summary for logging Gemini HTTP errors."""
    try:
        payload = response.json()
    except ValueError:
        text = response.text.strip()
        return text or "No response body"

    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            status = error.get("status") or error.get("code")
            summary_parts = []
            if isinstance(status, str) and status:
                summary_parts.append(status)
            if isinstance(message, str) and message:
                summary_parts.append(message)
            return ": ".join(summary_parts) or "Gemini returned an error"
        message = payload.get("message")
        if isinstance(message, str) and message:
            return message
    if isinstance(payload, list):
        return f"Response contained {len(payload)} error item(s)"
    return json.dumps(payload)


def _extract_error_body(response: httpx.Response) -> JSONValue | str | None:
    """Return a JSON-serialisable body for failed Gemini responses."""
    try:
        payload = response.json()
    except ValueError:
        text = response.text.strip()
        return text or None

    try:
        if isinstance(payload, dict):
            return ensure_json_object(payload)
        if isinstance(payload, list):
            return [
                _ensure_json_value(item, path=f"[error][{index}]")
                for index, item in enumerate(payload)
            ]
        return _ensure_json_value(payload)
    except GeminiClientError:
        return json.dumps(payload)
