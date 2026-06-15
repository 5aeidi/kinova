"""Tests for cinema schemas."""

from app.schemas.cinema import Cinema, CinemaSearchParams


class TestCinema:
    def test_accepts_image_lists(self):
        cinema = Cinema.model_validate(
            {
                "id": "123",
                "name": "Kino Berlin",
                "thumbnail": [{"url": "https://example.com/thumb.png"}],
                "heroImage": [{"url": "https://example.com/hero.jpg"}],
            },
        )
        assert cinema.thumbnail is not None
        assert str(cinema.thumbnail.url) == "https://example.com/thumb.png"
        assert cinema.hero_image is not None
        assert str(cinema.hero_image.url) == "https://example.com/hero.jpg"

    def test_accepts_postcode_object(self):
        cinema = Cinema.model_validate(
            {
                "id": "123",
                "name": "Kino",
                "postcode": {"id": "1", "postcode": "10115"},
            },
        )
        assert cinema.postcode == "10115"

    def test_accepts_postcode_string(self):
        cinema = Cinema.model_validate(
            {
                "id": "123",
                "name": "Kino",
                "postcode": "10115",
            },
        )
        assert cinema.postcode == "10115"


class TestCinemaSearchParams:
    def test_populate_by_name_allows_field_name(self):
        params = CinemaSearchParams(only_bookable=True, is_open_air=False)
        assert params.only_bookable is True
        assert params.is_open_air is False

    def test_json_dump_uses_aliases(self):
        params = CinemaSearchParams(only_bookable=True, is_drive_in=True)
        dumped = params.model_dump(mode="json", by_alias=True)
        assert dumped["onlyBookable"] is True
        assert dumped["isDriveIn"] is True
        assert dumped["limit"] == 20
