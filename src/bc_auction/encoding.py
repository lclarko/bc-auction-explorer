import codecs
import re
from dataclasses import dataclass

from charset_normalizer import from_bytes

from bc_auction.errors import DecodeError

_CHARSET_HEADER = re.compile(r"charset\s*=\s*[\"']?([^\s;\"']+)", re.IGNORECASE)
_META_CHARSET = re.compile(br"<meta[^>]+charset\s*=\s*[\"']?\s*([^\s\"'/>;]+)", re.IGNORECASE)
_META_HTTP_EQUIV = re.compile(
    br"<meta[^>]+http-equiv\s*=\s*[\"']?content-type[\"']?[^>]+content\s*=\s*[\"'][^\"']*charset\s*=\s*([^\s;\"']+)",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class DecodedPage:
    text: str
    encoding: str


def decode_html(body: bytes, content_type: str | None = None) -> DecodedPage:
    if not body:
        return DecodedPage(text="", encoding="utf-8")

    candidates = _encoding_candidates(body, content_type)
    errors: list[str] = []

    for encoding in candidates:
        try:
            return DecodedPage(text=body.decode(encoding, errors="strict"), encoding=encoding)
        except (LookupError, UnicodeDecodeError) as exc:
            errors.append(f"{encoding}: {exc}")

    match = from_bytes(body).best()
    if match is not None:
        return DecodedPage(text=str(match), encoding=match.encoding)

    detail = "; ".join(errors)
    raise DecodeError(f"unable to decode response body: {detail}")


def _encoding_candidates(body: bytes, content_type: str | None) -> tuple[str, ...]:
    candidates: list[str] = []

    bom_encoding = _bom_encoding(body)
    if bom_encoding is not None:
        candidates.append(bom_encoding)

    if content_type:
        header_match = _CHARSET_HEADER.search(content_type)
        if header_match:
            candidates.append(header_match.group(1))

    sample = body[:4096]
    for pattern in (_META_CHARSET, _META_HTTP_EQUIV):
        meta_match = pattern.search(sample)
        if meta_match:
            candidates.append(meta_match.group(1).decode("ascii", errors="ignore"))

    candidates.extend(("utf-8", "windows-1252"))

    unique: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        try:
            normalized = codecs.lookup(candidate).name
        except LookupError:
            continue
        if normalized not in seen:
            unique.append(normalized)
            seen.add(normalized)

    return tuple(unique)


def _bom_encoding(body: bytes) -> str | None:
    if body.startswith(codecs.BOM_UTF8):
        return "utf-8-sig"
    if body.startswith(codecs.BOM_UTF32_LE) or body.startswith(codecs.BOM_UTF32_BE):
        return "utf-32"
    if body.startswith(codecs.BOM_UTF16_LE) or body.startswith(codecs.BOM_UTF16_BE):
        return "utf-16"
    return None
