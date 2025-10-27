# ZiStudy API

## AI-Assisted Study Card Generation

The API now exposes `/api/v1/ai/study-cards/generate` for orchestrating Gemini-powered card creation.

- **Authentication**: Bearer token or API key required (same as existing endpoints).
- **Request**: `multipart/form-data` with a JSON `payload` (matching `StudyCardGenerationRequest`) and optional `pdfs` uploads.
- **Output**: Structured JSON containing persisted cards, a Markdown retention aid, and generation metadata.
- **Incremental generation**: include `existing_card_ids` in the payload to avoid duplicates and request additional cards that build on previously generated items.

```bash
curl -X POST "https://localhost:8000/api/v1/ai/study-cards/generate" \
  -H "Authorization: Bearer <token>" \
  -F 'payload={"topics":["Sepsis"],"target_card_count":3};type=application/json' \
  -F 'pdfs=@/path/to/notes.pdf;type=application/pdf'
```

Configure the Gemini client via environment variables (prefixed with `ZISTUDY_`):

| Variable | Description |
| --- | --- |
| `ZISTUDY_GEMINI_API_KEY` | Required API key for Gemini access |
| `ZISTUDY_GEMINI_MODEL` | Model identifier (default `models/gemini-2.5-pro`) |
| `ZISTUDY_AI_GENERATION_DEFAULT_TEMPERATURE` | Temperature override |
| `ZISTUDY_AI_GENERATION_MAX_ATTEMPTS` | Max retries when the model fails to produce valid JSON or enough cards |

Run the test suite with:

```bash
uv run zistudy-test
```

Launch the server (local or production) with:

```bash
uv run main.py
```

- `main.py` applies migrations automatically; run the Celery worker in a separate process with `ZISTUDY_PROCESS_TYPE=worker uv run main.py` (or `uv run celery -A zistudy_api.celery_app:celery_app worker --loglevel=INFO`). For quick local hacking you can run both via `ZISTUDY_PROCESS_TYPE=api-with-worker uv run main.py`.
- Docker Compose now includes PostgreSQL, Redis, the API process, and a Celery worker—`docker compose up` will run migrations and start everything for you. Core service URLs (Postgres/Redis) are defined directly in `docker-compose.yml`; additional overrides (for secrets, etc.) can live in `.env`. Containers run with `ZISTUDY_ENVIRONMENT=production` to mirror deployment defaults, while host-based dev can keep `local`.

### Configuration

Provide configuration via environment variables (they are automatically read from `.env` / `.env.local` if present). A typical local setup for running outside Docker:

```bash
cp .env.example .env  # once per machine
export ZISTUDY_DATABASE_URL="sqlite+aiosqlite:///./dev.db"
export ZISTUDY_JWT_SECRET="replace-with-a-strong-secret"
export ZISTUDY_CELERY_BROKER_URL="redis://localhost:6379/0"
export ZISTUDY_CELERY_RESULT_BACKEND="redis://localhost:6379/1"
export ZISTUDY_ENVIRONMENT="local"
# Optional: switch between inline PDF ingestion (`ingest`) and native Gemini PDF understanding (`native`).
export ZISTUDY_GEMINI_PDF_MODE="native"
```

When using Docker Compose these variables are already seeded by the compose file (with optional overrides from `.env`); for other environments ensure they are set before invoking `main.py`.

### Manual AI Smoke Test

To exercise the full Gemini-powered study card pipeline end-to-end, use the helper script (it calls the live API and consumes tokens, so keep it out of CI):

```bash
uv run python scripts/ai_manual_check.py \
  --topics "Sepsis management" \
  --learning-objectives "Stabilise the patient" "Escalate vasopressors" \
  --card-count 2
```

Requirements:

- `ZISTUDY_GEMINI_API_KEY` must be defined (see `.env`).
- The API must be running locally (`uv run main.py` automatically loads `.env`), and Postgres/Redis available (`docker compose up db redis -d` works well).
- The script registers its own throwaway user, triggers `/api/v1/ai/study-cards/generate`, polls `/api/v1/jobs/{id}`, and prints a summary plus sample persisted cards.

Use the script to validate real LLM round-trips. For automated tests, continue mocking Gemini responses to keep the suite fast and deterministic.
