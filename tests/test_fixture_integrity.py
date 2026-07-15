import json
import re
from datetime import datetime
from pathlib import Path

from bc_auction.parsers import parse_search_results

_FIXTURES = Path(__file__).parent / "fixtures"
_MANIFEST = _FIXTURES / "manifest.json"
_EMAIL = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)
_SESSION_VALUE = re.compile(r"(?i)sessionID=([^&^\s'\"<>]+)")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_RESULTS_URL = "https://www.bcauction.ca/open.dll/submitDocSearch"


def test_fixture_manifest_covers_every_html_fixture() -> None:
    manifest = json.loads(_MANIFEST.read_text(encoding="utf-8"))

    assert manifest["version"] == 1
    assert set(manifest["fixtures"]) == {path.name for path in _FIXTURES.glob("*.html")}

    for fixture_name, metadata in manifest["fixtures"].items():
        assert set(metadata) == {
            "capture",
            "route",
            "captured_at",
            "source_content_type",
            "declared_charset",
            "decoded_as",
            "stored_encoding",
            "scope",
            "sanitization",
            "source_sha256",
        }
        assert metadata["route"].startswith("/")
        assert metadata["source_content_type"].startswith("text/html")
        assert metadata["declared_charset"] is None or isinstance(
            metadata["declared_charset"], str
        )
        assert metadata["decoded_as"] in {"utf-8", "windows-1252"}
        assert metadata["stored_encoding"] == "utf-8"
        assert metadata["scope"] in {"complete", "reduced"}
        assert metadata["sanitization"]
        assert _SHA256.fullmatch(metadata["source_sha256"])
        assert datetime.fromisoformat(metadata["captured_at"].replace("Z", "+00:00")).tzinfo

        text = (_FIXTURES / fixture_name).read_text(encoding=metadata["stored_encoding"])
        assert "\ufffd" not in text
        assert "mailto:" not in text.casefold()
        assert _EMAIL.search(text) is None
        assert set(_SESSION_VALUE.findall(text)) <= {"SESSION_ID"}


def test_populated_result_fixtures_contain_only_synthetic_bid_amounts() -> None:
    expected_ranges = {
        "results-open-page-1.html": range(100, 130),
        "results-open-page-2.html": range(200, 230),
        "results-open-highest-price.html": range(900, 870, -1),
    }

    for fixture_name, expected_values in expected_ranges.items():
        page = parse_search_results(
            (_FIXTURES / fixture_name).read_text(encoding="utf-8"),
            _RESULTS_URL,
        )
        assert [record.current_bid for record in page.records] == [
            value for value in expected_values
        ]
