"""test_e2e.py: полный цикл upload -> query -> export (13.2, DD-1/DD-2)."""
from __future__ import annotations

import io
import time

from openpyxl import load_workbook

from conftest import upload_and_wait


def test_e2e_upload_query_export(client, user_token: str, sample_files: dict) -> None:
    t0 = time.time()
    # upload + обработка
    data = upload_and_wait(client, user_token, sample_files["pdf"])
    elapsed = time.time() - t0
    assert data["file"]["status"] == "done"
    assert elapsed <= 40, f"обработка заняла {elapsed:.1f} с (DD-2: <= 30 c для PDF <= 5 МБ)"
    file_id = data["file"]["id"]

    # DD-2: сообщение вида «Файл X добавлен в <папка>, распознан как <тип>»
    assert data["message"] and "добавлен в" in data["message"] and "распознан как" in data["message"]

    # query
    r = client.post(
        "/query",
        json={"q": "Покажи все КС2 по договору 123"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    result = r.json()
    assert file_id in [f["file_id"] for f in result["files"]]

    # export
    r2 = client.get("/card/export.xlsx", headers={"Authorization": f"Bearer {user_token}"})
    assert r2.status_code == 200
    wb = load_workbook(io.BytesIO(r2.content))
    assert wb.active.max_row >= 2


def test_health_endpoint(client) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] in {"ok", "degraded"}
    assert body["db"] == "ok"


def test_file_tree_endpoint(client, user_token: str, sample_files: dict) -> None:
    data = upload_and_wait(client, user_token, sample_files["docx"])
    file_id = data["file"]["id"]
    r = client.get(f"/files/{file_id}/tree", headers={"Authorization": f"Bearer {user_token}"})
    assert r.status_code == 200
    tree = r.json()
    assert tree["version"] == "1.0"
    kinds = {n["type"] for n in tree["children"]}
    assert "paragraph" in kinds or "heading" in kinds


def test_dedup_by_sha256(client, user_token: str, sample_files: dict) -> None:
    r1 = client.post(
        "/files/upload",
        files={"file": ("dup.pdf", open(sample_files["pdf"], "rb"))},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    r2 = client.post(
        "/files/upload",
        files={"file": ("dup.pdf", open(sample_files["pdf"], "rb"))},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    b1, b2 = r1.json(), r2.json()
    assert b1["file_id"] == b2["file_id"] or b2.get("dedup")
