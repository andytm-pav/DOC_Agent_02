"""Database session management."""

from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from doc_agent.db.models import Base

_engine = None
_SessionLocal = None


def init_db(data_dir: str) -> None:
    """Initialize the database and create tables."""
    global _engine, _SessionLocal

    db_path = Path(data_dir) / "sqlite" / "app.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)

    _engine = create_engine(f"sqlite:///{db_path}", echo=False)
    _SessionLocal = sessionmaker(bind=_engine, autocommit=False, autoflush=False)

    # Create all tables
    Base.metadata.create_all(bind=_engine)

    # Create default admin user if not exists
    with get_session() as session:
        from doc_agent.db.models import User
        from doc_agent.auth import get_password_hash

        existing = session.query(User).filter(User.username == "admin").first()
        if not existing:
            admin = User(
                username="admin",
                password_hash=get_password_hash("admin"),
                role="admin",
            )
            session.add(admin)
            session.commit()


def get_session() -> Session:
    """Get a database session."""
    if _SessionLocal is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return _SessionLocal()


def check_db() -> bool:
    """Check if database is accessible."""
    try:
        with get_session() as session:
            session.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
