"""SQLAlchemy-модели. Схема 1:1 соответствует DDL из раздела 5.1 ТЗ."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

DOC_TYPES = ["ks2", "ks3", "ks6", "ttn", "ds", "id", "invoice", "contract", "other"]
FILE_STATUSES = ["pending", "processing", "done", "failed", "description_only"]


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Base(DeclarativeBase):
    pass


class File(Base):
    __tablename__ = "files"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sha256: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    original_name: Mapped[str] = mapped_column(String, nullable=False)
    stored_path: Mapped[str] = mapped_column(String, nullable=False)
    format: Mapped[str] = mapped_column(String, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    mtime: Mapped[str] = mapped_column(String, nullable=False)
    city: Mapped[str | None] = mapped_column(String, nullable=True)
    customer: Mapped[str | None] = mapped_column(String, nullable=True)
    contract_no: Mapped[str | None] = mapped_column(String, nullable=True)
    contract_date: Mapped[str | None] = mapped_column(String, nullable=True)
    doc_type: Mapped[str | None] = mapped_column(String, nullable=True)
    doc_number: Mapped[str | None] = mapped_column(String, nullable=True)
    doc_date: Mapped[str | None] = mapped_column(String, nullable=True)
    amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    ocr_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False, default=utcnow)
    updated_at: Mapped[str] = mapped_column(String, nullable=False, default=utcnow, onupdate=utcnow)


Index("idx_files_contract", File.contract_no)
Index("idx_files_type", File.doc_type)
Index("idx_files_city", File.city)


class FileLink(Base):
    __tablename__ = "file_links"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    parent_id: Mapped[int] = mapped_column(ForeignKey("files.id", ondelete="CASCADE"), nullable=False)
    child_id: Mapped[int] = mapped_column(ForeignKey("files.id", ondelete="CASCADE"), nullable=False)
    link_type: Mapped[str] = mapped_column(String, nullable=False)
    __table_args__ = (UniqueConstraint("parent_id", "child_id", "link_type"),)


class Chunk(Base):
    __tablename__ = "chunks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    file_id: Mapped[int] = mapped_column(ForeignKey("files.id", ondelete="CASCADE"), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    char_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    char_end: Mapped[int | None] = mapped_column(Integer, nullable=True)


Index("idx_chunks_file", Chunk.file_id)


class TableFlat(Base):
    __tablename__ = "tables_flat"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    file_id: Mapped[int] = mapped_column(ForeignKey("files.id", ondelete="CASCADE"), nullable=False)
    table_name: Mapped[str | None] = mapped_column(String, nullable=True)
    row_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    col_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    cell_ref: Mapped[str | None] = mapped_column(String, nullable=True)


Index("idx_tables_file", TableFlat.file_id)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    file_id: Mapped[int | None] = mapped_column(ForeignKey("files.id", ondelete="CASCADE"), nullable=True)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    status: Mapped[str] = mapped_column(String, nullable=False, default="queued")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False, default=utcnow)
    updated_at: Mapped[str] = mapped_column(String, nullable=False, default=utcnow, onupdate=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor: Mapped[str] = mapped_column(String, nullable=False)
    action: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False, default=utcnow)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False, default="user")


class OcrCorrection(Base):
    __tablename__ = "ocr_corrections"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    file_id: Mapped[int] = mapped_column(ForeignKey("files.id", ondelete="CASCADE"), nullable=False)
    original: Mapped[str] = mapped_column(Text, nullable=False)
    corrected: Mapped[str] = mapped_column(Text, nullable=False)
    user: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False, default=utcnow)


class ChatMessage(Base):
    """Сообщение чата: персистентная история + актуальный контекст беседы.

    Переживает обновление страницы (история грузится из БД). active=1 —
    сообщение входит в актуальный контекст, который передаётся репортеру;
    после «Очистить контекст» сообщения остаются в истории, но получают
    active=0, а их сжатая памятка пишется в context_archives — архив не
    занимает контекстное окно актуального контекста.
    """

    __tablename__ = "chat_messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False)  # user | agent | system
    content: Mapped[str] = mapped_column(Text, nullable=False)
    meta: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON: grounded, files, recall…
    active: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[str] = mapped_column(String, nullable=False, default=utcnow)


Index("idx_chat_user", ChatMessage.user, ChatMessage.id)


class ContextArchive(Base):
    """Сжатая памятка свёрнутого контекста («архив памяти»).

    Создаётся при «Очистить контекст». Не занимает контекстное окно
    актуального контекста; поднимается по запросу вида «вспомни …».
    """

    __tablename__ = "context_archives"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    message_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[str] = mapped_column(String, nullable=False, default=utcnow)


Index("idx_archives_user", ContextArchive.user, ContextArchive.id)
