# Tender Agent

Document ingestion + retrieval intelligence for tender documents. Queue-driven LangGraph workers that turn tender PDFs/DOCX/XLSX into a hybrid-searchable knowledge base, then answer tender questions through specialized agents over that base.

<p align="left">
  <img src="https://skillicons.dev/icons?i=python,postgres,rabbitmq,docker,githubactions,git&perline=8" alt="Python, PostgreSQL, RabbitMQ, Qdrant, Docker, GitHub Actions" />
</p>

<p align="left">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white" />
  <img alt="LangGraph" src="https://img.shields.io/badge/LangGraph-1.2-1C3C3C" />
  <img alt="Qdrant" src="https://img.shields.io/badge/Qdrant-hybrid%20search-DC244C" />
  <img alt="OpenAI" src="https://img.shields.io/badge/OpenAI-embeddings%20%2B%20gpt--4o--mini-412991?logo=openai&logoColor=white" />
  <img alt="Docling" src="https://img.shields.io/badge/Docling-OCR%20%2F%20parse-0B7285" />
  <img alt="uv" src="https://img.shields.io/badge/uv-package%20manager-DE5FE9" />
</p>

---

## 📚 Table of Contents

- [What this project does](#-what-this-project-does)
- [Architecture](#-architecture)
- [Tech stack](#-tech-stack)
- [Repository layout](#-repository-layout)
- [Pipeline 1 — Ingestion](#-pipeline-1--ingestion)
- [Pipeline 2 — Intelligence](#-pipeline-2--intelligence)
- [Orchestrator (designed, not yet implemented)](#-orchestrator-designed-not-yet-implemented)
- [Data model](#-data-model)
- [Vector store layout](#-vector-store-layout)
- [Message contracts](#-message-contracts)
- [Configuration](#-configuration)
- [Getting started](#-getting-started)
- [Deployment](#-deployment)
- [Current status](#-current-status)

---

## 🎯 What this project does

Two independent RabbitMQ workers, one shared codebase and Docker image.

| Worker | Queue | Job | Entry point |
|---|---|---|---|
| **Ingestion** | `agent:ingestion` | Download → parse → chunk → embed → index → persist | `worker/ingestion_worker.py` |
| **Intelligence** | `agent:intelligence` | Plan searches → hybrid retrieve → rerank → structured answer | `worker/intelligence_worker.py` |

Ingestion builds the knowledge base offline. Intelligence answers questions against it, filtered by tender `reference_no`.

---

## 🏗 Architecture

### Overall flow

![Overall flow: user query → orchestrator → specialized agents → shared search sub-agent → Qdrant → structured result → webhook](docs/Overall%20Flow.png)

The knowledge base (left, pink) is prepared offline by the ingestion worker: documents are chunked, embedded, and stored in Qdrant as dense + sparse vectors. At query time the orchestrator plans which specialized agents to run; each agent generates its own `(query, keywords)` pairs and delegates retrieval to one shared Search Sub-Agent.

### Orchestrator node workflow

![Orchestrator node-level LangGraph workflow: analyze request → create checklist → select next task → call sub-agent → process result → more tasks? → synthesize → send to target](docs/Orchestrator%20Agent.png)

Full node-by-node spec, state schema, prompts and I/O examples: [`docs/Orchestrator Agent — LangGraph Implementation Specification.md`](docs/Orchestrator%20Agent%20%E2%80%94%20LangGraph%20Implementation%20Specification.md).

### Layer responsibilities

```
ORCHESTRATOR        decides WHAT work needs doing, tracks the checklist
      ↓
SPECIALIZED AGENT   decides HOW to research one domain (documents, eligibility, …)
      ↓
SEARCH SUB-AGENT    performs retrieval (hybrid search + cross-encoder rerank)
      ↓
QDRANT              stores/serves the indexed chunks
```

---

## 🧰 Tech stack

<img src="https://skillicons.dev/icons?i=python,docker,postgres,rabbitmq,githubactions,git&perline=6" alt="stack" />

| Layer | Choice | Notes |
|---|---|---|
| Language | Python 3.12 (`>=3.12,<3.13`) | pinned via `.python-version` |
| Packaging | `uv` | `uv.lock` committed, `package = false` |
| Orchestration | LangGraph 1.2 | one `StateGraph` per pipeline, `TypedDict` state |
| Checkpointing | `langgraph-checkpoint-postgres` | ingestion only, optional — falls back to no checkpointer |
| Queue | RabbitMQ via `pika` | durable queues, `prefetch_count=1`, manual ack/nack |
| Relational store | PostgreSQL via SQLModel + psycopg3 | Alembic migrations in `alembic/versions/` |
| Vector store | Qdrant | named vectors: `dense` (OpenAI) + `sparse` (BM25) |
| Parsing | Docling, pypdf, openpyxl | per-page markdown, tables preserved as pipe tables |
| Embeddings | `text-embedding-3-small` (1536d) + FastEmbed `Qdrant/bm25` | dense-only fallback if FastEmbed missing |
| Reranking | `sentence-transformers` CrossEncoder `ms-marco-MiniLM-L-6-v2` | CPU by default, env-configurable |
| LLM | `gpt-4o-mini` via `langchain-openai` | structured output via Pydantic |
| Observability | Langfuse | dependency present, **disabled by default** (`LANGFUSE_ENABLED`) |
| CI/CD | GitHub Actions → GHCR → self-hosted runner | `.github/workflows/deploy.yml` |

---

## 📁 Repository layout

```
tender-agent/
├── core/config.py              # pydantic-settings Settings, single source of env truth
├── database/
│   ├── models.py               # SQLModel tables: users, documents, document_pages
│   └── connection.py           # engine, session helpers, health check
├── vector/qdrant.py            # client + ensure_collection (schema migrate, payload indexes)
├── ingestion/
│   ├── graph.py                # ingestion StateGraph
│   ├── state.py                # IngestionState
│   └── nodes/                  # initialize → download → parse_* → chunk/persist → cleanup
├── intelligence/
│   ├── graph.py                # intelligence StateGraph
│   ├── state.py                # IntelligenceState
│   ├── prompts.py              # search-plan system prompt
│   ├── nodes/                  # generate_search_plan, execute_search
│   └── subagents/search/       # shared Search Sub-Agent (hybrid_search → rerank)
├── worker/
│   ├── job.py                  # IngestionJob / IntelligenceJob payload validation
│   ├── ingestion_worker.py     # agent:ingestion consumer
│   └── intelligence_worker.py  # agent:intelligence consumer
├── scripts/
│   ├── publish_job.py          # publish a test ingestion job
│   └── view_graph.py           # print mermaid for intelligence + search graphs
├── alembic/                    # migrations
├── docs/                       # architecture diagrams + orchestrator spec
├── compose.yml                 # two services off one image
└── Dockerfile                  # uv multi-stage build
```

---

## 📥 Pipeline 1 — Ingestion

`worker/ingestion_worker.py` → `ingestion/graph.py`

```mermaid
flowchart TD
    START([START]) --> INIT[initialize_document]
    INIT --> DL[download_document]
    DL -->|route_by_ext| PDF[parse_pdf]
    DL --> DOCX[parse_docx]
    DL --> XLSX[parse_xlsx]
    DL --> TXT[parse_txt]
    PDF --> CHUNK[chunk_embed_push]
    PDF --> PERSIST[persist_document]
    DOCX --> CHUNK
    DOCX --> PERSIST
    XLSX --> CHUNK
    XLSX --> PERSIST
    TXT --> CHUNK
    TXT --> PERSIST
    CHUNK --> CLEAN[cleanup]
    PERSIST --> CLEAN
    CLEAN --> END([END])
```

**Node by node**

| Node | Does |
|---|---|
| `initialize_document` | Validates `job_id`/`file_url`/`reference_no`, mints `document_id` (uuid4), creates `TEMP_DIR/job_id/document_id/` |
| `download_document` | Google Drive (OAuth refresh-token, no key file, exports Google-native docs to PDF/XLSX/PPTX) or plain HTTPS streaming download; filename from `Content-Disposition` |
| `route_by_ext` | Conditional edge on file suffix → `.txt` / `.xlsx .xls .csv` / `.docx .doc` / everything else → PDF branch |
| `parse_pdf` / `parse_docx` / `parse_xlsx` / `parse_txt` | Docling convert (singleton converter), per-page markdown via `export_to_markdown(page_no=i)`, caches `doc.json` in the working dir. Page-level failures are preserved, not fatal — status becomes `partial` |
| `chunk_embed_push` | Table-aware chunking (pipe tables stay intact, header repeated when a table exceeds `CHUNK_SIZE`; prose goes through `RecursiveCharacterTextSplitter`), OpenAI dense embeddings in batches with 3-attempt backoff, BM25 sparse via FastEmbed, upsert to Qdrant in batches of 128. Chunk IDs are `uuid5(document_id:page_no:chunk_idx)` — re-ingest overwrites instead of duplicating |
| `persist_document` | Idempotent upsert of `documents` + delete/reinsert of `document_pages`. Runs in parallel with `chunk_embed_push` |
| `cleanup` | Unlinks the downloaded file and `doc.json`, guarded to stay inside `TEMP_DIR`; removes the working dir only if empty |

**Failure handling.** A failed graph run nacks the message with `requeue=False` (no infinite redelivery). `prefetch_count=1` keeps one document per worker in flight. RabbitMQ heartbeat is forced to 600s so long Docling conversions don't drop the connection.

**Checkpointing.** `PostgresSaver.from_conn_string(...)` with `thread_id = "{job_id}:{external_document_id or file_url}"` — one thread per file, no cross-file collision. If Postgres or the library is unavailable the worker logs a warning and runs without checkpoints.

---

## 🔎 Pipeline 2 — Intelligence

`intelligence/graph.py` + the shared Search Sub-Agent.

```mermaid
flowchart LR
    subgraph Intelligence
        A([START]) --> B[generate_search_plan]
        B --> C[execute_search]
        C --> Z([END])
    end
    subgraph Search Sub-Agent
        D([START]) --> E[hybrid_search]
        E --> F[rerank]
        F --> G([END])
    end
    C -.invoke per plan item.-> D
```

| Node | Does |
|---|---|
| `generate_search_plan` | `gpt-4o-mini` with Pydantic structured output → 5–10 items of `{query, keyword[]}` covering EMD, eligibility, scope, deadlines, fees, technical specs, payment terms |
| `execute_search` | Sequential loop; invokes the Search Sub-Agent once per plan item with the tender `reference_no` as filter |
| `hybrid_search` | Dense query embedding + BM25 sparse over `query + keywords`; Qdrant `query_points` with dual `Prefetch` (dense + sparse), filtered on `reference_no`, top 20. Falls back to dense-only if sparse is unavailable |
| `rerank` | CrossEncoder scores all hits in one batched `predict`; keeps score `> 0`, top 5. Weak-relevance fallback takes top 3 if nothing clears the threshold; on model failure falls back to Qdrant scores |

Print the live mermaid for both graphs:

```bash
uv run python scripts/view_graph.py
```

---

## 🧠 Orchestrator (designed, not yet implemented)

The spec in `docs/` defines the layer above intelligence. Checklist-driven loop, no RAG of its own:

```mermaid
flowchart TD
    S([START]) --> A[1. Analyze Request — LLM]
    A --> B[2. Create Checklist — LLM]
    B --> C[3. Select Next Task — logic]
    C --> D[4. Call Sub-Agent — subgraph]
    D --> E[5. Process Result — validation]
    E --> F{6. More tasks?}
    F -->|yes| C
    F -->|no| G[7. Synthesize — LLM]
    G --> H[8. Send to Target — webhook]
    H --> Z([END])
```

State: `user_query`, `reference_number`, `parsed_request`, `checklist`, `current_task`, `agent_results`, `errors`, `final_response`. Checklist item statuses: `pending | running | success | failed | skipped`.

Planned specialized agents — `document_finder`, `reverse_auction`, `eligibility`, `important_dates`, `financial_terms` — each a subgraph that generates its own `(query, keywords)` pairs and calls the **existing** Search Sub-Agent. Every agent returns the same envelope (`task_id`, `agent`, `status`, `result`, `sources`, `error`) so the orchestrator never changes when an agent is added.

Design rule from the spec: the final synthesis LLM sees structured agent results only, never the raw Qdrant context again.

---

## 🗄 Data model

`database/models.py`, migrations under `alembic/versions/`.

**`documents`** — one row per ingested file, unique on `document_id`.

`document_id` (uuid) · `external_document_id` · `job_id` · `reference_no` · `document_tag` · `document_name` · `original_url` · `file_url` · `file_path` · `status` · `error` · `total_pages` · `chunk_count` · timestamps

**`document_pages`** — one row per page, FK → `documents.document_id`.

`page_no` · `total_pages` · `markdown` · `text` · `status` · `error` · plus denormalized `reference_no` / `document_tag` / `job_id` for direct filtering

**`users`** — email/name/hashed_password/is_active. Present from the initial schema; not used by the workers.

---

## 🧭 Vector store layout

Collection: `QDRANT_COLLECTION` (default `tender_chunks`).

```
vectors:        { "dense": VectorParams(size=1536, distance=COSINE) }
sparse_vectors: { "sparse": SparseVectorParams() }   # BM25
point id:       uuid5(document_id:page_no:chunk_idx)
```

`ensure_collection()` is idempotent and self-migrating: it recreates the collection if it finds the legacy unnamed-vector schema or a dimension mismatch (**this drops existing points — reindex after an embedding-model change**), and creates keyword/integer payload indexes on every filterable field.

Payload carries **both** snake_case and camelCase keys (`reference_no` *and* `referenceNo`, `page_no` *and* `pageNo`, …) so upstream services can filter with either convention. `null` values are stripped before upsert.

Payload fields: `text`, `page_no`, `chunk_idx`, `chunk_count`, `document_id`, `job_id`, `reference_no`, `document_tag` (also exposed as `document_type`), `document_name`, `original_url`, `total_pages`.

---

## 📨 Message contracts

Validation lives in `worker/job.py`. Field aliases accept snake_case and camelCase.

**`agent:ingestion`**

```json
{
  "jobId": "9f4c...",
  "referenceNo": "T123",
  "files": [
    {
      "fileName": "tender-notice.pdf",
      "fileType": "pdf",
      "fileUrl": "https://drive.google.com/file/d/<id>/view",
      "fileTag": "notice",
      "documentId": 4821
    }
  ]
}
```

`fileUrl` must start with `http://` or `https://`. `files` must be non-empty; each file becomes its own graph invocation.

**`agent:intelligence`**

```json
{ "referenceNo": "T123" }
```

Invalid payloads are nacked with `requeue=False` and logged with the full Pydantic error list.

---

## ⚙️ Configuration

Copy `.env.example` → `.env`. All settings resolve through `core/config.py` (`pydantic-settings`, case-insensitive, unknown keys ignored).

| Variable | Required | Default | Purpose |
|---|:---:|---|---|
| `DATABASE_URL` | ✅ | — | Postgres DSN. `postgres://` and `postgresql://` are auto-normalized to `postgresql+psycopg://` |
| `DB_ECHO` | | `false` | SQLAlchemy statement logging |
| `QDRANT_URL` | ✅ | — | Qdrant endpoint |
| `QDRANT_API_KEY` | ✅ | — | Rejected if blank |
| `RABBITMQ_URL` | ✅ | — | AMQP URL; heartbeat params appended automatically |
| `TEMP_DIR` | ✅ | — | Working directory for downloads/parsing; cleanup is confined to this path |
| `OPENAI_API_KEY` | ✅ | — | Embeddings + LLM. Ingestion fails fast without it |
| `EMBEDDING_MODEL` | | `text-embedding-3-small` | `text-embedding-3-large` → 3072 dims (forces collection recreate) |
| `EMBEDDING_BATCH_SIZE` | | `100` | Texts per embedding request |
| `QDRANT_COLLECTION` | | `tender_chunks` | Collection name |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | | `1000` / `200` | Splitter config |
| `RERANK_MODEL` | | `cross-encoder/ms-marco-MiniLM-L-6-v2` | CrossEncoder model |
| `RERANK_DEVICE` | | `cpu` | Set `cuda` where a GPU exists |
| `LANGFUSE_ENABLED` | | `false` | Tracing off by default; `LANGFUSE_PUBLIC_KEY` / `SECRET_KEY` / `HOST` when enabled |
| `GOOGLE_OAUTH_CLIENT_ID` | Drive only | — | Desktop OAuth client |
| `GOOGLE_OAUTH_CLIENT_SECRET` | Drive only | — | |
| `GOOGLE_OAUTH_REFRESH_TOKEN` | Drive only | — | Generate offline with scope `https://www.googleapis.com/auth/drive.readonly` |
| `GOOGLE_OAUTH_TOKEN_URI` | | `https://oauth2.googleapis.com/token` | |

> Google Drive **folder** links are rejected — pass file links. Files must be shared with the OAuth account.

---

## 🚀 Getting started

### Prerequisites

Python 3.12, [uv](https://docs.astral.sh/uv/), and reachable PostgreSQL, RabbitMQ and Qdrant instances.

### Install

```bash
uv sync
cp .env.example .env      # then fill in real values
```

### Migrate

```bash
uv run alembic upgrade head
```

### Run the workers

```bash
uv run python -m worker.ingestion_worker      # consumes agent:ingestion
uv run python -m worker.intelligence_worker   # consumes agent:intelligence
```

Both declare their queue durably on startup, so order does not matter.

### Publish a test job

```bash
uv run python scripts/publish_job.py "https://example.com/tender.pdf" \
  --reference-no T123 --tag notice --name "Tender Notice"
```

> ⚠️ `scripts/publish_job.py` still builds the pre-multi-file `IngestionJob` (flat `file_url`) and will fail validation against the current `files: [...]` schema. Publish the JSON above directly to `agent:ingestion` until the script is updated.

### Inspect the graphs

```bash
uv run python scripts/view_graph.py
```

---

## 📦 Deployment

Single image, two services (`compose.yml`):

```bash
docker compose pull ingestion-agent intelligence-agent
docker compose up -d
```

Both services read `.env.production` and join the external `infra` network. Postgres, Qdrant and RabbitMQ are external — no `depends_on`.

CI (`.github/workflows/deploy.yml`) on push to `main`:

1. Build the multi-stage `uv` image with GitHub Actions cache.
2. Push to `ghcr.io/<owner>/tender-agent` tagged `latest` and the short SHA.
3. On the self-hosted Windows runner: sync `compose.yml` to `D:/tender-agent/`, `docker compose pull` + `up -d`, then prune all but the two most recent images.

The runtime image installs `libgl1`, `libglib2.0-0`, `libsm6`, `libxext6`, `libxrender1`, `libgomp1` for Docling/OpenCV.

---

## ✅ Current status

| Area | State |
|---|---|
| Ingestion pipeline | ✅ Complete end to end — download, parse, chunk, embed, index, persist, cleanup |
| Search Sub-Agent | ✅ Hybrid search + cross-encoder rerank, `reference_no` filtering |
| Intelligence graph | ✅ Plan → search wired; results are printed to stdout, no sink yet |
| Intelligence worker | ⚠️ **Stub** — validates the payload and acks; does not invoke `build_intelligence_graph()` yet |
| Specialized agents | ⛔ Not implemented (`document_finder`, `reverse_auction`, `eligibility`, `important_dates`, `financial_terms`) |
| Orchestrator | ⛔ Specified in `docs/`, no code yet |
| Webhook / target delivery | ⛔ Not implemented |
| Langfuse tracing | ⚠️ Wired into `download_document` only, disabled by default |

**Next steps, in dependency order:** wire the intelligence graph into its worker → build one specialized agent as a subgraph over the existing Search Sub-Agent → add the orchestrator checklist loop → add the webhook node.
