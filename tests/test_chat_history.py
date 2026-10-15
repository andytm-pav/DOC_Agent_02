"""v2.4: персистентная история чата, очистка истории/контекста, архив памяти
(«вспомни …»), строка статуса и админ-диагностика.

Конфиг тестов — provider=none: суммаризация/ответ «вспомни» идут
детерминированным extractive-путём (LLM-ветки покрыты смоуком с мок-API).
"""
from __future__ import annotations

from tests.conftest import upload_and_wait

H = lambda token: {"Authorization": f"Bearer {token}"}  # noqa: E731


def _q(client, token: str, q: str) -> dict:
    r = client.post("/query", json={"q": q}, headers=H(token))
    assert r.status_code == 200, r.text
    return r.json()


def test_history_persists_and_ui_elements(client, admin_token, sample_files):
    """Ответы /query сохраняются в историю и доступны после «обновления страницы»."""
    upload_and_wait(client, admin_token, sample_files["pdf"])
    data = _q(client, admin_token, "Покажи все КС2 по договору 123")
    assert data["answer"]

    h = client.get("/chat/history", headers=H(admin_token)).json()
    assert h["total"] >= 2 and h["active"] >= 2
    roles = [m["role"] for m in h["items"]]
    assert roles.count("user") >= 1 and roles.count("agent") >= 1
    agent_msgs = [m for m in h["items"] if m["role"] == "agent"]
    assert agent_msgs[-1]["meta"]["grounded"] in (True, False)
    assert agent_msgs[-1]["content"] == data["answer"]

    # история отдаётся и второму «открытию страницы» (переживает обновление)
    h2 = client.get("/chat/history", headers=H(admin_token)).json()
    assert h2["items"] == h["items"]

    page = client.get("/", headers=H(admin_token)).text
    for marker in ("agentStatus", "clearHistoryBtn", "clearContextBtn", "archiveToggleBtn"):
        assert marker in page, marker


def test_history_per_user(client, admin_token, user_token):
    """История персональная: сообщения разных пользователей не смешиваются."""
    _q(client, admin_token, "Покажи все КС2 по договору 123")
    _q(client, user_token, "Дай ТТН №999")
    ha = client.get("/chat/history", headers=H(admin_token)).json()
    hu = client.get("/chat/history", headers=H(user_token)).json()
    assert all("КС2" in m["content"] for m in ha["items"] if m["role"] == "user")
    assert all("ТТН" in m["content"] for m in hu["items"] if m["role"] == "user")


def test_clear_history(client, admin_token):
    _q(client, admin_token, "Покажи все КС2 по договору 123")
    r = client.post("/chat/clear-history", headers=H(admin_token))
    assert r.status_code == 200
    deleted = r.json()["deleted"]
    assert deleted >= 2
    assert client.get("/chat/history", headers=H(admin_token)).json()["total"] == 0
    # 401 без авторизации
    assert client.post("/chat/clear-history").status_code == 401
    assert client.get("/chat/history").status_code == 401


def test_clear_context_archives_and_recall(client, admin_token, sample_files):
    """Очистка контекста: сообщения остаются в истории, но покидают актуальный
    контекст; памятка попадает в архив и поднимается запросом «вспомни …»."""
    upload_and_wait(client, admin_token, sample_files["pdf"])
    _q(client, admin_token, "Покажи все КС2 по договору 123")

    r = client.post("/chat/clear-context", headers=H(admin_token))
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["archived"] is True and data["messages"] >= 2
    assert data["summary"].strip()

    h = client.get("/chat/history", headers=H(admin_token)).json()
    assert h["total"] >= 2          # история осталась на экране
    assert h["active"] == 0         # но контекст опустел
    # сервисный уровень: контекстный блок действительно пуст
    from doc_agent.services.chat import context_block

    assert context_block("admin", 20) == ""

    items = client.get("/chat/archives", headers=H(admin_token)).json()["items"]
    assert len(items) == 1 and items[0]["message_count"] >= 2

    # «вспомни …» поднимает памятку
    rec = _q(client, admin_token, "Вспомни, что мы обсуждали?")
    assert rec.get("recall") is True
    assert "КС2" in rec["answer"]
    assert rec["archives"] and rec["archives"][0]["title"]

    # в истории появился и этот обмен
    h2 = client.get("/chat/history", headers=H(admin_token)).json()
    assert any(m["role"] == "agent" and m["meta"].get("recall") for m in h2["items"])


def test_recall_empty_archive_falls_through(client, admin_token):
    """Архив пуст — «вспомни …» уходит в обычный поиск по документам."""
    data = _q(client, admin_token, "Вспомни, что было по договору 123?")
    assert "recall" not in data or data.get("recall") is not True


def test_recall_no_match_lists_titles(client, admin_token, sample_files):
    upload_and_wait(client, admin_token, sample_files["pdf"])
    _q(client, admin_token, "Покажи все КС2 по договору 123")
    client.post("/chat/clear-context", headers=H(admin_token))
    rec = _q(client, admin_token, "Вспомни, когда мы загружали файлы про котиков?")
    assert rec.get("recall") is True
    assert "не нашлось" in rec["answer"] or "не нашлось" in rec["answer"].lower()


def test_reporter_prompt_has_context_placeholder():
    """Промпт репортера содержит блок контекста и подставляет его значение."""
    from doc_agent.llm.prompts import get_prompt, prompts_dir

    raw = (prompts_dir() / "reporter.txt").read_text(encoding="utf-8")
    assert "{context}" in raw
    rendered = get_prompt("reporter", question="q", fragments="f", context="мы уже смотрели КС2")
    assert "мы уже смотрели КС2" in rendered
    # пустой контекст не ломает промпт
    assert get_prompt("reporter", question="q", fragments="f", context="")


def test_status_endpoint(client, admin_token, user_token):
    r = client.get("/status", headers=H(admin_token))
    assert r.status_code == 200
    d = r.json()
    assert d["version"] and d["health"] and "llm" in d and "activity" in d and "chat" in d
    assert d["llm"]["provider"] == "none"  # конфиг тестов
    assert client.get("/status").status_code == 401
    # user-роль тоже видит статус (строка в UI доступна всем)
    assert client.get("/status", headers=H(user_token)).status_code == 200


def test_admin_debug(client, admin_token, user_token):
    r = client.get("/admin/debug", headers=H(admin_token))
    assert r.status_code == 200
    d = r.json()
    for key in ("version", "platform", "config_file", "llm", "database",
                "audit_tail", "error_log_tail", "sort_jobs"):
        assert key in d, key
    assert d["llm"]["api_key_set"] is False
    assert "chat_messages" in d["database"] and "context_archives" in d["database"]
    # user-роль не допускается
    assert client.get("/admin/debug", headers=H(user_token)).status_code == 403


def test_admin_ui_has_debug_panel(client, admin_token):
    page = client.get("/admin-ui", headers=H(admin_token)).text
    assert "debugBox" in page and "loadDebug" in page


def test_llm_summary_path(monkeypatch):
    """LLM-ветка суммаризации: строгий JSON {"title", "summary"} из промпта."""
    from doc_agent.config import load_settings
    from doc_agent.services import chat as chat_service

    cfg = load_settings()
    cfg.llm.provider = "openai_compatible"  # включает LLM-ветку _llm_summary

    class FakeLLM:
        def chat(self, prompt: str, model: str | None = None, timeout: float | None = None) -> str:
            assert "памятку" in prompt  # промпт context_summary.txt подставлен
            return '{"title": "Загрузка КС2", "summary": "Мы разбирали КС-2 по договору 123"}'

        def ping(self) -> bool:
            return True

    monkeypatch.setattr(chat_service, "load_settings", lambda: cfg)
    monkeypatch.setattr(chat_service, "get_llm", lambda: FakeLLM())
    msgs = [
        chat_service.ChatMessage(user="admin", role="user", content="Покажи КС2"),
        chat_service.ChatMessage(user="admin", role="agent", content="Ответ"),
    ]
    title, summary = chat_service._llm_summary(msgs)  # type: ignore[arg-type,misc]
    assert title == "Загрузка КС2" and "КС-2" in summary
