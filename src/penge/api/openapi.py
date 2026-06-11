"""Export the committed OpenAPI schema artifact.

The schema at ``docs/api/openapi.json`` is the contract the WebUI's
generated TypeScript client builds against (issue #203). It is
committed so client generation is deterministic and reviewable; CI
regenerates it and fails on drift.

Run via ``just api-openapi``.
"""

from __future__ import annotations

import json
from pathlib import Path

from penge.api.app import create_app

SCHEMA_PATH = Path(__file__).resolve().parents[3] / "docs" / "api" / "openapi.json"


def render_schema() -> str:
    """Return the OpenAPI schema as stable, pretty-printed JSON."""
    schema = create_app().openapi()
    return json.dumps(schema, indent=2, sort_keys=True) + "\n"


def main() -> None:
    """Write the schema to ``docs/api/openapi.json``."""
    SCHEMA_PATH.parent.mkdir(parents=True, exist_ok=True)
    SCHEMA_PATH.write_text(render_schema(), encoding="utf-8")
    print(f"wrote {SCHEMA_PATH}")  # CLI entrypoint; print is allowed here


if __name__ == "__main__":
    main()
