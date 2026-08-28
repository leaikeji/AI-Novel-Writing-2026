from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from backend.narration import narration_api, playback_api, release_gate, script_api


IDENTITY = "20000000-0000-4000-8000-000000000001"


@pytest.fixture(autouse=True)
def _reset_access_policy():  # type: ignore[no-untyped-def]
    release_gate.uninstall_narration_t4_http_access_policy()
    yield
    release_gate.uninstall_narration_t4_http_access_policy()


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(narration_api.router)
    app.include_router(script_api.router)
    app.include_router(playback_api.router)
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize(
    "path",
    (
        f"/narration-requests/{IDENTITY}",
        f"/narration-script-versions/{IDENTITY}",
        f"/narration-editions/{IDENTITY}/manifest",
    ),
)
def test_t4_routes_are_hidden_when_no_application_policy_is_installed(
    path: str,
) -> None:
    response = _client().get(path)

    assert response.status_code == 404
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["detail"]["code"] == "RESOURCE_NOT_FOUND"


def test_explicit_policy_is_required_and_policy_failures_fail_closed() -> None:
    client = _client()
    release_gate.install_narration_t4_http_access_policy(
        lambda _request: True
    )
    allowed = client.get(f"/narration-requests/{IDENTITY}")
    assert allowed.status_code == 503
    assert allowed.json()["detail"]["code"] == (
        "NARRATION_PRODUCTION_BACKEND_NOT_INSTALLED"
    )

    release_gate.uninstall_narration_t4_http_access_policy()

    def failing_policy(_request):  # type: ignore[no-untyped-def]
        raise RuntimeError("must not escape")

    release_gate.install_narration_t4_http_access_policy(failing_policy)
    denied = client.get(f"/narration-requests/{IDENTITY}")
    assert denied.status_code == 404
    assert "must not escape" not in denied.text
