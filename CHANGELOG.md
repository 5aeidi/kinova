# Changelog

## Unreleased

### Frontend API: Yorck Kinogruppe

#### Added

- Yorck source routes under `/api/v1/yorck/*`: `/cinemas`, `/movies`, `/shows`, `/cities`, and `/genres` normalized from Yorck's public Next.js data endpoints (no scraping; the site serves its full programme as JSON).
- Cache-backed Yorck routes under `/api/v1/internal/yorck/*` plus `/api/v1/internal/yorck/health` for cache status.
- Yorck results in the unified routes: `source=yorck` filters them, `yorck:<id>` prefixed IDs address them, and omitting `source` now returns Kinoheld, Cinetixx, and Yorck together.
- Rich Yorck movie metadata merged from each film's detail page: directors, cast, writers, description, countries, year, FSK, content descriptors, distributor, TMDB ID, trailer, poster, and hero image. Special events and presale ("coming soon") films are included and flagged via `isSpecial`/`isPresale`.
- Yorck shows carry ISO-8601 start times and `formats` (`OV`/`OmU`/`OmeU`/`DF`) mapped directly onto the existing show flags.

#### Changed

- Yorck show `bookingUrl` (and the unified show `detailUrl`) now deep-links into the yorck.de checkout for that specific session — `/checkout/seats?sessionid=…` for screens with allocated seating, `/checkout/tickets?sessionid=…` otherwise — instead of pointing at the film's page. The `allocatedSeating` flag is missing from the Next.js programme data, so it is read once per refresh from the public Contentful space the website itself queries; `YORCK_FETCH_SESSION_SEATING=false` skips that lookup and links every session to seat selection.
- Yorck's public Contentful space and delivery token are now re-scraped from the site's JS bundle when Contentful rejects the configured pair, the same self-healing treatment the Next.js `buildId` already gets, so a rotation upstream no longer needs a redeploy.
- Yorck cache population runs in the background at startup and refreshes hourly by default (`YORCK_SYNC_INTERVAL_SECONDS`), mirroring Cinetixx. The Next.js `buildId` is resolved automatically and re-resolved when Yorck deploys a new build.

### Frontend API: Cinetixx and Unified Data

#### Added

- Cinetixx source routes under `/api/v1/cinetixx/*`:
  - `/mandators` for cinema/mandator lookup
  - `/cinemas`, `/movies`, `/shows`, `/cities`, and `/genres` for normalized Cinetixx data
- Cache-backed Cinetixx routes under `/api/v1/internal/cinetixx/*` for lower-latency reads.
- Unified cache-backed routes under `/api/v1/internal/unified/*` that combine Kinoheld and Cinetixx results:
  - `/cinemas`, `/movies`, `/shows`, `/cities`, and `/genres`
  - Set `source=kinoheld` or `source=cinetixx` to filter; omit it to receive all sources.
- Unified resources include `source` and `sourceId`. Their `id` is source-prefixed, for example `kinoheld:123` or `cinetixx:456`, so frontend clients must treat IDs as strings.
- Cinetixx cinemas now include booking-index metadata when available: address, postal code, phone, coordinates, and programme URLs. This metadata also appears in unified cinema responses.

#### Changed

- Cinetixx data is discovered and cached automatically. Frontend requests to normalized Cinetixx or unified routes do not need to send `mandatorId`.
- A `mandatorId` is Cinetixx's internal operator/tenant identifier used by its legacy programme API. It remains an optional filter for a single Cinetixx operator and is still required only by the raw `/api/v1/cinetixx/show-info` endpoint.
- Cinetixx discovery uses the public booking search because Cinetixx does not provide an unauthenticated all-cinemas directory. Initial cache population may take time; use `/api/v1/internal/cinetixx/health` to inspect cache availability before rendering Cinetixx-only results.
- Cinetixx cache population runs in the background at application startup and refreshes hourly by default. It does not delay unrelated API requests.
- Cinetixx does not reliably provide cinema images in the public booking index. Frontend clients should treat cinema image fields as optional; movie artwork is provided separately when available.

#### Frontend Guidance

- Prefer `/api/v1/internal/unified/*` for source-agnostic browse and search views.
- Prefer `/api/v1/internal/cinetixx/*` when the UI specifically requires Cinetixx data.
- Keep `source` and `sourceId` when storing or linking result data. Do not assume a Kinoheld numeric ID and a Cinetixx numeric ID share the same namespace.
- Handle an empty Cinetixx result while its background cache is warming; retry after checking `/api/v1/internal/cinetixx/health`.
