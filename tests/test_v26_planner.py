"""Тесты v2.6: LLM-планировщик чата (понимание естественного языка без
жёстких привязок к фразам), синтез списков/подсчётов через LLM, прямой
ответ на приветствия, параметры плана в RAG и глубоком чтении,
офлайн-fallback при сбое планировщика, эмбеддинги по API (backend: api)."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from doc_agent.config import load_settings

_RAISE = object()  # сигнал «LLM планировщика упал»


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


def _make_dump(tmp_data_dir: Path) -> Path:
    dump = tmp_data_dir / "dump26"
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


def _plan_json(**kw) -> str:
    base: dict = {"action": "search_content", "doc_type": None, "terms": [],
                  "file_ids": [], "search_query": "", "reply": ""}
    base.update(kw)
    return json.dumps(base, ensure_ascii=False)


def _enable_planner(monkeypatch, planner_reply: str | object,
                    synthesis_reply: str | None = None):
    """Включает LLM-ветку: provider=openai_compatible для planner/query,
    FakeLLM у планировщика и (опционально) у синтеза."""
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


# ---------- планировщик: естественные формулировки ----------

def test_planner_count_natural_phrasing(client, admin_token, tmp_data_dir,
                                        monkeypatch) -> None:
    _import_dump(client, admin_token, _make_dump(tmp_data_dir))
    ids = _name_to_id(client, admin_token)
    # формулировка НЕ покрыта ключевыми словами qa.* («сколько»/«покажи все»)
    pll = _enable_planner(
        monkeypatch, _plan_json(action="count_files", terms=["вилоновская"]),
        synthesis_reply="По Вилоновской сейчас 2 файла в картотеке.")

    res = _q(client, admin_token, "посчитай мне всё по вилоновской, пжт")
    assert pll.calls == 1
    assert res["intent"] == "count_files"
    assert "2 файла" in res["answer"]          # синтез LLM, а не детерминированный текст
    assert {f["file_id"] for f in res["files"]} == {
        ids["Вилоновская_смета.txt"], ids["КС2_акт_Вилоновская_23.txt"]}
    # планировщик видел картотеку
    assert "Картотека" in pll.prompts[0]


def test_planner_find_by_type_natural(client, admin_token, tmp_data_dir,
                                      monkeypatch) -> None:
    _import_dump(client, admin_token, _make_dump(tmp_data_dir))
    ids = _name_to_id(client, admin_token)
    _enable_planner(
        monkeypatch,
        _plan_json(action="find_files", doc_type="ks2", terms=["старый", "город"]),
        synthesis_reply="По картотеке нашёлся 1 подходящий файл.")

    res = _q(client, admin_token, "есть ли у нас что-нибудь от старого города, типа акта?")
    assert res["intent"] == "find_files"
    assert [f["file_id"] for f in res["files"]] == [ids["КС2_акт_Старый_город.txt"]]
    assert "нашёлся 1" in res["answer"]


def test_planner_read_file_by_ids(client, admin_token, tmp_data_dir,
                                  monkeypatch) -> None:
    _import_dump(client, admin_token, _make_dump(tmp_data_dir))
    ids = _name_to_id(client, admin_token)
    _enable_planner(
        monkeypatch, _plan_json(action="read_file", file_ids=[ids["Вилоновская_смета.txt"]]))

    import doc_agent.services.deep_read as dr

    base = load_settings()

    def fake_load():
        st = base.model_copy(deep=True)
        st.llm.provider = "openai_compatible"
        return st

    captured: dict = {}

    class FakeLLM:
        def chat(self, prompt: str, model: str | None = None,
                 timeout: float | None = None) -> str:
            captured["prompt"] = prompt
            return "В смете один итог: 100000 руб. [file_id:%d]" % ids["Вилоновская_смета.txt"]

    monkeypatch.setattr(dr, "load_settings", fake_load)
    monkeypatch.setattr(dr, "get_llm", lambda: FakeLLM())

    # ни одной «команды» из deep_read_cues — планировщик сам понял просьбу
    res = _q(client, admin_token, "открой пожалуйста смету по вилоновской и расскажи, что там")
    assert res["intent"] == "deep_read"
    assert [f["file_id"] for f in res["files"]] == [ids["Вилоновская_смета.txt"]]
    assert "итог: 100000 руб." in res["answer"]
    # в промпте — ПОЛНЫЙ текст файла
    assert "Итого 100000 руб." in captured["prompt"]


def test_planner_direct_greeting_no_rag(client, admin_token, tmp_data_dir,
                                        monkeypatch) -> None:
    _import_dump(client, admin_token, _make_dump(tmp_data_dir))

    import doc_agent.services.query as qmod

    class NoRetriever:
        def run(self, *a, **kw):  # noqa: ANN002, ANN003
            raise AssertionError("RAG не должен вызываться на приветствии")

    monkeypatch.setattr(qmod, "_retriever", NoRetriever())
    _enable_planner(
        monkeypatch,
        _plan_json(action="direct", reply="Здравствуйте! Загрузите документы — и спрашивайте."))

    res = _q(client, admin_token, "привет, как дела?")
    assert res["intent"] == "direct"
    assert res["answer"] == "Здравствуйте! Загрузите документы — и спрашивайте."
    assert res["grounded"] is False


def test_planner_search_content_uses_query_and_filters(client, admin_token,
                                                       tmp_data_dir,
                                                       monkeypatch) -> None:
    _import_dump(client, admin_token, _make_dump(tmp_data_dir))
    ids = _name_to_id(client, admin_token)
    _enable_planner(
        monkeypatch,
        _plan_json(action="search_content", doc_type="ks2", terms=["вилоновская"],
                   search_query="Вилоновская 23 КС-2 итоговая сумма"))

    import doc_agent.services.query as qmod
    import doc_agent.subagents.reporter_agent as ra

    captured: dict = {}

    class FakeRetriever:
        def run(self, db, question, filters, limit=20, stats=None):  # noqa: ANN001, ARG002
            captured["question"] = question
            captured["filters"] = filters
            return [{
                "chunk_id": 1, "file_id": ids["КС2_акт_Вилоновская_23.txt"],
                "file_name": "КС2_акт_Вилоновская_23.txt", "doc_type": "ks2",
                "page": 1, "score": 0.9,
                "text": "Акт КС-2 № 5. Объект Вилоновская 23. Итого 50000 руб.",
            }], []  # (фрагменты, кандидаты) — как RetrieverAgent.run

    base = load_settings()

    def fake_load():
        st = base.model_copy(deep=True)
        st.llm.provider = "openai_compatible"
        return st

    class FakeLLM:
        def chat(self, prompt: str, model: str | None = None,
                 timeout: float | None = None) -> str:
            # дословные данные из фрагмента — проходят groundrails-поддержку
            return "Итого 50000 руб. [file_id:%d]" % ids["КС2_акт_Вилоновская_23.txt"]

    monkeypatch.setattr(qmod, "_retriever", FakeRetriever())
    monkeypatch.setattr(ra, "load_settings", fake_load)
    monkeypatch.setattr(ra, "get_llm", lambda: FakeLLM())

    res = _q(client, admin_token, "какая итоговая сумма в акте по вилоновской?")
    # RAG получил ПЕРЕФОРМУЛИРОВАННЫЙ запрос и фильтр типа из плана
    assert captured["question"] == "Вилоновская 23 КС-2 итоговая сумма"
    assert captured["filters"].get("doc_type") == "ks2"
    assert "Итого 50000 руб." in res["answer"]
    assert "[file_id:%d]" % ids["КС2_акт_Вилоновская_23.txt"] in res["answer"]
    assert [f["file_id"] for f in res["files"]] == [ids["КС2_акт_Вилоновская_23.txt"]]


def test_planner_help_action(client, admin_token, tmp_data_dir, monkeypatch) -> None:
    _enable_planner(monkeypatch, _plan_json(action="help"))
    res = _q(client, admin_token, "расскажи, что ты вообще умеешь делать")
    assert res["intent"] == "help"
    assert "Документовед" in res["answer"]


# ---------- санитизация плана и отказобезопасность ----------

def test_planner_drops_stopword_terms_and_service_ids(client, admin_token,
                                                      tmp_data_dir,
                                                      monkeypatch) -> None:
    _import_dump(client, admin_token, _make_dump(tmp_data_dir))
    _enable_planner(
        monkeypatch,
        _plan_json(action="find_files", terms=["покажи", "все"],
                   file_ids=[999]))  # несуществующий id + служебные слова

    res = _q(client, admin_token, "найди договор 555")
    # термы планировщика вырезаны (стоп-слова) -> механизм вернул None ->
    # сработал офлайн-fallback по ключевым словам («найди»)
    assert res["intent"] == "find_files"
    assert "не нашлось" in res["answer"]


def test_planner_failure_falls_back_to_keywords(client, admin_token,
                                                tmp_data_dir, monkeypatch) -> None:
    _import_dump(client, admin_token, _make_dump(tmp_data_dir))
    pll = _enable_planner(monkeypatch, _RAISE)
    res = _q(client, admin_token, "сколько штук файлов ты обработал?")
    assert pll.calls == 2  # retries: 1 -> две попытки
    assert res["intent"] == "count_files"
    assert "Сейчас загружено файлов: 4" in res["answer"]


def test_planner_garbage_json_falls_back(client, admin_token, tmp_data_dir,
                                         monkeypatch) -> None:
    _import_dump(client, admin_token, _make_dump(tmp_data_dir))
    _enable_planner(monkeypatch, "Извините, я не понял ваш вопрос, но вот список...")
    res = _q(client, admin_token, "покажи все файлы")
    assert res["intent"] == "list_files"
    assert "Сейчас загружено файлов: 4" in res["answer"]


def test_provider_none_skips_planner(client, admin_token, tmp_data_dir,
                                     monkeypatch) -> None:
    _import_dump(client, admin_token, _make_dump(tmp_data_dir))
    # конфиг по умолчанию (provider none): планировщик не вызывается в принципе
    import doc_agent.services.planner as pl

    def no_llm():
        raise AssertionError("планировщик не должен вызываться при provider: none")

    monkeypatch.setattr(pl, "get_llm", no_llm)
    res = _q(client, admin_token, "покажи все файлы")
    assert res["intent"] == "list_files"
    assert "Сейчас загружено файлов: 4" in res["answer"]


# ---------- эмбеддинги по API ----------

def test_api_embeddings_backend(monkeypatch) -> None:
    import doc_agent.vector.embedder as emb

    base = load_settings()

    def fake_load():
        st = base.model_copy(deep=True)
        st.embeddings.backend = "api"
        st.embeddings.batch_size = 2
        st.embeddings.api.model = "emb-test"
        st.llm.base_url = "http://emb.test/v1"
        st.llm.api_key = "secret-key"
        return st

    monkeypatch.setattr(emb, "load_settings", fake_load)
    captured: dict = {}

    class FakeResp:
        def __init__(self, n: int) -> None:
            self.n = n
            self.status_code = 200
            self.text = ""
            self.headers: dict[str, str] = {}

        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            # индексами перемешаны специально: порядок восстанавливается
            pairs: list[list[Any]] = [[0, [0.1, 0.2]], [1, [0.3, 0.4]]][: self.n]
            data = [{"index": i, "embedding": v} for i, v in
                    sorted(pairs, key=lambda p: -p[0])]
            return {"data": data}

    class FakeClient:
        def __init__(self, **kw) -> None:  # noqa: ANN003
            captured["client_kw"] = kw

        def post(self, url, json=None, headers=None):  # noqa: A002
            captured.setdefault("calls", []).append(
                {"url": url, "payload": json, "headers": headers})
            return FakeResp(len(json["input"]))

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(emb.httpx, "Client", FakeClient)

    out = emb.embed_passages(["текст один", "текст два", "текст три"])
    assert len(out) == 3
    assert out[0] == [0.1, 0.2] and out[1] == [0.3, 0.4] and out[2] == [0.1, 0.2]
    call = captured["calls"][0]
    assert call["url"] == "http://emb.test/v1/embeddings"
    assert call["payload"]["model"] == "emb-test"
    assert call["headers"]["Authorization"] == "Bearer secret-key"
    # батчинг по embeddings.batch_size=2: три текста -> два POST-а
    assert len(captured["calls"]) == 2

    single = emb.embed_query("вопрос")
    assert single == [0.1, 0.2]
