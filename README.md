# ZiStudy API

ZiStudy is a FastAPI-powered backend for managing study cards, study sets, answers, tags, and background jobs. It is designed for dependable day-to-day use while embracing AI-assisted study card generation as a first-class workflow.

---

## What the API provides

- **Typed study cards & sets** – CRUD endpoints with ownership and visibility rules.
- **Learner answers & progress** – record attempts, compute accuracy, and summarise per-set progress.
- **Background jobs** – queue clone/export tasks (Celery + Redis) and poll `/api/v1/jobs/{id}` for status.
- **Tag catalogue** – create, search, and attach tags to study sets.
- **AI generation** – submit PDFs + JSON payloads to offload card authoring to Gemini while automatically curating structured cards.

---

## Quick start

1. **Install prerequisites**
   - Python 3.12+ and [uv](https://docs.astral.sh/uv/) (recommended)
   - Redis (for background jobs) and PostgreSQL or any SQLAlchemy-compatible database

2. **Clone + install**
   ```bash
   git clone https://github.com/<you>/zistudy-api.git
   cd zistudy-api
   uv sync
   ```

3. **Create an environment file**
   ```bash
   cp .env.example .env

   # Minimal local overrides
   echo 'ZISTUDY_DATABASE_URL=sqlite+aiosqlite:///./dev.db' >> .env
   echo 'ZISTUDY_JWT_SECRET=replace-with-a-strong-secret' >> .env
   ```

4. **Start PostgreSQL & Redis (examples)**
   ```bash
   docker compose up db redis -d
   ```
   or install them locally and point the connection strings at your instances.

5. **Run database migrations**
   ```bash
   uv run alembic upgrade head
   ```

6. **Start the API**
   ```bash
   uv run main.py
   ```
   The server runs on `http://127.0.0.1:8000`. To run the worker alongside the API in the same process, set `ZISTUDY_PROCESS_TYPE=api-with-worker`. Otherwise keep the default (`api`) and start a dedicated Celery worker:
   ```bash
   uv run celery -A zistudy_api.celery_app:celery_app worker --loglevel=INFO
   ```

---

## Configuration reference

All settings are read from environment variables (prefixed with `ZISTUDY_`). Values in `.env` / `.env.local` are loaded automatically.

| Variable | Purpose | Default |
| --- | --- | --- |
| `DATABASE_URL` | SQLAlchemy connection string | *required* |
| `JWT_SECRET` | Secret used to sign access tokens | *required* |
| `ENVIRONMENT` | `local`, `test`, or `production` (affects CORS) | `local` |
| `CORS_ORIGINS` | JSON array of allowed origins | `["http://localhost", "http://localhost:3000", …]` |
| `AI_PDF_MAX_BYTES` | Max PDF size accepted by AI endpoint (bytes) | `150 * 1024 * 1024` |
| `CELERY_BROKER_URL` | Celery broker | `redis://localhost:6379/0` |
| `CELERY_RESULT_BACKEND` | Celery result backend | `redis://localhost:6379/1` |
| `PROCESS_TYPE` | `api`, `worker`, or `api-with-worker` | `api` |
| `GEMINI_API_KEY` | Required for AI card generation | `None` |
| `GEMINI_MODEL` | Gemini model identifier | `gemini-2.5-pro` |
| `GEMINI_PDF_MODE` | `native` or `ingest` | `native` |

> **Production**
>
> Setting `ENVIRONMENT=production` enforces a non-wildcard CORS list. Add approved origins via `CORS_ORIGINS='["https://app.example.com"]'`.

---

## Running tests & tooling

```bash
uv run coverage run -m pytest      # tests with coverage
uv run coverage report             # text summary
uv run coverage xml                # generate coverage.xml
uv run ruff check                  # linting
uv run ruff format                 # formatting
uv run mypy src tests              # static type checks
```

For convenience you can also run `uv run zistudy-test`, which executes the project’s default test script.

---

## API highlights

- **Authentication**
  - Username/password (JWT access + refresh tokens)
  - API keys (single reveal, hashed at rest)
  - Both mechanisms use the same `Authorization: Bearer` header

- **Study cards**
  - `POST /api/v1/study-cards` creates a card owned by the caller
  - `GET /api/v1/study-cards?card_type=mcq_single&page=1&page_size=20`
    honours privacy: system cards are public; user cards are private
  - `POST /api/v1/study-cards/search` filters + paginates typed results

- **Study sets**
  - Ownership determines whether a user can modify, delete, or add cards
  - `GET /api/v1/study-sets/{id}/can-access` returns `{can_access, can_modify}`
  - `POST /api/v1/study-sets/bulk-add` and `/bulk-delete` provide batch operations with per-item error detail

- **Answers**
  - Users can submit multiple attempts per card; history, stats, and per-set progress endpoints summarise usage

- **Tags**
  - `POST /api/v1/tags` authenticated creation
  - `GET /api/v1/tags/search?query=cardio` for quick lookup

- **Jobs**
  - Clone/export study sets using `POST /api/v1/study-sets/clone` or `/export`
  - Poll job status at `GET /api/v1/jobs/{job_id}`

---

## AI-assisted card generation

This is the primary path for authoring fresh study material. Clients generate new study cards via:

```
POST /api/v1/ai/study-cards/generate
```

with `multipart/form-data` containing:

- `payload`: JSON matching `StudyCardGenerationRequest`
- `pdfs`: up to the configured size limit (`ai_pdf_max_bytes`)

The server enqueues a job that:
1. Pipes the request through Gemini with the supplied context
2. Persists clean, typed study cards (plus an optional retention note)
3. Returns job status and results via `/api/v1/jobs/{id}`

To quickly smoke-test the pipeline end-to-end:

```bash
uv run python scripts/ai_manual_check.py \
  --card-count 2
```

> Provide `ZISTUDY_GEMINI_API_KEY` and keep the API running locally. The script consumes tokens and should only be used for manual validation. By default it asks Gemini for “Clinical reasoning” cards; supply `--topics` or `--learning-objectives` with one or more phrases (e.g., `--topics "Septic shock management" --learning-objectives "Escalate vasopressors"`) when you need a narrower focus.

---

## Docker Compose option

The repository ships with a Compose stack that provisions PostgreSQL, Redis, the API, and a worker:

```bash
docker compose up --build
```

Compose injects sensible defaults for production-like settings; override values in `.env` as needed. The API becomes available on port `8000`.

---

## Contributing

1. Fork and create a feature branch.
2. Keep coverage above 90% (`uv run coverage report`).
3. Submit a PR describing the change and relevant tests.

Issues and pull requests are welcome—especially around performance, security, and developer ergonomics.

---

Happy learning! If you run into trouble or have ideas, open an issue or start a discussion.♪
