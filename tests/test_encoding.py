import codecs

from bc_auction.encoding import decode_html


def test_decodes_utf8_from_header() -> None:
    page = decode_html("Café".encode(), "text/html; charset=utf-8")

    assert page.text == "Café"
    assert page.encoding == "utf-8"


def test_bom_takes_precedence_over_header() -> None:
    body = codecs.BOM_UTF16_LE + "Test".encode("utf-16-le")

    page = decode_html(body, "text/html; charset=windows-1252")

    assert page.text == "Test"
    assert page.encoding == "utf-16"


def test_uses_meta_charset() -> None:
    body = '<meta charset="windows-1252"><p>Price: £10</p>'.encode("windows-1252")

    page = decode_html(body)

    assert "£10" in page.text
    assert page.encoding == "cp1252"


def test_empty_body_is_utf8() -> None:
    page = decode_html(b"")

    assert page.text == ""
    assert page.encoding == "utf-8"


def test_ignores_unknown_declared_charset() -> None:
    page = decode_html(b"<p>plain text</p>", "text/html; charset=not-a-real-charset")

    assert page.text == "<p>plain text</p>"
    assert page.encoding == "utf-8"
