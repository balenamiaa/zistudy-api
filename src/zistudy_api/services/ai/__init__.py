from __future__ import annotations

from .agents import AgentConfiguration, AgentResult, StudyCardGenerationAgent
from .clients import GeminiGenerativeClient, GenerativeClient
from .generation_service import AiStudyCardService
from .pdf import DocumentIngestionService, PDFIngestionResult, UploadedPDF
from .pdf_strategies import IngestedPDFContextStrategy, NativePDFContextStrategy, PDFContextStrategy
from .prompts import STUDY_CARD_SYSTEM_PROMPT

__all__ = [
    "AiStudyCardService",
    "AgentConfiguration",
    "AgentResult",
    "DocumentIngestionService",
    "GeminiGenerativeClient",
    "GenerativeClient",
    "IngestedPDFContextStrategy",
    "NativePDFContextStrategy",
    "PDFContextStrategy",
    "PDFIngestionResult",
    "STUDY_CARD_SYSTEM_PROMPT",
    "UploadedPDF",
    "StudyCardGenerationAgent",
]
