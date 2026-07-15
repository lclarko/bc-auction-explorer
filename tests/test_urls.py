import pytest

from bc_auction.urls import canonicalize_source_url, normalize_public_url


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

    assert canonical_url == (
        "https://www.bcauction.ca/open.dll/showDisplayDocument?disID=8733643&docType=Tender"
    )


def test_canonicalize_source_url_rejects_an_embedded_session_id() -> None:
    with pytest.raises(ValueError, match="embedded session ID"):
        canonicalize_source_url(
            "https://www.bcauction.ca/open.dll/showDisplayDocument?disID=8733643&"
            "redirect=showDocSummary%3FsessionID%3DSECRET"
        )
