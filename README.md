# Kinova

![CI](https://github.com/5aeidi/kinova/actions/workflows/ci.yml/badge.svg)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

**Kinova** is a small, production-ready **FastAPI** wrapper around the **Kinoheld GraphQL API**.

It exposes clean REST routes for cinemas, movies, shows, cities, and genres while handling GraphQL introspection, error mapping, connection pooling, and Pydantic validation for you. It also includes source-specific Cinetixx and Yorck Kinogruppe routes plus cache-backed internal variants. Cinetixx mandators are discovered automatically from its public cinema index, and the Yorck programme is fetched from the yorck.de public Next.js data endpoints.

## Why this exists

The Kinoheld GraphQL endpoint (`https://graph.kinoheld.de/graphql/v1/query`) is free to query and exposes introspection, but it is not REST. This project gives you:

- Typed REST endpoints you can call from any frontend / mobile app.
- Centralised config, logging, and error handling.
- Async `httpx` client with connection pooling.
- Pydantic v2 request/response models.
- Simple project layout that scales.

## Quick start

```bash
# 1. Create a virtual environment
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Copy and edit environment variables
cp .env.example .env

# 4. Run the server
uvicorn app.main:app --reload
```

Open `http://localhost:8000/docs` for interactive Swagger UI.

## Available routes

All routes are prefixed with `/api/v1`.

| Method | Route | Description |
|--------|-------|-------------|
| GET | `/health` | Liveness check |
| GET | `/cinemas` | Search cinemas |
| GET | `/cinemas/{cinema_id}` | Get cinema by ID |
| GET | `/movies` | Search movies |
| GET | `/movies/{movie_id}` | Get movie by ID |
| GET | `/shows` | List shows for a cinema |
| GET | `/shows/{show_id}` | Get show by ID |
| GET | `/cities` | Search cities |
| GET | `/cities/me` | City inferred from request IP |
| GET | `/genres` | List genres |
| GET | `/cinetixx/show-info` | Fetch Cinetixx legacy showtime data by `mandatorId` |
| GET | `/cinetixx/mandators` | Discover Cinetixx `mandatorId` values by cinema name, city, or `cinemaId` |
| GET | `/cinetixx/cinemas` | List Cinetixx cinemas derived from program data |
| GET | `/cinetixx/movies` | List Cinetixx movies/events derived from program data |
| GET | `/cinetixx/shows` | List Cinetixx shows derived from program data |
| GET | `/cinetixx/cities` | List Cinetixx cities derived from program data |
| GET | `/cinetixx/genres` | List Cinetixx genres/categories derived from program data |
| GET | `/yorck/cinemas` | List Yorck Kinogruppe cinemas |
| GET | `/yorck/movies` | List Yorck movies/specials with rich metadata |
| GET | `/yorck/shows` | List Yorck shows/sessions |
| GET | `/yorck/cities` | List Yorck cities |
| GET | `/yorck/genres` | List Yorck genres/labels |
| GET | `/internal/cinetixx/*` | Cache-backed Cinetixx resource routes |
| GET | `/internal/yorck/*` | Cache-backed Yorck resource routes |
| GET | `/internal/unified/*` | Cache-backed unified resources with Kinoheld-shaped fields plus `source` metadata |

### Example requests

```bash
# Search cinemas in Berlin
curl "http://localhost:8000/api/v1/cinemas?search=Berlin&limit=3"

# Search movies
curl "http://localhost:8000/api/v1/movies?search=Inception&limit=5"

# Shows for a cinema today
curl "http://localhost:8000/api/v1/shows?cinemaId=254&date=2026-06-14"

# List genres
curl "http://localhost:8000/api/v1/genres"

# Cinetixx legacy showtime data for a known mandatorId
curl "http://localhost:8000/api/v1/cinetixx/show-info?mandatorId=1234"

# Discover the current mandatorId for a Cinetixx cinema
curl "http://localhost:8000/api/v1/cinetixx/mandators?search=ACUDkino"

# Normalized Cinetixx shows and internal cached shows
curl "http://localhost:8000/api/v1/cinetixx/shows?mandatorId=1234"
curl "http://localhost:8000/api/v1/internal/cinetixx/shows?mandatorId=1234"

# Unified cached movies across providers
curl "http://localhost:8000/api/v1/internal/unified/movies?mandatorId=1234"
curl "http://localhost:8000/api/v1/internal/unified/movies?source=cinetixx&mandatorId=1234"
```

> **Frontend integration:** see [`API.md`](./API.md) for the full frontend guide, including request/response schemas and copy-paste `curl` examples.

## Project structure

```
.
├── app/
│   ├── api/
│   │   ├── deps.py              # FastAPI dependencies
│   │   └── v1/
│   │       ├── router.py        # v1 route aggregation
│   │       └── endpoints/       # cinemas, movies, shows, cities, genres, health
│   ├── core/
│   │   ├── config.py            # Pydantic settings
│   │   └── exceptions.py        # App exceptions & handlers
│   ├── schemas/
│   │   ├── cinema.py
│   │   ├── movie.py
│   │   ├── show.py
│   │   ├── city.py
│   │   └── common.py
│   ├── services/
│   │   ├── graphql_client.py    # Async httpx GraphQL client
│   │   └── kinoheld.py          # Kinoheld business logic
│   └── main.py                  # FastAPI factory
├── tests/
├── .env.example
├── requirements.txt
├── pyproject.toml
├── Makefile
├── LICENSE
├── CONTRIBUTING.md
├── .gitignore
├── .editorconfig
├── .pre-commit-config.yaml
└── README.md
```

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run linting and tests
make check

# Auto-format code
make format

# Run the server locally
make run
```

A `Makefile` with common tasks is included. See `CONTRIBUTING.md` for the full contributor guide.

## Kinoheld GraphQL schema overview

The upstream API exposes these main **queries** (from introspection):

- `cinemas(search, location, distance, limit, ...)`
- `cinema(id, urlSlug, city, ...)`
- `movies(search, location, distance, limit, playing, ...)`
- `movie(id, cinemaId, urlSlug, ...)`
- `shows(cinemaId, date, days, movie, ...)`
- `show(id)`
- `cities(search, location, distance, limit)`
- `city(name, urlSlug)`
- `cityByIp`
- `genres(search, filter, ofMoviesPlaying)`
- `postcode(postcode, countryCode)` / `postcodes(search, limit)`
- `account`, `cart`, `order`, `affiliate`, `banner`, `config`, `content`, `design`

And many **mutations** for cart, account, and payment flows (`cartCreate`, `cartAddItem`, `accountLogin`, etc.).

This project exposes the most useful read-only queries first. You can extend `app/services/kinoheld.py` and `app/api/v1/endpoints` to add cart/booking mutations when you need them.

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `APP_NAME` | `Kinova` | App name |
| `DEBUG` | `false` | Debug logging |
| `HOST` | `0.0.0.0` | Bind host |
| `PORT` | `8000` | Bind port |
| `KINOHELD_GRAPHQL_URL` | `https://graph.kinoheld.de/graphql/v1/query` | Upstream endpoint |
| `KINOHELD_REQUEST_TIMEOUT` | `30.0` | HTTP timeout |
| `KINOHELD_POOL_LIMITS` | `10` | Connection pool size |
| `KINOHELD_AFFILIATE_KEY` | `None` | Optional affiliate key |
| `CINETIXX_SHOW_INFO_URL` | `https://api.cinetixx.de/Services/CinetixxService.asmx/GetShowInfoV6` | Cinetixx legacy showtime endpoint |
| `CINETIXX_CINEMA_SEARCH_URL` | `https://booking.cinetixx.de/api/cinemas/` | Cinetixx cinema discovery endpoint |
| `CINETIXX_REQUEST_TIMEOUT` | `30.0` | Cinetixx HTTP timeout |
| `CINETIXX_POOL_LIMITS` | `10` | Cinetixx connection pool size |
| `CINETIXX_SYNC_INTERVAL_SECONDS` | `3600` | Cinetixx cache refresh interval (one hour) |
| `CINETIXX_SYNC_MANDATOR_IDS` | `[]` | Optional additional mandator IDs to pre-fetch; automatic discovery does not require this |
| `CINETIXX_SYNC_DISCOVERY_SEARCHES` | `[]` | Optional additional cinema search terms; automatic discovery runs without this |
| `CINETIXX_DISCOVERY_PAGE_SIZE` | `100` | Booking-index cinemas requested per discovery page |
| `CINETIXX_DISCOVERY_MAX_PAGES` | `100` | Safety limit for booking-index discovery pages |
| `CINETIXX_DISCOVERY_TERMS` | `a-z,0-9` | Search terms used to enumerate the public booking index; blank uses the default |
| `CINETIXX_SYNC_SHOW_DAYS` | `7` | Default number of Cinetixx show days returned by date filters |

## Running tests

```bash
pip install -e ".[dev]"
pytest
```

## License

MIT
