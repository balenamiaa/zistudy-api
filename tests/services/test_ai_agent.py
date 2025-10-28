from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence, cast

import pytest

from zistudy_api.domain.enums import CardType
from zistudy_api.domain.schemas.ai import StudyCardGenerationRequest
from zistudy_api.services.ai.agents import AgentConfiguration, StudyCardGenerationAgent
from zistudy_api.services.ai.clients import (
    GeminiClientError,
    GeminiMessage,
    GenerationConfig,
    JSONObject,
    JSONValue,
)
from zistudy_api.services.ai.pdf import PDFImageFragment, PDFIngestionResult, PDFTextSegment


@dataclass(slots=True)
class RecordedCall:
    system_instruction: str
    messages: Sequence[GeminiMessage]
    response_schema: Mapping[str, JSONValue] | None
    generation_config: GenerationConfig | None
    model: str | None


class StubGenerativeClient:
    def __init__(self, responses: list[JSONObject | Exception]) -> None:
        self._responses = responses
        self.calls: list[RecordedCall] = []
        self.upload_calls: list[tuple[bytes, str, str | None]] = []
        self._default_model = "models/gemini-stub"

    async def generate_json(
        self,
        *,
        system_instruction: str,
        messages: Sequence[GeminiMessage],
        response_schema: Mapping[str, JSONValue] | None = None,
        generation_config: GenerationConfig | None = None,
        model: str | None = None,
    ) -> Mapping[str, JSONValue]:
        self.calls.append(
            RecordedCall(
                system_instruction=system_instruction,
                messages=messages,
                response_schema=response_schema,
                generation_config=generation_config,
                model=model,
            )
        )
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    async def upload_file(
        self,
        *,
        data: bytes,
        mime_type: str,
        display_name: str | None = None,
    ) -> str:
        self.upload_calls.append((data, mime_type, display_name))
        return "uploaded://stub"

    async def aclose(self) -> None:
        return None

    @property
    def default_model(self) -> str:
        return self._default_model

    @property
    def supports_file_uploads(self) -> bool:
        return True


pytestmark = pytest.mark.asyncio


async def test_agent_respects_target_count_and_context() -> None:
    fake_response = cast(
        JSONObject,
        {
            "cards": [
                {
                    "card_type": CardType.MCQ_SINGLE.value,
                    "difficulty": 3,
                    "payload": {
                        "question": "A 62-year-old presents with crushing chest pain. Interpret the ECG findings.",
                        "options": [
                            {"id": "A", "text": "Inferior STEMI"},
                            {"id": "B", "text": "Anterior NSTEMI"},
                        ],
                        "correct_answers": ["A"],
                        "rationale": {
                            "primary": "ST elevations in II, III, aVF with reciprocal depression indicate an inferior STEMI.",
                            "alternatives": {
                                "B": "Anterior involvement would elevate V2-V4 instead."
                            },
                        },
                        "connections": [
                            "Consider right ventricular involvement.",
                            "Assess for hypotension before nitrates.",
                        ],
                        "glossary": {"STEMI": "ST-elevation myocardial infarction."},
                        "numerical_ranges": ["Troponin I > 0.04 ng/mL"],
                        "references": ["ACC/AHA STEMI Guideline 2024"],
                    },
                },
                {
                    "card_type": CardType.MCQ_SINGLE.value,
                    "difficulty": 4,
                    "payload": {
                        "question": "What complication is most likely within the first 24 hours of an inferior MI?",
                        "options": [
                            {"id": "A", "text": "Papillary muscle rupture"},
                            {"id": "B", "text": "Sinus bradycardia"},
                        ],
                        "correct_answers": ["B"],
                        "rationale": {
                            "primary": "AV nodal ischemia frequently causes bradyarrhythmias early after inferior MI.",
                            "alternatives": {"A": "Structural rupture occurs days later."},
                        },
                        "connections": [
                            "Monitor with telemetry.",
                            "Consider atropine if symptomatic.",
                        ],
                        "glossary": {"Atropine": "Anticholinergic that increases heart rate."},
                        "numerical_ranges": ["Heart rate < 60 bpm"],
                        "references": ["ESC Arrhythmia Guideline 2023"],
                    },
                },
            ],
            "retention_aid": {
                "markdown": "## Inferior STEMI\n- RCA occlusion common\n- Watch for AV block"
            },
        },
    )
    stub_client = StubGenerativeClient([fake_response])
    agent = StudyCardGenerationAgent(
        client=stub_client,
        config=AgentConfiguration(
            default_model="models/gemini-2.5-pro",
            default_temperature=0.35,
            default_card_count=3,
            max_card_count=5,
        ),
    )
    request = StudyCardGenerationRequest(
        topics=["Acute coronary syndrome"],
        target_card_count=1,
        model="models/gemini-2.5-pro-exp",
        temperature=0.5,
    )
    documents = [
        PDFIngestionResult(
            filename="case.pdf",
            text_segments=(
                PDFTextSegment(page_index=1, content="Classic inferior STEMI with hypotension."),
            ),
            images=(PDFImageFragment(page_index=1, mime_type="image/png", data_base64="ZmFrZQ=="),),
            page_count=1,
        )
    ]

    result = await agent.generate(request, documents=documents)

    assert len(result.cards) == 1
    assert result.retention_aid is not None
    assert result.model_used == "models/gemini-2.5-pro-exp"
    assert result.temperature_applied == 0.5
    assert stub_client.calls, "Expected Gemini client to be invoked"
    recorded = stub_client.calls[-1]
    assert recorded.model == "models/gemini-2.5-pro-exp"
    first_message = recorded.messages[0]
    assert any(
        "Acute coronary syndrome" in part.text
        for part in first_message.parts
        if hasattr(part, "text")
    )


async def test_agent_retries_when_response_invalid() -> None:
    good_response = cast(
        JSONObject,
        {
            "cards": [
                {
                    "card_type": CardType.MCQ_SINGLE.value,
                    "difficulty": 2,
                    "payload": {
                        "question": "Name the pathogen causing Lyme disease.",
                        "options": [
                            {"id": "A", "text": "Borrelia burgdorferi"},
                            {"id": "B", "text": "Borrelia recurrentis"},
                        ],
                        "correct_answers": ["A"],
                        "rationale": {
                            "primary": "Lyme disease is caused by the spirochete Borrelia burgdorferi transmitted by Ixodes ticks.",
                            "alternatives": {"B": "Borrelia recurrentis causes relapsing fever."},
                        },
                        "connections": [],
                        "glossary": {"Spirochete": "A spiral-shaped bacterium."},
                        "numerical_ranges": [],
                        "references": [],
                    },
                }
            ],
            "retention_aid": None,
        },
    )
    stub_client = StubGenerativeClient(
        [
            GeminiClientError("invalid JSON"),
            good_response,
        ]
    )
    agent = StudyCardGenerationAgent(
        client=stub_client,
        config=AgentConfiguration(
            default_model="models/gemini-2.5-pro",
            default_temperature=0.2,
            default_card_count=1,
            max_card_count=2,
            max_attempts=3,
        ),
    )
    request = StudyCardGenerationRequest(topics=["Infectious diseases"])
    documents: list[PDFIngestionResult] = []

    result = await agent.generate(request, documents=documents)

    assert len(result.cards) == 1
    assert len(stub_client.calls) == 2
    retry_message = stub_client.calls[-1].messages[-1].parts[0]
    assert hasattr(retry_message, "text") and "could not be processed" in retry_message.text


async def test_agent_requests_additional_cards_until_target_met() -> None:
    partial_response = cast(
        JSONObject,
        {
            "cards": [
                {
                    "card_type": CardType.MCQ_SINGLE.value,
                    "difficulty": 2,
                    "payload": {
                        "question": "Which nerve innervates the diaphragm?",
                        "options": [
                            {"id": "A", "text": "Phrenic nerve"},
                            {"id": "B", "text": "Vagus nerve"},
                        ],
                        "correct_answers": ["A"],
                        "rationale": {
                            "primary": "The phrenic nerve (C3-C5) provides motor supply to the diaphragm.",
                            "alternatives": {
                                "B": "Vagus controls parasympathetics but not diaphragmatic contraction."
                            },
                        },
                        "connections": [],
                        "glossary": {},
                        "numerical_ranges": [],
                        "references": [],
                    },
                }
            ],
            "retention_aid": None,
        },
    )
    final_response = cast(
        JSONObject,
        {
            "cards": [
                {
                    "card_type": CardType.MCQ_SINGLE.value,
                    "difficulty": 3,
                    "payload": {
                        "question": "What is the primary toxin produced by Clostridium botulinum?",
                        "options": [
                            {"id": "A", "text": "Botulinum neurotoxin"},
                            {"id": "B", "text": "Tetanospasmin"},
                        ],
                        "correct_answers": ["A"],
                        "rationale": {
                            "primary": "Botulinum neurotoxin prevents acetylcholine release, leading to flaccid paralysis.",
                            "alternatives": {
                                "B": "Tetanospasmin is produced by C. tetani and causes spastic paralysis."
                            },
                        },
                        "connections": [],
                        "glossary": {},
                        "numerical_ranges": [],
                        "references": [],
                    },
                }
            ],
            "retention_aid": None,
        },
    )
    stub_client = StubGenerativeClient([partial_response, final_response])
    agent = StudyCardGenerationAgent(
        client=stub_client,
        config=AgentConfiguration(
            default_model="models/gemini-2.5-pro",
            default_temperature=0.1,
            default_card_count=2,
            max_card_count=3,
            max_attempts=3,
        ),
    )
    request = StudyCardGenerationRequest(target_card_count=2)

    result = await agent.generate(request, documents=[])

    assert len(result.cards) == 2
    assert len(stub_client.calls) == 2
    second_instruction = stub_client.calls[-1].messages[0].parts[0]
    assert hasattr(second_instruction, "text")
    assert "additional distinct card" in second_instruction.text


async def test_agent_retains_note_cards_from_model() -> None:
    note_response = cast(
        JSONObject,
        {
            "cards": [
                {
                    "card_type": CardType.NOTE.value,
                    "difficulty": 2,
                    "payload": {
                        "question": "Summarise balanced crystalloid priorities.",
                        "options": [],
                        "correct_answers": [],
                        "rationale": {
                            "primary": "## Fluid Strategy\n- Prefer balanced crystalloids\n- Reassess lactate trends",
                            "alternatives": {},
                        },
                        "connections": [],
                        "glossary": {"title": "Fluid Resuscitation Strategy"},
                        "numerical_ranges": [],
                        "references": [],
                    },
                }
            ],
            "retention_aid": None,
        },
    )
    stub_client = StubGenerativeClient([note_response])
    agent = StudyCardGenerationAgent(
        client=stub_client,
        config=AgentConfiguration(
            default_model="models/gemini-2.0-pro",
            default_temperature=0.2,
            default_card_count=2,
            max_card_count=5,
        ),
    )
    request = StudyCardGenerationRequest(target_card_count=1, preferred_card_types=[CardType.NOTE])

    result = await agent.generate(request, documents=[])

    assert len(result.cards) == 1
    assert result.cards[0].card_type == CardType.NOTE


async def test_agent_raises_when_unable_to_reach_target() -> None:
    empty_response = cast(JSONObject, {"cards": [], "retention_aid": None})
    stub_client = StubGenerativeClient([empty_response, empty_response])
    agent = StudyCardGenerationAgent(
        client=stub_client,
        config=AgentConfiguration(
            default_model="models/gemini-2.5-pro",
            default_temperature=0.1,
            default_card_count=2,
            max_card_count=2,
            max_attempts=2,
        ),
    )
    request = StudyCardGenerationRequest(target_card_count=2)

    with pytest.raises(GeminiClientError):
        await agent.generate(request, documents=[])
