from pathlib import Path

import pytest

from bc_auction.errors import ParserContractError
from bc_auction.parsers.search import (
    ProductGroup,
    parse_browse_url,
    parse_product_groups,
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


@pytest.mark.parametrize(
    ("html", "parser", "error"),
    [
        ("<html></html>", parse_welcome_content_url, "one content frame"),
        (
            '<frame src="showWelcomeContent?one"><frame src="showWelcomeContent?two">',
            parse_welcome_content_url,
            "one content frame",
        ),
        ("<html></html>", parse_browse_url, "one auction browse link"),
        (
            '<a href="submitLogin?redirect=showDocumentSearch">one</a>'
            '<a href="submitLogin?redirect=showDocumentSearch">two</a>',
            parse_browse_url,
            "one auction browse link",
        ),
    ],
)
def test_requires_one_navigation_candidate(html: str, parser: object, error: str) -> None:
    with pytest.raises(ParserContractError, match=error):
        parser(html, "https://www.bcauction.ca/open.dll/welcome")  # type: ignore[operator]


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
    assert form.display_orders == (
        "EndingFirst",
        "EndingLast",
        "HighestPrice",
        "LowestPrice",
        "PublishDate",
    )

    open_auction_fields = dict(
        form.open_auction_fields(keyword="truck", display_order="HighestPrice")
    )
    assert open_auction_fields["Keyword"] == "truck"
    assert open_auction_fields["display_order"] == "HighestPrice"
    assert open_auction_fields["productDisID"] == "simpleAll"
    assert open_auction_fields["dllAnchor"] == "allOpenOpportunities"
    assert open_auction_fields["productDesc"] == "Browse All Open Auctions"
    assert open_auction_fields["field_disID1"] == "5810716"

    with pytest.raises(ParserContractError, match="did not permit display order"):
        form.open_auction_fields(display_order="UncapturedSort")


def test_parses_product_groups_and_builds_group_search_fields() -> None:
    html = _fixture("search-entry.html")
    form = parse_search_form(
        html,
        "https://www.bcauction.ca/open.dll/showDocumentSearch?sessionID=SESSION_ID",
    )

    product_groups = parse_product_groups(html)

    assert product_groups[0] == ProductGroup("5810716", "Antiques and Collectibles")
    assert product_groups[-1] == ProductGroup("4369498", "Vehicles & Automotive")
    assert len(product_groups) == 16
    group_fields = dict(
        form.product_group_fields(product_groups[0], keyword="truck", display_order="HighestPrice")
    )
    assert group_fields["Keyword"] == "truck"
    assert group_fields["display_order"] == "HighestPrice"
    assert group_fields["dllAnchor"] == ""
    assert group_fields["productDisID"] == "5810716"
    assert group_fields["productDesc"] == "Antiques and Collectibles"


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
