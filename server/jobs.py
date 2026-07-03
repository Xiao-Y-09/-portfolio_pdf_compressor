"""In-memory job manager: one thread pool, no queue service, no database."""

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from enum import Enum
from pathlib import Path

from pydantic import BaseModel

from compressor import config
from compressor.exceptions import CompressorError
from compressor.pipeline import compress_pdf
from compressor.schemas import CompressionResult

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
OUTPUT_DIR = DATA_DIR / "outputs"


class JobStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    DONE = "done"
    ERROR = "error"


class JobRecord(BaseModel):
    job_id: str
    status: JobStatus = JobStatus.QUEUED
    created_at: float
    filename: str
    target_mb: float
    input_path: Path
    output_path: Path
    result: CompressionResult | None = None
    error: str | None = None


class JobManager:
    """Tracks jobs in a dict and runs compression on a small thread pool."""

    def __init__(self, max_workers: int = 2) -> None:
        self._jobs: dict[str, JobRecord] = {}
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=max_workers)
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    def submit(self, filename: str, payload: bytes, target_mb: float) -> JobRecord:
        self._evict_expired()
        job_id = uuid.uuid4().hex
        input_path = UPLOAD_DIR / f"{job_id}.pdf"
        output_path = OUTPUT_DIR / f"{job_id}.pdf"
        input_path.write_bytes(payload)
        record = JobRecord(
            job_id=job_id,
            created_at=time.time(),
            filename=filename,
            target_mb=target_mb,
            input_path=input_path,
            output_path=output_path,
        )
        with self._lock:
            self._jobs[job_id] = record
        self._pool.submit(self._run, job_id)
        return record

    def get(self, job_id: str) -> JobRecord | None:
        with self._lock:
            return self._jobs.get(job_id)

    def _run(self, job_id: str) -> None:
        record = self.get(job_id)
        if record is None:
            return
        record.status = JobStatus.PROCESSING
        try:
            record.result = compress_pdf(
                record.input_path, record.target_mb, record.output_path
            )
            record.status = JobStatus.DONE
        except CompressorError as exc:
            record.status = JobStatus.ERROR
            record.error = str(exc)
        except Exception:
            record.status = JobStatus.ERROR
            record.error = "internal error during compression"
        finally:
            record.input_path.unlink(missing_ok=True)

    def _evict_expired(self) -> None:
        cutoff = time.time() - config.JOB_RETENTION_SECONDS
        with self._lock:
            expired = [j for j in self._jobs.values() if j.created_at < cutoff]
            for job in expired:
                self._jobs.pop(job.job_id, None)
        for job in expired:
            job.input_path.unlink(missing_ok=True)
            job.output_path.unlink(missing_ok=True)
