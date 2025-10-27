from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Iterable, Sequence

import anyio
import fitz  # type: ignore[import-untyped]


@dataclass(frozen=True, slots=True)
class PDFTextSegment:
    page_index: int
    content: str


@dataclass(frozen=True, slots=True)
class PDFImageFragment:
    page_index: int
    mime_type: str
    data_base64: str


@dataclass(frozen=True, slots=True)
class PDFIngestionResult:
    filename: str | None
    text_segments: Sequence[PDFTextSegment]
    images: Sequence[PDFImageFragment]
    page_count: int


@dataclass(frozen=True, slots=True)
class UploadedPDF:
    filename: str | None
    payload: bytes


class DocumentIngestionService:
    """Utilities for extracting structured context from PDF documents."""

    def __init__(
        self,
        *,
        text_chunk_size: int = 1_200,
        max_text_length: int = 18_000,
    ) -> None:
        self._text_chunk_size = text_chunk_size
        self._max_text_length = max_text_length

    async def ingest_pdf(
        self, payload: bytes, *, filename: str | None = None
    ) -> PDFIngestionResult:
        return await anyio.to_thread.run_sync(self._extract, payload, filename)

    def _extract(self, payload: bytes, filename: str | None) -> PDFIngestionResult:
        document = fitz.open(stream=payload, filetype="pdf")
        try:
            text_segments: list[PDFTextSegment] = []
            images: list[PDFImageFragment] = []
            for page_index, page in enumerate(document, start=1):
                text = page.get_text("text").strip()
                if text:
                    text_segments.extend(self._chunk(page_index, text))

                for image in page.get_images(full=True):
                    xref = image[0]
                    pixmap = fitz.Pixmap(document, xref)
                    if pixmap.alpha or pixmap.colorspace is None:
                        pixmap = fitz.Pixmap(fitz.csRGB, pixmap)
                    data = pixmap.tobytes("png")

                    encoded = base64.b64encode(data).decode("ascii")
                    images.append(
                        PDFImageFragment(
                            page_index=page_index,
                            mime_type="image/png",
                            data_base64=encoded,
                        )
                    )

            cropped_segments = self._truncate(text_segments)
            return PDFIngestionResult(
                filename=filename,
                text_segments=cropped_segments,
                images=tuple(images),
                page_count=document.page_count,
            )
        finally:
            document.close()

    def _chunk(self, page_index: int, content: str) -> Iterable[PDFTextSegment]:
        sanitized = " ".join(content.split())
        size = self._text_chunk_size
        for start in range(0, len(sanitized), size):
            segment = sanitized[start : start + size].strip()
            if segment:
                yield PDFTextSegment(page_index=page_index, content=segment)

    def _truncate(self, segments: Sequence[PDFTextSegment]) -> Sequence[PDFTextSegment]:
        total = 0
        output: list[PDFTextSegment] = []
        for segment in segments:
            if total >= self._max_text_length:
                break
            remaining = self._max_text_length - total
            content = (
                segment.content
                if len(segment.content) <= remaining
                else segment.content[:remaining]
            )
            output.append(PDFTextSegment(page_index=segment.page_index, content=content))
            total += len(content)
        return tuple(output)


__all__ = [
    "DocumentIngestionService",
    "PDFImageFragment",
    "PDFIngestionResult",
    "UploadedPDF",
    "PDFTextSegment",
]
