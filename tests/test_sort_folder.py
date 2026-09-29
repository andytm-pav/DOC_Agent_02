"""Разгребание свалки (v2.3): POST /files/sort-folder + GET статуса.

Проверяем: копирование по тематическим папкам, fallback без LLM
(by_extension), LLM-названия (мок) с очисткой запрещённых символов и
лимитом числа папок, режим перемещения, пустую папку, ошибки API
(404/401/404 задания/409 отключённой функции) и панель в UI.
"""
from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

import yaml


def _start_sort(client, token: str, body: dict):
    return client.post("/files/sort-folder", json=body,
                       headers={"Authorization": f"Bearer {token}"})


def _wait_done(client, token: str, job_id: str, timeout: float = 30.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = client.get(f"/files/sort-folder/{job_id}",
                       headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200, r.text
        data = r.json()
        if data["state"] in {"done", "error"}:
            return data
        time.sleep(0.2)
    raise TimeoutError("задание разбора не завершилось")


def _tune_config(tmp_data_dir: Path, patch: dict) -> None:
    """Правит тестовый config.yaml (все настройки — только через конфиг)."""
    cfg_path = Path(os.environ["DOC_AGENT_CONFIG"])
    data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    for section, values in patch.items():
        data.setdefault(section, {}).update(values)
    cfg_path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


def _enable_fake_llm(monkeypatch, assignments: list[dict]) -> None:
    """LLM-заглушка возвращает assignments вне зависимости от запроса."""
    from doc_agent.services import sorting

    class FakeLLM:
        def chat(self, prompt: str, model: str | None = None, timeout: float | None = None) -> str:
            return json.dumps({"assignments": assignments})

        def ping(self) -> bool:
            return True

    monkeypatch.setattr(sorting, "get_llm", lambda: FakeLLM())


def test_sort_folder_fallback_by_extension(client, admin_token, sample_files, tmp_path):
    dump = tmp_path / "свалка"
    dump.mkdir()
    shutil.copy(sample_files["docx"], dump / "акт.docx")
    (dump / "заметка.txt").write_text("Договор № 1", encoding="utf-8")
    (dump / "другая.txt").write_text("Договор № 2", encoding="utf-8")
    (dump / "мусор.exe").write_bytes(b"MZ\x90\x00")
    (dump / ".hidden.txt").write_text("x", encoding="utf-8")

    r = _start_sort(client, admin_token, {"path": str(dump)})
    assert r.status_code == 200, r.text
    data = _wait_done(client, admin_token, r.json()["job_id"])
    assert data["state"] == "done", data
    res = data["result"]

    run_dir = Path(res["run_dir"])
    assert run_dir.is_dir()
    assert "Разобранная свалка_" in run_dir.name          # имя из конфига
    assert run_dir.parent.name == "свалка_разобрано"      # суффикс из конфига
    assert res["mode"] == "copy"
    assert res["llm_named"] == 0 and res["fallback_used"] == 3
    folders = {f["folder"]: f["count"] for f in res["folders"]}
    assert folders == {"Файлы DOCX": 1, "Файлы TXT": 2}   # шаблон fallback из конфига

    # файлы скопированы, оригиналы остались на месте (свалка не тронута)
    assert (run_dir / "Файлы DOCX" / "акт.docx").exists()
    assert (dump / "акт.docx").exists()
    assert res["counters"]["unsupported"] == 1            # мусор.exe
    assert res["counters"]["skipped"] == 1                # .hidden.txt
    assert res["counters"]["placed"] == 3


def test_sort_folder_llm_names_sanitization_and_cap(client, admin_token, tmp_path,
                                                    tmp_data_dir, monkeypatch):
    _tune_config(tmp_data_dir, {
        "llm": {"provider": "openai_compatible", "base_url": "http://localhost:9", "api_key": "k"},
        "sorting": {"max_folders": 2},
    })
    dirty = 'Договоры/аренды:*?"<>|'
    _enable_fake_llm(monkeypatch, [
        {"index": 1, "folder": dirty},
        {"index": 2, "folder": dirty},
        {"index": 3, "folder": "Редкая тема"},
        {"index": 4, "folder": "Ещё тема"},
        {"index": 5, "folder": "Ещё тема"},
        {"index": 6, "folder": "Ещё тема"},
    ])

    dump = tmp_path / "доки"
    dump.mkdir()
    for i in range(1, 7):
        (dump / f"док{i}.txt").write_text(f"Содержимое {i}", encoding="utf-8")

    r = _start_sort(client, admin_token, {"path": str(dump)})
    assert r.status_code == 200, r.text
    data = _wait_done(client, admin_token, r.json()["job_id"])
    assert data["state"] == "done", data
    res = data["result"]

    assert res["llm_named"] == 6 and res["fallback_used"] == 0
    folders = {f["folder"]: f["count"] for f in res["folders"]}
    # запрещённые символы очищены; папок больше max_folders=2 -> редкая уходит в «Прочее»
    assert folders == {"Договоры аренды": 2, "Ещё тема": 3, "Прочее": 1}
    run_dir = Path(res["run_dir"])
    assert (run_dir / "Договоры аренды" / "док1.txt").exists()
    assert (run_dir / "Прочее" / "док3.txt").exists()


def test_sort_folder_move_mode(client, admin_token, tmp_path, tmp_data_dir):
    _tune_config(tmp_data_dir, {"sorting": {"move_files": True}})
    dump = tmp_path / "бардак"
    dump.mkdir()
    (dump / "один.txt").write_text("Договор № 1", encoding="utf-8")
    (dump / "два.txt").write_text("Договор № 2", encoding="utf-8")

    r = _start_sort(client, admin_token, {"path": str(dump)})
    assert r.status_code == 200, r.text
    data = _wait_done(client, admin_token, r.json()["job_id"])
    assert data["state"] == "done", data
    res = data["result"]

    assert res["mode"] == "move"
    assert res["moved"] == 2 and res["copied"] == 0
    assert list(dump.glob("*.txt")) == []                 # оригиналы перемещены
    run_dir = Path(res["run_dir"])
    assert (run_dir / "Файлы TXT" / "один.txt").exists()


def test_sort_folder_empty_dump(client, admin_token, tmp_path):
    dump = tmp_path / "пусто"
    dump.mkdir()
    (dump / "program.exe").write_bytes(b"MZ")

    r = _start_sort(client, admin_token, {"path": str(dump)})
    assert r.status_code == 200
    data = _wait_done(client, admin_token, r.json()["job_id"])
    assert data["state"] == "error"
    assert "нет поддерживаемых файлов" in data["error"]


def test_sort_folder_api_errors(client, admin_token, tmp_data_dir):
    assert _start_sort(client, admin_token, {"path": "Z:/нет/такой/папки"}).status_code == 404
    assert client.post("/files/sort-folder", json={"path": "/tmp"}).status_code == 401
    r = client.get("/files/sort-folder/нет-такого-задания",
                   headers={"Authorization": f"Bearer {admin_token}"})
    assert r.status_code == 404

    _tune_config(tmp_data_dir, {"sorting": {"enabled": False}})
    r2 = _start_sort(client, admin_token, {"path": str(tmp_data_dir)})
    assert r2.status_code == 409
    assert "отключено" in r2.json()["detail"]


def test_chat_page_has_sort_panel(client, admin_token):
    """В UI есть обе панели: импорт папки + разбор свалки."""
    r = client.get("/")
    assert r.status_code == 200
    html = r.text
    assert 'id="scanFolderBtn"' in html                   # импорт (не сломали)
    assert 'id="sortDumpPath"' in html
    assert 'id="sortOutputPath"' in html
    assert 'id="sortFolderBtn"' in html
    assert "Разобрать свалку" in html
    assert 'data-poll-ms=' in html                        # интервал из конфига
