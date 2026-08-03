# Frontend Update: Yorck Kinogruppe Data Source

Kinova now serves a third data source alongside Kinoheld and Cinetixx: **Yorck Kinogruppe** — Berlin's largest art-house cinema chain (15 venues: Babylon Kreuzberg, Delphi Filmpalast, Kino International, delphi LUX, Passage, Rollberg, and others). This adds roughly **200 movies and 800+ upcoming sessions**, all Berlin-based.

All routes below are relative to the usual base prefix `/api/v1`.

---

## TL;DR for existing frontends

- **Nothing breaks.** All existing routes and response shapes are unchanged.
- The unified routes (`/internal/unified/*`) now return Yorck items **by default**. If your UI filters by `source`, add `yorck` to the accepted values; if it renders `source` badges, expect a new `"yorck"` value.
- Unified Yorck IDs look like `yorck:HO00005912` or `yorck:babylon-kreuzberg` (slugs, not numbers — keep treating IDs as opaque strings).
- Prefer the cache-backed `/internal/yorck/*` routes in the UI; the non-internal `/yorck/*` routes hit yorck.de live on every request and are slower.

---

## New routes

### Cache-backed (use these): `/internal/yorck/*`

| Method | Route | Description |
|--------|-------|-------------|
| GET | `/internal/yorck/health` | Cache status: `last_refresh` + cached counts |
| GET | `/internal/yorck/cinemas` | List/search cinemas |
| GET | `/internal/yorck/cinemas/{id}` | One cinema by slug (`babylon-kreuzberg`) or Vista ID (`1002`) |
| GET | `/internal/yorck/movies` | List/search movies & specials |
| GET | `/internal/yorck/movies/{id}` | One movie by ID, slug (`dreams`), or Vista ID (`HO00005912`) |
| GET | `/internal/yorck/shows` | List/filter sessions |
| GET | `/internal/yorck/shows/{id}` | One session by ID (`1002-15565`) |
| GET | `/internal/yorck/cities` | Cities derived from cinema addresses |
| GET | `/internal/yorck/genres` | Genres/labels from the programme |

### Live passthrough (debugging / freshness checks): `/yorck/*`

Same resource routes without the `/internal` prefix. They fetch yorck.de on demand — expect multi-second latency and possible `502` if yorck.de is down. Don't use them in user-facing views.

### Query parameters

- All list routes: `search` (free text), `limit` (default 100, max 1000).
- `/yorck/shows` and `/internal/yorck/shows` additionally: `date` (YYYY-MM-DD), `days` (1–30, window starting at `date`), `movieId`, `cinemaId` (slug or Vista ID).

Examples:

```bash
curl "/api/v1/internal/yorck/shows?cinemaId=babylon-kreuzberg&date=2026-07-27&days=3"
curl "/api/v1/internal/yorck/movies?search=dreams"
curl "/api/v1/internal/yorck/cinemas/kino-international"
```

---

## Response shapes

### Cinema

```json
{
  "id": "babylon-kreuzberg",
  "source": "yorck",
  "slug": "babylon-kreuzberg",
  "vistaId": "1002",
  "name": "Babylon Kreuzberg",
  "shortName": "BAB",
  "address": "Dresdener Straße 126, 10999 Berlin",
  "postCode": "10999",
  "city": "Berlin",
  "district": "Kreuzberg",
  "latitude": 52.50066,
  "longitude": 13.41694,
  "phone": "030 322 931 322",
  "email": "hilfe@yorck.de",
  "numberOfAuditoriums": 2,
  "accessibility": "Fully accessible",
  "shortDescription": "…",
  "heroImageUrl": "https://images.ctfassets.net/…",
  "detailUrl": "https://www.yorck.de/en/cinemas/babylon-kreuzberg"
}
```

### Movie

Yorck movies are unusually rich — richer than Kinoheld or Cinetixx:

```json
{
  "id": "HO00005912",
  "source": "yorck",
  "slug": "dreams",
  "vistaId": "HO00005912",
  "title": "Dreams",
  "originalTitle": "Dreams: Sueños",
  "originalLanguage": "Spanish, English",
  "tagline": "Erotic thriller with Jessica Chastain",
  "description": "…full synopsis…",
  "runtime": 98,
  "genres": ["Thriller", "Drama"],
  "fsk": 16,
  "descriptors": ["Violence", "Strong Language"],
  "releaseDate": "2026-07-23",
  "year": 2026,
  "directors": ["Michel Franco"],
  "actors": ["Jessica Chastain", "Isaac Hernández"],
  "writers": ["Michel Franco"],
  "countries": ["Mexico", "USA"],
  "distributor": "Weltkino",
  "tmdbId": 1134463,
  "trailerUrl": "https://www.youtube.com/watch?v=…",
  "posterUrl": "https://images.ctfassets.net/…",
  "heroImageUrl": "https://images.ctfassets.net/…",
  "detailUrl": "https://www.yorck.de/en/films/dreams",
  "isSpecial": false,
  "isPresale": false,
  "yorckPick": false
}
```

Notable fields:

- **`fsk`** — German age rating (0/6/12/16/18) as a plain integer.
- **`descriptors`** — content warnings; render near the age rating if you show them.
- **`tmdbId`** — TMDB movie ID, usable to fetch extra artwork/ratings client-side.
- **`trailerUrl`** — a YouTube watch URL when a trailer exists.
- **`isSpecial: true`** — a curated series/event (e.g. "Mongay"), not a regular film. These may lack runtime, FSK, and release date; their IDs are `special-<slug>`.
- **`isPresale: true`** — a coming-soon film in presale; usually has **no sessions yet**. Good for a "Coming soon" rail; filter these out of "Now playing".
- **`yorckPick`** — Yorck's own editorial highlight flag.

### Show (session)

```json
{
  "id": "1002-15565",
  "source": "yorck",
  "movieId": "HO00005912",
  "movieTitle": "Dreams",
  "cinemaId": "babylon-kreuzberg",
  "cinemaVistaId": "1002",
  "cinemaName": "Babylon Kreuzberg",
  "city": "Berlin",
  "beginsAt": "2026-07-26T21:00:00+01:00",
  "date": "2026-07-26",
  "formats": ["OmU"],
  "flags": ["OmU"],
  "accessibility": "Fully accessible",
  "runtime": 98,
  "bookingUrl": "https://www.yorck.de/en/checkout/seats?sessionid=1002-15565"
}
```

- **`formats`** uses the same vocabulary you already handle: `OV`, `OmU`, `OmeU`, `DF`. It's duplicated into `flags` for consistency with other sources.
- **`beginsAt`** is ISO 8601 with an offset, exactly as yorck.de publishes it. Parse it as a full datetime and display in local time — do not assume the offset is always `+02:00`/CEST (upstream currently emits `+01:00`).
- **`bookingUrl`** deep-links into the yorck.de checkout for **that specific session** — send users straight there instead of to the film page. It lands on `/checkout/seats?sessionid=…` for screens with allocated seating (the large majority) and `/checkout/tickets?sessionid=…` for the rest, mirroring what Yorck's own showtime buttons do. Only if the session has no usable ID does it fall back to the film's detail page.

---

## Unified layer changes (`/internal/unified/*`)

- Yorck is now included by default in `/internal/unified/{cinemas,movies,shows,cities,genres}`.
- `source=yorck` returns only Yorck items; `source=kinoheld` / `source=cinetixx` behave as before.
- Unified IDs: `yorck:HO00005912` (movie), `yorck:babylon-kreuzberg` (cinema), `yorck:1002-15565` (show). `sourceId` carries the raw Yorck ID.
- Get-by-ID accepts prefixed IDs: `GET /internal/unified/movies/yorck:dreams`.
- In the unified movie shape, Yorck's `tagline` maps to `additionalDescription`, `poster`/`hero` map to `thumb`/`heroImage`, and `slug` maps to `urlSlug`. Yorck-only fields (`fsk`, `tmdbId`, `trailerUrl`, `isSpecial`, `isPresale`, …) are **not** in the unified shape — call `/internal/yorck/movies/{id}` when you need them.
- `mandatorId` is Cinetixx-only and ignored for Yorck.

---

## Caching & operational notes

- The Yorck cache populates **in the background at startup** and refreshes **hourly** (same policy as Cinetixx). A request arriving before the first refresh triggers an on-demand fill, so very early requests may be slow once.
- Check readiness with `GET /internal/yorck/health` → `last_refresh` is `null` until the first successful refresh; counts should be ~15 cinemas / ~200 movies / ~800 shows when healthy.
- If yorck.de is temporarily unreachable, the cache keeps serving the last good data.

## Data caveats

- **Berlin only.** All Yorck cinemas are in Berlin. City names derived from addresses include `Berlin`, `Berlin-Kreuzberg`, and `Berlin-Neukölln` — treat them all as Berlin if you group by city.
- **Images** are Contentful CDN URLs (`images.ctfassets.net`). You can append Contentful image params (e.g. `?w=400&fm=webp`) for resizing.
- **Movies without sessions** exist (presales, some specials); don't assume every movie has shows.
- Movie/cinema lookups accept slug **or** Vista ID interchangeably, so links built from either will resolve.
