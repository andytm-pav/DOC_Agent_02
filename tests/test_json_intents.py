"""Тесты v2.4.1: устойчивое извлечение JSON из ответов LLM (reasoning-модели
вроде glm-4.5-flash оборачивают ответ в <think>/```json) и сервисные ответы
чата («покажи все файлы», «что ты можешь?») вне поиска по документам."""
from __future__ import annotations

import time

import pytest

from doc_agent.services.sorting import _parse_assignments
from doc_agent.subagents.classifier_agent import ClassifierAgent
from doc_agent.utils.json_extract import extract_json

# ---------- utils.json_extract ----------

def test_extract_json_plain() -> None:
    assert extract_json('{"a": 1}') == {"a": 1}
    assert extract_json("  [1, 2]  ") == [1, 2]


def test_extract_json_think_and_fence() -> None:
    """glm-4.5-flash: размышления + ```json-ограждение + текст вокруг."""
    raw = (
        '<think>Нужно назвать папки. Пример из промпта: {"assignments": []} — не годится.'
        '</think>\nВот результат:\n```json\n'
        '{"assignments": [{"index": 1, "folder": "Договоры"}]}\n```\nГотово!'
    )
    assert extract_json(raw) == {"assignments": [{"index": 1, "folder": "Договоры"}]}


def test_extract_json_last_candidate_wins() -> None:
    """Braces в тексте-рассуждении не должны ломать разбор: берём последний
    валидный кандидат (финальный ответ модели)."""
    raw = (
        'Сначала про структуру {"doc_type": "ks2"} — это пример. '
        'Финальный ответ: {"doc_type": "contract", "confidence": 0.9}'
    )
    data = extract_json(raw)
    assert data == {"doc_type": "contract", "confidence": 0.9}


def test_extract_json_trailing_commas_and_python_style() -> None:
    assert extract_json('{"a": 1, "b": [1, 2,],}') == {"a": 1, "b": [1, 2]}
    assert extract_json("{'a': 'Привет', 'ok': True, 'n': None}") == {
        "a": "Привет", "ok": True, "n": None,
    }


def test_extract_json_no_json_raises() -> None:
    with pytest.raises(ValueError):
        extract_json("никакого JSON здесь нет")
    with pytest.raises(ValueError):
        extract_json("")
    with pytest.raises(ValueError):
        extract_json("   ")


# ---------- sorting._parse_assignments ----------

def test_parse_assignments_survives_messy_llm() -> None:
    raw = (
        '<think>Пример из промпта: {"assignments": [{"index": 1, "folder": "Пример"}]}</think>\n'
        'Ответ:\n```json\n{"assignments": [{"index": 1, "folder": "Акты (КС-2)"},'
        ' {"index": 2, "folder": "Счета"}]}\n```'
    )
    assert _parse_assignments(raw, {0, 1}) == {0: "Акты (КС-2)", 1: "Счета"}


def test_parse_assignments_bare_array() -> None:
    raw = '```json\n[{"index": 2, "folder": "Счета"}]\n```'
    assert _parse_assignments(raw, {1}) == {1: "Счета"}


def test_parse_assignments_garbage_raises() -> None:
    with pytest.raises(ValueError):
        _parse_assignments("совсем не JSON", {0})


# ---------- classifier ----------

def test_classifier_extract_json_with_fence() -> None:
    agent = ClassifierAgent()
    raw = 'Вот классификация:\n```json\n{"doc_type": "ks2", "confidence": 0.9}\n```'
    assert agent._extract_json(raw)["doc_type"] == "ks2"


# ---------- llm.extra_body + reasoning_content ----------

def test_openai_compatible_extra_body_and_reasoning_fallback(monkeypatch) -> None:
    from doc_agent.config import LLMSettings
    from doc_agent.llm.ollama_client import OpenAICompatible

    captured: dict = {}

    class _Resp:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"choices": [{"message": {
                "content": "",
                "reasoning_content": 'думаю… итог: {"assignments": []}',
            }}]}

    def fake_post(url, json=None, headers=None, timeout=None):  # noqa: A002
        captured["url"] = url
        captured["payload"] = json
        return _Resp()

    monkeypatch.setattr("doc_agent.llm.ollama_client.httpx.post", fake_post)
    s = LLMSettings(
        provider="openai_compatible", base_url="http://llm.test/v1", api_key="k",
        extra_body={"thinking": {"type": "disabled"}},
    )
    out = OpenAICompatible(s).chat("тест")
    assert captured["payload"]["thinking"] == {"type": "disabled"}
    assert '{"assignments": []}' in out  # fallback на reasoning_content


# ---------- сервисные интенты через API ----------

def _wait_done(client, token: str, file_id: int, timeout: float = 25.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = client.get(f"/files/{file_id}", headers={"Authorization": f"Bearer {token}"})
        data = r.json()
        if data["file"]["status"] in {"done", "failed", "description_only"}:
            return data
        time.sleep(0.2)
    raise TimeoutError(f"файл {file_id} не обработан")


def _q(client, token: str, q: str) -> dict:
    r = client.post("/query", json={"q": q}, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    return r.json()


def test_intents_list_files_and_help(client, admin_token, tmp_data_dir) -> None:
    # пока файлов нет
    res = _q(client, admin_token, "покажи все файлы")
    assert res["intent"] == "list_files" and "пока нет" in res["answer"]

    # импортируем два файла
    dump = tmp_data_dir / "dump"
    dump.mkdir()
    (dump / "Вилоновская_смета.txt").write_text(
        "Смета на работы по объекту Вилоновская. Итого 100000 руб.", encoding="utf-8")
    (dump / "Договор_555_Самара.txt").write_text(
        "Договор № 555 подряда. Город Самара. Сумма 50000 руб.", encoding="utf-8")
    r = client.post("/files/scan-folder", json={"path": str(dump)},
                    headers={"Authorization": f"Bearer {admin_token}"})
    assert r.status_code == 200 and r.json()["queued"] == 2
    _wait_done(client, admin_token, 1)
    _wait_done(client, admin_token, 2)

    # «покажи все файлы» — оба файла, без LLM
    res = _q(client, admin_token, "покажи все файлы")
    assert res["intent"] == "list_files" and res["grounded"] is True
    assert "Вилоновская_смета.txt" in res["answer"]
    assert "Договор_555_Самара.txt" in res["answer"]
    assert "[file_id:1]" in res["answer"]
    assert {f["file_id"] for f in res["files"]} == {1, 2}

    # «какие файлы есть по вилоновской» — только совпадение по названию
    res = _q(client, admin_token, "какие файлы есть по вилоновской")
    assert "Вилоновская_смета.txt" in res["answer"]
    assert "Договор_555" not in res["answer"]
    assert [f["file_id"] for f in res["files"]] == [1]

    # числа короче name_min_word_len тоже ищутся по названиям
    res = _q(client, admin_token, "какие файлы есть по 555?")
    assert [f["file_id"] for f in res["files"]] == [2]

    # ничего не нашлось по названию — честный ответ с общим количеством
    res = _q(client, admin_token, "какие файлы есть по марсианской")
    assert "не нашлось" in res["answer"] and "2" in res["answer"]

    # «что ты можешь?» — подсказка из config/prompts/help.txt
    res = _q(client, admin_token, "что ты можешь?")
    assert res["intent"] == "help" and "Документовед" in res["answer"]
    assert res["files"] == []

    # intent сохраняется в истории чата (переживает обновление страницы)
    r = client.get("/chat/history", headers={"Authorization": f"Bearer {admin_token}"})
    metas = [m.get("meta", {}) for m in r.json()["items"] if m["role"] == "agent"]
    assert any(m.get("intent") == "list_files" for m in metas)
    assert any(m.get("intent") == "help" for m in metas)

    # обычный вопрос по-прежнему идёт через RAG (файлов с договором 999 нет)
    res = _q(client, admin_token, "Какая сумма по договору 999?")
    assert "НЕТ ДАННЫХ" in res["answer"]
