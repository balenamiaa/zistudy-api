from __future__ import annotations

import pytest
from tests.utils import create_pdf_with_text_and_image

from zistudy_api.services.ai.pdf import DocumentIngestionService

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
