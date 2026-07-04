"""In-memory job manager: one thread pool, no queue service, no database.

v4 job lifecycle:
    upload -> analysis (synchronous) -> WAITING_CONFIRM
    confirm(selected_pages, target)  -> PROCESSING -> DONE | ERROR
"""

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from enum import Enum
from pathlib import Path

from pydantic import BaseModel

from compressor import config
from compressor.exceptions import CompressorError
from compressor.pipeline import run_analysis, run_compression
from compressor.schemas import AnalysisResult, CompressionResult

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
OUTPUT_DIR = DATA_DIR / "outputs"


class JobStatus(str, Enum):
    WAITING_CONFIRM = "waiting_confirm"
    PROCESSING = "processing"
    DONE = "done"
    ERROR = "error"


class JobRecord(BaseModel):
    job_id: str
    status: JobStatus = JobStatus.WAITING_CONFIRM
    created_at: float
    filename: str
    target_mb: float = 0.0
    input_path: Path
    output_path: Path
    analysis: AnalysisResult | None = None
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

    def create(self, filename: str, payload: bytes) -> JobRecord:
        """Store the upload and run the analysis phase synchronously."""
        self._evict_expired()
        job_id = uuid.uuid4().hex
        input_path = UPLOAD_DIR / f"{job_id}.pdf"
        output_path = OUTPUT_DIR / f"{job_id}.pdf"
        input_path.write_bytes(payload)

        try:
            analysis = run_analysis(input_path)
        except CompressorError:
            input_path.unlink(missing_ok=True)
            raise
        analysis = analysis.model_copy(update={"job_id": job_id})

        record = JobRecord(
            job_id=job_id,
            created_at=time.time(),
            filename=filename,
            input_path=input_path,
            output_path=output_path,
            analysis=analysis,
        )
        with self._lock:
            self._jobs[job_id] = record
        return record

    def confirm(
        self, job_id: str, target_mb: float, selected_pages: list[int]
    ) -> JobRecord | None:
        """Kick off compression for a job that is waiting for user review."""
        record = self.get(job_id)
        if record is None or record.status != JobStatus.WAITING_CONFIRM:
            return record
        record.target_mb = target_mb
        record.status = JobStatus.PROCESSING
        self._pool.submit(self._run, job_id, selected_pages)
        return record

    def get(self, job_id: str) -> JobRecord | None:
        with self._lock:
            return self._jobs.get(job_id)

    def _run(self, job_id: str, selected_pages: list[int]) -> None:
        record = self.get(job_id)
        if record is None:
            return
        try:
            record.result = run_compression(
                record.input_path,
                record.target_mb,
                selected_pages,
                record.output_path,
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
