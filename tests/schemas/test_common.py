"""Tests for shared schema helpers."""

import pytest

from app.schemas.common import Image, Url, first_image


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        ({"url": "https://example.com/image.png"}, {"url": "https://example.com/image.png"}),
        (
            [{"url": "https://example.com/1.png"}, {"url": "https://example.com/2.png"}],
            {"url": "https://example.com/1.png"},
        ),
        ([], None),
    ],
)
def test_first_image(value, expected):
    assert first_image(value) == expected


class TestImageModel:
    def test_accepts_single_object(self):
        image = Image.model_validate({"url": "https://example.com/a.jpg", "alt": "A"})
        assert image.url is not None
        assert str(image.url) == "https://example.com/a.jpg"
        assert image.alt == "A"

    def test_accepts_list_and_takes_first(self):
        image = Image.model_validate(
            first_image(
                [
                    {"url": "https://example.com/first.jpg"},
                    {"url": "https://example.com/second.jpg"},
                ],
            )
        )
        assert image is not None
        assert str(image.url) == "https://example.com/first.jpg"


class TestUrlModel:
    def test_accepts_url_string(self):
        url = Url.model_validate({"url": "https://example.com/page"})
        assert str(url.url) == "https://example.com/page"
