"""Тесты v2.7 — промышленный ретрив (кейс «агент не видит и галлюцинирует»).

Покрывают:
  - Snowball-стемминг: «вилоновской» ~ «Вилоновская», «материалов» ~ «материал»
    (в т.ч. префиксная совместимость для пережатых форм);
  - BM25 видит ВЕСЬ корпус (регресс LIMIT 4000 без ORDER BY);
  - filename-boost: файлы с объектом в имени ранжируются выше;
  - отсев слабых векторных хитов (relative cutoff);
  - табличный чанкинг: чанки по строкам, шапка в каждом чанке;
  - калиброванная уверенность (retrieval + grounding);
  - изоляция векторных пространств (суффикс коллекции);
  - backend auto (api при наличии ключа, hashing без);
  - reset_database.py: полный сброс и пересоздание.
"""
from __future__ import annotations

from pathlib import Path

import yaml


def _make_config(data_dir: Path, **overrides) -> Path:
    from tests.conftest import _make_base_config

    cfg_path = _make_base_config(data_dir)
    if overrides:
        data = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
        for key, value in overrides.items():
            section, field = key.split(".", 1)
            data.setdefault(section, {})[field] = value
        cfg_path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
        import os

        os.environ["DOC_AGENT_CONFIG"] = str(cfg_path)
    return cfg_path


# ---------- 1. Стеммер ----------

def test_stemmer_matches_inflections() -> None:
    from doc_agent.vector.stemmer import stem_token, stems_compatible

    assert stem_token("вилоновской") == stem_token("Вилоновская")
    assert stem_token("сметы") == stem_token("смета")
    assert stem_token("отмостки") == stem_token("отмостка")
    # пережатая форма «материал» -> «материа» компенсируется префиксной
    # совместимостью
    assert stems_compatible(stem_token("материал"), stem_token("материалов"))


def test_lexical_tokens_stemming_toggle(tmp_data_dir: Path) -> None:
    _make_config(tmp_data_dir, **{"embeddings.stem_lexical": True})
    from doc_agent.vector.embedder import lexical_tokens

    toks = lexical_tokens("какой материал по вилоновской")
    assert "вилоновск" in toks

    _make_config(tmp_data_dir, **{"embeddings.stem_lexical": False})
    toks_raw = lexical_tokens("какой материал по вилоновской")
    assert "вилоновской" in toks_raw


# ---------- 2. BM25 по всему корпусу (регресс LIMIT 4000) ----------

def test_bm25_sees_chunks_beyond_4000(tmp_data_dir: Path) -> None:
    """Чанки файла, добавленного ПОСЛЕ 4000 старых, должны находиться."""
    _make_config(tmp_data_dir)
    from sqlalchemy import select

    from doc_agent.db.migrations import init_db
    from doc_agent.db.models import Chunk, File
    from doc_agent.db.session import get_session_factory
    from doc_agent.subagents.retriever_agent import RetrieverAgent

    init_db()
    factory = get_session_factory()
    with factory() as db:
        f_noise = File(sha256="n" * 64, original_name="Старый документ.txt",
                       stored_path="/tmp/x", format="txt", size_bytes=1, mtime="0",
                       status="done", doc_type="other")
        f_target = File(sha256="t" * 64, original_name="Смета Вилоновская 23.xlsx",
                        stored_path="/tmp/y", format="txt", size_bytes=1, mtime="0",
                        status="done", doc_type="other")
        db.add_all([f_noise, f_target])
        db.commit()
        noise_id, target_id = f_noise.id, f_target.id
        # 4001 «старых» чанков без ключевых слов
        db.add_all([Chunk(file_id=noise_id, chunk_index=i, text=f"запись номер {i}")
                    for i in range(4001)])
        db.commit()
        target_chunk = Chunk(file_id=target_id, chunk_index=0,
                             text="материалы: Унифлекс ЭПП 48 рул")
        db.add(target_chunk)
        db.commit()

    with factory() as db:
        files = db.execute(select(File)).scalars().all()
        chunks = db.execute(select(Chunk)).scalars().all()
        ret = RetrieverAgent()
        hits = ret.bm25_top(chunks, "материалы вилоновская унифлекс", 10)
        assert hits, "BM25 ничего не нашёл"
        assert hits[0][0] == target_chunk.id, "целевой чанк не первый"
        assert files  # кандидаты присутствуют


# ---------- 3. Retrieval end-to-end на мини-библиотеке ----------

def _seed_library(tmp_data_dir: Path) -> dict[str, int]:
    """Мини-версия библиотеки пользователя: сметы Вилоновской + шум."""
    from openpyxl import Workbook

    from doc_agent.db.migrations import init_db
    from doc_agent.services.ingest import enqueue_file, process_file

    init_db()
    base = tmp_data_dir / "inbox"
    base.mkdir(parents=True, exist_ok=True)

    def xlsx(path: Path, rows: list[list]) -> Path:
        wb = Workbook()
        ws = wb.active
        ws.title = "Смета"
        for r in rows:
            ws.append(r)
        wb.save(path)
        return path

    files = {
        "Сводная смета Вилоновская 23.xlsx": xlsx(base / "a.xlsx", [
            ["№", "Вид работ", "Объём", "Ед."],
            [1, "Насечка поверхности", 584, "м2"],
            [2, "Шпатлевка под окраску", 584, "м2"],
        ]),
        "Смета по кровле Вилоновская 23.xlsx": xlsx(base / "b.xlsx", [
            ["№", "Наименование", "Кол-во", "Ед."],
            [1, "Унифлекс ЭПП 3.0", 48, "рул"],
            [2, "Праймер битумный", 200, "кг"],
        ]),
        "Смета по стена и отмостка Вилоновская 23 (2).xlsx": xlsx(base / "c.xlsx", [
            ["№", "Вид работ", "Объём", "Ед."],
            [1, "Устройство отмостки бетонной", 120, "м2"],
            [2, "Бетон класса B15", 24, "м3"],
        ]),
        "Конкурсная документация ЗК об. 700.docx": None,  # шум добавим txt ниже
    }
    # шумовой файл (имитация Конкурсной документации) — txt
    noise = base / "noise.txt"
    noise.write_text(
        "Документация по отбору. «более 5» — необходимо указать единственное "
        "числовое значение строго выше указанного, крайнее числовое значение "
        "не входит в диапазон.", encoding="utf-8")

    ids: dict[str, int] = {}
    for name, path in files.items():
        if path is None:
            continue
        res = enqueue_file(path, name, source="test")
        process_file(res["file_id"])
        ids[name] = res["file_id"]
    res = enqueue_file(noise, "Конкурсная документация ЗК об. 700.txt", source="test")
    process_file(res["file_id"])
    ids["Конкурсная документация ЗК об. 700.txt"] = res["file_id"]
    return ids


def test_retrieval_prefers_named_object_files(tmp_data_dir: Path) -> None:
    _make_config(tmp_data_dir)
    _seed_library(tmp_data_dir)
    from doc_agent.db.session import get_session_factory
    from doc_agent.subagents.retriever_agent import RetrieverAgent

    factory = get_session_factory()
    with factory() as db:
        ret = RetrieverAgent()
        fragments, _ = ret.run(db, "какой материал по вилоновской", {}, limit=20)
        top_names = [f["file_name"] for f in fragments[:3]]
        assert top_names, "выдача пустая"
        # все топ-фрагменты — сметы Вилоновской, а не конкурсная документация
        assert all("вилоновская" in n.lower() for n in top_names), top_names
        # filename-boost сработал: первый фрагмент из файла с «вилоновская»
        assert "вилоновская" in fragments[0]["file_name"].lower()


def test_retrieval_offmostka_query(tmp_data_dir: Path) -> None:
    _make_config(tmp_data_dir)
    _seed_library(tmp_data_dir)
    from doc_agent.db.session import get_session_factory
    from doc_agent.subagents.retriever_agent import RetrieverAgent

    factory = get_session_factory()
    with factory() as db:
        ret = RetrieverAgent()
        fragments, _ = ret.run(db, "нужны материалы по отмостке вилоновская", {}, limit=20)
        assert fragments
        assert "отмостка" in fragments[0]["file_name"].lower(), \
            f"первый не отмостка: {fragments[0]['file_name']}"


def test_retrieval_drops_zero_overlap_noise(tmp_data_dir: Path) -> None:
    """Запрос про материалы НЕ должен приносить чанки про числовые диапазоны."""
    _make_config(tmp_data_dir)
    _seed_library(tmp_data_dir)
    from doc_agent.db.session import get_session_factory
    from doc_agent.subagents.retriever_agent import RetrieverAgent

    factory = get_session_factory()
    with factory() as db:
        ret = RetrieverAgent()
        fragments, _ = ret.run(db, "материалы по вилоновской", {}, limit=20)
        # шумовой фрагмент (диапазоны «более 5») имеет нулевое перекрытие
        # с запросом и выбрасывается реранкером, если есть содержательные
        noise = [f for f in fragments if "диапазон" in f["text"]]
        if noise:
            assert all(f["score"] == 0 for f in noise), "шум в выдаче с ненулевым score"


# ---------- 4. Табличный чанкинг ----------

def test_table_chunking_keeps_rows_whole(tmp_data_dir: Path) -> None:
    _make_config(tmp_data_dir)
    from doc_agent.vector.chunker import chunk_lines

    rows = [f"{i}; Унифлекс ЭПП рулонный материал номер {i}; {i}; рул" for i in range(60)]
    text = "\n".join(["№; Наименование; Кол-во; Ед."] + rows)
    chunks = chunk_lines(text, preamble="[Смета.xlsx] ", header_line="№; Наименование; Кол-во; Ед.")
    assert len(chunks) > 1, "ожидались несколько чанков"
    body_re = "Унифлекс ЭПП рулонный материал номер"
    for c in chunks:
        # каждая строка в чанке ЦЕЛАЯ (не обрезана на полутокене)
        lines = c["text"].split("\n")[1:]  # первая — шапка
        for ln in lines:
            if ln.strip().split(";")[0].isdigit():
                assert ln.rstrip().endswith("рул"), f"строка обрезана: {ln!r}"
        assert body_re in c["text"] or c is chunks[0], "шапка/контент потерялись"


def test_xlsx_ingest_kv_rows_with_sheet(tmp_data_dir: Path) -> None:
    _make_config(tmp_data_dir)
    ids = _seed_library(tmp_data_dir)
    from sqlalchemy import select

    from doc_agent.db.models import Chunk
    from doc_agent.db.session import get_session_factory

    fid = ids["Смета по кровле Вилоновская 23.xlsx"]
    factory = get_session_factory()
    with factory() as db:
        texts = [t for (t,) in db.execute(
            select(Chunk.text).where(Chunk.file_id == fid)).all()]
    assert texts
    joined = "\n".join(texts)
    # KV-сериализация: колонка шапки в строке данных
    assert "Наименование: Унифлекс ЭПП 3.0" in joined
    # имя листа в преамбуле
    # v2.8: после листа в преамбуле может быть заметка о документе
    assert "Лист: Смета" in joined


# ---------- 5. Уверенность ----------

def test_confidence_calibrated_mix(tmp_data_dir: Path) -> None:
    _make_config(tmp_data_dir)
    from doc_agent.subagents.validator_agent import ValidatorAgent

    frags_good = [{"score": 1.0}, {"score": 0.8}, {"score": 0.6}]
    c_good = ValidatorAgent.confidence(frags_good, grounding_ratio=1.0)
    c_bad = ValidatorAgent.confidence(frags_good, grounding_ratio=0.0)
    c_none = ValidatorAgent.confidence([], grounding_ratio=1.0)
    assert c_good > c_bad, "grounding не влияет на уверенность"
    assert c_good > 0.5
    assert c_none == 0.0
    # w_r=0.6, w_g=0.4: (0.6*0.8 + 0.4*1.0) = 0.88
    assert abs(c_good - 0.88) < 0.01


# ---------- 6. Изоляция векторных пространств ----------

def test_collection_suffix_per_backend(tmp_data_dir: Path) -> None:
    _make_config(tmp_data_dir)
    from doc_agent.vector.embedder import embedding_space_id

    suffix = embedding_space_id()
    assert suffix.startswith("hashing"), suffix
    assert suffix == embedding_space_id(), "идентификатор пространства нестабилен"


def test_store_uses_suffixed_collection(tmp_data_dir: Path) -> None:
    _make_config(tmp_data_dir)
    from doc_agent.vector.chroma_client import get_vector_store

    store = get_vector_store()
    name = getattr(store.collection, "name", "")
    assert name.startswith("chunks-"), name


# ---------- 7. backend auto ----------

def test_backend_auto_with_and_without_key(tmp_data_dir: Path) -> None:
    _make_config(tmp_data_dir, **{"embeddings.backend": "auto"})
    from doc_agent.vector.embedder import resolve_backend

    assert resolve_backend() == "hashing", "без ключа auto должен дать hashing"

    _make_config(tmp_data_dir, **{"embeddings.backend": "auto",
                                  "llm.provider": "openai_compatible",
                                  "llm.base_url": "https://api.example.com/v1",
                                  "llm.api_key": "k-test"})
    assert resolve_backend() == "api", "с ключом auto должен дать api"


# ---------- 8. reset_database.py ----------

def test_reset_database_full(tmp_data_dir: Path) -> None:
    _make_config(tmp_data_dir)
    _seed_library(tmp_data_dir)

    from sqlalchemy import select

    from doc_agent.db.migrations import log_audit
    from doc_agent.db.models import ChatMessage, Chunk, File
    from doc_agent.db.session import get_session_factory

    log_audit("test", "seed", {})
    factory = get_session_factory()
    with factory() as db:
        db.add(ChatMessage(user="admin", role="user", content="вопрос"))
        db.commit()
        assert db.execute(select(File)).scalars().all()
        assert db.execute(select(Chunk)).scalars().all()

    import subprocess
    import sys

    env = {"DOC_AGENT_CONFIG": str(tmp_data_dir.parent / "config" / "config.yaml"),
           "PATH": "/usr/bin:/bin", "HOME": str(tmp_data_dir)}
    r = subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parents[1] / "scripts" / "reset_database.py"),
         "--yes"],
        capture_output=True, text=True, env=env, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Готово" in r.stdout

    # subprocess удалил файл БД — сбрасываем кэш движков, чтобы соединиться
    # с заново созданной базой (иначе SQLite отдаёт данные из открытого fd)
    from doc_agent.db import session as db_session

    db_session._engines.clear()
    db_session._factories.clear()
    factory = get_session_factory()

    with factory() as db:
        assert db.execute(select(File)).scalars().all() == []
        assert db.execute(select(Chunk)).scalars().all() == []
        assert db.execute(select(ChatMessage)).scalars().all() == []
        # admin пересоздан
        from doc_agent.db.models import User

        admins = [u for u in db.execute(select(User)).scalars().all() if u.role == "admin"]
        assert admins, "администратор не пересоздан"


def test_reset_history_only(tmp_data_dir: Path) -> None:
    _make_config(tmp_data_dir)
    _seed_library(tmp_data_dir)

    from doc_agent.db.models import ChatMessage
    from doc_agent.db.session import get_session_factory

    factory = get_session_factory()
    with factory() as db:
        db.add(ChatMessage(user="admin", role="user", content="вопрос"))
        db.commit()

    import subprocess
    import sys

    env = {"DOC_AGENT_CONFIG": str(tmp_data_dir.parent / "config" / "config.yaml"),
           "PATH": "/usr/bin:/bin", "HOME": str(tmp_data_dir)}
    r = subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parents[1] / "scripts" / "reset_database.py"),
         "--yes", "--history-only"],
        capture_output=True, text=True, env=env, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr

    from sqlalchemy import select

    from doc_agent.db.models import File

    with factory() as db:
        assert db.execute(select(File)).scalars().all(), "файлы не должны стираться"
        assert db.execute(select(ChatMessage)).scalars().all() == [], "история не стёрта"
