"""API tests: two-phase flow (upload+analyze -> confirm -> poll -> download)."""

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


def _upload(client: TestClient, path: Path) -> dict:
    with path.open("rb") as fh:
        response = client.post(
            "/api/jobs",
            files={"file": (path.name, fh, "application/pdf")},
        )
    assert response.status_code == 201, response.text
    return response.json()


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


def test_upload_returns_analysis(client: TestClient, portfolio_pdf: Path) -> None:
    analysis = _upload(client, portfolio_pdf)
    assert analysis["job_id"]
    assert analysis["page_count"] == 4
    assert len(analysis["thumbnails"]) == 4
    assert len(analysis["page_classifications"]) == 4
    assert all(p >= 1 for p in analysis["ai_suggested_pages"])

    status = client.get(f"/api/jobs/{analysis['job_id']}").json()
    assert status["status"] == "waiting_confirm"


def test_full_two_phase_flow(client: TestClient, portfolio_pdf: Path) -> None:
    analysis = _upload(client, portfolio_pdf)
    job_id = analysis["job_id"]

    confirm = client.post(
        f"/api/jobs/{job_id}/confirm",
        json={"target_size_mb": 5, "selected_pages": analysis["ai_suggested_pages"]},
    )
    assert confirm.status_code == 202, confirm.text

    payload = _wait_for_done(client, job_id)
    assert payload["status"] == "done", payload.get("error")
    assert payload["result"]["output_bytes"] <= payload["result"]["target_bytes"]
    assert payload["result"]["strategy"] == "vector_preserving"

    download = client.get(f"/api/jobs/{job_id}/download")
    assert download.status_code == 200
    assert download.headers["content-type"] == "application/pdf"
    assert download.content.startswith(b"%PDF-")


def test_confirm_rejects_bad_target(client: TestClient, small_pdf: Path) -> None:
    analysis = _upload(client, small_pdf)
    response = client.post(
        f"/api/jobs/{analysis['job_id']}/confirm",
        json={"target_size_mb": 7, "selected_pages": []},
    )
    assert response.status_code == 422


def test_confirm_rejects_out_of_range_pages(
    client: TestClient, small_pdf: Path
) -> None:
    analysis = _upload(client, small_pdf)
    response = client.post(
        f"/api/jobs/{analysis['job_id']}/confirm",
        json={"target_size_mb": 5, "selected_pages": [99]},
    )
    assert response.status_code == 422


def test_double_confirm_conflicts(client: TestClient, small_pdf: Path) -> None:
    analysis = _upload(client, small_pdf)
    job_id = analysis["job_id"]
    first = client.post(
        f"/api/jobs/{job_id}/confirm",
        json={"target_size_mb": 5, "selected_pages": []},
    )
    assert first.status_code == 202
    _wait_for_done(client, job_id)
    second = client.post(
        f"/api/jobs/{job_id}/confirm",
        json={"target_size_mb": 5, "selected_pages": []},
    )
    assert second.status_code == 409


def test_download_before_confirm_conflicts(client: TestClient, small_pdf: Path) -> None:
    analysis = _upload(client, small_pdf)
    response = client.get(f"/api/jobs/{analysis['job_id']}/download")
    assert response.status_code == 409


def test_rejects_non_pdf(client: TestClient) -> None:
    response = client.post(
        "/api/jobs",
        files={"file": ("x.pdf", b"plain text", "application/pdf")},
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
