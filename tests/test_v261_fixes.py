"""Тесты v2.6.1: точность ответов по сметам.

1. Преамбула «[имя_файла] » в каждом чанке (chunking.filename_prefix) —
   строки смет xlsx становятся находимыми по объекту («Вилоновская»).
2. Поиск по содержимому находит смету по объекту (раньше — только чужие
   документы с «материалами» в тексте).
3. confidence = среднее TOP-K score (раньше минимум из 5 давал «0»).
4. Названный файл читается ЦЕЛИКОМ (read_file -> deep_read), материалы
   из конца файла попадают в промпт LLM.
5. «reprocess:»/«reindex_all» переобрабатывают файл из оригинала с
   текущими настройками чанкинга.
"""
from __future__ import annotations

import json
import time

from doc_agent.config import load_settings
from doc_agent.subagents.validator_agent import ValidatorAgent

_RAISE = object()  # сигнал «LLM планировщика упал»


def _enable_planner(monkeypatch, planner_reply: str | object,
                    synthesis_reply: str | None = None):
    """Включает LLM-ветку: provider=openai_compatible для planner/query,
    FakeLLM у планировщика (копия помощника из test_v26_planner)."""
    base = load_settings()

    def fake_load():
        st = base.model_copy(deep=True)
        st.llm.provider = "openai_compatible"
        return st

    import doc_agent.services.planner as pl
    import doc_agent.services.query as qmod

    monkeypatch.setattr(pl, "load_settings", fake_load)
    monkeypatch.setattr(qmod, "load_settings", fake_load)

    class PlannerLLM:
        def __init__(self) -> None:
            self.calls = 0
            self.prompts: list[str] = []

        def chat(self, prompt: str, model: str | None = None, timeout: float | None = None) -> str:
            self.calls += 1
            self.prompts.append(prompt)
            if planner_reply is _RAISE:
                raise RuntimeError("planner down")
            return str(planner_reply)

        def ping(self) -> bool:
            return True

    pll = PlannerLLM()
    monkeypatch.setattr(pl, "get_llm", lambda: pll)
    if synthesis_reply is not None:
        reply: str = synthesis_reply  # сужение типа до вложенного класса

        class SynthLLM:
            def chat(self, prompt: str, model: str | None = None,
                     timeout: float | None = None) -> str:
                return reply

        monkeypatch.setattr(qmod, "get_llm", lambda: SynthLLM())
    return pll


def _plan_json(**kw) -> str:
    base: dict = {"action": "search_content", "doc_type": None, "terms": [],
                  "file_ids": [], "search_query": "", "reply": ""}
    base.update(kw)
    return json.dumps(base, ensure_ascii=False)

# ---------- помощники ----------


def _wait_done(client, token: str, file_id: int, timeout: float = 25.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = client.get(f"/files/{file_id}", headers={"Authorization": f"Bearer {token}"})
        data = r.json()
        if data["file"]["status"] in {"done", "failed", "description_only"}:
            return
        time.sleep(0.2)
    raise TimeoutError(f"файл {file_id} не обработан")


def _upload_xlsx(client, token: str, name: str, rows: list[list[object]]) -> int:
    import io

    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Смета"
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    r = client.post(
        "/files/upload",
        files={"file": (name, buf, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    fid = r.json()["file_id"]
    _wait_done(client, token, fid)
    return fid


def _chunks_text(file_id: int) -> list[str]:
    from sqlalchemy import select

    from doc_agent.db.models import Chunk
    from doc_agent.db.session import get_session_factory

    factory = get_session_factory()
    with factory() as db:
        rows = db.execute(
            select(Chunk.text).where(Chunk.file_id == file_id).order_by(Chunk.chunk_index)
        ).scalars().all()
    return list(rows)


def _name_to_id(client, token: str) -> dict[str, int]:
    r = client.post("/query", json={"q": "покажи все файлы"},
                    headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    return {f["file_name"]: f["file_id"] for f in r.json()["files"]}


def _make_estimate_rows() -> list[list[object]]:
    """Реплика структуры реальной сметы: шапка-«Приложение №3», работы,
    «Итого по работе», затем в КОНЦЕ файла раздел «Материалы»."""
    rows: list[list[object]] = [
        ["Приложение №3", "", "", "", "", "", ""],
        ["к договору подряда №27-07/2026 от 27.07.2026г", "", "", "", "", "", ""],
        ["Подрядчик:", "Заказчик:", "", "", "", "", ""],
        ["ООО РЕГИОН", 'ТСЖ "СТАРЫЙ ГОРОД"', "", "", "", "", ""],
        ["г.Самара, ул.Вилоновская,д.2", "", "", "", "", "", ""],
        ["№ п/п", "Обоснование", "Вид работ", "Ед. изм.", "Объём", "Цена", "Сумма"],
        [1, "Договорная цена", "Насечка поверхности", "м2", 584, 12, 7008],
        [2, "Договорная цена", "Обеспыливание поверхности", "м2", 584, 5, 2920],
        [3, "Договорная цена", "Сплошное выравнивание (оштукатуривание) стен", "м2", 584, 350, 204400],
        [4, "Договорная цена", "Шпатлевка под высококачественную окраску", "м2", 584, 180, 105120],
        [5, "Договорная цена", "Отмостка: разобрать асфальтобетон", "м2", 40, 220, 8800],
        [6, "Договорная цена", "Отмостка: устройство новой из а/б", "м2", 40, 1800, 72000],
    ]
    # разделитель-«работы» до 37 строк, как в реальной смете
    for i in range(7, 36):
        rows.append([i, "Договорная цена", f"Работа {i}", "м2", 2, 100, 200])
    rows.append([37, "Договорная цена", "Итого по работе", "", "", "", 672103.3])
    rows.append([38, "Договорная цена", "Материалы", "", "", "", ""])
    rows.append([39, "Договорная цена", "Унифлекс ЭПП, 10м", "рул", 48, 450, 21600])
    rows.append([40, "Договорная цена", "Грунтовка акрилатная", "л", 116.8, 90, 10512])
    rows.append([41, "Договорная цена", "Смесь гипсовая штукатурная", "кг", 4964, 12, 59568])
    rows.append([42, "Договорная цена", "Профиль штукатурный", "м.п", 120, 60, 7200])
    rows.append([43, "Договорная цена", "Итого по материалам", "", "", "", 98880])
    return rows


# ---------- 1. преамбула имени файла в чанках ----------

def test_xlsx_chunks_carry_filename_prefix(client, admin_token) -> None:
    name = "Смета  по стена и отмостка Вилоновская 23 (2).xlsx"
    fid = _upload_xlsx(client, admin_token, name, _make_estimate_rows())
    texts = _chunks_text(fid)
    assert texts, "смета не дала чанков"
    # каждый чанк начинается с имени файла (v2.7: + имя листа в преамбуле)
    # — иначе поиск по объекту не свяжет строки сметы с файлом
    for t in texts:
        assert t.startswith(f"[{name}"), t[:80]


# ---------- 2. поиск по содержимому находит смету ----------

def test_content_search_finds_estimate_by_object(client, admin_token) -> None:
    _upload_xlsx(client, admin_token,
                 "Смета  по стена и отмостка Вилоновская 23 (2).xlsx", _make_estimate_rows())
    _upload_xlsx(client, admin_token,
                 "Сводная смета Вилоновская 23.xlsx",
                 [["№", "Наименование", "Сумма"], [1, "Итого по смете", 672103.3],
                  [2, "Материалы", 98880]])
    # файл-«отвлекатель»: материалы без Вилоновской
    import io

    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Лист1"
    ws.append(["Материалы склада №2"])
    ws.append(["Цемент М500", 120])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    r = client.post("/files/upload",
                    files={"file": ("Складские остатки.xlsx", buf, "application/octet-stream")},
                    headers={"Authorization": f"Bearer {admin_token}"})
    assert r.status_code == 200, r.text
    _wait_done(client, admin_token, r.json()["file_id"])

    res = client.post("/query", json={"q": "какие материалы в смете по вилоновской отмостка"},
                      headers={"Authorization": f"Bearer {admin_token}"}).json()
    file_ids = {f["file_id"] for f in res["files"]}
    names = _name_to_id(client, admin_token)
    est_id = names["Смета  по стена и отмостка Вилоновская 23 (2).xlsx"]
    assert est_id in file_ids, f"смета не найдена поиском: {file_ids}"
    assert res["confidence"] > 0.3, res["confidence"]


# ---------- 3. формула уверенности ----------

def test_confidence_is_topk_mean() -> None:
    conf = ValidatorAgent.confidence
    # раньше: min(...) = 0.0 — один слабый фрагмент обнулял уверенность
    assert conf([{"score": 0.8}, {"score": 0.5}, {"score": 0.3},
                 {"score": 0.1}, {"score": 0.0}]) == 0.53
    assert conf([{"score": 0.9}, {"score": 0.0}, {"score": 0.0}]) == 0.3
    assert conf([{"score": 0.7}]) == 0.7
    assert conf([]) == 0.0
    assert conf([{"score": 2.0}, {"score": 1.5}, {"score": 1.0}]) == 1.0  # кламп [0,1]


# ---------- 4. названный файл читается целиком ----------

def test_named_file_deep_read_includes_materials(client, admin_token, monkeypatch) -> None:
    name = "Смета  по стена и отмостка Вилоновская 23 (2).xlsx"
    fid = _upload_xlsx(client, admin_token, name, _make_estimate_rows())

    # план: планировщик выбрал read_file для названного файла
    _enable_planner(
        monkeypatch, _plan_json(action="read_file", file_ids=[fid], terms=["вилоновская"]))

    import doc_agent.services.deep_read as dr

    base = load_settings()

    def fake_load():
        st = base.model_copy(deep=True)
        st.llm.provider = "openai_compatible"
        return st

    captured: dict = {}

    class DeepLLM:
        def chat(self, prompt: str, model: str | None = None,
                 timeout: float | None = None) -> str:
            captured["prompt"] = prompt
            return ("По смете Вилоновская работы включают насечку и "
                    "оштукатуривание стен; материалы: Унифлекс ЭПП [file_id:%d]."
                    % fid)

    monkeypatch.setattr(dr, "load_settings", fake_load)
    monkeypatch.setattr(dr, "get_llm", lambda: DeepLLM())

    r = client.post("/query", json={"q": "файл сметы по вилоновской отмостка, нужно материалы"},
                    headers={"Authorization": f"Bearer {admin_token}"})
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["intent"] == "deep_read"
    assert [f["file_id"] for f in res["files"]] == [fid]
    assert res["confidence"] == 0.9
    # полный текст файла (включая КОНЕЦ с материалами) попал в промпт
    p = captured["prompt"]
    assert "Унифлекс ЭПП" in p, "раздел Материалы не дошёл до LLM"
    assert "Итого по материалам" in p
    assert f"[file_id:{fid}]" in p


def test_planner_failure_still_answers(client, admin_token, monkeypatch) -> None:
    """Сбой планировщика -> обычный RAG (не 500, не пусто)."""
    _upload_xlsx(client, admin_token,
                 "Смета  по стена и отмостка Вилоновская 23 (2).xlsx", _make_estimate_rows())
    _enable_planner(monkeypatch, _RAISE)
    res = client.post("/query", json={"q": "какие материалы в смете по вилоновской"},
                      headers={"Authorization": f"Bearer {admin_token}"}).json()
    assert res["answer"]
    file_ids = {f["file_id"] for f in res["files"]}
    names = _name_to_id(client, admin_token)
    assert names["Смета  по стена и отмостка Вилоновская 23 (2).xlsx"] in file_ids


# ---------- 5. полная переобработка применяет новые настройки ----------

def test_reprocess_job_rebuilds_chunks_with_prefix(client, admin_token) -> None:
    fid = _upload_xlsx(client, admin_token,
                       "Смета  по стена и отмостка Вилоновская 23 (2).xlsx",
                       _make_estimate_rows())
    # имитируем «старые» чанки без преамбулы (как до обновления)
    from sqlalchemy import select

    from doc_agent.db.models import Chunk
    from doc_agent.db.session import get_session_factory

    factory = get_session_factory()
    with factory() as db:
        for c in db.execute(select(Chunk).where(Chunk.file_id == fid)).scalars().all():
            if c.text.startswith("["):
                c.text = c.text[c.text.index("] ") + 2:]
        db.commit()
    assert not any(t.startswith("[") for t in _chunks_text(fid))

    from doc_agent.db.models import Job
    from doc_agent.services.jobs import _handle

    with factory() as db:
        job = Job(file_id=fid, kind=f"reprocess:{fid}", priority=2)
        db.add(job)
        db.commit()
        _handle(job)

    texts = _chunks_text(fid)
    assert texts
    for t in texts:
        # v2.7: преамбула расширена листом — «[имя | Лист: N] …»
        assert t.startswith("[Смета  по стена и отмостка Вилоновская 23 (2).xlsx"), t[:90]


def test_reprocess_disabled_prefix(client, admin_token, monkeypatch) -> None:
    """chunking.filename_prefix: false -> чанки без преамбулы (config-driven)."""
    fid = _upload_xlsx(client, admin_token,
                       "Смета  по стена и отмостка Вилоновская 23 (2).xlsx",
                       _make_estimate_rows())
    base = load_settings()

    def fake_load():
        st = base.model_copy(deep=True)
        st.chunking.filename_prefix = False
        return st

    import doc_agent.services.ingest as ing

    monkeypatch.setattr(ing, "load_settings", fake_load)

    from doc_agent.db.models import Job
    from doc_agent.db.session import get_session_factory
    from doc_agent.services.jobs import _handle

    factory = get_session_factory()
    with factory() as db:
        job = Job(file_id=fid, kind=f"reprocess:{fid}", priority=2)
        db.add(job)
        db.commit()
        _handle(job)

    texts = _chunks_text(fid)
    assert texts
    assert not any(t.startswith("[") for t in texts)
    assert any("Унифлекс" in t for t in texts)


# ---------- план планировщика: групповое чтение ----------

def test_planner_group_read_all_estimates(client, admin_token, monkeypatch) -> None:
    """«что в сметах по вилоновской» -> read_file нескольких файлов."""
    f1 = _upload_xlsx(client, admin_token,
                      "Смета  по стена и отмостка Вилоновская 23 (2).xlsx",
                      _make_estimate_rows())
    f2 = _upload_xlsx(client, admin_token, "Сводная смета Вилоновская 23.xlsx",
                      [[1, "Итого", 672103.3]])
    _enable_planner(
        monkeypatch,
        _plan_json(action="read_file", file_ids=[f1, f2], terms=["вилоновская", "смета"]))

    import doc_agent.services.deep_read as dr

    base = load_settings()

    def fake_load():
        st = base.model_copy(deep=True)
        st.llm.provider = "openai_compatible"
        return st

    prompts: list[str] = []

    class DeepLLM:
        def chat(self, prompt: str, model: str | None = None,
                 timeout: float | None = None) -> str:
            prompts.append(prompt)
            return "В сметах по Вилоновской: работы и материалы, итог 672103.3."

    monkeypatch.setattr(dr, "load_settings", fake_load)
    monkeypatch.setattr(dr, "get_llm", lambda: DeepLLM())

    res = client.post("/query", json={"q": "что в сметах по вилоновской?"},
                      headers={"Authorization": f"Bearer {admin_token}"}).json()
    assert res["intent"] == "deep_read"
    assert sorted(f["file_id"] for f in res["files"]) == sorted([f1, f2])
    # оба файла целиком в одном промпте
    assert prompts and f"[file_id:{f1}]" in prompts[0] and f"[file_id:{f2}]" in prompts[0]
