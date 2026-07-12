# Kinova REST API — Frontend Integration Guide

This document is the single source of truth for frontend developers integrating with the **Kinova** backend. It describes every public route, its request format, its response shape, and provides copy-paste `curl` examples.

> **Tip:** The server also exposes interactive documentation at `/docs` (Swagger UI) and `/openapi.json` (OpenAPI spec).

---

## Table of contents

- [Base URL & versioning](#base-url--versioning)
- [Conventions](#conventions)
- [Authentication](#authentication)
- [Common headers](#common-headers)
- [Rate limits, timeouts & CORS](#rate-limits-timeouts--cors)
- [Error responses](#error-responses)
- [Status code quick reference](#status-code-quick-reference)
- [Endpoints](#endpoints)
  - [Health](#get-health)
  - [Cities](#cities)
  - [Cinemas](#cinemas)
  - [Movies](#movies)
  - [Shows](#shows)
  - [Genres](#genres)
  - [Cinetixx](#cinetixx)
- [Frontend integration tips](#frontend-integration-tips)
- [Generating TypeScript types](#generating-typescript-types)
- [Quick command reference](#quick-command-reference)

---

## Base URL & versioning

All routes are prefixed with `/api/v1`.

| Environment | Base URL |
|-------------|----------|
| Local dev   | `http://localhost:8000/api/v1` |
| Production  | Configured per deployment (e.g. `https://api.example.com/api/v1`) |

The API is read-only and primarily wraps the upstream [Kinoheld](https://www.kinoheld.de/) GraphQL endpoint. Source-specific Cinetixx routes are namespaced under `/cinetixx`.

---

## Conventions

- **JSON only.** Every response is `application/json`.
- **camelCase aliases.** Some query parameters accept a camelCase alias because they are forwarded to Kinoheld. Both forms are accepted unless noted otherwise.
- **Dates.** Use ISO-8601 date format: `YYYY-MM-DD`.
- **IDs.** IDs are strings. Kinoheld often returns numeric-looking IDs, but treat them as opaque strings.
- **Images.** Image fields are objects with `url` and `alt`. `url` may be `null` if no image is available.
- **Coordinates.** Geo fields are objects with `latitude` and `longitude`.

---

## Authentication

None of the current routes require authentication. If auth is added in the future, this section will be updated and the relevant endpoints will return `401 Unauthorized` when credentials are missing or invalid.

The source-specific `GET /cinetixx/show-info` route uses Cinetixx's legacy showtime endpoint and does not accept credentials. Cinetixx's current public REST API documentation describes a separate token-authenticated API using a `Cinetixx-AccessToken` header; Kinova does not wrap those official REST routes yet.

---

## Common headers

No special headers are required. Standard request headers are sufficient:

```http
Accept: application/json
```

For `POST`/`PUT` endpoints (when they are added), include:

```http
Content-Type: application/json
```

---

## Rate limits, timeouts & CORS

### Timeouts

The backend forwards requests to the upstream Kinoheld GraphQL API. Default upstream timeout is **30 seconds**. Frontend clients should use their own timeout (recommended: **10–15 seconds**) so a slow upstream response does not lock the UI.

### Rate limiting

There is no enforced rate limit in Kinova itself, but the upstream Kinoheld API may throttle aggressive clients. A reasonable frontend guideline:

- Debounce search inputs to **at most one request per 300 ms**.
- Cache list responses (cinemas, genres, cities) for the user session.
- Do not poll `/shows` more often than every **60 seconds** unless the user explicitly refreshes.

### CORS

FastAPI serves the API with CORS enabled by default for local development. In production, configure the allowed origins via the deployment environment. If you see `CORS policy` errors in the browser, the production allow-list needs to include your frontend domain.

---

## Error responses

The API uses standard HTTP status codes. Error responses follow this shape:

### Validation error — `422 Unprocessable Entity`

Returned when a query/path parameter fails validation (wrong type, out of range, missing required value, etc.).

```json
{
  "detail": [
    {
      "type": "missing",
      "loc": ["query", "cinemaId"],
      "msg": "Field required",
      "input": null
    }
  ]
}
```

### Not found — `404 Not Found`

Returned when a requested resource cannot be resolved by the upstream Kinoheld API.

```json
{
  "detail": "Cinema not found"
}
```

### Internal error — `500 Internal Server Error`

Returned when the upstream Kinoheld API is unreachable or returns an unexpected error.

```json
{
  "detail": "Upstream API error"
}
```

When Kinoheld returns a GraphQL-level error (e.g. an invalid enum value), the response includes the upstream message so you can debug:

```json
{
  "detail": "GraphQL errors: Variable \"$playing\" got invalid value \"SOON\"; Expected type ShowsPlayingFilterEnum.",
  "upstream_errors": [
    {
      "message": "Variable \"$playing\" got invalid value \"SOON\"; Expected type ShowsPlayingFilterEnum.",
      "extensions": { "category": "graphql" },
      "locations": [{ "line": 7, "column": 11 }]
    }
  ]
}
```

---

## Status code quick reference

| Endpoint | Success | Validation error | Not found | Server error |
|----------|---------|------------------|-----------|--------------|
| `GET /health` | `200` | — | — | `500` |
| `GET /cities` | `200` | `422` | — | `500` |
| `GET /cities/me` | `200` | — | `404` | `500` |
| `GET /cinemas` | `200` | `422` | — | `500` |
| `GET /cinemas/{cinema_id}` | `200` | `422` | `404` | `500` |
| `GET /movies` | `200` | `422` | — | `500` |
| `GET /movies/{movie_id}` | `200` | `422` | `404` | `500` |
| `GET /shows` | `200` | `422` | — | `500` |
| `GET /shows/{show_id}` | `200` | `422` | `404` | `500` |
| `GET /genres` | `200` | — | — | `500` |
| `GET /cinetixx/show-info` | `200` | `422` | — | `500` |
| `GET /cinetixx/{resource}` | `200` | `422` | — | `500` |
| `GET /cinetixx/{resource}/{id}` | `200` | `422` | `404` | `500` |
| `GET /internal/cinetixx/{resource}` | `200` | `422` | — | `500` |
| `GET /internal/cinetixx/{resource}/{id}` | `200` | `422` | `404` | `500` |
| `GET /internal/unified/{resource}` | `200` | `422` | — | `500` |
| `GET /internal/unified/{resource}/{id}` | `200` | `422` | `404` | `500` |

> **Empty list vs. 404:** Search endpoints (`/cinemas`, `/movies`, `/shows`, `/cities`) return `200 OK` with an empty array `[]` when no results match. A `404` is only returned for single-resource lookups (`/{id}`) or `/cities/me` when geolocation fails.

---

## Endpoints

### `GET /health`

Liveness / readiness probe.

#### Response

| Field   | Type   | Description            |
|---------|--------|------------------------|
| `status`| string | Always `"ok"`          |
| `app`   | string | Application name       |

#### Example request

```bash
curl "http://localhost:8000/api/v1/health"
```

#### Example response — `200 OK`

```json
{
  "status": "ok",
  "app": "Kinova"
}
```

---

## Cities

### `GET /cities`

Search cities by name or location.

#### Query parameters

| Parameter  | Type    | Required | Default | Description                                      |
|------------|---------|----------|---------|--------------------------------------------------|
| `search`   | string  | No       | —       | Free-text city search                            |
| `location` | string  | No       | —       | City name to centre the search                   |
| `distance` | integer | No       | —       | Search radius in kilometres (`1`–`100`)          |
| `limit`    | integer | No       | `20`    | Maximum number of results (`1`–`100`)            |

#### Response model

Array of `City` objects.

| Field         | Type        | Nullable | Description                          |
|---------------|-------------|----------|--------------------------------------|
| `id`          | string      | Yes      | Kinoheld city ID                     |
| `name`        | string      | No       | City name                            |
| `urlSlug`     | string      | Yes      | URL-friendly identifier              |
| `coordinates` | `Geo`       | Yes      | `{ latitude, longitude }`            |
| `detailUrl`   | `Url`       | Yes      | `{ url }` link to Kinoheld city page |

#### Example request

```bash
curl "http://localhost:8000/api/v1/cities?search=Berlin&limit=5"
```

#### Example response — `200 OK`

```json
[
  {
    "id": "1149",
    "name": "Berlin",
    "urlSlug": "berlin",
    "coordinates": {
      "latitude": 52.524681,
      "longitude": 13.40535
    },
    "detailUrl": {
      "url": "https://www.kinoheld.de/cinema/berlin/"
    }
  },
  {
    "id": "1151",
    "name": "Berlingerode",
    "urlSlug": "berlingerode",
    "coordinates": {
      "latitude": 51.45797,
      "longitude": 10.23971
    },
    "detailUrl": {
      "url": "https://www.kinoheld.de/cinema/berlingerode/"
    }
  }
]
```

---

### `GET /cities/me`

Return the city inferred from the request's public IP address.

> **Note:** This relies on the upstream `cityByIp` query. Accuracy depends on the caller's IP and Kinoheld's geolocation data.

#### Response

Single `City` object (same model as `GET /cities`) on success.

If Kinoheld cannot determine a city from the IP, the endpoint returns `404 Not Found`:

```json
{
  "detail": "Could not determine city by IP"
}
```

#### Example request

```bash
curl "http://localhost:8000/api/v1/cities/me"
```

#### Example response — `200 OK`

```json
{
  "id": "1149",
  "name": "Berlin",
  "urlSlug": "berlin",
  "coordinates": {
    "latitude": 52.524681,
    "longitude": 13.40535
  },
  "detailUrl": {
    "url": "https://www.kinoheld.de/cinema/berlin/"
  }
}
```

---

## Cinemas

### `GET /cinemas`

Search cinemas by city, name, or free-text query.

#### Query parameters

| Parameter      | Type    | Required | Default | Description                                      |
|----------------|---------|----------|---------|--------------------------------------------------|
| `search`       | string  | No       | —       | Free-text cinema/city search                     |
| `location`     | string  | No       | —       | City name to centre the search                   |
| `distance`     | integer | No       | —       | Search radius in kilometres (`1`–`100`)          |
| `limit`        | integer | No       | `1000`  | Maximum number of results (`1`–`1000`)           |
| `onlyBookable` | boolean | No       | `false` | Only return cinemas that support booking         |
| `isOpenAir`    | boolean | No       | —       | Filter by open-air cinemas                       |
| `isDriveIn`    | boolean | No       | —       | Filter by drive-in cinemas                       |

#### Response model

Array of `Cinema` objects.

| Field                | Type         | Nullable | Description                            |
|----------------------|--------------|----------|----------------------------------------|
| `id`                 | string       | No       | Kinoheld cinema ID                     |
| `name`               | string       | No       | Cinema name                            |
| `street`             | string       | Yes      | Street address                         |
| `city`               | `CitySummary`| Yes      | `{ id, name, urlSlug }`                |
| `distance`           | float        | Yes      | Distance from search centre (km)       |
| `coordinates`        | `Geo`        | Yes      | `{ latitude, longitude }`              |
| `postcode`           | string       | Yes      | Postal code                            |
| `phonenumber`        | string       | Yes      | Phone number                           |
| `detailUrl`          | `Url`        | Yes      | `{ url }` link to Kinoheld detail page |
| `thumbnail`          | `Image`      | Yes      | `{ url, alt }` — `alt` is often `null` |
| `heroImage`          | `Image`      | Yes      | `{ url, alt }` — may be `null` entirely |
| `urlSlug`            | string       | Yes      | URL-friendly identifier                |
| `isDriveInCinema`    | boolean      | Yes      | Whether the cinema is a drive-in       |
| `isOpenAirCinema`    | boolean      | Yes      | Whether the cinema is open-air         |
| `isStationaryCinema` | boolean      | Yes      | Whether the cinema is stationary       |

#### Example request

```bash
curl "http://localhost:8000/api/v1/cinemas?search=Berlin&limit=3"
```

#### Example response — `200 OK`

```json
[
  {
    "id": "614",
    "name": "Hackesche Höfe Kino Berlin",
    "street": "Rosenthaler Straße 40/41/Hof 1",
    "city": {
      "id": "1149",
      "name": "Berlin",
      "urlSlug": "berlin"
    },
    "distance": null,
    "coordinates": {
      "latitude": 52.52478,
      "longitude": 13.40171
    },
    "postcode": "10178",
    "phonenumber": "030 2834603",
    "detailUrl": {
      "url": "https://www.kinoheld.de/cinema/berlin/hackesche-hoefe-kino"
    },
    "thumbnail": {
      "url": "https://media.kinoheld.de/TV0c753PWrF_7GQj8Wj7A8I4lXQ=/fit-in/400x300/images%2Fkino%2Fhackesche-hoefe-200-280.v2.png",
      "alt": null
    },
    "heroImage": {
      "url": "https://media.kinoheld.de/4WU5qQtdvyQWlV4dhWjeMYBZiDo=/fit-in/400x300/images%2Fcinemas%2Fhero%2Fhackesche-hoefe-kino-berlin-614.v2.png",
      "alt": null
    },
    "urlSlug": "hackesche-hoefe-kino",
    "isDriveInCinema": false,
    "isOpenAirCinema": false,
    "isStationaryCinema": true
  }
]
```

---

### `GET /cinemas/{cinema_id}`

Fetch a single cinema by its Kinoheld ID.

#### Path parameters

| Parameter   | Type   | Required | Description           |
|-------------|--------|----------|-----------------------|
| `cinema_id` | string | Yes      | Kinoheld cinema ID    |

#### Response

Single `Cinema` object (same model as `GET /cinemas`).

#### Example request

```bash
curl "http://localhost:8000/api/v1/cinemas/614"
```

#### Example response — `200 OK`

```json
{
  "id": "614",
  "name": "Hackesche Höfe Kino Berlin",
  "street": "Rosenthaler Straße 40/41/Hof 1",
  "city": {
    "id": "1149",
    "name": "Berlin",
    "urlSlug": "berlin"
  },
  "distance": null,
  "coordinates": {
    "latitude": 52.52478,
    "longitude": 13.40171
  },
  "postcode": "10178",
  "phonenumber": "030 2834603",
  "detailUrl": {
    "url": "https://www.kinoheld.de/cinema/berlin/hackesche-hoefe-kino"
  },
  "thumbnail": {
    "url": "https://media.kinoheld.de/TV0c753PWrF_7GQj8Wj7A8I4lXQ=/fit-in/400x300/images%2Fkino%2Fhackesche-hoefe-200-280.v2.png",
    "alt": null
  },
  "heroImage": {
    "url": "https://media.kinoheld.de/4WU5qQtdvyQWlV4dhWjeMYBZiDo=/fit-in/400x300/images%2Fcinemas%2Fhero%2Fhackesche-hoefe-kino-berlin-614.v2.png",
    "alt": null
  },
  "urlSlug": "hackesche-hoefe-kino",
  "isDriveInCinema": false,
  "isOpenAirCinema": false,
  "isStationaryCinema": true
}
```

---

## Movies

### `GET /movies`

Search movies by title or playing location.

#### Query parameters

| Parameter  | Type    | Required | Default | Description                                      |
|------------|---------|----------|---------|--------------------------------------------------|
| `search`   | string  | No       | —       | Free-text movie title search                     |
| `location` | string  | No       | —       | City name to restrict results                    |
| `distance` | integer | No       | —       | Search radius in kilometres (`1`–`100`)          |
| `limit`    | integer | No       | `20`    | Maximum number of results (`>= 1`)               |
| `playing`  | string  | No       | —       | Filter by playing status: `NOW`, `FUTURE`, or `UPCOMING` |

#### Response model

Array of `Movie` objects.

| Field                  | Type           | Nullable | Description                            |
|------------------------|----------------|----------|----------------------------------------|
| `id`                   | string         | No       | Kinoheld movie ID                      |
| `title`                | string         | No       | Movie title                            |
| `description`          | string         | Yes      | Short plot / synopsis                  |
| `additionalDescription`| string         | Yes      | Extra description text                 |
| `duration`             | integer        | Yes      | Runtime in minutes                     |
| `genres`               | `Genre[]`      | No       | List of genres                         |
| `directors`            | `Person[]`     | No       | List of directors — may be empty       |
| `actors`               | `Person[]`     | No       | List of actors — may be empty          |
| `productionYear`       | string         | Yes      | Year of release — often `null`         |
| `thumb`                | `Image`        | Yes      | Poster thumbnail — `alt` often `null`  |
| `heroImage`            | `Image`        | Yes      | Hero image — may be `null`             |
| `detailUrl`            | `Url`          | Yes      | `{ url }` link to Kinoheld detail page |
| `urlSlug`              | string         | Yes      | URL-friendly identifier                |
| `imdbRating`           | float          | Yes      | IMDb rating — often `null`             |
| `imdbVotes`            | integer        | Yes      | IMDb vote count — often `null`         |

**`Genre`** — `{ id?: string, name: string, urlSlug?: string }`

**`Person`** — `{ id?: string, name?: string }`

#### Example request

```bash
curl "http://localhost:8000/api/v1/movies?search=Star%20Wars&limit=3"
```

#### Example response — `200 OK`

```json
[
  {
    "id": "89783",
    "title": "Star Wars: The Mandalorian and Grogu",
    "description": "Das Dunkle Imperium ist gefallen und die imperialen Kriegstreiber sind weiterhin über die Galaxis verstreut...",
    "additionalDescription": "",
    "duration": 132,
    "genres": [
      { "id": "9", "name": "Abenteuer", "urlSlug": "abenteuer" },
      { "id": "11", "name": "Science Fiction", "urlSlug": "science-fiction" },
      { "id": "12", "name": "Action", "urlSlug": "action" }
    ],
    "directors": [
      { "id": "23615", "name": "Jon Favreau" }
    ],
    "actors": [
      { "id": "36668", "name": "Pedro Pascal" },
      { "id": "384", "name": "Sigourney Weaver" }
    ],
    "productionYear": "2026",
    "thumb": {
      "url": "https://media.kinoheld.de/MuFdhdoqRz7pG27QJrSWevk62WQ=/fit-in/400x300/images%2Ffilm%2Fthe-mandalorian-grogu-89783.v17695674879056.jpg",
      "alt": null
    },
    "heroImage": {
      "url": "https://media.kinoheld.de/YKUd2YbzkU2VK3nOgFUfR20j17A=/fit-in/400x300/images%2Ffilm%2Fstar-wars-the-mandalorian-and-grogu-89783-hero.v17762557140123.jpg",
      "alt": null
    },
    "detailUrl": {
      "url": "https://www.kinoheld.de/movie/the-mandalorian-grogu"
    },
    "urlSlug": "the-mandalorian-grogu",
    "imdbRating": null,
    "imdbVotes": null
  }
]
```

---

### `GET /movies/{movie_id}`

Fetch a single movie by its Kinoheld ID.

#### Path parameters

| Parameter   | Type   | Required | Description          |
|-------------|--------|----------|----------------------|
| `movie_id`  | string | Yes      | Kinoheld movie ID    |

#### Response

Single `Movie` object (same model as `GET /movies`).

#### Example request

```bash
curl "http://localhost:8000/api/v1/movies/89783"
```

#### Example response — `200 OK`

```json
{
  "id": "89783",
  "title": "Star Wars: The Mandalorian and Grogu",
  "description": "Das Dunkle Imperium ist gefallen und die imperialen Kriegstreiber sind weiterhin über die Galaxis verstreut...",
  "additionalDescription": "",
  "duration": 132,
  "genres": [
    { "id": "9", "name": "Abenteuer", "urlSlug": "abenteuer" },
    { "id": "11", "name": "Science Fiction", "urlSlug": "science-fiction" },
    { "id": "12", "name": "Action", "urlSlug": "action" }
  ],
  "directors": [
    { "id": "23615", "name": "Jon Favreau" }
  ],
  "actors": [
    { "id": "36668", "name": "Pedro Pascal" },
    { "id": "384", "name": "Sigourney Weaver" },
    { "id": "212397", "name": "Jeremy Allen White" }
  ],
  "productionYear": "2026",
  "thumb": {
    "url": "https://media.kinoheld.de/MuFdhdoqRz7pG27QJrSWevk62WQ=/fit-in/400x300/images%2Ffilm%2Fthe-mandalorian-grogu-89783.v17695674879056.jpg",
    "alt": null
  },
  "heroImage": {
    "url": "https://media.kinoheld.de/YKUd2YbzkU2VK3nOgFUfR20j17A=/fit-in/400x300/images%2Ffilm%2Fstar-wars-the-mandalorian-and-grogu-89783-hero.v17762557140123.jpg",
    "alt": null
  },
  "detailUrl": {
    "url": "https://www.kinoheld.de/movie/the-mandalorian-grogu"
  },
  "urlSlug": "the-mandalorian-grogu",
  "imdbRating": null,
  "imdbVotes": null
}
```

---

## Shows

### `GET /shows`

List shows / screenings for a cinema, optionally filtered by date and movie.

#### Query parameters

| Parameter  | Type    | Required | Default | Description                                      |
|------------|---------|----------|---------|--------------------------------------------------|
| `cinemaId` | string  | Yes      | —       | Kinoheld cinema ID                               |
| `date`     | date    | No       | —       | Start date in `YYYY-MM-DD` format                |
| `days`     | integer | No       | —       | Number of days to fetch (`1`–`30`)               |
| `movieId`  | string  | No       | —       | Filter by Kinoheld movie ID                      |

#### Response model

Array of `Show` objects.

| Field         | Type                | Nullable | Description                            |
|---------------|---------------------|----------|----------------------------------------|
| `id`          | string              | No       | Kinoheld show ID                                        |
| `name`        | string              | No       | Show name / label                                       |
| `beginning`   | `DateTimeFormatted` | Yes      | `{ formatted, timestamp }`                              |
| `admission`   | `DateTimeFormatted` | Yes      | Doors open time                                         |
| `duration`    | string              | Yes      | Runtime in minutes as a string, e.g. `"132"`            |
| `flags`       | `ShowFlag[]`        | No       | Attribute flags (subtitles, 3D, event, etc.)            |
| `detailUrl`   | `Url`               | Yes      | `{ url }` link to Kinoheld detail page                  |
| `isSoldOut`   | boolean             | Yes      | Whether tickets are sold out                            |
| `movie`       | `Movie`             | Yes      | Movie object — may be sparser than `GET /movies/{id}`   |
| `auditorium`  | `Auditorium`        | Yes      | `{ id, name, seatCount }`                               |

**`DateTimeFormatted`** — `{ formatted?: string, timestamp?: integer }`

**`ShowFlag`** — `{ name: string, code?: string, category?: string }`

The `flags` array is the source of truth for language, subtitle, format, and special-event information. The values below are observed in real Kinoheld responses — always render the `name` field to users and treat `code`/`category` as optional hints.

| `name`            | `code`         | `category`   | Meaning                                         |
|-------------------|----------------|--------------|-------------------------------------------------|
| `subtitled OV`    | `subtitled`    | `language`   | Original version with subtitles                 |
| `OmU`             | `omu`          | `language`   | Original version with German subtitles          |
| `OmeU`            | `omeu`         | `language`   | Original version with English subtitles         |
| `OV`              | `original`     | `language`   | Original version, no dubbing                    |
| `Originalversion` | `ov`           | `language`   | Original version, no dubbing                    |
| `3D`              | `3d`           | `technology` | 3D screening                                    |
| `Preview`         | `preview`      | `event`      | Preview / sneak screening                       |
| `Kino Dienstag`   | `kinodienstag` | `event`      | Promotional "Kino Dienstag" pricing / event     |

> **Note:** Flag names are not guaranteed to be exhaustive. New cinemas or movies may introduce additional values. Use `name` for display and fall back gracefully when `code` or `category` are `null`.

**`Auditorium`** — `{ id?: string, name?: string, seatCount?: integer }`

#### Example request

```bash
curl "http://localhost:8000/api/v1/shows?cinemaId=614&date=2026-06-15&days=3"
```

#### Example response — `200 OK`

```json
[
  {
    "id": "126112767",
    "name": "Star Wars: The Mandalorian and Grogu",
    "beginning": {
      "formatted": "Jun 15, 2026, 2:30 PM",
      "timestamp": 1781526600
    },
    "admission": {
      "formatted": "Jun 15, 2026, 1:30 PM",
      "timestamp": 1781523000
    },
    "duration": "132",
    "flags": [
      { "name": "subtitled OV", "code": "subtitled", "category": "language" }
    ],
    "detailUrl": {
      "url": "https://www.kinoheld.de/cinema/berlin/hackesche-hoefe-kino/show/895747/star-wars-the-mandalorian-and-grogu"
    },
    "isSoldOut": false,
    "movie": {
      "id": "89783",
      "title": "Star Wars: The Mandalorian and Grogu",
      "description": "Das Dunkle Imperium ist gefallen und die imperialen Kriegstreiber sind weiterhin über die Galaxis verstreut...",
      "additionalDescription": "",
      "duration": 132,
      "genres": [
        { "id": "9", "name": "Abenteuer", "urlSlug": null },
        { "id": "11", "name": "Science Fiction", "urlSlug": null },
        { "id": "12", "name": "Action", "urlSlug": null }
      ],
      "directors": [],
      "actors": [],
      "productionYear": null,
      "thumb": {
        "url": "https://media.kinoheld.de/MuFdhdoqRz7pG27QJrSWevk62WQ=/fit-in/400x300/images%2Ffilm%2Fthe-mandalorian-grogu-89783.v17695674879056.jpg",
        "alt": null
      },
      "heroImage": null,
      "detailUrl": {
        "url": "https://www.kinoheld.de/movie/the-mandalorian-grogu"
      },
      "urlSlug": "the-mandalorian-grogu",
      "imdbRating": null,
      "imdbVotes": null
    },
    "auditorium": {
      "id": "2834",
      "name": "Kino 2",
      "seatCount": 100
    }
  }
]
```

---

### `GET /shows/{show_id}`

Fetch a single show by its Kinoheld ID.

#### Path parameters

| Parameter   | Type   | Required | Description         |
|-------------|--------|----------|---------------------|
| `show_id`   | string | Yes      | Kinoheld show ID    |

#### Response

Single `Show` object (same model as `GET /shows`).

#### Example request

```bash
curl "http://localhost:8000/api/v1/shows/126112767"
```

#### Example response — `200 OK`

```json
{
  "id": "126112767",
  "name": "Star Wars: The Mandalorian and Grogu",
  "beginning": {
    "formatted": "Jun 15, 2026, 2:30 PM",
    "timestamp": 1781526600
  },
  "admission": {
    "formatted": "Jun 15, 2026, 1:30 PM",
    "timestamp": 1781523000
  },
  "duration": "132",
  "flags": [
    { "name": "subtitled OV", "code": "subtitled", "category": "language" }
  ],
  "detailUrl": {
    "url": "https://www.kinoheld.de/cinema/berlin/hackesche-hoefe-kino/show/895747/star-wars-the-mandalorian-and-grogu"
  },
  "isSoldOut": false,
  "movie": {
    "id": "89783",
    "title": "Star Wars: The Mandalorian and Grogu",
    "description": "Das Dunkle Imperium ist gefallen und die imperialen Kriegstreiber sind weiterhin über die Galaxis verstreut...",
    "additionalDescription": "",
    "duration": 132,
    "genres": [
      { "id": "9", "name": "Abenteuer", "urlSlug": null },
      { "id": "11", "name": "Science Fiction", "urlSlug": null },
      { "id": "12", "name": "Action", "urlSlug": null }
    ],
    "directors": [],
    "actors": [],
    "productionYear": null,
    "thumb": {
      "url": "https://media.kinoheld.de/MuFdhdoqRz7pG27QJrSWevk62WQ=/fit-in/400x300/images%2Ffilm%2Fthe-mandalorian-grogu-89783.v17695674879056.jpg",
      "alt": null
    },
    "heroImage": null,
    "detailUrl": {
      "url": "https://www.kinoheld.de/movie/the-mandalorian-grogu"
    },
    "urlSlug": "the-mandalorian-grogu",
    "imdbRating": null,
    "imdbVotes": null
  },
  "auditorium": {
    "id": "2834",
    "name": "Kino 2",
    "seatCount": 100
  }
}
```

---

## Genres

### `GET /genres`

List all available movie genres.

#### Response model

Array of `Genre` objects.

| Field     | Type    | Nullable | Description               |
|-----------|---------|----------|---------------------------|
| `id`      | string  | Yes      | Kinoheld genre ID         |
| `name`    | string  | No       | Genre name                |
| `urlSlug` | string  | Yes      | URL-friendly identifier   |

#### Example request

```bash
curl "http://localhost:8000/api/v1/genres"
```

#### Example response — `200 OK`

```json
[
  { "id": "9", "name": "Abenteuer", "urlSlug": "abenteuer" },
  { "id": "12", "name": "Action", "urlSlug": "action" },
  { "id": "8", "name": "Animation", "urlSlug": "animation" },
  { "id": "35", "name": "Comedy", "urlSlug": "comedy" },
  { "id": "18", "name": "Drama", "urlSlug": "drama" },
  { "id": "11", "name": "Science Fiction", "urlSlug": "science-fiction" }
]
```

---

## Cinetixx

### `GET /cinetixx/show-info`

Fetch source-specific Cinetixx legacy showtime data for a known `mandatorId`.

The Cinetixx `mandatorId` is not guaranteed to match the `kino` value used by `https://booking.cinetixx.de/frontend/?kino=...`. Store the correct `mandatorId` alongside your internal cinema record when you have confirmed it.

#### Query parameters

| Parameter    | Type    | Required | Default | Description                  |
|--------------|---------|----------|---------|------------------------------|
| `mandatorId` | integer | Yes      | —       | Cinetixx legacy mandator ID  |

#### Response model

| Field         | Type     | Nullable | Description                             |
|---------------|----------|----------|-----------------------------------------|
| `source`      | string   | No       | Always `"cinetixx"`                     |
| `endpoint`    | string   | No       | Always `"GetShowInfoV6"`                |
| `mandatorId`  | integer  | No       | The requested Cinetixx mandator ID      |
| `contentType` | string   | Yes      | Upstream response content type          |
| `data`        | any JSON | Yes      | Parsed JSON/XML, or plain text fallback |

#### Example request

```bash
curl "http://localhost:8000/api/v1/cinetixx/show-info?mandatorId=1234"
```

#### Example response — `200 OK`

```json
{
  "source": "cinetixx",
  "endpoint": "GetShowInfoV6",
  "mandatorId": 1234,
  "contentType": "application/json",
  "data": {
    "shows": []
  }
}
```

### Normalized Cinetixx Resource Routes

Use `/cinetixx/mandators` when you know a Cinetixx cinema name, city, or booking
`cinemaId` but do not know the legacy `mandatorId`.

| Method | Route | Description |
|--------|-------|-------------|
| GET | `/cinetixx/mandators` | Discover current Cinetixx mandator IDs from the booking cinema index |

Query parameters:

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `search` | string | No | — | Cinema name or city search |
| `cinemaId` | string | No | — | Exact Cinetixx booking cinema ID, e.g. the `kino`/`cinemaId` value from a booking URL |
| `lat`, `lon` | number | No | — | Optional coordinates for distance-aware search |
| `page` | integer | No | — | Upstream result page |
| `limit` | integer | No | `100` | Max results, sent upstream as `pageSize` |

Examples:

```bash
curl "http://localhost:8000/api/v1/cinetixx/mandators?search=ACUDkino"
curl "http://localhost:8000/api/v1/cinetixx/mandators?cinemaId=1627459203"
```

Example response:

```json
[
  {
    "source": "cinetixx",
    "cinemaId": "1627459203",
    "mandatorId": 1627457285,
    "name": "ACUDkino GmbH - Berlin",
    "cinemaName": "ACUDkino GmbH",
    "mandatorName": "Kaczor; Berlin",
    "address": "Veteranenstr. 21, 10119 Berlin",
    "city": "Berlin",
    "postCode": "10119",
    "phone": "",
    "latitude": 52.533608,
    "longitude": 13.40086,
    "hasShows": true,
    "programUrl": "http://booking.cinetixx.de/frontend/#/program/1627459203",
    "prettyProgramUrl": "http://booking.cinetixx.de/Kinoprogramm/acudkino+gmbh-berlin",
    "giftCardsUrl": "http://booking.cinetixx.de/frontend/?gutscheine=1627459203",
    "cardBalanceUrl": "http://booking.cinetixx.de/frontend/?guthaben=1627459203"
  }
]
```

These routes derive Kinoheld-like read-only resources from the legacy show-info/program payload. They only contain fields Cinetixx exposes in the payload for the requested `mandatorId`; use `/cinetixx/show-info` if you need the unmodified source body.

If `mandatorId` is omitted, the live routes use configured `CINETIXX_SYNC_MANDATOR_IDS`. If that list is empty, they return an empty list.

| Method | Route | Description |
|--------|-------|-------------|
| GET | `/cinetixx/cinemas` | Cinemas derived from program rows |
| GET | `/cinetixx/cinemas/{cinema_id}` | One derived Cinetixx cinema |
| GET | `/cinetixx/movies` | Movies/events derived from program rows |
| GET | `/cinetixx/movies/{movie_id}` | One derived Cinetixx movie/event |
| GET | `/cinetixx/shows` | Shows/screenings derived from program rows |
| GET | `/cinetixx/shows/{show_id}` | One derived Cinetixx show |
| GET | `/cinetixx/cities` | Cities derived from program rows |
| GET | `/cinetixx/genres` | Genres/categories derived from program rows |

Common query parameters:

| Parameter | Routes | Description |
|-----------|--------|-------------|
| `mandatorId` | all | Optional Cinetixx mandator ID. Required unless sync IDs are configured. |
| `search` | list routes | Free-text filter where supported |
| `limit` | list routes | Max results, default `100`, max `1000` |
| `date`, `days` | `/cinetixx/shows` | Date window for shows |
| `movieId` | `/cinetixx/shows` | Filter shows by movie/event ID |
| `cinemaId` | `/cinetixx/shows` | Filter shows by Cinetixx cinema ID |

Example:

```bash
curl "http://localhost:8000/api/v1/cinetixx/shows?mandatorId=1234&date=2026-07-13&days=7"
curl "http://localhost:8000/api/v1/cinetixx/movies?mandatorId=1234&search=dune"
```

### Internal Cinetixx Cache Routes

Internal cache-backed Cinetixx routes live under `/internal/cinetixx/*` and mirror the normalized public Cinetixx routes:

```bash
curl "http://localhost:8000/api/v1/internal/cinetixx/health"
curl "http://localhost:8000/api/v1/internal/cinetixx/shows?mandatorId=1234"
curl "http://localhost:8000/api/v1/internal/cinetixx/movies?mandatorId=1234"
```

The cache refreshes periodically from `CINETIXX_SYNC_MANDATOR_IDS`. If an internal request includes a `mandatorId` that is not cached yet, Kinova fetches and stores it on demand.

The cache can also rediscover mandators periodically from
`CINETIXX_SYNC_DISCOVERY_SEARCHES`. Use specific cinema names rather than broad
city searches when you enable this, because each discovered mandator is
pre-fetched during refresh. List-style env values accept JSON arrays or
comma-separated strings, for example `CINETIXX_SYNC_DISCOVERY_SEARCHES=ACUDkino`
or `CINETIXX_SYNC_MANDATOR_IDS=1627457285,42`.

## Unified Internal Layer

Unified cache-backed routes live under `/internal/unified/*`. They combine cached provider data into the same Kinoheld-shaped response models and add a `source` tag plus `sourceId` metadata to every item.

The unified `id` is source-prefixed, for example `kinoheld:123` or `cinetixx:123`. The original upstream ID is also returned as `sourceId`.

| Method | Route | Description |
|--------|-------|-------------|
| GET | `/internal/unified/cinemas` | Unified cached cinemas |
| GET | `/internal/unified/cinemas/{cinema_id}` | One unified cinema |
| GET | `/internal/unified/movies` | Unified cached movies/events |
| GET | `/internal/unified/movies/{movie_id}` | One unified movie/event |
| GET | `/internal/unified/shows` | Unified cached shows |
| GET | `/internal/unified/shows/{show_id}` | One unified show |
| GET | `/internal/unified/cities` | Unified cached cities |
| GET | `/internal/unified/cities/{city_id}` | One unified city |
| GET | `/internal/unified/genres` | Unified cached genres/categories |

Common query parameters:

| Parameter | Description |
|-----------|-------------|
| `source` | Optional source filter. Currently `kinoheld`, `cinetixx`, or omitted/`all`. |
| `mandatorId` | Optional Cinetixx mandator ID. Used for Cinetixx on-demand cache fill. |
| `search` | Free-text search where supported by the resource. |
| `limit` | Max results, default `100`, max `1000`. |
| `date`, `days`, `movieId`, `cinemaId` | Show filters for `/internal/unified/shows`. |

Example:

```bash
curl "http://localhost:8000/api/v1/internal/unified/movies?mandatorId=1234"
curl "http://localhost:8000/api/v1/internal/unified/shows?source=cinetixx&mandatorId=1234"
curl "http://localhost:8000/api/v1/internal/unified/movies/cinetixx:456?mandatorId=1234"
```

---

## Frontend integration tips

### Handling nullable fields

Many fields in Kinoheld responses are optional. Frontends should always guard against `null`:

- **Images:** `url` may be `null`; show a fallback poster / cinema placeholder.
- **Image alt text:** `alt` is frequently `null`. Use the movie/cinema name as fallback for accessibility.
- **IMDb fields:** `imdbRating` and `imdbVotes` are often `null`; hide the IMDb section when missing.
- **Production year:** may be `null`; omit the year label when unavailable.
- **Show `movie` object:** can be sparse (empty `directors`/`actors`, null `productionYear`). Use it for the show card but fetch `GET /movies/{id}` if you need full cast/crew.

### Showing language / subtitle info

Use `show.flags` to render badges. Display the `name` value directly:

- `subtitled OV` → "Subtitled OV"
- `OmU` → "OmU"
- `OmeU` → "OmeU"
- `OV` / `Originalversion` → "OV"
- `3D` → "3D"

Do not rely only on `code` or `category` — new cinemas may introduce flag names your app has not seen before.

### Search UX

- `/cinemas?search=...` and `/movies?search=...` are free-text searches. Debounce input to ~300 ms.
- `/shows` always requires `cinemaId`. Typical flow: user picks a cinema → list movies/shows for that cinema.
- `/cities/me` can fail with `404`. Always have a manual city picker fallback.

### Caching

- `GET /genres` — cache for the whole session (rarely changes).
- `GET /cities` — cache for the whole session.
- `GET /cinemas` — cache search results for the session or invalidate when location changes.
- `GET /shows` — cache per cinema/date; refresh when the user changes date or cinema.
- `GET /movies/{id}` — cache indefinitely; invalidate only if the movie data looks stale.

---

## Generating TypeScript types

Because the API exposes an OpenAPI spec at `/openapi.json`, you can auto-generate typed clients:

```bash
# Using openapi-typescript
npx openapi-typescript http://localhost:8000/openapi.json -o kinova-api.d.ts

# Or generate a full fetch client with openapi-fetch
npx openapi-typescript http://localhost:8000/openapi.json -o kinova-api.d.ts
npm install openapi-fetch
```

This gives you strongly typed request parameters and response shapes directly from the running backend.

---

## Quick command reference

```bash
# Health
curl "http://localhost:8000/api/v1/health"

# Cities
curl "http://localhost:8000/api/v1/cities?search=Berlin&limit=5"
curl "http://localhost:8000/api/v1/cities/me"

# Cinemas
curl "http://localhost:8000/api/v1/cinemas?search=Berlin&limit=3"
curl "http://localhost:8000/api/v1/cinemas/614"

# Movies
curl "http://localhost:8000/api/v1/movies?search=Star%20Wars&limit=3"
curl "http://localhost:8000/api/v1/movies/89783"

# Shows
curl "http://localhost:8000/api/v1/shows?cinemaId=614&date=2026-06-15&days=3"
curl "http://localhost:8000/api/v1/shows/126112767"

# Genres
curl "http://localhost:8000/api/v1/genres"

# Cinetixx source-specific showtime data
curl "http://localhost:8000/api/v1/cinetixx/show-info?mandatorId=1234"
curl "http://localhost:8000/api/v1/cinetixx/shows?mandatorId=1234"
curl "http://localhost:8000/api/v1/internal/cinetixx/shows?mandatorId=1234"
curl "http://localhost:8000/api/v1/internal/unified/movies?mandatorId=1234"
```

---

## Changelog

| Date       | Author | Change                  |
|------------|--------|-------------------------|
| 2026-06-15 | —      | Initial frontend guide  |
