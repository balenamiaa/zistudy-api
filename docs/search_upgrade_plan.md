# Search Upgrade Plan

## Goals
- Replace current SQL `LIKE` filtering with a robust hybrid search stack that offers:
  - Lexical relevance (BM25) with snippet highlighting.
  - Semantic similarity results via vector embeddings.
  - Faceting / sorting metadata surfaced in API responses.
  - Self-hosted deployment without multi-node cluster requirements.

## Recommended Architecture
- **Lexical engine**: Tantivy (Rust) via a lightweight service (e.g. Toshi or custom wrapper) for BM25 + highlight generation.
- **Vector engine**: Qdrant single-node for ANN similarity search with payload filters.
- **Hybrid orchestration**: FastAPI endpoint performs dual retrieval (lexical + vector), merges scores (Reciprocal Rank Fusion), returns highlights and semantic scores.
- **Embeddings**: Precompute with `intfloat/e5-large-v2` (or `all-MiniLM-L6-v2` for lighter footprint) using `sentence-transformers`.
- **Ingestion**: Background worker syncs Postgres → Tantivy/Qdrant via bulk upserts (Celery/ Dramatiq). Store metadata (tags, difficulty) as payloads for faceting in Qdrant.

## Implementation Steps
1. **Index Schema**
   - Tantivy: fields (`id`, `title`, `content`, `tags`, `difficulty`, analyzers + stored fields for highlighting).
   - Qdrant: collection with vector size matching embedding model; payload fields for `tags`, `difficulty`, `study_set_ids`.

2. **Data Pipeline**
   - Command or background task to full-reindex existing cards.
   - Event-driven (DB triggers or change queue) to upsert updates.
   - Ensure deletions cascade to both indexes.

3. **Search Endpoint**
   - Request model includes filters (tags, difficulty, study set), sort preferences, toggle for semantic weighting.
   - Execute lexical search (with highlight request) and vector search (top-k).
   - Merge results via RRF or weighted normalized scores.
   - Return JSON with `items`, `total`, `facets` (tag counts/difficulty buckets), `highlights`, `semantic_score`.

4. **Faceting & Sorting**
   - Use Tantivy’s term aggregations for tags/difficulty (or maintain precomputed counts in Postgres).
   - Support sort modes: relevance (hybrid), newest, hardest (difficulty desc).

5. **Benchmarking & Tuning**
   - Measure latency under expected load; tune Tantivy index (doc store, segment merging) and Qdrant HNSW params (`ef_search`, `ef_construct`).
   - Add telemetry (timings, recall) to adjust fusion weights.

6. **Operations**
   - Package Tantivy + Qdrant as services in docker-compose.
   - Provide CLI management commands (`rebuild-index`, `dump-index`, `verify-sync`).
   - Monitoring endpoints (health, queue depth, index stats).

## Deliverables
- New search service modules (`search/indexer.py`, `search/service.py`).
- Updated FastAPI routes (`/search`, `/search/facets`, `/search/debug`).
- Background worker for reindexing.
- Documentation for deployment & ops.
