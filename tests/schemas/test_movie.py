"""Tests for movie schemas."""

from app.schemas.movie import Movie, MovieSearchParams


class TestMovie:
    def test_accepts_image_lists(self):
        movie = Movie.model_validate(
            {
                "id": "456",
                "title": "Dune",
                "thumb": [{"url": "https://example.com/thumb.jpg"}],
                "heroImage": [{"url": "https://example.com/hero.jpg"}],
            },
        )
        assert movie.thumb is not None
        assert str(movie.thumb.url) == "https://example.com/thumb.jpg"
        assert movie.hero_image is not None
        assert str(movie.hero_image.url) == "https://example.com/hero.jpg"

    def test_accepts_single_image_object(self):
        movie = Movie.model_validate(
            {
                "id": "456",
                "title": "Dune",
                "thumb": {"url": "https://example.com/thumb.jpg"},
                "heroImage": {"url": "https://example.com/hero.jpg"},
            },
        )
        assert movie.thumb is not None
        assert str(movie.thumb.url) == "https://example.com/thumb.jpg"


class TestMovieSearchParams:
    def test_populate_by_name_allows_field_name(self):
        params = MovieSearchParams(search="Dune", limit=5)
        assert params.search == "Dune"
        assert params.limit == 5

    def test_json_dump_uses_aliases(self):
        params = MovieSearchParams(search="Dune", location="Berlin")
        dumped = params.model_dump(mode="json", by_alias=True)
        assert dumped["search"] == "Dune"
        assert dumped["location"] == "Berlin"
        assert dumped["limit"] == 20
