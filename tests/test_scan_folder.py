"""Импорт свалки файлов из папки (требование пользователя): POST /files/scan-folder.

Проверяем: приём поддерживаемых файлов, пропуск мусора, dedup по sha256
при повторном импорте, recursive/non-recursive, source="folder",
обработку импортированного DOCX воркером, ошибки и UI-панель.
"""
from __future__ import annotations

import shutil
import time
from pathlib import Path

HEADERS = {"Authorization": ""}


def _scan(client, token: str, path: Path, recursive: bool | None = None) -> dict:
    body: dict = {"path": str(path)}
    if recursive is not None:
        body["recursive"] = recursive
    r = client.post("/files/scan-folder", json=body,
                    headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    return r.json()


def test_scan_folder_import_and_dedup(client, admin_token, sample_files, tmp_path):
    dump = tmp_path / "dump"
    (dump / "sub").mkdir(parents=True)
    shutil.copy(sample_files["docx"], dump / "акт_КС-2.docx")
    (dump / "заметка.txt").write_text("Договор № 555 от 01.05.2024. Сумма 10000 руб", encoding="utf-8")
    (dump / "sub" / "извещение.txt").write_text(
        "Извещение о получении корреспонденции", encoding="utf-8")
    (dump / "program.exe").write_bytes(b"MZ\x90\x00binary")
    (dump / "сломанный.docx").write_bytes(b"PK\x03\x04broken-zip")
    (dump / ".DS_Store").write_bytes(b"junk")
    (dump / "~$акт.docx").write_bytes(b"junk")

    data = _scan(client, admin_token, dump)

    assert data["path"] == str(dump)
    assert data["recursive"] is True
    assert data["queued"] == 3, data              # docx + заметка + извещение
    assert data["unsupported"] == 1               # program.exe
    assert data["failed"] == 1                    # сломанный.docx (битый zip)
    assert data["skipped"] == 2                   # .DS_Store + ~$акт.docx
    assert data["truncated"] is False
    assert len(data["file_ids"]) == 3

    # source="folder" у всех импортированных файлов
    for fid in data["file_ids"]:
        r = client.get(f"/files/{fid}", headers={"Authorization": f"Bearer {admin_token}"})
        assert r.status_code == 200
        assert r.json()["file"]["source"] == "folder"

    # Повторный импорт той же папки: всё уходит в дубликаты (dedup по sha256)
    data2 = _scan(client, admin_token, dump)
    assert data2["queued"] == 0
    assert data2["duplicates"] == 4               # 3 принятых + 1 сломанный

    # Импортированный DOCX доводится воркером до done и классифицируется как КС-2
    docx_id = None
    for fid in data["file_ids"]:
        r = client.get(f"/files/{fid}", headers={"Authorization": f"Bearer {admin_token}"})
        if r.json()["file"]["original_name"] == "акт_КС-2.docx":
            docx_id = fid
            break
    assert docx_id is not None
    deadline = time.time() + 40
    status = None
    while time.time() < deadline:
        r = client.get(f"/files/{docx_id}", headers={"Authorization": f"Bearer {admin_token}"})
        status = r.json()["file"]["status"]
        if status in {"done", "failed", "description_only"}:
            break
        time.sleep(0.3)
    assert status == "done", status
    r = client.get(f"/files/{docx_id}", headers={"Authorization": f"Bearer {admin_token}"})
    assert r.json()["file"]["doc_type"] == "ks2"


def test_scan_folder_non_recursive(client, admin_token, tmp_path):
    dump = tmp_path / "dump_flat"
    (dump / "sub").mkdir(parents=True)
    (dump / "верхний.txt").write_text("Договор № 1", encoding="utf-8")
    (dump / "sub" / "глубокий.txt").write_text("Договор № 2", encoding="utf-8")

    data = _scan(client, admin_token, dump, recursive=False)
    assert data["recursive"] is False
    assert data["queued"] == 1
    fid = data["file_ids"][0]
    r = client.get(f"/files/{fid}", headers={"Authorization": f"Bearer {admin_token}"})
    assert r.json()["file"]["original_name"] == "верхний.txt"


def test_scan_folder_not_found(client, admin_token):
    r = client.post("/files/scan-folder", json={"path": "Z:/нет/такой/папки"},
                    headers={"Authorization": f"Bearer {admin_token}"})
    assert r.status_code == 404
    assert "не найдена" in r.json()["detail"]


def test_scan_folder_requires_auth(client):
    r = client.post("/files/scan-folder", json={"path": "/tmp"})
    assert r.status_code == 401


def test_chat_page_has_folder_panel(client, admin_token):
    """В UI есть и drag&drop, и панель импорта папки — обе возможности."""
    r = client.get("/")
    assert r.status_code == 200
    html = r.text
    assert 'id="dropzone"' in html                 # перетаскивание по одному
    assert 'id="folderPath"' in html               # папка свалки
    assert 'id="scanFolderBtn"' in html
    assert "Импортировать папку" in html
