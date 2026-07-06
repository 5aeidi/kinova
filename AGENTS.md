# Kinova — Agent Guide

This file is a single source of truth for AI coding agents working on **Kinova**.
Kinova is a small, production-oriented FastAPI application that wraps the public
[Kinoheld](https://www.kinoheld.de/) GraphQL API and exposes a typed REST API on
top of it.

Everything below is derived from the actual project files (configuration, source
code, tests, and CI). Do not assume conventions that are not explicitly
documented here.

---

## Project overview

- **Name:** `kinova`
- **Version:** `0.1.0`
- **License:** MIT
- **Python:** `>=3.10`
- **Entry point:** `app.main:app`
- **API prefix:** `/api/v1`

The application translates REST requests into Kinoheld GraphQL queries, validates
responses with Pydantic v2, and returns clean JSON. It also includes an optional
LLM-powered natural-language search endpoint, an in-memory cache with a
background refresh task, and a set of cache-backed "internal" endpoints.

---

## Technology stack

| Layer | Tech |
|-------|------|
| Web framework | FastAPI |
| Server | Uvicorn (standard extras) |
| HTTP client | `httpx` (async, with connection pooling) |
| Validation / settings | Pydantic v2 + `pydantic-settings` |
| LLM client | `openai` Python SDK (OpenAI-compatible endpoints, e.g. Groq) |
| Lint / format | Ruff |
| Tests | pytest + pytest-asyncio |
| Git hooks | pre-commit (Ruff + standard hooks) |
| CI | GitHub Actions (`python-version: ["3.10", "3.11", "3.12"]`) |

---

## Project structure

```
.
├── app/
│   ├── main.py                      # FastAPI factory + lifespan
│   ├── api/
│   │   ├── deps.py                  # FastAPI dependencies
│   │   └── v1/
│   │       ├── router.py            # v1 router aggregation
│   │       └── endpoints/           # route modules
│   │           ├── health.py
│   │           ├── cinemas.py
│   │           ├── movies.py
│   │           ├── shows.py
│   │           ├── cities.py
│   │           ├── genres.py
│   │           ├── search.py        # NL / structured search
│   │           └── internal.py      # cache-backed endpoints
│   ├── core/
│   │   ├── config.py                # Pydantic settings
│   │   └── exceptions.py            # app exceptions & handlers
│   ├── schemas/                     # Pydantic request/response models
│   │   ├── common.py
│   │   ├── cinema.py
│   │   ├── movie.py
│   │   ├── show.py
│   │   └── city.py
│   └── services/
│       ├── graphql_client.py        # async httpx GraphQL client
│       ├── kinoheld.py              # Kinoheld business logic
│       ├── cache.py                 # in-memory Kinoheld cache
│       ├── sync.py                  # background periodic sync
│       ├── llm_client.py            # OpenAI-compatible LLM client
│       └── nl_search.py             # natural-language search service
├── tests/
│   ├── conftest.py                  # shared pytest fixtures
│   ├── api/v1/                      # endpoint tests
│   ├── services/                    # service-layer tests
│   └── schemas/                     # schema tests
├── pyproject.toml                   # project metadata, Ruff, pytest config
├── requirements.txt                 # production dependencies
├── Makefile                         # common tasks
├── .pre-commit-config.yaml
├── .github/workflows/ci.yml
├── .env.example
├── README.md
├── API.md                           # frontend integration guide
└── CONTRIBUTING.md
```

---

## Configuration

Configuration is loaded from environment variables via `pydantic-settings` in
`app/core/config.py`. The project reads a `.env` file if present.

Copy `.env.example` to `.env` for local development:

```bash
cp .env.example .env
```

Key variables (all have defaults):

| Variable | Default | Purpose |
|----------|---------|---------|
| `APP_NAME` | `Kinova` | App display name |
| `DEBUG` | `false` | Debug logging |
| `HOST` | `0.0.0.0` | Uvicorn bind host |
| `PORT` | `8000` | Uvicorn bind port |
| `KINOHELD_GRAPHQL_URL` | `https://graph.kinoheld.de/graphql/v1/query` | Upstream GraphQL endpoint |
| `KINOHELD_REQUEST_TIMEOUT` | `30.0` | HTTP timeout (seconds) |
| `KINOHELD_POOL_LIMITS` | `10` | Max keepalive connections |
| `KINOHELD_AFFILIATE_KEY` | `None` | Optional affiliate key |
| `KINOHELD_SYNC_INTERVAL_SECONDS` | `600` | Background cache refresh interval |
| `KINOHELD_SYNC_CINEMA_IDS` | `[]` | Cinema IDs to pre-fetch shows for |
| `KINOHELD_SYNC_SHOW_DAYS` | `7` | Days of shows to pre-fetch |
| `KINOHELD_SYNC_MOVIE_LIMIT` | `100` | Movies fetched per refresh |
| `KINOHELD_SYNC_CINEMA_LIMIT` | `100` | Cinemas fetched per refresh |
| `LLM_BASE_URL` | `https://api.groq.com/openai/v1` | OpenAI-compatible base URL |
| `LLM_API_KEY` | `None` | LLM provider API key |
| `LLM_MODEL` | `llama-3.3-70b-versatile` | Model name |
| `LLM_REQUEST_TIMEOUT` | `60.0` | LLM request timeout |
| `LLM_MAX_TOKENS` | `1024` | Max completion tokens |
| `LLM_TEMPERATURE` | `0.0` | Sampling temperature |
| `LLM_FALLBACK_SEARCH_ENABLED` | `true` | Fallback text search on LLM failure |

The settings object `settings` is a module-level singleton; do not mutate it at
runtime.

---

## Build, run, and check commands

```bash
# Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Install production dependencies
pip install -r requirements.txt

# Install the package in editable mode with dev dependencies
pip install -e ".[dev]"

# Copy environment file and edit as needed
cp .env.example .env

# Run the development server with auto-reload
make run
# equivalent to:
uvicorn app.main:app --reload
```

`Makefile` targets:

| Target | Command |
|--------|---------|
| `make install` | `pip install -r requirements.txt` |
| `make dev` | `pip install -e ".[dev]"` |
| `make lint` | `ruff check app tests && ruff format --check app tests` |
| `make format` | `ruff format app tests && ruff check --fix app tests` |
| `make test` | `pytest` |
| `make check` | `make lint && make test` |
| `make clean` | remove build artifacts and caches |

---

## Architecture and runtime

### Application lifecycle

`app/main.py` exports a FastAPI application via the factory `create_application()`
and a module-level `app` instance. The `lifespan` context manager:

1. Creates a shared `KinoheldCache` and stores it on `app.state.kinoheld_cache`.
2. Creates a long-lived `GraphQLClient` and `KinoheldService`, stored on
   `app.state.kinoheld_service`.
3. Performs an initial cache refresh (errors are suppressed).
4. Starts a background `asyncio` task that re-runs `cache.refresh(service)` every
   `KINOHELD_SYNC_INTERVAL_SECONDS`.
5. On shutdown, cancels the sync task and closes the GraphQL client.

### Request flow

- Public endpoints (e.g. `/cinemas`) use `get_kinoheld_service`, which yields a
  request-scoped `GraphQLClient` and `KinoheldService`.
- Natural-language/structured search endpoints also depend on `get_llm_client`
  (request-scoped) and `get_kinoheld_cache` (shared in-memory cache).
- Internal endpoints under `/api/v1/internal/*` read from the shared cache; some
  fall back to the live service for on-demand data or IP-based lookups.

### Service modules

- `app/services/graphql_client.py` — thin `httpx.AsyncClient` wrapper that POSTs
  GraphQL queries, checks for HTTP and GraphQL errors, and returns the `data`
  payload. Raises `KinoheldAPIError` on upstream failures.
- `app/services/kinoheld.py` — maps REST parameters to GraphQL queries for
  cinemas, movies, shows, cities, and genres. Raises `KinoheldNotFoundError` when
  a single-resource lookup returns `None`.
- `app/services/cache.py` — atomic in-memory cache with async lock. Supports
  filtering/searching by name, location/distance, and date. Pre-fetches shows for
  configured cinema IDs; otherwise fetches shows on demand.
- `app/services/sync.py` — simple periodic refresh loop.
- `app/services/llm_client.py` — OpenAI-compatible chat-completion wrapper that
  returns parsed JSON.
- `app/services/nl_search.py` — parses natural-language prompts (via LLM with a
  heuristic fallback), builds structured filters, and executes the appropriate
  Kinoheld queries with deterministic post-filtering.

### Exception handling

All application exceptions inherit from `KinovaError`. Handlers in
`app/core/exceptions.py` produce JSON responses:

- `KinoheldNotFoundError` → `404 Not Found`
- `KinoheldAPIError` → `502 Bad Gateway` (includes `upstream_errors` when present)
- Other `KinovaError` → configured status code
- Unhandled exceptions → `500 Internal Server Error` with a generic message

---

## API surface overview

All routes are prefixed with `/api/v1`. Public endpoints:

| Method | Route | Description |
|--------|-------|-------------|
| GET | `/health` | Liveness probe |
| GET | `/cinemas` | Search cinemas |
| GET | `/cinemas/{cinema_id}` | Single cinema |
| GET | `/movies` | Search movies |
| GET | `/movies/{movie_id}` | Single movie |
| GET | `/shows` | List shows for a cinema |
| GET | `/shows/{show_id}` | Single show |
| GET | `/cities` | Search cities |
| GET | `/cities/me` | City inferred from request IP |
| GET | `/genres` | List genres |

Search endpoints:

| Method | Route | Description |
|--------|-------|-------------|
| POST | `/search/natural` | LLM-powered natural-language search |
| POST | `/search/structured` | Deterministic filter-panel search |

Both search endpoints accept a `useCache` flag and return a unified `SearchResult`
with `cinemas`, `movies`, `shows`, `intent`, and `totalResults`.

Internal/cache-backed endpoints under `/api/v1/internal/*` mirror the public
resource routes and add `/internal/health` for cache status. They are intended
for use-cases that need lower latency or offline resilience. `/internal/cities/me`
still calls the live API because it is IP-specific.

Full request/response schemas and `curl` examples are in `API.md`.

---

## Development conventions and code style

- Target **Python 3.10+**.
- **Line length:** 100 characters (configured in `pyproject.toml`).
- **Formatter / linter:** Ruff. The CI runs `ruff check app tests` and
  `ruff format --check app tests`.
- **Import order:** handled automatically by Ruff.
- **Type hints:** encouraged for new public functions and methods. The codebase
  uses `str | None` etc., not `Optional`.
- **EditorConfig:** spaces, 4-space indentation for Python, 2-space for YAML/JSON/TOML,
  LF line endings, final newlines, trimmed trailing whitespace.
- **Docstrings:** modules, classes, and public functions have docstrings.
- **Pydantic models:** use `ConfigDict(populate_by_name=True)` and camelCase
  aliases for fields that are serialized to/from JSON (e.g. `detail_url` with
  alias `detailUrl`).
- **GraphQL variable naming:** camelCase to match the upstream Kinoheld schema.
- **Tests:** prefer `unittest.mock.AsyncMock` and `fastapi.testclient.TestClient`.
  Override dependencies in fixtures rather than monkey-patching global state.

Pre-commit hooks are configured in `.pre-commit-config.yaml`:

- `ruff` (with `--fix`)
- `ruff-format`
- trailing-whitespace, end-of-file-fixer, check-yaml, check-toml, check-added-large-files

---

## Testing strategy

```bash
# Run the full suite
pytest

# Run linting + tests
make check
```

Key testing patterns used in this repo:

- `tests/conftest.py` provides `mock_graphql_client`, `kinoheld_service`, and
  `test_app` fixtures.
- API tests create a `TestClient` and override `get_kinoheld_service` with an
  async generator that yields a `KinoheldService` backed by a mocked GraphQL
  client.
- Service tests use `@pytest.mark.asyncio` and directly await service methods.
- Schema tests validate model parsing, aliases, and validators (e.g. image-list
  normalization).

The GitHub Actions workflow (`.github/workflows/ci.yml`) installs the package
with `pip install -e ".[dev]"`, runs lint/format checks, and then runs `pytest`
on Python 3.10, 3.11, and 3.12.

---

## Security considerations

- **No authentication** is currently implemented for any public route.
- **CORS** is enabled with `allow_origins=["*"]` in `app/main.py`. This is fine
  for local development but must be narrowed in production.
- **Secrets** (LLM API key, affiliate key) live in `.env` and are read by
  `pydantic-settings`. `.env` is gitignored; only `.env.example` is committed.
- **LLM endpoints** return `503 Service Unavailable` when the provider is
  misconfigured or unreachable. The natural-language search falls back to a
  heuristic parser and, if enabled, to a local text search.
- **No persistent database** is used. The cache is in-memory only and scoped to
  the running process.
- **Upstream trust:** the app forwards user-supplied query parameters to the
  Kinoheld GraphQL API. Inputs are validated by Pydantic, but the upstream API
  ultimately controls availability and rate limits.
- **No built-in rate limiting** in Kinova itself; rely on upstream behavior or a
  reverse proxy in production.

---

## Deployment notes

- Run with Uvicorn directly:

  ```bash
  uvicorn app.main:app --host "${HOST:-0.0.0.0}" --port "${PORT:-8000}"
  ```

- There is **no Dockerfile** in the repository at this time.
- Set `DEBUG=false` and configure `allow_origins` for production deployments.
- Because the cache is in-memory and the background sync task runs inside each
  process, scaling horizontally will create independent caches per worker. If
  strong cache consistency across instances is required, you will need to
  replace the in-memory cache with an external store or adjust the architecture.
- Consider running behind a reverse proxy (nginx, Caddy, cloud load balancer) for
  TLS termination and CORS/rate-limit control.

---

## Common commands reference

```bash
# Setup
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env

# Development server
make run

# Code quality
make lint      # check only
make format    # auto-fix and format
make check     # lint + test

# Tests
pytest
pytest -x     # stop on first failure

# Manual smoke tests against a running server
bash curl_tests.sh
```

---

## Useful files for agents

- `README.md` — quick start, project description, and high-level config table.
- `API.md` — detailed frontend integration guide with schemas and curl examples.
- `CONTRIBUTING.md` — contributor setup and PR process.
- `app/core/config.py` — authoritative list of environment variables and defaults.
- `app/main.py` — application factory, lifespan, middleware, and router wiring.
- `app/api/deps.py` — dependency definitions for endpoints.
- `app/core/exceptions.py` — exception hierarchy and handlers.
