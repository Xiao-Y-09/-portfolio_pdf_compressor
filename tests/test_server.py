"""API tests: upload -> poll -> download, plus validation and rate limiting."""

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server import routes
from server.main import app
from server.ratelimit import RateLimiter


@pytest.fixture()
def client() -> TestClient:
    routes.limiter.reset()
    return TestClient(app)


def _wait_for_done(client: TestClient, job_id: str, timeout: float = 120.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        payload = client.get(f"/api/jobs/{job_id}").json()
        if payload["status"] in ("done", "error"):
            return payload
        time.sleep(0.2)
    raise TimeoutError("job did not finish in time")


def test_health(client: TestClient) -> None:
    assert client.get("/api/health").json() == {"status": "ok"}


def test_full_job_flow(client: TestClient, portfolio_pdf: Path) -> None:
    with portfolio_pdf.open("rb") as fh:
        response = client.post(
            "/api/jobs",
            files={"file": ("portfolio.pdf", fh, "application/pdf")},
            data={"target_mb": "5"},
        )
    assert response.status_code == 202
    job_id = response.json()["job_id"]

    payload = _wait_for_done(client, job_id)
    assert payload["status"] == "done", payload.get("error")
    assert payload["result"]["output_bytes"] <= payload["result"]["target_bytes"]

    download = client.get(f"/api/jobs/{job_id}/download")
    assert download.status_code == 200
    assert download.headers["content-type"] == "application/pdf"
    assert download.content.startswith(b"%PDF-")


def test_rejects_bad_target(client: TestClient, small_pdf: Path) -> None:
    with small_pdf.open("rb") as fh:
        response = client.post(
            "/api/jobs",
            files={"file": ("x.pdf", fh, "application/pdf")},
            data={"target_mb": "7"},
        )
    assert response.status_code == 422


def test_rejects_non_pdf(client: TestClient) -> None:
    response = client.post(
        "/api/jobs",
        files={"file": ("x.pdf", b"plain text", "application/pdf")},
        data={"target_mb": "5"},
    )
    assert response.status_code == 422


def test_unknown_job_404(client: TestClient) -> None:
    assert client.get("/api/jobs/deadbeef").status_code == 404
    assert client.get("/api/jobs/deadbeef/download").status_code == 404


def test_rate_limiter_blocks_after_limit() -> None:
    limiter = RateLimiter(max_requests=3, window_seconds=60)
    assert all(limiter.allow("1.2.3.4") for _ in range(3))
    assert not limiter.allow("1.2.3.4")
    assert limiter.allow("5.6.7.8")
