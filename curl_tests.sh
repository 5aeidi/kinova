#!/usr/bin/env bash
# Test requests for the Kinova API running on localhost:8000.
# Update BASE_URL below if your server is running elsewhere.

set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8000}"
API_PREFIX="/api/v1"

echo "=== Health ==="
curl -s "${BASE_URL}${API_PREFIX}/health" | jq .

echo ""
echo "=== List cinemas (default) ==="
curl -s "${BASE_URL}${API_PREFIX}/cinemas" | jq .

echo ""
echo "=== Search cinemas by city/location ==="
curl -s -G "${BASE_URL}${API_PREFIX}/cinemas" \
  --data-urlencode "location=Berlin" \
  --data-urlencode "limit=5" | jq .

echo ""
echo "=== Get cinema by ID (replace <cinema_id>) ==="
curl -s "${BASE_URL}${API_PREFIX}/cinemas/<cinema_id>" | jq .

echo ""
echo "=== List movies (default) ==="
curl -s "${BASE_URL}${API_PREFIX}/movies" | jq .

echo ""
echo "=== Search movies ==="
curl -s -G "${BASE_URL}${API_PREFIX}/movies" \
  --data-urlencode "search=Dune" \
  --data-urlencode "location=Berlin" \
  --data-urlencode "limit=5" | jq .

echo ""
echo "=== Get movie by ID (replace <movie_id>) ==="
curl -s "${BASE_URL}${API_PREFIX}/movies/<movie_id>" | jq .

echo ""
echo "=== List shows for a cinema (replace <cinema_id>) ==="
curl -s -G "${BASE_URL}${API_PREFIX}/shows" \
  --data-urlencode "cinemaId=<cinema_id>" \
  --data-urlencode "date=$(date +%Y-%m-%d)" \
  --data-urlencode "days=3" | jq .

echo ""
echo "=== List shows for a cinema + movie (replace IDs) ==="
curl -s -G "${BASE_URL}${API_PREFIX}/shows" \
  --data-urlencode "cinemaId=<cinema_id>" \
  --data-urlencode "movieId=<movie_id>" \
  --data-urlencode "date=$(date +%Y-%m-%d)" | jq .

echo ""
echo "=== Get show by ID (replace <show_id>) ==="
curl -s "${BASE_URL}${API_PREFIX}/shows/<show_id>" | jq .

echo ""
echo "=== List cities ==="
curl -s "${BASE_URL}${API_PREFIX}/cities" | jq .

echo ""
echo "=== Search cities ==="
curl -s -G "${BASE_URL}${API_PREFIX}/cities" \
  --data-urlencode "search=Berlin" \
  --data-urlencode "limit=5" | jq .

echo ""
echo "=== City by IP ==="
curl -s "${BASE_URL}${API_PREFIX}/cities/me" | jq .

echo ""
echo "=== List genres ==="
curl -s "${BASE_URL}${API_PREFIX}/genres" | jq .
