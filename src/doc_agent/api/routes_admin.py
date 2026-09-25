"""Admin routes."""

from fastapi import APIRouter, Depends

from doc_agent.auth import require_admin
from doc_agent.db.session import get_session
from doc_agent.db.models import Job, AuditLog

router = APIRouter()


@router.get("/jobs")
async def get_jobs(user: dict = Depends(require_admin)) -> dict:
    """Get the job queue."""
    with get_session() as session:
        jobs = session.query(Job).order_by(Job.priority, Job.created_at.desc()).limit(100).all()
        return {
            "jobs": [
                {
                    "id": j.id,
                    "file_id": j.file_id,
                    "kind": j.kind,
                    "priority": j.priority,
                    "status": j.status,
                    "attempts": j.attempts,
                    "last_error": j.last_error,
                    "created_at": j.created_at.isoformat() if j.created_at else None,
                }
                for j in jobs
            ]
        }


@router.post("/reindex")
async def reindex(user: dict = Depends(require_admin)) -> dict:
    """Trigger full reindex."""
    from doc_agent.db.models import File

    with get_session() as session:
        files = session.query(File).filter(File.status == "done").all()
        for f in files:
            job = Job(
                file_id=f.id,
                kind="reindex",
                priority=3,
                status="queued",
            )
            session.add(job)
        session.commit()

        return {"status": "ok", "jobs_created": len(files)}


@router.get("/metrics")
async def get_metrics(user: dict = Depends(require_admin)) -> dict:
    """Get system metrics."""
    from doc_agent.db.models import File, Chunk

    with get_session() as session:
        total_files = session.query(File).count()
        done_files = session.query(File).filter(File.status == "done").count()
        total_chunks = session.query(Chunk).count()

        return {
            "total_files": total_files,
            "done_files": done_files,
            "total_chunks": total_chunks,
        }


@router.get("/logs")
async def get_logs(
    tail: int = 200,
    user: dict = Depends(require_admin),
) -> dict:
    """Get recent audit logs."""
    with get_session() as session:
        logs = session.query(AuditLog).order_by(AuditLog.created_at.desc()).limit(tail).all()
        return {
            "logs": [
                {
                    "id": log.id,
                    "actor": log.actor,
                    "action": log.action,
                    "payload": log.payload,
                    "created_at": log.created_at.isoformat() if log.created_at else None,
                }
                for log in logs
            ]
        }
