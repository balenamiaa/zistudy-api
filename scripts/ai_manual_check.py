from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

import fitz  # type: ignore[import-untyped]
import httpx

from zistudy_api.config.settings import get_settings


def _create_pdf_bytes(text: str) -> bytes:
    document = fitz.open()
    try:
        page = document.new_page(width=595, height=842)  # A4
        page.insert_textbox(
            fitz.Rect(40, 40, 555, 800),
            text,
            fontsize=11,
            fontname="helv",
        )
        return bytes(document.tobytes())
    finally:
        document.close()


async def _register_and_login(
    client: httpx.AsyncClient,
    email: str,
    password: str,
) -> str:
    register_payload = {
        "email": email,
        "password": password,
        "full_name": "AI Manual Tester",
    }
    response = await client.post("/api/v1/auth/register", json=register_payload)
    if response.status_code not in (201, 409):
        raise RuntimeError(f"Failed to register: {response.status_code} {response.text}")

    login_payload = {"email": email, "password": password}
    login_response = await client.post("/api/v1/auth/login", json=login_payload)
    login_response.raise_for_status()
    token = login_response.json()["access_token"]
    return token


async def _trigger_generation(
    client: httpx.AsyncClient,
    token: str,
    payload: dict[str, Any],
    pdf_bytes: bytes | None,
) -> tuple[int, dict[str, Any]]:
    files: list[tuple[str, tuple[str | None, bytes | str, str | None]]] = [
        ("payload", (None, json.dumps(payload), "application/json")),
    ]
    if pdf_bytes:
        files.append(("pdfs", ("context.pdf", pdf_bytes, "application/pdf")))

    response = await client.post(
        "/api/v1/ai/study-cards/generate",
        headers={"Authorization": f"Bearer {token}"},
        files=files,
    )
    response.raise_for_status()
    job_summary = response.json()
    return job_summary["id"], job_summary


async def _poll_job(
    client: httpx.AsyncClient,
    token: str,
    job_id: int,
    timeout: float,
    interval: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    headers = {"Authorization": f"Bearer {token}"}
    last_status: str | None = None
    while True:
        response = await client.get(f"/api/v1/jobs/{job_id}", headers=headers)
        response.raise_for_status()
        payload = response.json()
        status = payload.get("status")
        if status != last_status:
            print(f"[ai-smoke] Job {job_id} status -> {status}")
            last_status = status
        if status in {"completed", "failed"}:
            return payload
        if time.monotonic() >= deadline:
            raise TimeoutError(
                f"Job {job_id} did not complete within {timeout} seconds. "
                f"Last payload: {json.dumps(payload, indent=2)}"
            )
        await asyncio.sleep(interval)


async def _fetch_generated_cards(
    client: httpx.AsyncClient,
    token: str,
    limit: int,
) -> list[dict[str, Any]]:
    headers = {"Authorization": f"Bearer {token}"}
    response = await client.get("/api/v1/study-cards", headers=headers, params={"page_size": limit})
    response.raise_for_status()
    body = response.json()
    return body.get("items", [])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Manual smoke-test the AI study card generation workflow."
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("ZISTUDY_API_BASE_URL", "http://localhost:8000"),
        help="FastAPI base URL (default: %(default)s)",
    )
    parser.add_argument(
        "--email",
        help="Email to reuse. Defaults to a generated value per run.",
    )
    parser.add_argument(
        "--password",
        default="Secret123!",
        help="Password to use when registering/logging in (default: %(default)s)",
    )
    parser.add_argument(
        "--topics",
        nargs="*",
        default=["Clinical reasoning"],
        help="Topics to include in the generation request.",
    )
    parser.add_argument(
        "--learning-objectives",
        nargs="*",
        default=["Differentiate shock states", "Prioritise stabilisation steps"],
        help="Learning objectives supplied to the AI.",
    )
    parser.add_argument(
        "--card-count",
        type=int,
        default=2,
        help="Target number of cards to request (default: %(default)s).",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.2,
        help="Temperature override for the generation request.",
    )
    parser.add_argument(
        "--context-text",
        default=(
            "Patient presents with septic shock. Discuss initial resuscitation priorities, "
            "antibiotic timing, and markers for escalation."
        ),
        help="Optional text that will be embedded into a PDF and uploaded as context.",
    )
    parser.add_argument(
        "--pdf-path",
        type=Path,
        help="Use an existing PDF as context instead of generating one from --context-text.",
    )
    parser.add_argument(
        "--job-timeout",
        type=float,
        default=120.0,
        help="Maximum seconds to wait for the job to complete (default: %(default)s).",
    )
    parser.add_argument(
        "--job-interval",
        type=float,
        default=5.0,
        help="Polling interval in seconds while waiting for the job (default: %(default)s).",
    )
    parser.add_argument(
        "--summary-limit",
        type=int,
        default=5,
        help="Number of newly created cards to display at the end (default: %(default)s).",
    )
    return parser


async def main_async(args: argparse.Namespace) -> None:
    settings = get_settings()
    if not settings.gemini_api_key:
        raise SystemExit(
            "ZISTUDY_GEMINI_API_KEY is not set. Add it to your environment (see .env)."
        )

    base_url = args.base_url.rstrip("/")
    email = args.email or f"ai-smoke-{uuid.uuid4().hex[:8]}@example.com"

    async with httpx.AsyncClient(base_url=base_url, timeout=httpx.Timeout(60.0)) as client:
        token = await _register_and_login(client, email=email, password=args.password)
        print(f"[ai-smoke] Authenticated as {email}")

        if args.pdf_path:
            pdf_bytes = args.pdf_path.read_bytes()
            print(f"[ai-smoke] Using supplied PDF: {args.pdf_path}")
        else:
            pdf_bytes = _create_pdf_bytes(args.context_text)
            print("[ai-smoke] Generated inline PDF context from --context-text.")

        payload = {
            "topics": args.topics,
            "learning_objectives": args.learning_objectives,
            "target_card_count": args.card_count,
            "temperature": args.temperature,
            "include_retention_aid": True,
        }

        job_id, job_summary = await _trigger_generation(client, token, payload, pdf_bytes)
        print(f"[ai-smoke] Job {job_id} enqueued (status={job_summary['status']}).")

        job_result = await _poll_job(
            client,
            token,
            job_id=job_id,
            timeout=args.job_timeout,
            interval=args.job_interval,
        )
        status = job_result["status"]
        print(f"[ai-smoke] Job {job_id} finished with status: {status}")
        if status == "failed":
            raise SystemExit(f"Job failed: {job_result.get('error')}")

        result_body = job_result["result"]
        summary = result_body["summary"]
        print(
            "[ai-smoke] Generated summary:",
            json.dumps(summary, indent=2),
        )
        if result_body.get("retention_aid"):
            print("[ai-smoke] Retention aid markdown preview:")
            print(result_body["retention_aid"]["markdown"][:600], "...\n")

        cards = await _fetch_generated_cards(client, token, args.summary_limit)
        print(f"[ai-smoke] Retrieved {len(cards)} persisted card(s). Sample:")
        for card in cards[: args.summary_limit]:
            payload = card["data"].get("payload", {})
            question = payload.get("question") or payload.get("prompt")
            print(f"  - [{card['card_type']}] Q: {question!r}")

        print("[ai-smoke] Done.")


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        asyncio.run(main_async(args))
    except KeyboardInterrupt:
        raise SystemExit("Aborted by user.") from None


if __name__ == "__main__":
    main()
