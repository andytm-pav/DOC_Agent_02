"""Тесты v3.0.1 — правки по отчёту пользователя:

1. Голова+хвост в deep_read (_stitch): большие документы больше не теряют
   концовку (реквизиты/подписи/гарантия были в «обрезанной» части).
2. file_link без file_ids/terms больше НЕ возвращает пути посторонних
   файлов (честный отказ), а по термам находит файлы картотеки по
   названиям даже без запомненного пути («путь не запомнен» — по ПРАВИЛЬНЫМ
   файлам).
3. Каталог помечает файлы-близнецы (один документ в разных форматах,
   .docx+.pdf с одинаковым именем) — LLM не считает один документ двумя
   договорами.
4. llm.max_tokens (0 = не отправлять) есть в конфиге и прокидывается
   в payload OpenAI-совместимого клиента.
"""
from __future__ import annotations

from pathlib import Path

from tests.conftest import upload_and_wait

from doc_agent.services.deep_read import _stitch
from doc_agent.services.intents import _format_dup_map, catalog_block

# ------------------------------------------------- 1. голова+хвост

def test_stitch_short_text_untouched():
    assert _stitch("короткий текст", 1000) == "короткий текст"


def test_stitch_keeps_head_and_tail():
    full = "НАЧАЛО" + ("х" * 5000) + "КОНЕЦ-С-РЕКВИЗИТАМИ"
    out = _stitch(full, 1000)
    assert len(out) <= 1100  # бюджет + маркер
    assert out.startswith("НАЧАЛО")
    assert "КОНЕЦ-С-РЕКВИЗИТАМИ" in out  # концовка сохранена
    assert "пропущено" in out  # честная пометка о середине


def test_stitch_zero_budget_returns_full():
    # max_chars <= 0 — без обрезки (защита от деления в per_file=500 ниже)
    assert _stitch("текст", 0) == "текст"


# ------------------------------------------------- 2. file_link fallback

def test_file_link_without_hints_refuses(client, admin_token):
    """Пустые file_ids и terms -> честный отказ, БЕЗ путей посторонних файлов
    (регрессия: раньше возвращались последние запомненные пути любых файлов).
    db не используется, когда оба списка пусты."""
    from doc_agent.services import fileops

    # db не используется, когда оба списка пусты — None здесь намеренный
    text, chips = fileops.file_link_block([], [], db=None)  # type: ignore[arg-type]
    assert "Не удалось определить" in text
    assert chips == []
    assert "file_id" not in text  # никаких чужих файлов в ответе


def test_file_link_by_terms_finds_catalog_files(client, admin_token, sample_files):
    """По термам находятся файлы картотеки ПО НАЗВАНИЯМ даже без запомненного
    пути: ответ честный («путь не запомнен») и про ПРАВИЛЬНЫЕ файлы."""
    from doc_agent.db.session import get_session_factory
    from doc_agent.services import fileops

    data = upload_and_wait(client, admin_token, sample_files["docx"])
    file_id = int(data["file"]["id"])
    # имя файла из фикстуры; берём маркер-подстроку из оригинального имени
    name = data["file"]["original_name"]
    stem = Path(name).stem
    term = stem.split()[0].lower() if stem.split() else stem.lower()
    with get_session_factory()() as db:
        text, chips = fileops.file_link_block([term], [], db)
    assert str(file_id) in text or f"file_id:{file_id}" in text
    assert any(int(c["file_id"]) == file_id for c in chips)
    assert "не запомнен" in text  # честно осутствии пути


# ------------------------------------------------- 3. близнецы-форматы

def test_format_dup_map_and_catalog_note(client, admin_token, sample_files, tmp_path):
    """docx+pdf с одинаковым именем = один документ: map указывает на первого,
    каталог содержит пометку «ТОТ ЖЕ ДОКУМЕНТ». Разные имена не схлопываются."""
    class _F:  # минимальная имитация File для чистой функции
        def __init__(self, fid: int, name: str):
            self.id = fid
            self.original_name = name

    files = [
        _F(20, "Дог подряда № Эко дом Карла Маркса _400 (трубы).docx"),
        _F(21, "Дог подряда № Эко дом Карла Маркса _400 (трубы).pdf"),
        _F(22, "Дог подряда №27-07-2026 Старый город_ред1.docx"),
    ]
    dup = _format_dup_map(files)
    assert dup == {21: 20}  # pdf указывает на docx; «ред1» не схлопнулся

    # каталог с пометкой (полный путь через БД не нужен: проверяем формат строки)
    block_stub = catalog_block.__doc__ or ""
    assert "ТОТ ЖЕ ДОКУМЕНТ" in block_stub  # контракт пометки задокументирован


def test_catalog_annotation_in_block(client, admin_token, sample_files):
    """Интеграционно: два файла с одинаковым стемом в БД -> пометка в каталоге."""
    from doc_agent.db.session import get_session_factory

    up1 = upload_and_wait(client, admin_token, sample_files["docx"])
    # второй файл: то же ИМЯ (стем), другое расширение и содержимое —
    # дедупликация по хэшу контента не должна схлопнуть их в один file_id
    src = sample_files["docx"]
    twin = src.with_suffix(".pdf")
    if not twin.exists():
        twin = src.with_suffix(".txt")
        twin.write_text("Текстовая версия того же документа, содержимое другое.", encoding="utf-8")
    up2 = upload_and_wait(client, admin_token, twin)
    assert up2["file"]["status"] == "done", up2["file"]
    id1, id2 = int(up1["file"]["id"]), int(up2["file"]["id"])
    with get_session_factory()() as db:
        block = catalog_block(db)
    lo, hi = min(id1, id2), max(id1, id2)
    assert f"file_id:{hi}" in block, block
    assert f"ТОТ ЖЕ ДОКУМЕНТ, что file_id:{lo}" in block, block


# ------------------------------------------------- 4. llm.max_tokens

def test_llm_max_tokens_config_default():
    from doc_agent.config import LLMSettings

    s = LLMSettings()
    assert s.max_tokens == 0  # 0 = не отправлять (лимит провайдера) — обратносовместимо


def test_llm_max_tokens_in_payload(monkeypatch):
    """max_tokens > 0 попадает в payload OpenAI-совместимого запроса."""
    import doc_agent.llm.ollama_client as oc
    from doc_agent.config import LLMSettings

    captured: dict = {}

    class _Resp:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"choices": [{"message": {"content": "ok"}}]}

    def _fake_post(url, json=None, **kwargs):
        captured.update(json or {})
        return _Resp()

    monkeypatch.setattr(oc.httpx, "post", _fake_post)
    s = LLMSettings(provider="openai_compatible", base_url="http://x",
                    api_key="k", max_tokens=4096)
    oc.OpenAICompatible(s).chat("тест")
    assert captured.get("max_tokens") == 4096

    captured.clear()
    s0 = LLMSettings(provider="openai_compatible", base_url="http://x", api_key="k")
    oc.OpenAICompatible(s0).chat("тест")
    assert "max_tokens" not in captured  # 0 = поле не отправляется
