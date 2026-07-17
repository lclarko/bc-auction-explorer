import json

from bc_auction.openapi import export_openapi_schema


def test_export_openapi_schema_writes_the_public_contract(tmp_path) -> None:
    output = tmp_path / "schema.json"

    export_openapi_schema(output)

    schema = json.loads(output.read_text(encoding="utf-8"))
    assert "/api/listings" in schema["paths"]
    assert "/api/listings/{source_id}" in schema["paths"]
