"""Tests for application settings parsing."""

from app.core.config import Settings


def test_list_settings_accept_blank_values() -> None:
    settings = Settings(
        _env_file=None,
        cinetixx_sync_mandator_ids="",
        cinetixx_sync_discovery_searches="",
        kinoheld_sync_cinema_ids="",
    )

    assert settings.cinetixx_sync_mandator_ids == []
    assert settings.cinetixx_sync_discovery_searches == []
    assert settings.kinoheld_sync_cinema_ids == []


def test_list_settings_accept_comma_separated_values() -> None:
    settings = Settings(
        _env_file=None,
        cinetixx_sync_mandator_ids="1627457285, 42",
        cinetixx_sync_discovery_searches="ACUDkino, Berlin",
        kinoheld_sync_cinema_ids="123, abc",
    )

    assert settings.cinetixx_sync_mandator_ids == [1627457285, 42]
    assert settings.cinetixx_sync_discovery_searches == ["ACUDkino", "Berlin"]
    assert settings.kinoheld_sync_cinema_ids == ["123", "abc"]


def test_list_settings_still_accept_json_arrays() -> None:
    settings = Settings(
        _env_file=None,
        cinetixx_sync_mandator_ids="[1627457285, 42]",
        cinetixx_sync_discovery_searches='["ACUDkino", "Berlin"]',
        kinoheld_sync_cinema_ids='["123", "abc"]',
    )

    assert settings.cinetixx_sync_mandator_ids == [1627457285, 42]
    assert settings.cinetixx_sync_discovery_searches == ["ACUDkino", "Berlin"]
    assert settings.kinoheld_sync_cinema_ids == ["123", "abc"]
