from pathlib import Path

import pytest
from sqlalchemy.engine import make_url

from bc_auction.database import DatabaseConfigurationError, resolve_database_url
from bc_auction.runtime import OperationsSettings, RuntimeConfigurationError


def test_resolve_database_url_uses_password_file(tmp_path: Path) -> None:
    password_file = tmp_path / "database-password"
    password_file.write_text(" secret value \n", encoding="utf-8")

    resolved = resolve_database_url(
        environ={
            "BC_AUCTION_DATABASE_HOST": "postgres",
            "BC_AUCTION_DATABASE_NAME": "bc_auction",
            "BC_AUCTION_DATABASE_USER": "bc_auction_api",
            "BC_AUCTION_DATABASE_PASSWORD_FILE": str(password_file),
        }
    )

    url = make_url(resolved)
    assert (url.username, url.password, url.host, url.port, url.database) == (
        "bc_auction_api",
        "secret value",
        "postgres",
        5432,
        "bc_auction",
    )


def test_resolve_database_url_rejects_incomplete_secret_file_settings() -> None:
    with pytest.raises(DatabaseConfigurationError, match="incomplete"):
        resolve_database_url(environ={"BC_AUCTION_DATABASE_HOST": "postgres"})


@pytest.mark.parametrize("database_url", ("postgresql://localhost/bc_auction", "://bad"))
def test_resolve_database_url_rejects_non_psycopg_or_invalid_direct_urls(
    database_url: str,
) -> None:
    with pytest.raises(DatabaseConfigurationError):
        resolve_database_url(database_url)


def test_operations_settings_validate_schedule_and_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BC_AUCTION_SCRAPE_TIMES", "18:00,06:00,12:00")
    monkeypatch.setenv("BC_AUCTION_SCRAPE_LIMIT", "1000")

    settings = OperationsSettings.from_environment()

    assert settings.scrape_times == ("06:00", "12:00", "18:00")
    assert settings.scrape_limit == 1000


@pytest.mark.parametrize("scrape_limit", ("zero", "0", "-1"))
def test_operations_settings_reject_invalid_scrape_limits(
    monkeypatch: pytest.MonkeyPatch,
    scrape_limit: str,
) -> None:
    monkeypatch.setenv("BC_AUCTION_SCRAPE_LIMIT", scrape_limit)

    with pytest.raises(RuntimeConfigurationError, match="BC_AUCTION_SCRAPE_LIMIT"):
        OperationsSettings.from_environment()


def test_operations_settings_reject_invalid_schedule(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BC_AUCTION_SCRAPE_TIMES", "tomorrow")

    with pytest.raises(RuntimeConfigurationError, match="SCRAPE_TIMES"):
        OperationsSettings.from_environment()
