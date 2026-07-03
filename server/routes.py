"""API endpoints: upload -> poll -> download."""

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from compressor import config
from compressor.schemas import CompressionResult
from server.jobs import JobManager, JobStatus
from server.ratelimit import RateLimiter

router = APIRouter(prefix="/api")
jobs = JobManager()
limiter = RateLimiter()


class JobCreatedResponse(BaseModel):
    job_id: str


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


@router.post("/jobs", response_model=JobCreatedResponse, status_code=202)
async def create_job(
    request: Request,
    file: UploadFile = File(...),
    target_mb: float = Form(...),
) -> JobCreatedResponse:
    if not limiter.allow(_client_ip(request)):
        raise HTTPException(
            status_code=429, detail="rate limit exceeded, try again later"
        )
    if target_mb not in config.ALLOWED_TARGETS_MB:
        raise HTTPException(
            status_code=422,
            detail=f"target_mb must be one of {list(config.ALLOWED_TARGETS_MB)}",
        )
    payload = await file.read()
    if len(payload) > config.MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(
            status_code=413, detail=f"file exceeds {config.MAX_UPLOAD_MB} MB"
        )
    if not payload.startswith(b"%PDF-"):
        raise HTTPException(status_code=422, detail="file does not look like a PDF")

    record = jobs.submit(file.filename or "portfolio.pdf", payload, target_mb)
    return JobCreatedResponse(job_id=record.job_id)


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job(job_id: str) -> JobStatusResponse:
    record = jobs.get(job_id)
    if record is None:
        raise HTTPException(status_code=404, detail="job not found")
    return JobStatusResponse(
        job_id=record.job_id,
        status=record.status,
        filename=record.filename,
        target_mb=record.target_mb,
        result=record.result,
        error=record.error,
    )


@router.get("/jobs/{job_id}/download")
async def download(job_id: str) -> FileResponse:
    record = jobs.get(job_id)
    if record is None:
        raise HTTPException(status_code=404, detail="job not found")
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
