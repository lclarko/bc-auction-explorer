import re
from dataclasses import dataclass
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from bc_auction.errors import ParserContractError

_SESSION_ID = re.compile(r"addSessionId\(\s*[\"']([^\"']+)[\"']\s*\)")
_REQUIRED_FIELDS = frozenset(
    {
        "doc_search_by",
        "searchResult",
        "dllAnchor",
        "productDisID",
        "productDesc",
        "Keyword",
        "display_order",
        "sessionID",
    }
)


@dataclass(frozen=True, slots=True)
class SearchForm:
    action_url: str
    fields: tuple[tuple[str, str], ...]
    session_id: str
    display_orders: tuple[str, ...]

    def open_auction_fields(
        self,
        *,
        keyword: str = "",
        display_order: str = "EndingFirst",
    ) -> tuple[tuple[str, str], ...]:
        if display_order not in self.display_orders:
            raise ParserContractError(
                f"auction search form did not permit display order: {display_order}"
            )
        replacements = {
            "Keyword": keyword,
            "display_order": display_order,
            "dllAnchor": "allOpenOpportunities",
            "productDisID": "simpleAll",
            "productDesc": "Browse All Open Auctions",
        }
        return tuple((name, replacements.get(name, value)) for name, value in self.fields)


def parse_session_id(html: str) -> str:
    session_ids = {
        match.group(1).strip()
        for match in _SESSION_ID.finditer(html)
        if match.group(1).strip()
    }
    if len(session_ids) != 1:
        raise ParserContractError("welcome page did not contain one session ID")
    return session_ids.pop()


def parse_welcome_content_url(html: str, page_url: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for frame in soup.find_all("frame", src=True):
        src = str(frame["src"]).strip()
        if "showwelcomecontent" in src.casefold():
            return urljoin(page_url, src)
    raise ParserContractError("welcome page did not contain a content frame")


def parse_browse_url(html: str, page_url: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for link in soup.find_all("a", href=True):
        href = str(link["href"]).strip()
        lowered = href.casefold()
        if "submitlogin" in lowered and "showdocumentsearch" in lowered:
            return urljoin(page_url, href)
    raise ParserContractError("welcome content did not contain the auction browse link")


def parse_search_form(html: str, page_url: str) -> SearchForm:
    soup = BeautifulSoup(html, "lxml")
    form = soup.find("form", action="submitDocSearch")
    if not isinstance(form, Tag):
        raise ParserContractError("auction search form was not found")

    method = str(form.get("method", "get")).casefold()
    if method != "post":
        raise ParserContractError("auction search form did not use POST")

    action = str(form.get("action", "")).strip()
    if not action:
        raise ParserContractError("auction search form did not have an action")

    fields = _form_fields(form)
    field_names = {name for name, _ in fields}
    missing = _REQUIRED_FIELDS - field_names
    if missing:
        missing_fields = ", ".join(sorted(missing))
        raise ParserContractError(f"auction search form was missing fields: {missing_fields}")

    session_id = next(value for name, value in fields if name == "sessionID")
    if not session_id:
        raise ParserContractError("auction search form had an empty session ID")
    display_orders = _display_orders(form)

    return SearchForm(
        action_url=urljoin(page_url, action),
        fields=fields,
        session_id=session_id,
        display_orders=display_orders,
    )


def _form_fields(form: Tag) -> tuple[tuple[str, str], ...]:
    fields: list[tuple[str, str]] = []
    for control in form.find_all(["input", "select"]):
        name = control.get("name")
        if not isinstance(name, str) or not name:
            continue
        fields.append((name, _control_value(control)))
    return tuple(fields)


def _display_orders(form: Tag) -> tuple[str, ...]:
    display_order = form.find("select", attrs={"name": "display_order"})
    if not isinstance(display_order, Tag):
        raise ParserContractError("auction search form did not contain display-order options")

    options = tuple(
        value
        for option in display_order.find_all("option")
        if (value := _option_value(option))
    )
    if not options:
        raise ParserContractError("auction search form did not contain display-order options")
    return options


def _control_value(control: Tag) -> str:
    if control.name != "select":
        value = control.get("value")
        return value if isinstance(value, str) else ""

    options = control.find_all("option")
    selected = next((option for option in options if option.has_attr("selected")), None)
    option = selected or (options[0] if options else None)
    if option is None:
        return ""
    return _option_value(option)


def _option_value(option: Tag) -> str:
    value = option.get("value")
    return value if isinstance(value, str) else option.get_text(strip=True)
