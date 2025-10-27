from __future__ import annotations

from typing import cast

import fitz  # type: ignore[import-untyped]


def create_pdf_with_text_and_image(
    text: str = "Patient presents with acute chest pain.",
    *,
    width: float = 120.0,
    height: float = 120.0,
) -> bytes:
    document = fitz.open()
    try:
        page = document.new_page()
        page.insert_text((72, 72), text, fontsize=12)
        rect = fitz.Rect(72, 120, 72 + width, 120 + height)
        bbox = fitz.IRect(0, 0, int(width), int(height))
        pixmap = fitz.Pixmap(fitz.csRGB, bbox)
        pixmap.clear_with(0xFF4444)
        page.insert_image(rect, pixmap=pixmap)
        return cast(bytes, document.tobytes())
    finally:
        document.close()


__all__ = ["create_pdf_with_text_and_image"]
