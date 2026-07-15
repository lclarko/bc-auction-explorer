from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from bc_auction.errors import ParserContractError
from bc_auction.models import SearchResultRecord


def parse_search_results(html: str, base_url: str) -> tuple[SearchResultRecord, ...]:
    soup = BeautifulSoup(html, "lxml")
    detail_rows = soup.select('tr[name="infoDetail"]')

    if not detail_rows:
        # todo: distinguish an empty result set from a changed page using a live fixture.
        return ()

    records: list[SearchResultRecord] = []
    for detail_row in detail_rows:
        summary_row = detail_row.find_previous_sibling("tr")
        if summary_row is None:
            raise ParserContractError("detail row has no preceding summary row")

        summary_cells = tuple(_text(cell) for cell in summary_row.find_all(["td", "th"], recursive=False))
        location_cell = summary_row.select_one('td[width="75"]')
        location_raw = _text(location_cell) if location_cell is not None else None
        source_url = _find_item_url(summary_row, detail_row, base_url)

        records.append(
            SearchResultRecord(
                source_url=source_url,
                # todo: derive the stable source ID after a live item URL is captured.
                source_id=None,
                location_raw=location_raw,
                summary_cells=summary_cells,
                detail_text=_text(detail_row),
            )
        )

    return tuple(records)


def _find_item_url(summary_row: Tag, detail_row: Tag, base_url: str) -> str | None:
    for row in (summary_row, detail_row):
        for link in row.find_all("a", href=True):
            href = str(link["href"]).strip()
            lowered = href.casefold()
            if not href or lowered.startswith(("#", "javascript:", "mailto:")):
                continue
            if "open.dll" not in lowered:
                continue
            if "submitdocsearch" in lowered or lowered.endswith("/welcome"):
                continue
            return urljoin(base_url, href)

    # todo: replace this heuristic after the detail link shape is confirmed.
    return None


def _text(node: Tag) -> str:
    return " ".join(node.get_text(" ", strip=True).split())
