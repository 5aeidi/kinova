# Changelog

## Unreleased

### Fixed

- `/internal/shows` served stale or empty programmes for a subset of cinemas. Kinoheld only publishes about a week ahead, so a request for a later date cached a day that was empty or half-filled at the time; the pre-warm window never covered that date again, and a present-but-empty entry was treated as cached, so the frozen day was served until it arrived. Cached days now carry a fetch timestamp and are re-fetched once they age past `KINOHELD_SHOW_CACHE_TTL_SECONDS` (default 1800), and the periodic refresh re-fetches every cached future date within `KINOHELD_SHOW_CACHE_HORIZON_DAYS` (default 21) rather than only its own pre-warm window. Emptiness alone is still not treated as a miss, so genuinely dark venues do not trigger repeated upstream calls.

### Kinoheld cache

#### Changed

- The show cache no longer keeps a separate copy of the same film for every screening. Kinoheld embeds a full movie record — description, cast, directors, genres — in each show, so a film screened 26 times arrived as 26 identical `Movie` objects; they are now collapsed onto one instance per movie ID as shows are fetched. Measured against live data this drops the show cache by **56%** (9.6 KB to 4.2 KB per show), with no change to the read path or to any response. Responses are collapsed as they arrive rather than at the end of the batch, so peak allocation falls by the same amount (32.8 MB to 14.8 MB per 3 500 shows) instead of the process keeping a high-water mark it never returns.

### Natural-language search

#### Fixed

- Genre searches returned nothing whenever the user's wording did not exactly equal a catalogue tag — "comedy"/"funny" never matched a German catalogue carrying `Komödie`, `Actionkomödie`, and `Familienkomödie`. The parser is now grounded in the real tags, and matching tolerates compound labels so `Komödie` also matches `Actionkomödie`.

#### Added

- `NL_GENRE_VOCABULARY_LIMIT` (default `60`): how many real genre tags are shown to the LLM, ranked by how many cached movies carry each one, so a short list still covers most queries while keeping prompt tokens down. `0` restores the previous ungrounded prompt.

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
