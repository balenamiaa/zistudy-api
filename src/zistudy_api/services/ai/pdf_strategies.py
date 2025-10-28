"""Strategies that prepare Gemini-ready context from uploaded PDFs."""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from typing import Protocol, Sequence

from zistudy_api.services.ai.clients import (
    MAX_INLINE_BYTES,
    GeminiClientError,
    GeminiFilePart,
    GeminiInlineDataPart,
    GeminiTextPart,
    GenerativeClient,
)
from zistudy_api.services.ai.pdf import DocumentIngestionService, PDFIngestionResult, UploadedPDF

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PDFContext:
    """Context bundle returned from a PDF strategy."""

    documents: Sequence[PDFIngestionResult]
    extra_parts: Sequence[GeminiTextPart | GeminiInlineDataPart | GeminiFilePart]


class PDFContextStrategy(Protocol):
    async def build_context(
        self,
        files: Sequence[UploadedPDF],
        *,
        client: GenerativeClient,
    ) -> PDFContext:
        """Create a context payload for the specified PDFs."""


class IngestedPDFContextStrategy(PDFContextStrategy):
    def __init__(self, ingestor: DocumentIngestionService) -> None:
        self._ingestor = ingestor

    async def build_context(
        self,
        files: Sequence[UploadedPDF],
        *,
        client: GenerativeClient,
    ) -> PDFContext:
        """Extract text from PDFs and ignore binary assets."""
        logger.info(
            "Building ingested PDF context",
            extra={"file_count": len(files)},
        )
        documents: list[PDFIngestionResult] = []
        for item in files:
            document = await self._ingestor.ingest_pdf(item.payload, filename=item.filename)
            logger.debug(
                "Ingested PDF",
                extra={
                    "pdf_filename": item.filename,
                    "pages": document.page_count,
                    "segments": len(document.text_segments),
                    "images": len(document.images),
                },
            )
            documents.append(document)
        return PDFContext(documents=tuple(documents), extra_parts=())


class NativePDFContextStrategy(PDFContextStrategy):
    def __init__(
        self, ingestor: DocumentIngestionService, inline_threshold: int = MAX_INLINE_BYTES
    ) -> None:
        self._ingestor = ingestor
        self._inline_threshold = inline_threshold

    async def build_context(
        self,
        files: Sequence[UploadedPDF],
        *,
        client: GenerativeClient,
    ) -> PDFContext:
        """Embed small PDFs inline and upload large PDFs to Gemini's file API."""
        logger.info(
            "Building native PDF context",
            extra={
                "file_count": len(files),
                "inline_threshold": self._inline_threshold,
            },
        )
        documents: list[PDFIngestionResult] = []
        extras: list[GeminiInlineDataPart | GeminiFilePart] = []

        for item in files:
            document = await self._ingestor.ingest_pdf(item.payload, filename=item.filename)
            size_bytes = len(item.payload)
            if len(item.payload) > self._inline_threshold:
                try:
                    file_uri = await client.upload_file(
                        data=item.payload,
                        mime_type="application/pdf",
                        display_name=item.filename or "uploaded.pdf",
                    )
                except GeminiClientError as exc:
                    logger.warning(
                        "Gemini upload failed; falling back to extracted text",
                        extra={
                            "pdf_filename": item.filename,
                            "pdf_bytes": size_bytes,
                            "reason": str(exc),
                        },
                    )
                else:
                    logger.debug(
                        "Uploaded PDF via File API",
                        extra={
                            "pdf_filename": item.filename,
                            "pdf_bytes": size_bytes,
                            "file_uri": file_uri,
                        },
                    )
                    extras.append(
                        GeminiFilePart(
                            mime_type="application/pdf",
                            file_uri=file_uri,
                        )
                    )
            else:
                encoded = base64.b64encode(item.payload).decode("ascii")
                extras.append(
                    GeminiInlineDataPart(
                        mime_type="application/pdf",
                        data=encoded,
                    )
                )
                logger.debug(
                    "Embedded PDF inline",
                    extra={
                        "pdf_filename": item.filename,
                        "pdf_bytes": size_bytes,
                    },
                )
            documents.append(document)

        return PDFContext(documents=tuple(documents), extra_parts=tuple(extras))


__all__ = [
    "PDFContext",
    "PDFContextStrategy",
    "IngestedPDFContextStrategy",
    "NativePDFContextStrategy",
]
