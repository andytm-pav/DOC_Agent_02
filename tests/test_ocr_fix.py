"""test_ocr_fix.py: confidence 0.4 -> reject; 0.7 -> диалог (13.2, DD-6)."""
from __future__ import annotations

from conftest import upload_and_wait


def _make_low_confidence_file(client, user_token: str, sample_files: dict) -> int:
    """Загружает файл и принудительно ставит низкую OCR-уверенность (как после плохого OCR)."""
    from doc_agent.db.models import Chunk, File
    from doc_agent.db.session import get_session_factory

    data = upload_and_wait(client, user_token, sample_files["txt"] if False else sample_files["pdf"])
    file_id = data["file"]["id"]
    factory = get_session_factory()
    with factory() as db:
        f = db.get(File, file_id)
        assert f is not None
        f.ocr_confidence = 0.55
        if db.query(Chunk).filter(Chunk.file_id == file_id).count() == 0:
            db.add(Chunk(file_id=file_id, chunk_index=0, text="Договор № 12З-А от 2024 года",
                         page=1, char_start=0, char_end=30))
        db.commit()
    return file_id


def test_suspects_listed(client, user_token: str, sample_files: dict) -> None:
    file_id = _make_low_confidence_file(client, user_token, sample_files)
    r = client.get(f"/ocr/{file_id}/suspects", headers={"Authorization": f"Bearer {user_token}"})
    assert r.status_code == 200
    data = r.json()
    assert data["suspects"], "должны быть подозрительные фрагменты"


def test_correct_with_big_edit_distance_rejected(client, user_token: str, sample_files: dict) -> None:
    """>50% отличий -> отказ и просьба скана >=300 dpi (8.3 шаг 4)."""
    file_id = _make_low_confidence_file(client, user_token, sample_files)
    r = client.get(f"/ocr/{file_id}/suspects", headers={"Authorization": f"Bearer {user_token}"})
    chunk_id = r.json()["suspects"][0]["chunk_id"]
    resp = client.post(
        f"/ocr/{file_id}/correct",
        json={"chunk_id": chunk_id, "corrected": "полностью другой текст вовсе не похож"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    body = resp.json()
    assert body["status"] == "rejected"
    assert "300 dpi" in body["message"]


def test_correct_small_change_dialog(client, user_token: str, sample_files: dict) -> None:
    """confidence 0.55 (между reject 0.5 и min 0.8) -> исправление принимается + уточняющий вопрос."""
    file_id = _make_low_confidence_file(client, user_token, sample_files)
    r = client.get(f"/ocr/{file_id}/suspects", headers={"Authorization": f"Bearer {user_token}"})
    chunk = r.json()["suspects"][0]
    corrected = chunk["text"].replace("12З", "123")
    resp = client.post(
        f"/ocr/{file_id}/correct",
        json={"chunk_id": chunk["chunk_id"], "corrected": corrected},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    body = resp.json()
    assert body["status"] == "ok"
    assert "reindex_job" in body
    assert body["questions"], "агент задаёт уточняющий вопрос вместо догадки (DD-6)"
    assert "Верно ли я понял" in body["questions"][0]
