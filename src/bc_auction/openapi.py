"""Export the public OpenAPI schema without opening a database connection."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from bc_auction.api import create_app


def export_openapi_schema(output_path: Path) -> None:
    """Write the API schema to an explicit JSON file."""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    schema = create_app().openapi()
    output_path.write_text(
        json.dumps(schema, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    """Export the schema for frontend type generation."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    export_openapi_schema(arguments.output)


if __name__ == "__main__":
    main()
