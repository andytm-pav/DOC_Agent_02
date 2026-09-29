"""Тесты v2.5: подсчёт файлов («сколько…»), поиск по названиям и типам
(«покажи все КС2»), морфология без ложных префиксов (баг «кс2»->«к»),
глубокое чтение файла по запросу, картотека в промпте репортера,
подсказка вместо голого «НЕТ ДАННЫХ», лимиты «0 = без лимита»."""
from __future__ import annotations

import time
from pathlib import Path

from doc_agent.config import Settings, SortingSettings, load_settings
from doc_agent.services.intents import _variants

# ---------- морфология: без ложных префиксов (баг v2.4.1) ----------

def test_variants_short_and_digit_tokens_exact_only() -> None:
    s = load_settings().qa
    assert _variants("кс2", s) == ["кс2"]      # раньше: ["кс2", "кс", "к"]
    assert _variants("23", s) == ["23"]        # раньше: ["23", "2"]
    assert _variants("555", s) == ["555"]


def test_variants_long_tokens_have_prefixes() -> None:
    s = load_settings().qa
    assert "вилоновск" in _variants("вилоновской", s)
    assert "договор" in _variants("договоров", s)
    assert _variants("смете", s) == ["смете", "смет"]


# ---------- лимиты: 0 = без лимита ----------

def test_scan_dump_unlimited(tmp_path: Path) -> None:
    from doc_agent.services.sorting import _scan_dump

    for i in range(7):
        (tmp_path / f"doc_{i}.txt").write_text(f"текст {i}", encoding="utf-8")
    files, counts = _scan_dump(tmp_path, False, Settings(sorting=SortingSettings(max_files=0)))
    assert len(files) == 7
    assert counts["truncated"] is False

    files2, counts2 = _scan_dump(tmp_path, False, Settings(sorting=SortingSettings(max_files=3)))
    assert len(files2) == 3
    assert counts2["truncated"] is True


# ---------- API-тесты ----------

def _wait_done(client, token: str, file_id: int, timeout: float = 25.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = client.get(f"/files/{file_id}", headers={"Authorization": f"Bearer {token}"})
        data = r.json()
        if data["file"]["status"] in {"done", "failed", "description_only"}:
            return
        time.sleep(0.2)
    raise TimeoutError(f"файл {file_id} не обработан")


def _import_dump(client, token: str, dump: Path) -> None:
    r = client.post("/files/scan-folder", json={"path": str(dump)},
                    headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    for fid in r.json()["file_ids"]:
        _wait_done(client, token, fid)


def _q(client, token: str, q: str) -> dict:
    r = client.post("/query", json={"q": q}, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    return r.json()


def _name_to_id(client, token: str) -> dict[str, int]:
    res = _q(client, token, "покажи все файлы")
    return {f["file_name"]: f["file_id"] for f in res["files"]}


def _make_dump(tmp_data_dir: Path) -> Path:
    dump = tmp_data_dir / "dump25"
    dump.mkdir(exist_ok=True)
    (dump / "Вилоновская_смета.txt").write_text(
        "Смета по объекту Вилоновская. Работы и материалы. Итого 100000 руб.",
        encoding="utf-8")
    (dump / "КС2_акт_Вилоновская_23.txt").write_text(
        "Акт КС-2 № 5. Объект Вилоновская 23. Итого 50000 руб.", encoding="utf-8")
    (dump / "КС2_акт_Старый_город.txt").write_text(
        "Акт КС-2 № 6. Объект Старый город. Итого 60000 руб.", encoding="utf-8")
    (dump / "Договор_подряда_27-07-2026_Старый_город.txt").write_text(
        "Договор подряда № 27-07-2026. Объект Старый город. Сумма 900000 руб.",
        encoding="utf-8")
    return dump


def test_count_total_and_filtered(client, admin_token, tmp_data_dir) -> None:
    _import_dump(client, admin_token, _make_dump(tmp_data_dir))
    ids = _name_to_id(client, admin_token)
    assert len(ids) == 4

    # «сколько штук файлов ты обработал?» — всего, без LLM
    res = _q(client, admin_token, "сколько штук файлов ты обработал?")
    assert res["intent"] == "count_files"
    assert res["grounded"] is True
    assert "Сейчас загружено файлов: 4" in res["answer"]

    # «сколько КС2 по вилоновской 23?» — по названию, ровно 1 файл
    res = _q(client, admin_token, "сколько КС2 по вилоновской 23?")
    assert res["intent"] == "count_files"
    assert "нашлось: 1" in res["answer"]
    assert [f["file_id"] for f in res["files"]] == [ids["КС2_акт_Вилоновская_23.txt"]]

    # «сколько файлов по вилоновской?» — название+тип, 2 файла (смета + акт)
    res = _q(client, admin_token, "сколько файлов по вилоновской?")
    assert res["intent"] == "count_files"
    assert "нашлось: 2" in res["answer"]


def test_find_show_all_ks2_not_contracts(client, admin_token, tmp_data_dir) -> None:
    _import_dump(client, admin_token, _make_dump(tmp_data_dir))
    ids = _name_to_id(client, admin_token)

    # регресс v2.4.1: «покажи все КС2» находило договоры (префикс «к»)
    res = _q(client, admin_token, "покажи все КС2")
    assert res["intent"] == "find_files"
    assert "нашлось: 2" in res["answer"]
    got = {f["file_id"] for f in res["files"]}
    assert got == {ids["КС2_акт_Вилоновская_23.txt"], ids["КС2_акт_Старый_город.txt"]}
    assert "Договор_подряда" not in res["answer"]

    # «покажи все суммы по смете» — НЕ файловый вопрос -> обычный поиск
    res = _q(client, admin_token, "покажи все суммы по смете")
    assert res.get("intent") is None


def test_count_by_content_fallback(client, admin_token, tmp_data_dir) -> None:
    dump = _make_dump(tmp_data_dir)
    (dump / "Записка_бригадира.txt").write_text(
        "Записка: на объекте Марсианская 5 заменены окна, итог 30000 руб.",
        encoding="utf-8")
    _import_dump(client, admin_token, dump)

    # в НАЗВАНИИ «марсианской» нет — считаем по содержимому чанков
    res = _q(client, admin_token, "сколько файлов по марсианской?")
    assert res["intent"] == "count_files"
    assert "нашлось: 1" in res["answer"]
    assert "Записка_бригадира.txt" in res["answer"]


def test_content_question_stays_no_data_but_hinted(client, admin_token, tmp_data_dir,
                                                   monkeypatch) -> None:
    _import_dump(client, admin_token, _make_dump(tmp_data_dir))
    # ретривер пуст (как при полном промахе поиска): репортер -> «НЕТ ДАННЫХ»,
    # deep read офлайн недоступен (provider none) -> срабатывает подсказка
    import doc_agent.services.query as qmod

    class EmptyRetriever:
        def run(self, db, question, filters, limit=20):  # noqa: ANN001, ARG002
            return [], []

    monkeypatch.setattr(qmod, "_retriever", EmptyRetriever())

    # несуществующий договор: без подсказки (совпадений с названиями нет)
    res = _q(client, admin_token, "Какая сумма по договору 999?")
    assert res.get("intent") is None
    assert res["answer"] == "НЕТ ДАННЫХ"

    # вопрос указывает на конкретный файл — вместо голого «НЕТ ДАННЫХ»
    # приходит подсказка «прочитай файл …»
    res = _q(client, admin_token, "какой цвет стен в вилоновской 23?")
    assert res["answer"].startswith("НЕТ ДАННЫХ")
    assert "похожие файлы" in res["answer"]
    assert "Вилоновская" in res["answer"]
    assert "прочитай файл" in res["answer"]


def test_deep_read_explicit(client, admin_token, tmp_data_dir, monkeypatch) -> None:
    _import_dump(client, admin_token, _make_dump(tmp_data_dir))
    ids = _name_to_id(client, admin_token)

    import doc_agent.services.deep_read as dr

    base = load_settings()

    def fake_load():
        st = base.model_copy(deep=True)
        st.llm.provider = "openai_compatible"
        return st

    captured: dict = {}

    class FakeLLM:
        def chat(self, prompt: str, model: str | None = None) -> str:
            captured["prompt"] = prompt
            return "По документу: Итого 50000 руб. [file_id:%d]" % ids["КС2_акт_Вилоновская_23.txt"]

    monkeypatch.setattr(dr, "load_settings", fake_load)
    monkeypatch.setattr(dr, "get_llm", lambda: FakeLLM())

    res = _q(client, admin_token, "прочитай файл КС2 акт вилоновская и скажи итог")
    assert res["intent"] == "deep_read"
    assert res["grounded"] is True and res["confidence"] == 0.9
    assert [f["file_id"] for f in res["files"]] == [ids["КС2_акт_Вилоновская_23.txt"]]
    assert "Итого 50000 руб." in res["answer"]
    # в промпте — ПОЛНЫЙ текст файла, а не векторные обрывки
    assert "Акт КС-2 № 5. Объект Вилоновская 23. Итого 50000 руб." in captured["prompt"]


def test_deep_read_auto_after_no_data(client, admin_token, tmp_data_dir, monkeypatch) -> None:
    _import_dump(client, admin_token, _make_dump(tmp_data_dir))
    ids = _name_to_id(client, admin_token)

    import doc_agent.services.deep_read as dr
    import doc_agent.services.query as qmod

    base = load_settings()

    def fake_load():
        st = base.model_copy(deep=True)
        st.llm.provider = "openai_compatible"
        return st

    captured: dict = {}

    class FakeLLM:
        def chat(self, prompt: str, model: str | None = None) -> str:
            captured["prompt"] = prompt
            return "В смете один лист, итог 100000 руб. [file_id:%d]" % ids["Вилоновская_смета.txt"]

    class EmptyRetriever:
        def run(self, db, question, filters, limit=20):  # noqa: ANN001, ARG002
            return [], []

    monkeypatch.setattr(dr, "load_settings", fake_load)
    monkeypatch.setattr(dr, "get_llm", lambda: FakeLLM())
    monkeypatch.setattr(qmod, "_retriever", EmptyRetriever())

    # нет явной просьбы («прочитай…»), обычный поиск пуст -> автодочтение
    res = _q(client, admin_token, "сколько листов в смете вилоновской?")
    assert res["intent"] == "deep_read"
    assert [f["file_id"] for f in res["files"]] == [ids["Вилоновская_смета.txt"]]
    assert "итог 100000 руб." in res["answer"]
    assert "Итого 100000 руб." in captured["prompt"]


def test_reporter_prompt_contains_catalog(monkeypatch) -> None:
    from doc_agent.subagents.reporter_agent import ReporterAgent

    captured: dict = {}

    class FakeLLM:
        def chat(self, prompt: str, model: str | None = None) -> str:
            captured["prompt"] = prompt
            return "ответ [file_id:1]"

    monkeypatch.setattr("doc_agent.subagents.reporter_agent.get_llm", lambda: FakeLLM())
    rep = ReporterAgent()
    out = rep.run(
        "что в файле?",
        [{"file_id": 1, "file_name": "a.txt", "text": "текст документа", "page": 1}],
        catalog="Картотека загруженных файлов:\n• a.txt [file_id:1] — КС-2",
    )
    assert "Картотека загруженных файлов" in captured["prompt"]
    assert "a.txt [file_id:1]" in captured["prompt"]
    assert "[file_id:1]" in out
