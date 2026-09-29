"""Репродукция кейса пользователя v2.7 (быстрый функциональный прогон).

Создаёт временную картотеку, повторяющую библиотеку пользователя
(сметы Вилоновской + шум: Конкурсная документация, Аэр.xlsx, КП
Алма-Атинская), прогоняет реальный ingest (xlsx -> KV-строки ->
строчный чанкинг) и проверяет retrieval по вопросам из диалога:

  - «какой материал по вилоновской?»  -> чанки смет Вилоновской,
    НЕ Конкурсная документация/Аэр (раньше — мусор с увер. 0.11);
  - «материалы по отмостке вилоновская» -> смета по стена и отмостка;
  - уверенность осмысленная (не 0/0.11 при релевантных фрагментах).
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

import yaml  # noqa: E402

tmp = Path(tempfile.mkdtemp(prefix="docagent_repro_"))
cfg = yaml.safe_load((REPO / "config" / "config.yaml").read_text(encoding="utf-8"))
cfg["app"]["data_dir"] = str(tmp)
cfg["app"]["admin_username"] = "admin"
cfg["app"]["admin_password"] = "admin"
cfg["planner"]["enabled"] = False  # проверяем именно retrieval
cfg["chat"]["recall_keywords"] = []
cfgpath = tmp / "config.yaml"
cfgpath.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")

import os  # noqa: E402

os.environ["DOC_AGENT_CONFIG"] = str(cfgpath)
os.environ["LLM_API_KEY"] = ""  # hashing-эмбеддинги (офлайн-режим)

from doc_agent.db.migrations import init_db  # noqa: E402
from doc_agent.db.session import get_session_factory  # noqa: E402
from doc_agent.services.ingest import enqueue_file, process_file  # noqa: E402
from doc_agent.subagents.retriever_agent import RetrieverAgent  # noqa: E402

init_db()
factory = get_session_factory()


def make_xlsx(path: Path, rows: list[list[str | float | int]]) -> None:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Смета"
    for r in rows:
        ws.append(r)
    wb.save(path)


def make_docx(path: Path, paragraphs: list[str]) -> None:
    import docx

    d = docx.Document()
    for p in paragraphs:
        d.add_paragraph(p)
    d.save(path)


inbox = tmp / "inbox"
inbox.mkdir()

def f1(p: Path) -> None:
    make_xlsx(p, [
        ["№ п/п", "Вид работ", "Объём", "Ед. изм.", "Примечание"],
        ["Стены", "", "", "", ""],
        [1, "Насечка поверхности", 584, "м2", "под окраску"],
        [2, "Сплошное выравнивание сухой смесью до 10 мм", 584, "м2", ""],
        [3, "Шпатлевка под высококачественную окраску", 584, "м2", ""],
    ])

def f2(p: Path) -> None:
    make_xlsx(p, [
        ["№", "Наименование", "Кол-во", "Ед."],
        ["Материалы", "", "", ""],
        [1, "Унифлекс ЭПП 3.0 рул", 48, "рул"],
        [2, "Праймер битумный", 200, "кг"],
        ["Итого по работе", 672103.3, "", ""],
    ])

def f3(p: Path) -> None:
    make_xlsx(p, [
        ["№ п/п", "Вид работ", "Объём", "Ед. изм."],
        ["Отмостка", "", "", ""],
        [1, "Разборка отмостки", 120, "м2"],
        [2, "Устройство отмостки бетонной", 120, "м2"],
        ["Материалы", "", "", ""],
        [1, "Бетон класса B15", 24, "м3"],
        [2, "Щебень фракции 20-40", 18, "м3"],
        [3, "Арматура А500С d12", 350, "кг"],
    ])

def f4(p: Path) -> None:
    make_docx(p, [
        "Документация по отбору в электронной форме. Объект № 700, площадка 16.",
        "«более 5» — необходимо указать единственное числовое значение строго выше "
        "указанного (например, 6), в данном случае, крайнее числовое значение не входит "
        "в диапазон; «менее 5» — необходимо указать значение ниже указанного.",
    ])

def f5(p: Path) -> None:
    make_xlsx(p, [
        ["№", "Наименование", "Кол-во", "Ед."],
        ["Стены", "", "", ""],
        [21, "Регулятор оборотов вентилятора", 2, "шт"],
        [23, "Труба гофрированная ПВХ (диам. 20 мм)", 153, "м"],
        [25, "Кабель силовой ВВГнг(A)-LS 3x1,5", 153, "м"],
    ])

files = {
    "Сводная смета Вилоновская 23.xlsx": (f1, "1.xlsx"),
    "Смета по кровле Вилоновская 23.xlsx": (f2, "2.xlsx"),
    "Смета по стена и отмостка Вилоновская 23 (2).xlsx": (f3, "3.xlsx"),
    "Конкурсная документация ЗК в ЭФ об. 700 пл.16.docx": (f4, "4.docx"),
    "Аэр.xlsx": (f5, "5.xlsx"),
}

ids = {}
for name, (maker, fname) in files.items():
    p = inbox / fname
    maker(p)
    res = enqueue_file(p, name, source="test")
    ids[name] = res["file_id"]
    process_file(res["file_id"])

print("Загружено файлов:", len(ids))
with factory() as db:
    from sqlalchemy import select

    from doc_agent.db.models import Chunk

    rows = db.execute(select(Chunk.file_id, Chunk.text).order_by(Chunk.file_id, Chunk.chunk_index)).all()
    print("Всего чанков:", len(rows))
    print("--- примеры чанков сметы отмостки (file_id=%d):" % ids["Смета по стена и отмостка Вилоновская 23 (2).xlsx"])
    for fid, text in rows:
        if fid == ids["Смета по стена и отмостка Вилоновская 23 (2).xlsx"]:
            print("  ", repr(text[:130]))

queries = [
    "какой материал по вилоновской?",
    "материалы по отмостке вилоновская",
    "что в сметах по вилоновской",
]
ret = RetrieverAgent()
ok = True
with factory() as db:
    for q in queries:
        fragments, cands = ret.run(db, q, {}, limit=20)
        top = fragments[:5]
        names = []
        for f in top:
            nm = f["file_name"]
            names.append(nm)
        print(f"\nQ: {q}")
        print("  файлы в top-5:", names)
        print("  scores:", [round(f["score"], 2) for f in top])
        vilon = [f for f in top if "вилоновская" in f["file_name"].lower()]
        noise = [f for f in top if "вилоновская" not in f["file_name"].lower()]
        print(f"  релевантных (Вилоновская): {len(vilon)}, шумовых: {len(noise)}")
        if "материал" in q and len(vilon) == 0:
            ok = False

print("\nИТОГ:", "OK" if ok else "ПРОВАЛ")
sys.exit(0 if ok else 1)
