import json
import os
import re
import sys
from datetime import UTC, datetime

import httpx

from bc_auction.client import AuctionClient
from bc_auction.errors import ScraperError
from bc_auction.parsers import parse_item_detail, parse_search_results, reconcile_search_result

_LIVE_SMOKE_FLAG = "BC_AUCTION_LIVE_SMOKE"
_SESSION_ID = re.compile(r"(?i)(sessionID=)[^&\s'\"<>]+")


def main() -> int:
    if os.environ.get(_LIVE_SMOKE_FLAG) != "1":
        print(f"live smoke requires {_LIVE_SMOKE_FLAG}=1", file=sys.stderr)
        return 2

    try:
        with AuctionClient() as client:
            search_page = client.search_open_auctions()
            results = parse_search_results(search_page.decode().text, search_page.url)
            if not results.records:
                _print_diagnostic({"status": "no_active_listings"})
                return 0

            search_result = results.records[0]
            detail_page = client.get_item_detail(str(search_result.request_url))
            detail = parse_item_detail(detail_page.decode().text, detail_page.url)
            record = reconcile_search_result(search_result, detail)
    except (ScraperError, httpx.HTTPError, ValueError) as exc:
        print(f"live smoke failed: {_redact_session_id(str(exc))}", file=sys.stderr)
        return 1

    _print_diagnostic(
        {
            "status": "ok",
            "source_id": record.source_id,
            "canonical_source_url": str(record.canonical_source_url),
            "image_count": len(record.image_urls),
            "checked_at": datetime.now(UTC).isoformat(),
        }
    )
    return 0


def _print_diagnostic(diagnostic: dict[str, object]) -> None:
    print(json.dumps(diagnostic, sort_keys=True))


def _redact_session_id(value: str) -> str:
    return _SESSION_ID.sub(r"\1REDACTED", value)


if __name__ == "__main__":
    raise SystemExit(main())
