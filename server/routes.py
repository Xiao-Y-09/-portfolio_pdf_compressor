"""API endpoints: upload+analyze -> review confirm -> poll -> download."""

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from compressor import config
from compressor.exceptions import CompressorError
from compressor.schemas import AnalysisResult, CompressionRequest, CompressionResult
from server.jobs import JobManager, JobStatus
from server.ratelimit import RateLimiter

router = APIRouter(prefix="/api")
jobs = JobManager()
limiter = RateLimiter()


class JobStatusResponse(BaseModel):
    job_id: str
    status: JobStatus
    filename: str
    target_mb: float
    result: CompressionResult | None = None
    error: str | None = None


def _client_ip(request: Request) -> str:
    if request.client:
        return request.client.host
    return "unknown"


def _get_or_404(job_id: str):
    record = jobs.get(job_id)
    if record is None:
        raise HTTPException(status_code=404, detail="job not found")
    return record


@router.post("/jobs", response_model=AnalysisResult, status_code=201)
def create_job(request: Request, file: UploadFile = File(...)) -> AnalysisResult:
    """Upload a PDF and run the analysis phase (thumbnails + AI labels)."""
    if not limiter.allow(_client_ip(request)):
        raise HTTPException(
            status_code=429, detail="rate limit exceeded, try again later"
        )
    payload = file.file.read()
    if len(payload) > config.MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(
            status_code=413, detail=f"file exceeds {config.MAX_UPLOAD_MB} MB"
        )
    if not payload.startswith(b"%PDF-"):
        raise HTTPException(status_code=422, detail="file does not look like a PDF")

    try:
        record = jobs.create(file.filename or "portfolio.pdf", payload)
    except CompressorError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    assert record.analysis is not None
    return record.analysis


@router.post(
    "/jobs/{job_id}/confirm", response_model=JobStatusResponse, status_code=202
)
def confirm_job(job_id: str, body: CompressionRequest) -> JobStatusResponse:
    """Submit the reviewed page selection and start compression."""
    record = _get_or_404(job_id)
    if body.target_size_mb not in config.ALLOWED_TARGETS_MB:
        raise HTTPException(
            status_code=422,
            detail=f"target_size_mb must be one of {list(config.ALLOWED_TARGETS_MB)}",
        )
    page_count = record.analysis.page_count if record.analysis else 0
    if any(p < 1 or p > page_count for p in body.selected_pages):
        raise HTTPException(
            status_code=422,
            detail=f"selected_pages must be within 1..{page_count}",
        )
    if record.status != JobStatus.WAITING_CONFIRM:
        raise HTTPException(
            status_code=409, detail=f"job is {record.status.value}, cannot confirm"
        )
    record = jobs.confirm(job_id, body.target_size_mb, sorted(set(body.selected_pages)))
    assert record is not None
    return JobStatusResponse(
        job_id=record.job_id,
        status=record.status,
        filename=record.filename,
        target_mb=record.target_mb,
    )


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
def get_job(job_id: str) -> JobStatusResponse:
    record = _get_or_404(job_id)
    return JobStatusResponse(
        job_id=record.job_id,
        status=record.status,
        filename=record.filename,
        target_mb=record.target_mb,
        result=record.result,
        error=record.error,
    )


@router.get("/jobs/{job_id}/download")
def download(job_id: str) -> FileResponse:
    record = _get_or_404(job_id)
    if record.status != JobStatus.DONE or not record.output_path.is_file():
        raise HTTPException(
            status_code=409, detail=f"job is {record.status.value}, not done"
        )
    stem = record.filename.rsplit(".", 1)[0] or "portfolio"
    return FileResponse(
        record.output_path,
        media_type="application/pdf",
        filename=f"{stem}_compressed.pdf",
    )
