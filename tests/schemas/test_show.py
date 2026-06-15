"""Tests for show schemas."""

import datetime as dt

from app.schemas.show import ShowSearchParams


class TestShowSearchParams:
    def test_populate_by_name_allows_field_name(self):
        params = ShowSearchParams(cinema_id="123", movie_id="456", days=3)
        assert params.cinema_id == "123"
        assert params.movie_id == "456"
        assert params.days == 3

    def test_json_dump_serializes_date(self):
        params = ShowSearchParams(cinema_id="123", date=dt.date(2024, 6, 15), days=3)
        dumped = params.model_dump(mode="json", by_alias=True)
        assert dumped["cinemaId"] == "123"
        assert dumped["date"] == "2024-06-15"
        assert dumped["days"] == 3
