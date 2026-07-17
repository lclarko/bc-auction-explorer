import pytest

from bc_auction.urls import canonicalize_source_url, extract_source_dis_id, normalize_public_url


def test_normalize_public_url_removes_session_ids_and_sorts_query_pairs() -> None:
    normalized_url = normalize_public_url(
        "https://www.bcauction.ca/open.dll/showDisplayDocument?z=2&sessionID=first&"
        "a=&SESSIONid=second&z=1#details"
    )

    assert normalized_url == (
        "https://www.bcauction.ca/open.dll/showDisplayDocument?a=&z=1&z=2"
    )


def test_canonicalize_source_url_removes_encoded_session_parameter_names() -> None:
    canonical_url = canonicalize_source_url(
        "https://www.bcauction.ca/open.dll/showDisplayDocument?docType=Tender&"
        "disID=8733643&session%49D=value"
    )

    assert canonical_url == "https://www.bcauction.ca/open.dll/showDisplayDocument?disID=8733643"


def test_canonicalize_source_url_keeps_only_the_stable_display_id() -> None:
    first = canonicalize_source_url(
        "https://www.bcauction.ca/open.dll/showDisplayDocument?disID=8733643&"
        "dis_version_nos=0&docType=Tender&docTypeQual=TN&doc_search_by=Tend&sessionID=ONE"
    )
    second = canonicalize_source_url(
        "https://www.bcauction.ca/open.dll/showDisplayDocument?doc_search_by=Tend&"
        "docTypeQual=TN&disID=8733643&docType=Tender&dis_version_nos=2&sessionID=TWO"
    )

    assert first == second == "https://www.bcauction.ca/open.dll/showDisplayDocument?disID=8733643"


def test_canonicalize_source_url_rejects_an_embedded_session_id() -> None:
    with pytest.raises(ValueError, match="embedded session ID"):
        canonicalize_source_url(
            "https://www.bcauction.ca/open.dll/showDisplayDocument?disID=8733643&"
            "redirect=showDocSummary%3FsessionID%3DSECRET"
        )


@pytest.mark.parametrize(
    "url",
    [
        "https://user@www.bcauction.ca/Pictures/8733643.jpg",
        "https://user:secret@www.bcauction.ca/Pictures/8733643.jpg",
    ],
)
def test_normalize_public_url_rejects_embedded_credentials(url: str) -> None:
    with pytest.raises(ValueError, match="embedded credentials"):
        normalize_public_url(url)


@pytest.mark.parametrize(
    ("url", "error"),
    [
        ("http://www.bcauction.ca/open.dll/showDisplayDocument?disID=8733643", "HTTPS host"),
        ("https://example.com/open.dll/showDisplayDocument?disID=8733643", "HTTPS host"),
        (
            "https://user@www.bcauction.ca/open.dll/showDisplayDocument?disID=8733643",
            "embedded credentials",
        ),
        ("https://www.bcauction.ca:8443/open.dll/showDisplayDocument?disID=8733643", "HTTPS host"),
        (
            "https://www.bcauction.ca/unrelated/showDisplayDocument?disID=8733643",
            "showDisplayDocument",
        ),
        ("https://www.bcauction.ca/open.dll/showDisplayDocument?docType=Tender", "display ID"),
        ("https://www.bcauction.ca/open.dll/showDisplayDocument?disID=", "display ID"),
        ("https://www.bcauction.ca/open.dll/showDisplayDocument?disID=1&disID=2", "display ID"),
        ("https://www.bcauction.ca/open.dll/showDisplayDocument?disID=1&disID=", "display ID"),
        (
            "https://www.bcauction.ca/open.dll/showDisplayDocument?disID=8733643&unexpected=1",
            "unexpected query",
        ),
    ],
)
def test_canonicalize_source_url_rejects_invalid_identity_urls(url: str, error: str) -> None:
    with pytest.raises(ValueError, match=error):
        canonicalize_source_url(url)


def test_extract_source_dis_id_uses_the_canonical_display_id() -> None:
    assert (
        extract_source_dis_id(
            "https://www.bcauction.ca/open.dll/showDisplayDocument?disID=8733643"
        )
        == "8733643"
    )


def test_extract_source_dis_id_normalizes_navigation_parameters_and_session_values() -> None:
    first = extract_source_dis_id(
        "https://www.bcauction.ca/open.dll/showDisplayDocument?docType=Tender&"
        "disID=8733643&doc_search_by=Tend&sessionID=private"
    )
    second = extract_source_dis_id(
        "https://www.bcauction.ca/open.dll/showDisplayDocument?session%49D=private&"
        "doc_search_by=Tend&disID=8733643&dis_version_nos=2"
    )

    assert first == second == "8733643"


@pytest.mark.parametrize(
    ("url", "error"),
    [
        (
            "https://example.com/open.dll/showDisplayDocument?disID=8733643",
            "BC Auction HTTPS host",
        ),
        (
            "https://www.bcauction.ca/open.dll/showDocSummary?disID=8733643",
            "showDisplayDocument",
        ),
        (
            "https://www.bcauction.ca/open.dll/showDisplayDocument?disID=1&disID=2",
            "display ID",
        ),
        (
            "https://www.bcauction.ca/open.dll/showDisplayDocument?disID=8733643&"
            "redirect=showDocSummary%3FsessionID%3Dprivate",
            "embedded session ID",
        ),
    ],
)
def test_extract_source_dis_id_rejects_unstable_or_session_bearing_urls(
    url: str,
    error: str,
) -> None:
    with pytest.raises(ValueError, match=error):
        extract_source_dis_id(url)
