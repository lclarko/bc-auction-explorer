import json
from pathlib import Path

from bc_auction.openapi import export_openapi_schema


def test_export_openapi_schema_writes_the_public_contract(tmp_path) -> None:
    output = tmp_path / "schema.json"

    export_openapi_schema(output)

    exported = json.loads(output.read_text(encoding="utf-8"))
    checked_in = json.loads(
        (Path(__file__).parents[1] / "frontend" / "src" / "api" / "schema.json").read_text(
            encoding="utf-8"
        )
    )

    assert exported == checked_in
