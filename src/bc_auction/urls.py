from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit

_ITEM_QUERY_NAMES = frozenset(
    {"disID", "dis_version_nos", "docType", "docTypeQual", "doc_search_by"}
)
_SESSION_MARKER = "sessionid="


def normalize_public_url(url: str) -> str:
    """Normalize a public URL while refusing embedded live session values."""
    parsed = urlsplit(url)
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("public URL contained embedded credentials")
    if _contains_session_marker(parsed.netloc) or _contains_session_marker(parsed.path):
        raise ValueError("public URL contained an embedded session ID")

    query_pairs: list[tuple[str, str]] = []
    for name, value in parse_qsl(parsed.query, keep_blank_values=True):
        if name.casefold() == "sessionid":
            continue
        if _contains_session_marker(name) or _contains_session_marker(value):
            raise ValueError("public URL contained an embedded session ID")
        query_pairs.append((name, value))

    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            urlencode(sorted(query_pairs)),
            "",
        )
    )


def canonicalize_source_url(url: str) -> str:
    """Return a stable, session-free identity URL for a BC Auction item."""
    normalized_url = normalize_public_url(url)
    parsed = urlsplit(normalized_url)
    if parsed.scheme.casefold() != "https" or parsed.netloc.casefold() != "www.bcauction.ca":
        raise ValueError("canonical item URL did not use the BC Auction HTTPS host")
    if parsed.path.casefold() != "/open.dll/showdisplaydocument":
        raise ValueError("canonical item URL did not use showDisplayDocument")

    query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
    unexpected_names = {name for name, _ in query_pairs} - _ITEM_QUERY_NAMES
    if unexpected_names:
        raise ValueError("canonical item URL contained unexpected query parameters")
    display_ids = [value for name, value in query_pairs if name == "disID"]
    if len(display_ids) != 1 or not display_ids[0]:
        raise ValueError("canonical item URL did not contain a display ID")
    return urlunsplit(
        (
            "https",
            "www.bcauction.ca",
            "/open.dll/showDisplayDocument",
            urlencode({"disID": display_ids[0]}),
            "",
        )
    )


def extract_source_dis_id(canonical_url: str) -> str:
    """Extract the stable display ID from a canonical BC Auction item URL."""
    normalized_url = canonicalize_source_url(canonical_url)
    display_ids = [
        value for name, value in parse_qsl(urlsplit(normalized_url).query) if name == "disID"
    ]
    if len(display_ids) != 1:
        raise ValueError("canonical item URL did not contain one display ID")
    return display_ids[0]


def _contains_session_marker(value: str) -> bool:
    decoded_value = value
    for _ in range(3):
        next_value = unquote(decoded_value)
        if next_value == decoded_value:
            break
        decoded_value = next_value
    return _SESSION_MARKER in decoded_value.casefold()
