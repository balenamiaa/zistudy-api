from __future__ import annotations

from typing import Mapping, Sequence

import pytest
from tests.utils import create_pdf_with_text_and_image

from zistudy_api.services.ai.clients import (
    GeminiClientError,
    GeminiFilePart,
    GeminiInlineDataPart,
    GeminiMessage,
    GenerationConfig,
    JSONValue,
)
from zistudy_api.services.ai.pdf import DocumentIngestionService, UploadedPDF
from zistudy_api.services.ai.pdf_strategies import (
    IngestedPDFContextStrategy,
    NativePDFContextStrategy,
)


class _StubClient:
    def __init__(self, *, file_uri: str = "file://uploaded", fail_upload: bool = False) -> None:
        self.default_model = "stub"
        self.supports_file_uploads = True
        self._uploads: list[dict[str, str]] = []
        self._file_uri = file_uri
        self._fail_upload = fail_upload

    async def generate_json(  # pragma: no cover - not used
        self,
        *,
        system_instruction: str,
        messages: Sequence[GeminiMessage],
        response_schema: Mapping[str, JSONValue] | None = None,
        generation_config: GenerationConfig | None = None,
        model: str | None = None,
    ) -> dict[str, JSONValue]:
        raise NotImplementedError

    async def upload_file(self, *, data: bytes, mime_type: str, display_name: str | None = None) -> str:
        if self._fail_upload:
            raise GeminiClientError("upload failed")
        self._uploads.append({"mime_type": mime_type, "display_name": display_name or "uploaded.pdf"})
        return self._file_uri

    async def aclose(self) -> None:  # pragma: no cover - not used
        return None

    @property
    def uploads(self) -> list[dict[str, str]]:
        return self._uploads

pytestmark = pytest.mark.asyncio


async def test_document_ingestion_extracts_text_and_images() -> None:
    service = DocumentIngestionService(text_chunk_size=64, max_text_length=256)
    payload = create_pdf_with_text_and_image(
        "The ECG shows ST-elevation in leads II, III, and aVF."
    )

    result = await service.ingest_pdf(payload, filename="inferior_mi.pdf")

    assert result.filename == "inferior_mi.pdf"
    assert result.page_count == 1
    assert result.text_segments, "Expected at least one text segment"
    assert any("ST-elevation" in segment.content for segment in result.text_segments)
    assert result.images, "Expected inline image extraction"
    first_image = result.images[0]
    assert first_image.mime_type == "image/png"
    assert len(first_image.data_base64) > 10


@pytest.mark.asyncio
async def test_ingested_strategy_returns_text_segments_only() -> None:
    service = DocumentIngestionService()
    payload = UploadedPDF(filename="context.pdf", payload=create_pdf_with_text_and_image("CABG"))
    strategy = IngestedPDFContextStrategy(service)

    context = await strategy.build_context((payload,), client=_StubClient())

    assert context.documents and context.documents[0].filename == "context.pdf"
    assert not context.extra_parts


@pytest.mark.asyncio
async def test_native_strategy_embeds_small_pdf_inline() -> None:
    service = DocumentIngestionService()
    payload = UploadedPDF(filename="inline.pdf", payload=create_pdf_with_text_and_image("Inline"))
    strategy = NativePDFContextStrategy(service, inline_threshold=1_000_000)
    client = _StubClient()

    context = await strategy.build_context((payload,), client=client)

    assert context.documents[0].filename == "inline.pdf"
    assert context.extra_parts, "Expected inline part for small PDF"
    inline_part = context.extra_parts[0]
    assert isinstance(inline_part, GeminiInlineDataPart)
    assert inline_part.mime_type == "application/pdf"
    assert not client.uploads


@pytest.mark.asyncio
async def test_native_strategy_uploads_large_pdf() -> None:
    service = DocumentIngestionService()
    payload = UploadedPDF(filename="upload.pdf", payload=create_pdf_with_text_and_image("Upload me"))
    strategy = NativePDFContextStrategy(service, inline_threshold=1)
    client = _StubClient(file_uri="file://pdf")

    context = await strategy.build_context((payload,), client=client)

    assert client.uploads, "Expected upload to be triggered"
    assert context.extra_parts
    file_part = context.extra_parts[0]
    assert isinstance(file_part, GeminiFilePart)
    assert file_part.file_uri == "file://pdf"


@pytest.mark.asyncio
async def test_native_strategy_falls_back_when_upload_fails() -> None:
    service = DocumentIngestionService()
    payload = UploadedPDF(filename="fallback.pdf", payload=create_pdf_with_text_and_image("Fallback"))
    strategy = NativePDFContextStrategy(service, inline_threshold=1)

    context = await strategy.build_context((payload,), client=_StubClient(fail_upload=True))

    assert not context.extra_parts, "Upload failure should skip extra parts"
