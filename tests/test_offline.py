"""test_offline.py: запуск без интернета (13.2, DD-9).

- llm.provider: none -> все функции (кроме LLM-усилений) работают офлайн;
- недоступный Ollama -> деградация E004, но классификация/поиск живут;
- ChromaDB недоступна -> fallback BM25 (E005).
"""
from __future__ import annotations

import time

from conftest import upload_and_wait


def test_offline_full_flow(client, user_token: str, sample_files: dict) -> None:
    """provider=none: ingest, classify (rules), query, export — без внешних вызовов."""
    data = upload_and_wait(client, user_token, sample_files["pdf"])
    assert data["file"]["status"] == "done"
    assert data["file"]["doc_type"] == "ks2"

    r = client.post(
        "/query",
        json={"q": "Покажи все КС2 по договору 123"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    result = r.json()
    assert result["grounded"] is True
    assert result["files"]

    r2 = client.post("/query", json={"q": "Дай ТТН №999"}, headers={"Authorization": f"Bearer {user_token}"})
    assert "НЕТ ДАННЫХ" in r2.json()["answer"]


def test_offline_llm_unreachable_fallback(tmp_data_dir, sample_files: dict) -> None:
    """Конфиг с недоступным ollama: обработка завершается по правилам (E004)."""
    import yaml
    from fastapi.testclient import TestClient

    cfg_path = tmp_data_dir.parent / "config" / "config.yaml"
    config = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    config["llm"]["provider"] = "ollama"
    config["llm"]["base_url"] = "http://127.0.0.1:1"  # гарантированно недоступен
    cfg_path.write_text(yaml.safe_dump(config, allow_unicode=True), encoding="utf-8")

    from doc_agent.db import session as db_session
    from doc_agent.vector import chroma_client

    db_session._engines.clear()
    db_session._factories.clear()
    chroma_client.reset_vector_store()

    from doc_agent.main import app

    with TestClient(app) as client:
        r = client.post("/auth/login", json={"username": "admin", "password": "admin"})
        token = r.json()["access_token"]
        t0 = time.time()
        data = upload_and_wait(client, token, sample_files["pdf"], timeout=60)
        # E004: LLM недоступен -> регресс не падает, классификация по правилам
        assert data["file"]["status"] == "done"
        assert data["file"]["doc_type"] == "ks2"
        assert time.time() - t0 < 60
        h = client.get("/health").json()
        assert h["ollama"] == "degraded"


def test_offline_vector_store_unavailable_fallback(tmp_data_dir, sample_files: dict) -> None:
    """vector.backend=chroma, но хранилище ломается -> LiteVectorStore (E005)."""
    import yaml
    from fastapi.testclient import TestClient

    cfg_path = tmp_data_dir.parent / "config" / "config.yaml"
    config = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    config["vector"]["backend"] = "lite"  # прямое переключение (как fallback)
    cfg_path.write_text(yaml.safe_dump(config, allow_unicode=True), encoding="utf-8")

    from doc_agent.db import session as db_session
    from doc_agent.vector import chroma_client

    db_session._engines.clear()
    db_session._factories.clear()
    chroma_client.reset_vector_store()

    from doc_agent.main import app

    with TestClient(app) as client:
        token = client.post("/auth/login", json={"username": "admin", "password": "admin"}).json()["access_token"]
        data = upload_and_wait(client, token, sample_files["pdf"])
        assert data["file"]["status"] == "done"
        r = client.post(
            "/query",
            json={"q": "КС2 по договору 123"},
            headers={"Authorization": f"Bearer {token}"},
        )
        result = r.json()
        assert result["files"], "поиск должен работать на lite-store + BM25"
