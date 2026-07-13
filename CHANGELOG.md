# Changelog

## Unreleased

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
