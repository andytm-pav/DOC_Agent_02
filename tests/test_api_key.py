"""Доступ к API агента из внешних систем по API-ключу (config auth.api_keys).

Проверяем: заголовок X-API-Key, фолбэк Authorization: Bearer <ключ>,
идентификацию api:<name>, роли user/admin, ошибки 401/403, сквозной сценарий
(загрузка файла -> запрос -> A2A) под ключом.
"""
from __future__ import annotations

import time

KU = {"X-API-Key": "test-api-key-user"}    # роль user
KA = {"X-API-Key": "test-api-key-admin"}   # роль admin


def test_me_and_query_with_api_key(client):
    r = client.get("/auth/me", headers=KU)
    assert r.status_code == 200, r.text
    me = r.json()
    assert me["username"] == "api:external-system"
    assert me["role"] == "user"

    r = client.post("/query", json={"q": "Дай ТТН №999"}, headers={**KU, "Content-Type": "application/json"})
    assert r.status_code == 200, r.text
    assert "НЕТ ДАННЫХ" in r.json()["answer"]


def test_bearer_api_key_fallback(client):
    """Bearer с API-ключом (вместо JWT) — удобно для curl/скриптов."""
    r = client.get("/auth/me", headers={"Authorization": "Bearer test-api-key-user"})
    assert r.status_code == 200
    assert r.json()["username"] == "api:external-system"


def test_wrong_key_401(client):
    r = client.get("/auth/me", headers={"X-API-Key": "wrong-key"})
    assert r.status_code == 401
    assert "API-ключ" in r.json()["detail"]


def test_no_auth_401(client):
    assert client.get("/auth/me").status_code == 401


def test_role_enforcement(client):
    # user-ключ не пускает в админку
    r = client.get("/admin/metrics", headers=KU)
    assert r.status_code == 403
    # admin-ключ пускает
    r = client.get("/admin/metrics", headers=KA)
    assert r.status_code == 200
    # admin-ключ проходит и user-эндпоинты
    assert client.get("/card", headers=KA).status_code == 200


def test_upload_and_folder_scan_with_api_key(client, sample_files, tmp_path):
    """Сквозной сценарий внешней системы: upload -> scan-folder -> query."""
    # 1) загрузка одного файла под ключом
    with open(sample_files["docx"], "rb") as fh:
        r = client.post("/files/upload", files={"file": ("ext_act.docx", fh)}, headers=KU)
    assert r.status_code == 200, r.text
    file_id = r.json()["file_id"]

    deadline = time.time() + 40
    status = None
    while time.time() < deadline:
        f = client.get(f"/files/{file_id}", headers=KU).json()["file"]
        status = f["status"]
        if status in {"done", "failed", "description_only"}:
            break
        time.sleep(0.3)
    assert status == "done", status

    # 2) импорт папки под ключом
    dump = tmp_path / "ext_dump"
    dump.mkdir()
    (dump / "заметка.txt").write_text("Договор № 777 от 01.07.2025", encoding="utf-8")
    r = client.post("/files/scan-folder", json={"path": str(dump)}, headers=KU)
    assert r.status_code == 200, r.text
    scan = r.json()
    assert scan["queued"] == 1

    # дожидаемся обработки импортированного файла воркером
    deadline = time.time() + 40
    while time.time() < deadline:
        f = client.get(f"/files/{scan['file_ids'][0]}", headers=KU).json()["file"]
        if f["status"] in {"done", "failed", "description_only"}:
            break
        time.sleep(0.3)
    assert f["status"] == "done", f

    # 3) вопрос по картотеке под ключом. Формулировка «по договору N»
    #    (как в ТЗ DD-4): вытаскивает фильтр contract_no=777 без фильтра
    #    doc_type=contract — заметка классифицирована как other.
    r = client.post("/query", json={"q": "Что по договору 777?"}, headers=KU)
    assert r.status_code == 200
    data = r.json()
    assert any(f["file_name"] == "заметка.txt" for f in data["files"]), data


def test_a2a_with_api_key(client):
    """A2A-клиент идентифицируется по X-API-Key (api:<name>)."""
    r = client.post("/a2a", json={
        "jsonrpc": "2.0", "id": 1, "method": "tasks/send",
        "params": {"message": {"role": "user", "parts": [{"type": "text", "text": "Есть документы?"}]}},
    }, headers=KU)
    assert r.status_code == 200, r.text
    body = r.json()
    # контракт ТЗ: result.status = "completed" (строка) + artifacts
    assert body.get("result", {}).get("status") == "completed", body
    assert body["result"].get("artifacts"), body


def test_health_without_auth(client):
    """/health остаётся открытым (без ключа) — для мониторинга."""
    assert client.get("/health").status_code == 200
