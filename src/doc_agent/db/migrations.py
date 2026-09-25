"""Manual database migrations."""

from sqlalchemy import text
from sqlalchemy.orm import Session


def run_migrations(session: Session) -> None:
    """Run any pending migrations."""
    # For v2.0, all tables are created by Base.metadata.create_all()
    # Future migrations would be added here

    # Example migration pattern:
    # try:
    #     session.execute(text("ALTER TABLE files ADD COLUMN new_field TEXT"))
    #     session.commit()
    # except Exception:
    #     session.rollback()  # Column already exists
    pass
