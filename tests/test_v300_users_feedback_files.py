"""Тесты v3.0.0: обратная связь («дообучение»), пользователи/группы
(users.yaml), файлы на диске (sandbox + память путей), CRUD документов
и чанков в админке.

Конфиг тестов: llm.provider=none (детерминированный офлайн-режим),
эмбеддинги hashing — фидбэк работает на лексической похожести.
"""
from __future__ import annotations

import time
from pathlib import Path

from tests.conftest import upload_and_wait

ADMIN = {"Authorization": "Bearer test-admin"}  # заменяется фикстурой ниже


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------- фидбэк

def test_feedback_submit_and_admin_list(client, admin_token):
    # пользовательский отзыв
    r = client.post("/feedback", headers=_auth(admin_token), json={
        "question": "сделай таблицу договоров по вилоновской",
        "answer": "таблица…", "rating": "down",
        "corrected_answer": "Правильная таблица: 4 договора [file_id:1,11,12,13]",
        "file_ids": [1, 11, 12, 13],
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True and body["id"] > 0
    # повтор того же вопроса тем же пользователем — обновление, не дубликат
    r2 = client.post("/feedback", headers=_auth(admin_token), json={
        "question": "сделай таблицу договоров по вилоновской",
        "answer": "таблица…", "rating": "up", "file_ids": [12],
    })
    assert r2.status_code == 200
    assert r2.json()["created"] is False
    # админский список + статистика
    r3 = client.get("/feedback/admin/list", headers=_auth(admin_token))
    assert r3.status_code == 200
    data = r3.json()
    assert data["stats"]["total"] == 1
    entry = data["items"][0]
    assert entry["rating"] == "up"  # обновился
    assert entry["file_ids"] == [12]
    assert entry["has_vector"] is True  # вектор вопроса сохранён


def test_feedback_requires_permission(client, user_token, admin_token):
    # user-роль умеет отправлять отзыв (feedback_submit в дефолтной группе)
    r = client.post("/feedback", headers=_auth(user_token), json={
        "question": "вопрос", "answer": "ответ", "rating": "up"})
    assert r.status_code == 200
    # user-роль НЕ может смотреть админский список (нет feedback_manage)
    r2 = client.get("/feedback/admin/list", headers=_auth(user_token))
    assert r2.status_code == 403
    # но админ может
    r3 = client.get("/feedback/admin/list", headers=_auth(admin_token))
    assert r3.status_code == 200


def test_feedback_edit_disable_delete(client, admin_token):
    r = client.post("/feedback", headers=_auth(admin_token), json={
        "question": "сколько файлов по старому городу", "answer": "3", "rating": "up"})
    entry_id = r.json()["id"]
    # правка веса и отключение
    r2 = client.put(f"/feedback/admin/{entry_id}", headers=_auth(admin_token),
                    json={"weight": 2.5, "status": "disabled"})
    assert r2.status_code == 200
    assert r2.json()["status"] == "disabled"
    assert r2.json()["weight"] == 2.5
    # отключённая запись не участвует в похожести
    from doc_agent.services import feedback as fb
    assert fb.known_answers_block("сколько файлов по старому городу") == ""
    # удаление
    r3 = client.delete(f"/feedback/admin/{entry_id}", headers=_auth(admin_token))
    assert r3.status_code == 200
    r4 = client.get("/feedback/admin/list", headers=_auth(admin_token))
    assert r4.json()["stats"]["total"] == 0


def test_known_answer_injection_and_boost(client, admin_token):
    """Похожий вопрос подхватывает проверенный ответ (флаг в /query) и
    бустит отмеченные файлы."""
    from doc_agent.services import feedback as fb

    fb.add_or_update("admin", "сделай таблицу договоров по вилоновской",
                     "промежуточный", rating="up",
                     corrected_answer="ПРОВЕРЕННАЯ ТАБЛИЦА: 4 договора",
                     file_ids=[12])
    # прямой вызов известного блока
    block = fb.known_answers_block("сделай таблицу договоров по вилоновской")
    assert "ПРОВЕРЕННАЯ ТАБЛИЦА" in block
    # буст-карта: file 12 получил положительный множитель
    boost = fb.boost_map("таблица договоров по вилоновской")
    assert 12 in boost and boost[12] > 0
    # apply_boost мутирует fused_scores
    fused = {101: 0.05, 202: 0.04}
    applied = fb.apply_boost(fused, {101: 12, 202: 1}, "таблица договоров по вилоновской")
    assert applied == [12]
    assert fused[101] > 0.05
    assert abs(fused[202] - 0.04) < 1e-9


# ------------------------------------------------- пользователи и группы

def test_users_crud_and_login(client, admin_token):
    # создание
    r = client.post("/admin/users", headers=_auth(admin_token), json={
        "username": "ivan", "password": "pass1234", "groups": ["users"],
        "display_name": "Иван"})
    assert r.status_code == 200, r.text
    # вход нового пользователя
    r2 = client.post("/auth/login", json={"username": "ivan", "password": "pass1234"})
    assert r2.status_code == 200
    ivan_token = r2.json()["access_token"]
    assert r2.json()["role"] == "user"
    # /me показывает группы и права
    r3 = client.get("/auth/me", headers=_auth(ivan_token))
    me = r3.json()
    assert me["groups"] == ["users"]
    assert "chat" in me["permissions"] and "admin" not in me["permissions"]
    # ivan не видит админ-панель пользователей
    r4 = client.get("/admin/users", headers=_auth(ivan_token))
    assert r4.status_code == 403
    # смена пароля админом, вход со старым падает, с новым работает
    r5 = client.put("/admin/users/ivan", headers=_auth(admin_token),
                    json={"password": "newpass99"})
    assert r5.status_code == 200
    r6 = client.post("/auth/login", json={"username": "ivan", "password": "pass1234"})
    assert r6.status_code == 401
    r7 = client.post("/auth/login", json={"username": "ivan", "password": "newpass99"})
    assert r7.status_code == 200
    # удаление
    r8 = client.delete("/admin/users/ivan", headers=_auth(admin_token))
    assert r8.status_code == 200
    r9 = client.post("/auth/login", json={"username": "ivan", "password": "newpass99"})
    assert r9.status_code == 401


def test_users_validation_guards(client, admin_token):
    # слабый пароль / дубль / неизвестная группа
    r = client.post("/admin/users", headers=_auth(admin_token),
                    json={"username": "x", "password": "1234"})
    assert r.status_code == 422  # логин короче 2
    r2 = client.post("/admin/users", headers=_auth(admin_token),
                     json={"username": "petr", "password": "12345", "groups": ["nope"]})
    assert r2.status_code == 422
    # нельзя удалить последнего админа
    r3 = client.delete("/admin/users/admin", headers=_auth(admin_token))
    assert r3.status_code == 422
    # нельзя удалить себя
    r4 = client.delete("/admin/users/admin2", headers=_auth(admin_token))
    assert r4.status_code == 404  # admin2 не существует — сначала 404, это ок
    r5 = client.delete("/admin/users/admin", headers=_auth(admin_token))
    assert r5.status_code == 422


def test_groups_permissions_and_roots(client, admin_token):
    # новая группа с правом files_manage и корнем
    disk_root = None
    from doc_agent.config import load_settings

    disk_root = load_settings().files.allowed_roots[0]
    r = client.post("/admin/groups/archivarius", headers=_auth(admin_token),
                    json={"permissions": ["chat", "files_manage"], "allowed_roots": [str(disk_root)]})
    assert r.status_code == 200
    # пользователь в новой группе
    r2 = client.post("/admin/users", headers=_auth(admin_token),
                     json={"username": "masha", "password": "pass1234", "groups": ["archivarius"]})
    assert r2.status_code == 200
    r3 = client.post("/auth/login", json={"username": "masha", "password": "pass1234"})
    masha = r3.json()["access_token"]
    # masha может создавать папки в разрешённом корне (files_manage)
    r4 = client.post("/admin/files/mkdir", headers=_auth(masha),
                     json={"path": str(Path(disk_root) / "новая_папка")})
    assert r4.status_code == 200, r4.text
    assert (Path(disk_root) / "новая_папка").is_dir()
    # masha НЕ может удалять документы (нет documents_manage)
    r5 = client.delete("/admin/documents/999", headers=_auth(masha))
    assert r5.status_code == 403
    # удаление группы с пользователем запрещено
    r6 = client.delete("/admin/groups/archivarius", headers=_auth(admin_token))
    assert r6.status_code == 422


# --------------------------------------------------- файлы на диске

def test_fileops_sandbox(client, admin_token):
    from doc_agent.config import load_settings
    from doc_agent.services import fileops

    root = Path(load_settings().files.allowed_roots[0]).resolve()
    inside = root / "sub"
    inside.mkdir(parents=True, exist_ok=True)
    assert fileops.resolve_safe(str(inside), [root]) == inside.resolve()
    # относительный путь запрещён
    try:
        fileops.resolve_safe("relative/path", [root])
        raise AssertionError("ожидали FileOpsError")
    except fileops.FileOpsError:
        pass
    # выход за корни запрещён
    try:
        fileops.resolve_safe(str(root.parent / "outside"), [root])
        raise AssertionError("ожидали FileOpsError")
    except fileops.FileOpsError:
        pass
    # обман через .. нейтрализуется resolve()
    try:
        fileops.resolve_safe(str(root / ".." / "escape"), [root])
        raise AssertionError("ожидали FileOpsError")
    except fileops.FileOpsError:
        pass


def test_move_copy_and_locations(client, admin_token, sample_files):
    from doc_agent.config import load_settings

    token = admin_token
    data = upload_and_wait(client, token, sample_files["docx"])
    file_id = data["file"]["id"]
    # путь не запомнен (файл загружен браузером) — копируем из картотеки
    root = Path(load_settings().files.allowed_roots[0])
    dest = root / "отчёты"
    r = client.post(f"/admin/files/{file_id}/copy", headers=_auth(token),
                    json={"dest": str(dest), "create_dest": True})
    assert r.status_code == 200, r.text
    copied = Path(r.json()["to"])
    assert copied.exists()
    # путь запомнился и виден в панели
    r2 = client.get("/admin/file-locations", headers=_auth(token))
    items = r2.json()["items"]
    assert any(i["file_id"] == file_id and Path(i["path"]) == copied for i in items)
    # перемещение копии в другую папку
    dest2 = root / "архив"
    r3 = client.post(f"/admin/files/{file_id}/move", headers=_auth(token),
                     json={"dest": str(dest2), "create_dest": True})
    assert r3.status_code == 200
    moved = Path(r3.json()["to"])
    assert moved.exists() and not copied.exists()
    # ручной путь + удаление записи
    r4 = client.post("/admin/file-locations", headers=_auth(token),
                     json={"file_id": file_id, "path": str(moved)})
    assert r4.status_code == 200
    loc_id = [i["id"] for i in client.get("/admin/file-locations", headers=_auth(token)).json()["items"]
              if i["file_id"] == file_id][0]
    r5 = client.delete(f"/admin/file-locations/{loc_id}", headers=_auth(token))
    assert r5.status_code == 200
    # mkdir через админ-эндпоинт
    r6 = client.post("/admin/files/mkdir", headers=_auth(token),
                     json={"path": str(root / "год2026")})
    assert r6.status_code == 200


def test_file_location_remembered_on_scan(client, admin_token, sample_files):
    """Импорт папки запоминает оригинальные пути файлов (v3.0.0)."""
    from doc_agent.services import ingest

    src_dir = sample_files["docx"].parent
    summary = ingest.scan_folder(src_dir, recursive=False, source="test")
    assert summary["queued"] >= 1
    # путей нет, пока файл не взят в работу? — нет: remember вызывается при
    # постановке в очередь, сразу после enqueue_file
    from doc_agent.db.models import FileLocation
    from doc_agent.db.session import get_session_factory

    time.sleep(0.1)
    factory = get_session_factory()
    with factory() as db:
        n = db.query(FileLocation).filter(FileLocation.kind == "original").count()
    assert n >= 1
    # дожидаемся опустошения очереди: воркер — поток ОДИН на процесс, и он
    # не должен быть занят при выходе из клиента (иначе следующий тест
    # не получит воркер — гонка start/stop в тестовом окружении)
    from doc_agent.db.models import Job

    deadline = time.time() + 30
    while time.time() < deadline:
        with factory() as db:
            busy = db.query(Job).filter(Job.status.in_(["queued", "processing"])).count()
        if busy == 0:
            break
        time.sleep(0.3)
    assert busy == 0, "очередь не опустела — воркер застрял"


# --------------------------------------- CRUD документов и чанков

def test_chunk_edit_and_delete(client, admin_token, sample_files):
    token = admin_token
    data = upload_and_wait(client, token, sample_files["xlsx"])
    file_id = data["file"]["id"]
    r = client.get(f"/admin/documents/{file_id}/chunks", headers=_auth(token))
    chunks = r.json()["chunks"]
    assert chunks, "у файла должны быть чанки"
    chunk_id = chunks[0]["id"]
    # правка текста чанка
    new_text = "ИСПРАВЛЕННЫЙ ТЕКСТ ЧАНКА: сумма 999999 руб"
    r2 = client.put(f"/admin/chunks/{chunk_id}", headers=_auth(token),
                    json={"text": new_text})
    assert r2.status_code == 200, r2.text
    assert r2.json()["vector_updated"] is True
    # текст в БД обновился
    r3 = client.get(f"/admin/documents/{file_id}/chunks", headers=_auth(token))
    assert any(new_text in c["text"] for c in r3.json()["chunks"])
    # удаление чанка
    total_before = r3.json()["chunks_total"]
    r4 = client.delete(f"/admin/chunks/{chunk_id}", headers=_auth(token))
    assert r4.status_code == 200
    r5 = client.get(f"/admin/documents/{file_id}/chunks", headers=_auth(token))
    assert r5.json()["chunks_total"] == total_before - 1


def test_document_reprocess_and_delete(client, admin_token, sample_files):
    token = admin_token
    data = upload_and_wait(client, token, sample_files["docx"])
    file_id = data["file"]["id"]
    # реиндексация одного файла ставится в очередь
    r = client.post(f"/admin/documents/{file_id}/reprocess", headers=_auth(token))
    assert r.status_code == 200
    assert r.json()["job_id"] > 0
    # удаление документа целиком
    r2 = client.delete(f"/admin/documents/{file_id}", headers=_auth(token))
    assert r2.status_code == 200
    r3 = client.get(f"/files/{file_id}", headers=_auth(token))
    assert r3.status_code == 404


def test_debug_includes_v300_sections(client, admin_token):
    r = client.get("/admin/debug", headers=_auth(admin_token))
    assert r.status_code == 200
    d = r.json()
    assert "feedback" in d and "users_file" in d and "file_locations_total" in d
