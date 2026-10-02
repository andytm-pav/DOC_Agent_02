"""v2.7.1: dimensions для api-эмбеддингов + честный health-check."""
from __future__ import annotations

from typing import Any

from doc_agent.config import load_settings
from doc_agent.llm import ollama_client
from doc_agent.llm.ollama_client import OpenAICompatible
from doc_agent.vector import embedder


class _FakeResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


def _set_api(monkeypatch, model: str = "embedding-3", dimensions: int = 0,
             base_url: str = "https://open.bigmodel.cn/api/paas/v4",
             api_key: str = "test-key") -> None:
    """Переопределяет конфиг эмбеддингов через monkeypatch load_settings."""

    def fake_load() -> Any:
        s = load_settings()
        s.embeddings.backend = "api"
        s.embeddings.api.model = model
        s.embeddings.api.dimensions = dimensions
        s.embeddings.api.base_url = base_url
        s.embeddings.api.api_key = api_key
        s.embeddings.api.api_path = "/embeddings"
        s.llm.provider = "openai_compatible"
        s.llm.base_url = "https://api.openai.com/v1"  # НЕ должен влиять
        s.llm.api_key = "llm-key"
        return s

    monkeypatch.setattr(embedder, "load_settings", fake_load)


def test_api_embed_sends_dimensions(monkeypatch) -> None:
    """dimensions > 0 -> параметр уходит в тело запроса к /embeddings."""
    captured: dict = {}

    class _FakeClient:
        def __init__(self, **kwargs: Any) -> None: ...

        def __enter__(self) -> "_FakeClient":
            return self

        def __exit__(self, *args: Any) -> None: ...

        def post(self, url: str, json: dict, headers: dict) -> Any:
            captured["url"] = url
            captured["json"] = json

            class _R:
                status_code = 200
                text = ""
                headers: dict[str, str] = {}

                def raise_for_status(self) -> None: ...

                def json(self) -> dict:
                    n = len(json["input"])
                    dim = json.get("dimensions", 3)
                    return {"data": [{"index": i, "embedding": [0.1] * dim}
                                     for i in range(n)]}
            return _R()

    monkeypatch.setattr(embedder.httpx, "Client", _FakeClient)
    _set_api(monkeypatch, dimensions=1024)
    vecs = embedder.embed_passages(["текст один", "текст два"])
    assert captured["json"]["dimensions"] == 1024
    assert captured["json"]["model"] == "embedding-3"
    assert len(vecs) == 2 and len(vecs[0]) == 1024
    assert "bigmodel.cn" in captured["url"]


def test_api_embed_omits_dimensions_by_default(monkeypatch) -> None:
    """dimensions: 0 -> параметр НЕ передаётся (дефолт провайдера)."""
    captured: dict = {}

    class _FakeClient:
        def __init__(self, **kwargs: Any) -> None: ...

        def __enter__(self) -> "_FakeClient":
            return self

        def __exit__(self, *args: Any) -> None: ...

        def post(self, url: str, json: dict, headers: dict) -> Any:
            captured["json"] = json

            class _R:
                status_code = 200
                text = ""
                headers: dict[str, str] = {}

                def raise_for_status(self) -> None: ...

                def json(self) -> dict:
                    return {"data": [{"index": i, "embedding": [0.2] * 2048}
                                     for i in range(len(json["input"]))]}
            return _R()

    monkeypatch.setattr(embedder.httpx, "Client", _FakeClient)
    _set_api(monkeypatch, dimensions=0)
    vecs = embedder.embed_passages(["один"])
    assert "dimensions" not in captured["json"]
    assert len(vecs[0]) == 2048


def test_space_id_differs_by_dimensions(monkeypatch) -> None:
    """Одна модель с разными dimensions -> РАЗНЫЕ коллекции (нет смешения)."""
    _set_api(monkeypatch, dimensions=1024)
    id_1024 = embedder.embedding_space_id()
    _set_api(monkeypatch, dimensions=0)
    id_auto = embedder.embedding_space_id()
    assert id_1024 != id_auto
    assert "d1024" in id_1024


def test_api_available_independent_of_llm(monkeypatch) -> None:
    """Полная конфигурация embeddings.api работает при любом llm.*."""
    _set_api(monkeypatch)  # base_url + api_key заданы в embeddings.api
    assert embedder.api_available() is True

    # Частичная конфигурация (без своего api_key) -> наследование из llm
    _set_api(monkeypatch, api_key="")
    assert embedder.api_available() is True  # возьмёт llm.api_key


def test_expected_dim(monkeypatch) -> None:
    _set_api(monkeypatch, dimensions=1024)
    assert embedder.expected_dim() == 1024
    _set_api(monkeypatch, dimensions=0)
    assert embedder.expected_dim() is None


def test_ping_403_is_unhealthy(monkeypatch) -> None:
    """401/403 от /models = отказ авторизации -> НЕ healthy (фикс v2.7.1)."""
    s = load_settings().llm
    s.provider = "openai_compatible"
    s.api_key = "test-key"
    client = OpenAICompatible(s)
    for code, expected in [(200, True), (201, True), (404, True),
                           (401, False), (403, False), (500, False), (503, False)]:
        monkeypatch.setattr(ollama_client.httpx, "get",
                            lambda *a, **kw: _FakeResponse(code))
        assert client.ping() is expected, f"status {code} -> {expected}"
