"""v3.0.3: реконсилиация watcher'а, анти-галлюцинация на всех путях,
привязка «число -> цитируемый файл», кэш BM25, честные лимиты фидбэка.

1. Watcher: путь watcher-файла запоминается; удаление -> forget_path/remove;
   изменение содержимого -> пере-приём; перемещение -> пере-привязка пути;
   догоняющая сверка карточек внутри watched-папок.
2. deep_read и synthesis проходят проверку на галлюцинации (раньше были
   единственными LLM-путями без неё).
3. Числа утверждения с цитатой [file_id:N] берутся из цитируемого файла.
4. Цитата после конца предложения не отрывается от утверждения.
5. BM25-индекс переиспользуется между запросами (кэш по корпусу).
6. Проверенные ответы из фидбэка не режутся жёсткими [:3000].
"""
from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from doc_agent.config import WatchdogSettings, load_settings
from doc_agent.db.migrations import init_db
from doc_agent.db.models import Chunk, File
from doc_agent.db.session import get_session_factory
from doc_agent.services import feedback as feedback_service
from doc_agent.services import fileops
from doc_agent.services import watcher as watcher_mod
from doc_agent.services.deep_read import try_deep_read
from doc_agent.services.groundrails import _split_claims, validate_answer
from doc_agent.services.query import _maybe_synthesize


@pytest.fixture()
def _db(tmp_data_dir: Path) -> Path:
    """Схема БД без поднятия FastAPI-приложения (прямые вызовы сервисов)."""
    init_db()
    return tmp_data_dir


# ---------- конфиг по умолчанию ----------

def test_watchdog_settings_defaults() -> None:
    s = WatchdogSettings()
    assert s.track_changes is True
    assert s.on_delete == "forget_path"
    assert s.on_modify == "reingest"


# ---------- watcher ----------

def _watcher_settings(monkeypatch, watched: Path, on_delete: str = "forget_path",
                      on_modify: str = "reingest"):
    def fake():
        s = load_settings().model_copy(deep=True)
        s.watchdog.enabled = True
        s.watchdog.paths = [str(watched)]
        s.watchdog.on_delete = on_delete
        s.watchdog.on_modify = on_modify
        return s

    monkeypatch.setattr(watcher_mod, "load_settings", fake)
    return fake()


def _single_file_id() -> int:
    with get_session_factory()() as db:
        files = db.execute(select(File)).scalars().all()
        assert len(files) == 1
        return int(files[0].id)


def test_watcher_ingest_remembers_path(_db: Path, monkeypatch) -> None:
    """v3.0.3: watcher-файл получает запись в file_locations (раньше
    watcher-приёмы были «без адреса» — file_link не работал). Повторный
    приём дубликата путь не задваивает."""
    watched = _db / "inbox"
    watched.mkdir(exist_ok=True)
    f = watched / "договор.txt"
    f.write_text("текст договора подряд 123", encoding="utf-8")
    _watcher_settings(monkeypatch, watched)

    watcher_mod._ingest_new(f)
    fid = _single_file_id()
    locs = fileops.locations_for(fid)
    assert any(loc["is_current"] and Path(loc["path"]) == f.resolve() for loc in locs)

    # перезапуск агента: файл «новый» для _seen, дедуп вернёт ту же карточку
    watcher_mod._ingest_new(f)
    locs = fileops.locations_for(fid)
    assert len(locs) == 1 and locs[0]["is_current"]


def test_watcher_delete_default_forgets_path(_db: Path, monkeypatch) -> None:
    """on_delete=forget_path (умолчание): путь устаревает, карточка остаётся."""
    watched = _db / "inbox"
    watched.mkdir(exist_ok=True)
    f = watched / "акт.txt"
    f.write_text("акт выполненных работ", encoding="utf-8")
    _watcher_settings(monkeypatch, watched)

    watcher_mod._ingest_new(f)
    fid = _single_file_id()
    f.unlink()
    watcher_mod._handle_gone(f)

    with get_session_factory()() as db:
        assert db.get(File, fid) is not None  # карточка жива (копия в storage)
    assert all(not loc["is_current"] for loc in fileops.locations_for(fid))


def test_watcher_delete_remove_policy(_db: Path, monkeypatch) -> None:
    """on_delete=remove: карточка удаляется целиком (чанки/векторы/аудит)."""
    watched = _db / "inbox"
    watched.mkdir(exist_ok=True)
    f = watched / "счёт.txt"
    f.write_text("счёт на оплату 5000", encoding="utf-8")
    _watcher_settings(monkeypatch, watched, on_delete="remove")

    watcher_mod._ingest_new(f)
    fid = _single_file_id()
    f.unlink()
    watcher_mod._handle_gone(f)

    with get_session_factory()() as db:
        assert db.get(File, fid) is None


def test_watcher_reingests_modified_file(_db: Path, monkeypatch) -> None:
    """Изменение содержимого: старая карточка (другой sha) удаляется, файл
    принимается заново. Неизменённый файл — пустой шум."""
    watched = _db / "inbox"
    watched.mkdir(exist_ok=True)
    f = watched / "смета.txt"
    f.write_text("смета материалы итого 100000", encoding="utf-8")
    _watcher_settings(monkeypatch, watched)

    watcher_mod._ingest_new(f)
    old_fid = _single_file_id()
    with get_session_factory()() as db:
        old_card = db.get(File, old_fid)
        assert old_card is not None
        old_sha = old_card.sha256

    f.write_text("смета материалы итого 250000 работа доп", encoding="utf-8")
    watcher_mod._handle_modified(f)

    # NB: SQLite переиспользует rowid после удаления — старую карточку
    # опознаём по sha, а не по id
    with get_session_factory()() as db:
        files = db.execute(select(File)).scalars().all()
        assert len(files) == 1
        assert files[0].sha256 != old_sha  # старая удалена, принята новая

    # повтор без изменений — шум, ничего не происходит
    watcher_mod._handle_modified(f)
    with get_session_factory()() as db:
        assert len(db.execute(select(File)).scalars().all()) == 1


def test_watcher_move_repoints_location(_db: Path, monkeypatch) -> None:
    """Перемещение/переименование: та же карточка, актуальный путь — новый."""
    watched = _db / "inbox"
    watched.mkdir(exist_ok=True)
    f = watched / "договор 123.txt"
    f.write_text("договор подряда 123", encoding="utf-8")
    _watcher_settings(monkeypatch, watched)

    watcher_mod._ingest_new(f)
    fid = _single_file_id()
    dst = watched / "архив" if False else watched / "договор 123 (переименован).txt"
    f.rename(dst)
    watcher_mod._handle_moved(f, dst)

    cur = [loc for loc in fileops.locations_for(fid) if loc["is_current"]]
    assert len(cur) == 1 and Path(cur[0]["path"]) == dst.resolve()
    with get_session_factory()() as db:
        assert db.get(File, fid) is not None  # карточка та же (дедуп по sha)


def test_watcher_reconcile_sweep(_db: Path, monkeypatch) -> None:
    """Догоняющая сверка: актуальный путь карточки внутри watched-папки,
    которого нет на диске (агент был выключен), устаревает."""
    watched = _db / "inbox"
    watched.mkdir(exist_ok=True)
    f = watched / "ттн.txt"
    f.write_text("товарно-транспортная накладная 7", encoding="utf-8")
    s = _watcher_settings(monkeypatch, watched)

    watcher_mod._ingest_new(f)
    fid = _single_file_id()
    f.unlink()
    watcher_mod._reconcile(s)

    assert all(not loc["is_current"] for loc in fileops.locations_for(fid))


def test_watcher_leaves_unwatched_paths_alone(_db: Path, monkeypatch) -> None:
    """Пути ВНЕ watched-папок реконсилиацией не трогаются (импорт папки
    в произвольное место не должен зачищаться watcher'ом)."""
    watched = _db / "inbox"
    watched.mkdir(exist_ok=True)
    s = _watcher_settings(monkeypatch, watched)

    elsewhere = _db / "elsewhere"
    elsewhere.mkdir(exist_ok=True)
    f = elsewhere / "договор 555.txt"
    f.write_text("договор 555", encoding="utf-8")
    watcher_mod._ingest_new(f)  # приём как таковой работает из любой папки
    fid = _single_file_id()

    f.unlink()
    watcher_mod._reconcile(s)  # файл вне watched-папок — судьбу не решаем
    cur = [loc for loc in fileops.locations_for(fid) if loc["is_current"]]
    assert len(cur) == 1  # путь остался актуальным (карточку не зачистили)


# ---------- groundrails: число -> цитируемый файл ----------

_FRAGS = [
    {"file_id": 1, "file_name": "смета.txt", "doc_type": "other",
     "text": "Смета по объекту. Работы и материалы. Итого 50000 руб."},
    {"file_id": 2, "file_name": "договор.txt", "doc_type": "contract",
     "text": "Договор подряда. Сумма 900000 руб."},
]


def test_number_must_come_from_cited_file() -> None:
    """Число с цитатой [file_id:1] должно идти из файла 1: число из файла 2
    больше не «подтверждает» утверждение про файл 1 (v3.0.3)."""
    bad = "Итого по акту 900000 руб. [file_id:1]"
    out = validate_answer(bad, _FRAGS)
    assert "900000" not in out["answer"], out

    good = "Итого по акту 50000 руб. [file_id:1]"
    out2 = validate_answer(good, _FRAGS)
    assert "50000" in out2["answer"]
    assert out2["grounded"] is True


def test_number_without_citation_corpus_wide() -> None:
    """Утверждение БЕЗ цитат проверяется по всему корпусу как раньше
    (обратная совместимость v2.7)."""
    out = validate_answer("Сумма по договору 900000 руб.", _FRAGS)
    assert "900000" in out["answer"]


def test_trailing_citation_stays_with_claim() -> None:
    """Цитата после конца предложения — якорь ПРЕДЫДУЩЕГО утверждения, а не
    отдельный «факт»: раньше отрывалась, утверждение теряло опору."""
    claims = _split_claims("В смете итог 100000 руб. [file_id:1]")
    assert len(claims) == 1
    assert "[file_id:1]" in claims[0][0]

    # слабая лексика («один лист» — этого нет в документе) спасается якорем
    # только если числа/цитата честные: число из файла, цитата реальная
    frags = [{"file_id": 1, "file_name": "смета.txt", "doc_type": "other",
              "text": "Смета по объекту. Работы и материалы. Итого 100000 руб."}]
    out = validate_answer("В смете один лист, итог 100000 руб. [file_id:1]", frags)
    assert "итог 100000 руб." in out["answer"]

    # а выдуманное число якорь не спасает
    out2 = validate_answer("В смете один лист, итог 555555 руб. [file_id:1]", frags)
    assert "555555" not in out2["answer"]


# ---------- deep_read: grounding-фильтр ----------

def _mk_file(text: str, name: str = "КС2_акт_Вилоновская_23.txt") -> int:
    with get_session_factory()() as db:
        f = File(sha256=f"sha-{name}-{abs(hash(text))}", original_name=name,
                 stored_path="/tmp/unused", format="txt", size_bytes=len(text),
                 mtime="0", status="done", doc_type="ks2")
        db.add(f)
        db.commit()
        db.add(Chunk(file_id=f.id, chunk_index=0, text=text))
        db.commit()
        return int(f.id)


def _deep_llm(monkeypatch, answer: str) -> None:
    import doc_agent.services.deep_read as dr

    base = load_settings()

    def fake_load():
        st = base.model_copy(deep=True)
        st.llm.provider = "openai_compatible"
        return st

    class FakeLLM:
        def chat(self, prompt: str, model: str | None = None) -> str:
            return answer

    monkeypatch.setattr(dr, "load_settings", fake_load)
    monkeypatch.setattr(dr, "get_llm", lambda: FakeLLM())


DOC_TEXT = "Акт КС-2 № 5. Объект Вилоновская 23. Итого 50000 руб."


def test_deep_read_hallucinated_answer_rejected(_db: Path, monkeypatch) -> None:
    """deep_read: выдуманное число -> None (вопрос уйдёт в обычный RAG-путь),
    а не «уверенная сводка» с выдумкой (раньше фильтра не было вовсе)."""
    fid = _mk_file(DOC_TEXT)
    _deep_llm(monkeypatch, f"В документе итог 12345678 руб. [file_id:{fid}]")

    with get_session_factory()() as db:
        res = try_deep_read("что в файле?", db, require_cue=False, file_ids=[fid])
    assert res is None


def test_deep_read_grounded_answer_passes(_db: Path, monkeypatch) -> None:
    fid = _mk_file(DOC_TEXT)
    _deep_llm(monkeypatch, f"Итого по акту 50000 руб. [file_id:{fid}]")

    with get_session_factory()() as db:
        res = try_deep_read("что в файле?", db, require_cue=False, file_ids=[fid])
    assert res is not None
    assert res["intent"] == "deep_read"
    assert res["grounded"] is True
    assert res["confidence"] == 0.9  # cut_ratio=0 -> прежняя уверенность
    assert "50000" in res["answer"]


def test_deep_read_partial_cuts_and_scales_confidence(_db: Path,
                                                      monkeypatch) -> None:
    fid = _mk_file(DOC_TEXT)
    _deep_llm(
        monkeypatch,
        f"Итого по акту 50000 руб. [file_id:{fid}] А также премия 777 руб. [file_id:{fid}]")

    with get_session_factory()() as db:
        res = try_deep_read("что в файле?", db, require_cue=False, file_ids=[fid])
    assert res is not None
    assert "50000" in res["answer"] and "777" not in res["answer"]
    assert res["partial"] is True
    assert res["confidence"] == 0.45  # 0.9 * (1 - 0.5)


# ---------- synthesis: гейт честного пересказа ----------

def _synth_llm(monkeypatch, answer: str) -> None:
    import doc_agent.services.query as qmod

    base = load_settings()

    def fake_load():
        st = base.model_copy(deep=True)
        st.llm.provider = "openai_compatible"
        return st

    class FakeLLM:
        def chat(self, prompt: str, model: str | None = None) -> str:
            return answer

    monkeypatch.setattr(qmod, "load_settings", fake_load)
    monkeypatch.setattr(qmod, "get_llm", lambda: FakeLLM())


def test_synthesis_invented_number_falls_back(_db: Path, monkeypatch) -> None:
    """LLM переписала список и придумала число -> откат к детерминированному
    тексту (раньше synthesis был без проверки)."""
    facts = "Найдено файлов: 3 [file_id:1] [file_id:2] [file_id:3]"
    _synth_llm(monkeypatch, "По вашему запросу найдено 7 файлов [file_id:1].")
    out = _maybe_synthesize("сколько файлов", {"answer": facts})
    assert out["answer"] == facts  # детерминированный текст сохранён


def test_synthesis_honest_rewrap_passes(_db: Path, monkeypatch) -> None:
    facts = "Найдено файлов: 3 [file_id:1] [file_id:2] [file_id:3]"
    _synth_llm(monkeypatch, "По вашему запросу найдено 3 файла [file_id:1].")
    out = _maybe_synthesize("сколько файлов", {"answer": facts})
    assert out["answer"].startswith("По вашему запросу найдено 3 файла")


# ---------- BM25: кэш индекса ----------

def test_bm25_index_cached_across_queries(_db: Path, monkeypatch) -> None:
    from doc_agent.subagents import retriever_agent as ra

    # реалистичный корпус: термы запроса есть только в части чанков
    # (BM25Okapi даёт отрицательный IDF, когда терм во ВСЕХ документах —
    # тогда фильтр s > 0 законно опустошает выдачу, как и в v2.7)
    texts = [f"смета материалы унифлекс позиция {i}" for i in range(3)] + \
            [f"договор подряда акт объект {i}" for i in range(2)]
    chunks = [Chunk(id=i + 1, file_id=1, chunk_index=i, text=t)
              for i, t in enumerate(texts)]
    calls = {"n": 0}
    real_lt = ra.lexical_tokens

    def counting(text: str) -> list[str]:
        calls["n"] += 1
        return real_lt(text)

    monkeypatch.setattr(ra, "lexical_tokens", counting)
    agent = ra.RetrieverAgent()

    first = agent.bm25_top(chunks, "материалы унифлекс", 5)
    assert first and calls["n"] > 0
    after_build = calls["n"]

    # второй запрос по ТОМУ ЖЕ корпусу — индекс переиспользуется
    second = agent.bm25_top(chunks, "материалы", 5)
    assert calls["n"] == after_build
    assert second[0][0] == first[0][0]

    # корпус изменился (новый id чанка) — пересборка
    chunks2 = chunks + [Chunk(id=999, file_id=2, chunk_index=0,
                              text="ещё смета материалы по объекту")]
    agent.bm25_top(chunks2, "материалы", 5)
    assert calls["n"] > after_build


# ---------- feedback: лимит длины проверенных ответов ----------

def test_known_answer_long_table_not_truncated(_db: Path) -> None:
    """Исправленный ответ с таблицей (>3000 символов) больше не режется
    жёсткими [:3000] — лимит из конфига (6000, 0 = без лимита)."""
    rows = "\n".join(f"| {i} | позиция ведомости номер {i} | 100{i} |"
                     for i in range(120))
    long_answer = ("| № | Наименование | Сумма |\n|---|---|---|\n" + rows)
    assert len(long_answer) > 3000

    feedback_service.add_or_update(
        "user", "дай таблицу материалов по смете", "старый ответ",
        rating="up", corrected_answer=long_answer)

    block = feedback_service.known_answers_block("дай таблицу материалов по смете")
    assert long_answer in block  # целиком, без обреза на 3000
