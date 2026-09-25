"""SQLAlchemy models matching the DDL from the specification."""

from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    """Base class for all models."""
    pass


class File(Base):
    """Document file metadata."""

    __tablename__ = "files"

    id = Column(Integer, primary_key=True, autoincrement=True)
    sha256 = Column(String, unique=True, nullable=False)
    original_name = Column(String, nullable=False)
    stored_path = Column(String, nullable=False)
    format = Column(String, nullable=False)
    size_bytes = Column(Integer, nullable=False)
    mtime = Column(String, nullable=False)
    city = Column(String, nullable=True)
    customer = Column(String, nullable=True)
    contract_no = Column(String, nullable=True)
    contract_date = Column(String, nullable=True)
    doc_type = Column(String, nullable=True)
    doc_number = Column(String, nullable=True)
    doc_date = Column(String, nullable=True)
    amount = Column(Float, nullable=True)
    status = Column(String, nullable=False, default="pending")
    ocr_confidence = Column(Float, nullable=True)
    description = Column(Text, nullable=True)
    source = Column(String, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    chunks = relationship("Chunk", back_populates="file", cascade="all, delete-orphan")
    tables = relationship("TableFlat", back_populates="file", cascade="all, delete-orphan")
    jobs = relationship("Job", back_populates="file", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_files_contract", "contract_no"),
        Index("idx_files_type", "doc_type"),
        Index("idx_files_city", "city"),
    )


class FileLink(Base):
    """Links between related files."""

    __tablename__ = "file_links"

    id = Column(Integer, primary_key=True, autoincrement=True)
    parent_id = Column(Integer, ForeignKey("files.id", ondelete="CASCADE"), nullable=False)
    child_id = Column(Integer, ForeignKey("files.id", ondelete="CASCADE"), nullable=False)
    link_type = Column(String, nullable=False)

    __table_args__ = (
        UniqueConstraint("parent_id", "child_id", "link_type"),
    )


class Chunk(Base):
    """Text chunks for vector search."""

    __tablename__ = "chunks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    file_id = Column(Integer, ForeignKey("files.id", ondelete="CASCADE"), nullable=False)
    chunk_index = Column(Integer, nullable=False)
    text = Column(Text, nullable=False)
    page = Column(Integer, nullable=True)
    char_start = Column(Integer, nullable=True)
    char_end = Column(Integer, nullable=True)

    file = relationship("File", back_populates="chunks")

    __table_args__ = (
        Index("idx_chunks_file", "file_id"),
    )


class TableFlat(Base):
    """Flattened table data."""

    __tablename__ = "tables_flat"

    id = Column(Integer, primary_key=True, autoincrement=True)
    file_id = Column(Integer, ForeignKey("files.id", ondelete="CASCADE"), nullable=False)
    table_name = Column(String, nullable=True)
    row_index = Column(Integer, nullable=True)
    col_index = Column(Integer, nullable=True)
    value = Column(Text, nullable=True)
    cell_ref = Column(String, nullable=True)

    file = relationship("File", back_populates="tables")

    __table_args__ = (
        Index("idx_tables_file", "file_id"),
    )


class Job(Base):
    """Background job queue."""

    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    file_id = Column(Integer, ForeignKey("files.id", ondelete="CASCADE"), nullable=True)
    kind = Column(String, nullable=False)
    priority = Column(Integer, nullable=False, default=5)
    status = Column(String, nullable=False, default="queued")
    attempts = Column(Integer, nullable=False, default=0)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    file = relationship("File", back_populates="jobs")


class AuditLog(Base):
    """Audit log for actions."""

    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    actor = Column(String, nullable=False)
    action = Column(String, nullable=False)
    payload = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class User(Base):
    """Application users."""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    role = Column(String, nullable=False, default="user")


class OcrCorrection(Base):
    """OCR corrections made by users."""

    __tablename__ = "ocr_corrections"

    id = Column(Integer, primary_key=True, autoincrement=True)
    file_id = Column(Integer, ForeignKey("files.id", ondelete="CASCADE"), nullable=False)
    original = Column(Text, nullable=False)
    corrected = Column(Text, nullable=False)
    user = Column(String, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
