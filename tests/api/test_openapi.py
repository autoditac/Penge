"""Tests for the committed OpenAPI schema artifact."""

from __future__ import annotations

import json

from penge.api.openapi import SCHEMA_PATH, render_schema


class TestOpenApiSchema:
    def test_renders_valid_json_with_all_routes(self) -> None:
        schema = json.loads(render_schema())
        assert schema["info"]["title"] == "Penge read API"
        assert set(schema["paths"]) == {
            "/net-worth/daily",
            "/cashflow/daily",
            "/allocation/current",
            "/accounts",
            "/meta/freshness",
            "/returns/daily",
            "/returns/summary",
            "/returns/fees",
            "/benchmarks",
            "/benchmarks/daily",
            "/imports",
            "/imports/{session_id}",
            "/imports/{session_id}/rows/{row_id}",
            "/imports/{session_id}/commit",
            "/imports/{session_id}/suggestions",
        }

    def test_render_is_deterministic(self) -> None:
        assert render_schema() == render_schema()

    def test_committed_artifact_is_current(self) -> None:
        """`just api-openapi` must be re-run when the API changes."""
        assert SCHEMA_PATH.exists(), "docs/api/openapi.json missing — run `just api-openapi`"
        assert (
            SCHEMA_PATH.read_text(encoding="utf-8") == render_schema()
        ), "docs/api/openapi.json is stale — run `just api-openapi` and commit the result"
