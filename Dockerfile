FROM python:3.14-rc-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends build-essential libpq-dev && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock*? /app/

COPY README.md /app/README.md
COPY src /app/src
COPY main.py /app/main.py
COPY alembic /app/alembic
COPY alembic.ini /app/alembic.ini

RUN pip install --no-cache-dir uv && \
    uv pip install --system --no-cache .[dev]

EXPOSE 8000

CMD ["python", "main.py"]
