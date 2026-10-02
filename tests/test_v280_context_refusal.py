"""v2.8.0: контекстуальные преамбулы чанков, отказ как фича, честные
ошибки API, rate-limit backoff."""
from __future__ import annotations

from typing import Any

from doc_agent.config import load_settings
from doc_agent.services import ingest as ingest_mod
from doc_agent.services import query as query_mod
from doc_agent.vector import embedder

# ---------- 1. путь заголовков в преамбуле чанков ----------

def test_heading_path_index_orders_and_paths() -> None:
    text = "Смета\nвведение\nМатериалы\nУнифлекс ЭПП 100 м2\nРаботы\nпокраска"
    tree = {"children": [
        {"type": "heading", "level": 1, "text": "Смета", "children": [
            {"type": "heading", "level": 2, "text": "Материалы"},
            {"type": "paragraph", "text": "Унифлекс ЭПП 100 м2"},
        ]},
        {"type": "heading", "level": 1, "text": "Работы"},
        {"type": "paragraph", "text": "покраска"},
    ]}
    idx = ingest_mod.heading_path_index(tree, text)
    assert idx, "индекс пуст"
    # путь в зоне «Унифлекс...» — Смета > Материалы
    pos_uniflex = text.find("Унифлекс")
    path = ingest_mod._path_at(idx, pos_uniflex)
    assert path == "Смета > Материалы"
    # путь в зоне «покраска» — Работы
    path2 = ingest_mod._path_at(idx, text.find("покраска"))
    assert path2 == "Работы"
    # до первого заголовка путь пуст
    assert ingest_mod._path_at(idx, -1) == ""


def test_build_chunk_prefix_formats() -> None:
    assert ingest_mod.build_chunk_prefix("Смета.xlsx", "Лист1", "Материалы",
                                         "ведомость") == \
        "[Смета.xlsx | Лист: Лист1 | Раздел: Материалы | ведомость] "
    # имя файла первым — совместимость с v2.6.1 (startswith «[<имя>»)
    p = ingest_mod.build_chunk_prefix("Смета.xlsx", None, "", "")
    assert p == "[Смета.xlsx] "
    # выключено — пусто
    assert ingest_mod.build_chunk_prefix("x.xlsx", None, "", "", enabled=False) == ""


def test_doc_note_fallback_offline(client, monkeypatch) -> None:
    """llm.provider: none -> детерминированный fallback из метаданных."""
    from doc_agent.db.session import get_session_factory

    st = load_settings()
    st.llm.provider = "none"
    st.chunking.context_note = True
    with get_session_factory()() as db:
        f = db.get(__import__("doc_agent.db.models", fromlist=["File"]).File, 1)
        if f is None:  # в тестовой БД файл 1 может отсутствовать — создадим прокси
            class _P:
                id = 1
                original_name = "Смета Вилоновская.xlsx"
                doc_type = "estimate"
                customer = "ООО Ромашка"
                city = "Самара"
                contract_no = "12"
            note = ingest_mod.doc_note(_P(), "текст")
        else:
            note = ingest_mod.doc_note(f, "текст")
    assert note
    assert len(note) <= max(st.chunking.note_max_chars, 40)


# ---------- 2. отказ как фича ----------

def test_weak_retrieval_gate(monkeypatch) -> None:
    st = load_settings()
    monkeypatch.setattr(query_mod, "load_settings", lambda: st)
    st.qa.refuse_enabled = True
    # оба сигнала слабы -> отказ
    assert query_mod._weak_retrieval([], {"best_vector_cosine": 0.05,
                                          "best_lexical": 0.0}) is True
    # сильный векторный сигнал -> отвечаем
    assert query_mod._weak_retrieval(
        [{"score": 0.0}], {"best_vector_cosine": 0.72, "best_lexical": 0.0}) is False
    # сильный лексический сигнал -> отвечаем
    assert query_mod._weak_retrieval(
        [{"score": 0.5}], {"best_vector_cosine": 0.0, "best_lexical": 0.0}) is False
    # выключен — не отказываем
    st.qa.refuse_enabled = False
    assert query_mod._weak_retrieval([], {}) is False
    st.qa.refuse_enabled = True


def test_query_refuses_on_weak_signals(client, user_token: str, monkeypatch) -> None:
    """Слабые сигналы ретрива -> детерминированный отказ, LLM не вызывается."""

    class _FakeRetriever:
        def run(self, db, query, filters, limit=20, stats=None):
            if stats is not None:
                stats.update({"best_vector_cosine": 0.05, "best_lexical": 0.0})
            return ([{"chunk_id": 1, "file_id": 9, "file_name": "мусор.docx",
                      "doc_type": "other", "page": 1, "text": "чужой текст",
                      "score": 0.0}], [])

    monkeypatch.setattr(query_mod, "_retriever", _FakeRetriever())
    r = client.post("/query", json={"q": "абсолютно посторонний вопрос 12345",
                                    "limit": 5},
                    headers={"Authorization": f"Bearer {user_token}"})
    assert r.status_code == 200, r.text
    res = r.json()
    assert "не найдено" in res["answer"]
    assert res["confidence"] == 0.0
    assert res["files"] == []


# ---------- 3. честные ошибки API (тело ответа) ----------

def test_api_embed_error_contains_body(monkeypatch) -> None:
    class _R:
        status_code = 400
        text = '{"error":{"code":"1211","message":"model not found"}}'
        headers: dict[str, str] = {}

        def raise_for_status(self) -> None:
            raise RuntimeError("400")

    class _Client:
        def __init__(self, **kw: Any) -> None: ...

        def __enter__(self) -> "_Client":
            return self

        def __exit__(self, *a: Any) -> None: ...

        def post(self, *a: Any, **kw: Any) -> _R:
            return _R()

    monkeypatch.setattr(embedder.httpx, "Client", _Client)

    def fake_load() -> Any:
        s = load_settings()
        s.embeddings.backend = "api"
        s.embeddings.api.model = "embedding-3"
        s.embeddings.api.dimensions = 0
        s.embeddings.api.base_url = "https://api.z.ai/api/paas/v4"
        s.embeddings.api.api_key = "k"
        s.embeddings.api.rate_limit_retries = 0
        s.llm.provider = "openai_compatible"
        s.llm.base_url = "https://api.z.ai/api/paas/v4"
        s.llm.api_key = "k"
        return s

    monkeypatch.setattr(embedder, "load_settings", fake_load)
    try:
        embedder.embed_passages(["текст"])
        raise AssertionError("ожидали исключение")
    except RuntimeError as exc:
        assert "model not found" in str(exc), "тело ошибки потеряно"
        assert "400" in str(exc)


# ---------- 4. rate-limit backoff (429) ----------

def test_chat_retries_on_429_then_succeeds(monkeypatch) -> None:
    from doc_agent.llm import ollama_client as oc

    calls = {"n": 0}
    sleeps: list[float] = []

    class _Resp:
        def __init__(self, status: int) -> None:
            self.status_code = status
            # httpx.Headers регистронезависимы; плоский dict — нет,
            # поэтому ключ в нижнем регистре (как читает .get в коде)
            self.headers = {"retry-after": "0"} if status == 429 else {}
            self.text = "rate limited"

        def raise_for_status(self) -> None:
            if self.status_code >= 400:
                raise oc.httpx.HTTPStatusError("err", request=None, response=None)

        def json(self) -> dict:
            return {"choices": [{"message": {"content": "ок"}}]}

    def fake_post(*a: Any, **kw: Any) -> _Resp:
        calls["n"] += 1
        return _Resp(429 if calls["n"] == 1 else 200)

    monkeypatch.setattr(oc.httpx, "post", fake_post)
    monkeypatch.setattr(oc.time, "sleep", lambda s: sleeps.append(s))
    s = load_settings().llm
    s.provider = "openai_compatible"
    s.api_key = "k"
    s.rate_limit_retries = 2
    s.rate_limit_backoff_sec = 2.0
    out = oc.OpenAICompatible(s).chat("привет")
    assert out == "ок"
    assert calls["n"] == 2
    assert sleeps == []  # Retry-After: 0 -> ждать нечего, sleep не зовётся


def test_chat_4xx_no_retry(monkeypatch) -> None:
    from doc_agent.llm import ollama_client as oc

    calls = {"n": 0}

    class _Resp:
        status_code = 400
        headers: dict[str, str] = {}
        text = '{"error":{"message":"model not found"}}'

        def raise_for_status(self) -> None:
            raise oc.httpx.HTTPStatusError("err", request=None, response=None)

    def fake_post(*a: Any, **kw: Any) -> _Resp:
        calls["n"] += 1
        return _Resp()

    monkeypatch.setattr(oc.httpx, "post", fake_post)
    s = load_settings().llm
    s.provider = "openai_compatible"
    s.api_key = "k"
    s.rate_limit_retries = 2
    try:
        oc.OpenAICompatible(s).chat("привет")
        raise AssertionError("ожидали исключение")
    except RuntimeError as exc:
        assert "model not found" in str(exc)
    assert calls["n"] == 1, "400 не должен ретраиться"
