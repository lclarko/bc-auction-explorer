import pytest

from bc_auction.errors import ParserContractError
from bc_auction.parsers import parse_search_results


def test_parses_known_two_row_result_shape() -> None:
    html = """
    <table>
      <tr>
        <td><a href="/open.dll/item?id=42">Utility trailer</a></td>
        <td width="75">Victoria - Uvic</td>
        <td>$120.00</td>
      </tr>
      <tr name="infoDetail">
        <td colspan="3">Closes July 30, 2026</td>
      </tr>
    </table>
    """

    records = parse_search_results(html, "https://www.bcauction.ca/")

    assert len(records) == 1
    assert str(records[0].source_url) == "https://www.bcauction.ca/open.dll/item?id=42"
    assert records[0].location_raw == "Victoria - Uvic"
    assert records[0].summary_cells == ("Utility trailer", "Victoria - Uvic", "$120.00")
    assert records[0].detail_text == "Closes July 30, 2026"


def test_returns_empty_tuple_when_no_detail_rows_exist() -> None:
    assert parse_search_results("<table></table>", "https://www.bcauction.ca/") == ()


def test_rejects_orphan_detail_row() -> None:
    html = '<table><tr name="infoDetail"><td>orphan</td></tr></table>'

    with pytest.raises(ParserContractError):
        parse_search_results(html, "https://www.bcauction.ca/")
