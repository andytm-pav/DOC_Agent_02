"""v2.9.1: админ-наблюдаемость — живой прогресс ингеста/эмбеддинга,
браузер документов и чанков, перечень моделей агента, новые поля /admin/debug,
вендоренные md-библиотеки в /static. Тесты офлайн (hashing-эмбеддинги)."""
from __future__ import annotations

from pathlib import Path

import pytest

from conftest import upload_and_wait


@pytest.fixture()
def done_file(client, admin_token, tmp_path: Path) -> dict:
    """Обработанный файл в картотеке (через полный конвейер ингеста)."""
    p = tmp_path / "sample_doc.txt"
    p.write_text(
        "Договор подряда № 123 от 01.02.2024\nИтого: 100 руб.\nМатериалы: доски, метизы.\n" * 40,
        encoding="utf-8",
    )
    return upload_and_wait(client, admin_token, p)


# --- GET /admin/ingest/progress ---


def test_progress_requires_admin(client, user_token):
    r = client.get("/admin/ingest/progress",
                   headers={"Authorization": f"Bearer {user_token}"})
    assert r.status_code == 403


def test_progress_ok(client, admin_token, done_file):
    r = client.get("/admin/ingest/progress",
                   headers={"Authorization": f"Bearer {admin_token}"})
    assert r.status_code == 200
    d = r.json()
    assert d["queue"]["done"] >= 1
    assert d["worker_alive"] is True
    assert d["embedding"]["resolved_backend"] == "hashing"
    assert d["embedding"]["count"] >= 1
    assert any(f["id"] == done_file["file"]["id"] and f["chunks"] >= 1
               for f in d["recent_files"])
    assert {"queued", "processing", "done", "failed"} <= set(d["queue"].keys())
    assert "done_last_hour" in d["throughput"]


# --- GET /admin/documents и /admin/documents/{id}/chunks ---


def test_documents_requires_admin(client, user_token):
    r = client.get("/admin/documents",
                   headers={"Authorization": f"Bearer {user_token}"})
    assert r.status_code == 403


def test_documents_lists_file_with_chunks(client, admin_token, done_file):
    r = client.get("/admin/documents",
                   headers={"Authorization": f"Bearer {admin_token}"})
    assert r.status_code == 200
    d = r.json()
    assert d["files_total"] >= 1
    mine = [f for f in d["files"] if f["id"] == done_file["file"]["id"]]
    assert mine and mine[0]["chunks"] >= 1
    assert mine[0]["status"] == "done"
    assert "size_bytes" in mine[0] and "doc_type" in mine[0]


def test_document_chunks_content(client, admin_token, done_file):
    fid = done_file["file"]["id"]
    r = client.get(f"/admin/documents/{fid}/chunks",
                   headers={"Authorization": f"Bearer {admin_token}"})
    assert r.status_code == 200
    d = r.json()
    assert d["chunks_total"] >= 1
    assert len(d["chunks"]) == d["chunks_total"]
    first = d["chunks"][0]
    assert first["chunk_index"] == 0
    assert first["chars"] > 0 and first["text"].strip()
    # text_max ограничивает текст и ставит флаг truncation
    r2 = client.get(f"/admin/documents/{fid}/chunks?text_max=100",
                    headers={"Authorization": f"Bearer {admin_token}"})
    c0 = r2.json()["chunks"][0]
    assert len(c0["text"]) <= 100
    assert c0["truncated"] == (c0["chars"] > 100)


def test_document_chunks_404(client, admin_token):
    r = client.get("/admin/documents/999999/chunks",
                   headers={"Authorization": f"Bearer {admin_token}"})
    assert r.status_code == 404


# --- GET /admin/models ---


def test_models_requires_admin(client, user_token):
    r = client.get("/admin/models",
                   headers={"Authorization": f"Bearer {user_token}"})
    assert r.status_code == 403


def test_models_lists_all_roles(client, admin_token):
    r = client.get("/admin/models",
                   headers={"Authorization": f"Bearer {admin_token}"})
    assert r.status_code == 200
    d = r.json()
    assert d["llm"]["model_main"]
    assert d["llm"]["planner_model"] in {d["llm"]["model_main"], d["llm"]["model_light"]}
    # resolved_backend обязан присутствовать и быть валидным
    assert d["embeddings"]["resolved_backend"] in {"hashing", "api", "sentence_transformers"}
    assert d["embeddings"]["device"] == "auto"
    assert "query_prefix" in d["embeddings"] and "passage_prefix" in d["embeddings"]
    assert d["vector"]["metric"] == "cosine"
    assert d["reranker"]["backend"] == "simple"
    assert d["ocr"]["engine"] == "tesseract"
    assert "fastapi" in d["packages"]


# --- /admin/debug: новые поля (обратносовместимое расширение) ---


def test_debug_has_new_observability_keys(client, admin_token):
    r = client.get("/admin/debug",
                   headers={"Authorization": f"Bearer {admin_token}"})
    assert r.status_code == 200
    d = r.json()
    assert "packages" in d and "fastapi" in d["packages"]
    assert d["worker_alive"] is True
    assert "reranker" in d and "ocr" in d
    # прежние ключи диагностики не сломаны
    for key in ("version", "health", "llm", "embeddings", "vector", "database",
                "audit_tail", "error_log_tail"):
        assert key in d, key
    # v2.9: поля локальной модели в секции embeddings
    assert d["embeddings"]["device"] == "auto"
    assert d["embeddings"]["local_dimensions"] == "auto (из модели)"
    assert d["embeddings"]["query_prefix"] == "query: "


# --- вендоренные md-библиотеки доступны в /static ---


def test_md_libraries_served(client):
    for name in ("marked.min.js", "purify.min.js"):
        r = client.get(f"/static/{name}")
        assert r.status_code == 200, name
        assert len(r.content) > 1000, name
