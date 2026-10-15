"""test_v302_table_fix.py — v3.0.2: groundrails не ломает Markdown-таблицы.

Дефект v3.0.1: validate_answer резал ответ на «утверждения» построчно
(\\n+ в _SPLIT_RE) и проверял КАЖДУЮ строку таблицы как отдельный факт.
Шапка «| № | Файл | Тип | Описание |» не находила лексической опоры во
фрагментах (это разметка, а не факты) и вырезалась, а разделитель
«|---|» (пустой набор токенов, support=1.0) переживал проверку. В ответ
уходила «осиротевшая» строка-разделитель, GFM-рендер ломался и
пользователь видел сырые пайпы вместо таблицы.

Фикс: строки таблицы образуют блок; шапка/разделитель — структурные
строки (structural=True), валидацию не проходят и остаются, пока у блока
жив хотя бы один ряд данных. Ряды данных валидируются как раньше.
"""
from __future__ import annotations

from doc_agent.services.groundrails import validate_answer

FRAGMENTS = [
    {
        "file_id": 1,
        "file_name": "Дог подряда №27-07-2026 Старый город.doc",
        "doc_type": "договор",
        "text": (
            "Договор подряда на капитальный ремонт кровли для ТСЖ «Старый "
            "город» по ул. Вилоновская, 23/173 в Самаре, договор №27-07/2026. "
            "Договор подряда на капремонт кровли, договор №27-07/2026."
        ),
        "score": 0.8,
    },
]

# Ряды данных почти дословно повторяют текст фрагмента — проходят
# лексическую поддержку (support >= 0.55), как в реальном сценарии.
_ROW = ("| {n} | Дог подряда №27-07-2026 Старый город.doc | договор | "
        "Договор подряда на капремонт кровли, договор №27-07/2026 [file_id:1] |")

TABLE_ANSWER = (
    "| № | Файл | Тип | Описание |\n"
    "|---|---|---|---|\n"
    + _ROW.format(n=1) + "\n"
    + _ROW.format(n=2)
)


def test_table_header_and_separator_survive() -> None:
    """Шапка и разделитель — разметка: не вырезаются grounding-валидацией."""
    out = validate_answer(TABLE_ANSWER, FRAGMENTS)
    lines = out["answer"].splitlines()
    assert lines[0].startswith("| № |"), lines
    assert lines[1].startswith("|---"), lines
    # ряды данных на месте, порядок сохранён
    assert "| 1 |" in out["answer"] and "| 2 |" in out["answer"]


def test_table_renders_as_intact_markdown() -> None:
    """Ответ не содержит «осиротевшей» строки-разделителя без шапки."""
    out = validate_answer(TABLE_ANSWER, FRAGMENTS)
    lines = out["answer"].splitlines()
    assert not lines[0].startswith("|---"), "разделитель не должен быть первой строкой"


def test_intro_cut_but_table_intact() -> None:
    """Вводная фраза без опоры во фрагментах вырезается, таблица цела."""
    answer = "Вот таблица с файлами картотеки:\n" + TABLE_ANSWER
    out = validate_answer(answer, FRAGMENTS)
    assert "Вот таблица" not in out["answer"]
    assert out["answer"].splitlines()[0].startswith("| № |")


def test_ungrounded_table_removed_entirely() -> None:
    """Таблица-выдумка (ни ряда с опорой) вырезается вместе с разметкой."""
    answer = "| Марс | Луна |\n|---|---|\n| 999999 | 888888 |"
    out = validate_answer(answer, FRAGMENTS)
    assert out["answer"].strip() == "НЕТ ДАННЫХ"


def test_orphan_markup_removed_when_all_rows_cut() -> None:
    """Если все ряды таблицы вырезаны — шапка/разделитель тоже уходят."""
    answer = (
        "Договор подряда на капремонт кровли, договор №27-07/2026 [file_id:1]\n"
        "| Марс | Венера |\n|---|---|\n| 999999 | 888888 |"
    )
    out = validate_answer(answer, FRAGMENTS)
    assert "|" not in out["answer"]
    assert "Марс" not in out["answer"]
    assert "Договор подряда" in out["answer"]  # вводная осталась


def test_plain_text_validation_unchanged() -> None:
    """Поведение на обычном тексте не изменилось (регресс старой логики)."""
    answer = ("Договор подряда на капремонт кровли, договор №27-07/2026 [file_id:1]\n"
              "Сумма по договору 999999999 рублей.")
    out = validate_answer(answer, FRAGMENTS)
    assert "Договор подряда" in out["answer"]
    assert "999999999" not in out["answer"]
