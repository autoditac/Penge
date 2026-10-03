"""Success responses must follow commit, not race the next browser read."""

from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest
from fastapi import FastAPI, Request, Response
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from penge.api import household


@pytest.mark.parametrize("commit_fails", [False, True])
def test_write_finishes_before_success_headers(
    engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    commit_fails: bool,
) -> None:
    monkeypatch.setenv("PENGE_HOUSEHOLD_ENABLED", "true")
    monkeypatch.setenv("PENGE_REFRESH_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(household, "get_import_engine", lambda: engine)
    committed: list[bool] = []
    headers_after_commit: list[bool] = []

    def before_commit(session: Session) -> None:
        if commit_fails:
            raise IntegrityError("synthetic commit failure", None, ValueError("synthetic"))

    def after_commit(session: Session) -> None:
        committed.append(True)

    app = FastAPI()
    app.include_router(household.router)

    @app.middleware("http")
    async def observe_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        if response.status_code == 201:
            headers_after_commit.append(bool(committed))
        return response

    event.listen(Session, "before_commit", before_commit)
    event.listen(Session, "after_commit", after_commit)
    try:
        with TestClient(app) as client:
            response = client.post(
                "/household/categories",
                json={
                    "expected_revision": 0,
                    "name": "Synthetic committed category",
                    "kind": "expense",
                },
            )
            if commit_fails:
                assert response.status_code == 409
                assert "constraint conflict" in response.json()["detail"]
                assert headers_after_commit == []
                assert client.get("/household/categories").json() == []
            else:
                assert response.status_code == 201
                assert headers_after_commit == [True]
                assert client.get("/household/categories").json()[0]["id"] == response.json()["id"]
    finally:
        event.remove(Session, "before_commit", before_commit)
        event.remove(Session, "after_commit", after_commit)
