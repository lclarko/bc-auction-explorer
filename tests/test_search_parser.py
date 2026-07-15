from pathlib import Path

import pytest

from bc_auction.errors import ParserContractError
from bc_auction.parsers.search import (
    parse_browse_url,
    parse_search_form,
    parse_session_id,
    parse_welcome_content_url,
)

_FIXTURES = Path(__file__).parent / "fixtures"


def _fixture(name: str) -> str:
    return (_FIXTURES / name).read_text(encoding="utf-8")


def test_parses_the_captured_search_flow() -> None:
    welcome_url = "https://www.bcauction.ca/open.dll/welcome?language=En"
    welcome_html = _fixture("welcome.html")

    assert parse_session_id(welcome_html) == "SESSION_ID"
    assert parse_welcome_content_url(welcome_html, welcome_url) == (
        "https://www.bcauction.ca/open.dll/showWelcomeContent?sessionID=SESSION_ID&Language=En&cssStyle="
    )

    browse_url = parse_browse_url(_fixture("welcome-content.html"), welcome_url)
    assert browse_url.startswith("https://www.bcauction.ca/open.dll/submitLogin?")


def test_preserves_captured_form_fields_and_applies_open_auction_values() -> None:
    form = parse_search_form(
        _fixture("search-entry.html"),
        "https://www.bcauction.ca/open.dll/showDocumentSearch?sessionID=SESSION_ID",
    )

    fields = dict(form.fields)
    assert form.action_url == "https://www.bcauction.ca/open.dll/submitDocSearch"
    assert form.session_id == "SESSION_ID"
    assert fields["UseProfile"] == ""
    assert fields["field_disID24"] == "4369498"
    assert fields["display_order"] == "EndingFirst"

    open_auction_fields = dict(
        form.open_auction_fields(keyword="truck", display_order="HighestPrice")
    )
    assert open_auction_fields["Keyword"] == "truck"
    assert open_auction_fields["display_order"] == "HighestPrice"
    assert open_auction_fields["productDisID"] == "simpleAll"
    assert open_auction_fields["dllAnchor"] == "allOpenOpportunities"
    assert open_auction_fields["productDesc"] == "Browse All Open Auctions"
    assert open_auction_fields["field_disID1"] == "5810716"


def test_rejects_a_search_form_that_is_not_posted() -> None:
    html = '<form action="submitDocSearch" method="get"></form>'

    with pytest.raises(ParserContractError, match="did not use POST"):
        parse_search_form(html, "https://www.bcauction.ca/open.dll/showDocumentSearch")


def test_rejects_a_search_form_without_a_session_id() -> None:
    html = '''
    <form action="submitDocSearch" method="post">
      <input name="doc_search_by" value="TendSimp">
      <input name="searchResult" value="True">
      <input name="dllAnchor" value="">
      <input name="productDisID" value="">
      <input name="productDesc" value="">
      <input name="Keyword" value="">
      <select name="display_order">
        <option value="EndingFirst" selected>Ending First</option>
      </select>
    </form>
    '''

    with pytest.raises(ParserContractError, match="sessionID"):
        parse_search_form(html, "https://www.bcauction.ca/open.dll/showDocumentSearch")
