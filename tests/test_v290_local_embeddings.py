"""v2.9: локальные эмбеддинги (sentence_transformers) настраиваются из конфига.

Проверяем: batch_size/device передаются в модель, e5-префиксы применяются
и отключаются из конфига, expected_dim честен (override / фактическая /
None до загрузки), space_id различает размерности, понятная ошибка без
пакета sentence-transformers.
"""
from __future__ import annotations

import sys
from typing import Any

import pytest

from doc_agent.config import load_settings
from doc_agent.vector import embedder


class _FakeST:
    """Фейковый SentenceTransformer: запоминает вызовы encode()."""

    calls: list[dict] = []
    init_args: dict = {}  # v3.0.3: аннотация класса (mypy attr-defined)
    dim = 384

    def __init__(self, model: str, device: Any = None) -> None:
        _FakeST.init_args = {"model": model, "device": device}

    def encode(self, texts: list[str], batch_size: int = 32,
               normalize_embeddings: bool = False, **kw: Any) -> list[list[float]]:
        _FakeST.calls.append({"texts": list(texts), "batch_size": batch_size,
                              "normalize": normalize_embeddings})
        return [[0.1] * _FakeST.dim for _ in texts]

    def get_sentence_embedding_dimension(self) -> int:
        return _FakeST.dim


class _FakeSTModule:
    """Фейковый модуль sentence_transformers для подмены в sys.modules."""

    SentenceTransformer = _FakeST


def _set_local(monkeypatch, model: str = "intfloat/multilingual-e5-small",
               batch_size: int = 32, device: str = "", dimensions: int = 0,
               query_prefix: str = "query: ",
               passage_prefix: str = "passage: ") -> None:
    """backend: sentence_transformers + параметры через monkeypatch."""

    def fake_load() -> Any:
        s = load_settings()
        s.embeddings.backend = "sentence_transformers"
        s.embeddings.model = model
        s.embeddings.batch_size = batch_size
        s.embeddings.device = device
        s.embeddings.dimensions = dimensions
        s.embeddings.query_prefix = query_prefix
        s.embeddings.passage_prefix = passage_prefix
        return s

    monkeypatch.setattr(embedder, "load_settings", fake_load)


@pytest.fixture(autouse=True)
def _reset_model_cache() -> None:
    embedder._st_model = None
    _FakeST.calls = []


def test_local_embed_passes_batch_and_device(monkeypatch) -> None:
    """batch_size и device из конфига доходят до модели (v2.9: раньше
    batch_size игнорировался)."""
    _set_local(monkeypatch, batch_size=64, device="cpu")
    monkeypatch.setitem(sys.modules, "sentence_transformers", _FakeSTModule)
    embedder.embed_passages(["текст один", "текст два"])
    assert _FakeST.init_args == {"model": "intfloat/multilingual-e5-small",
                                 "device": "cpu"}
    assert _FakeST.calls[0]["batch_size"] == 64


def test_e5_prefixes_applied(monkeypatch) -> None:
    """E5-префиксы: query:/passage: добавляются по типу запроса."""
    _set_local(monkeypatch)
    monkeypatch.setitem(sys.modules, "sentence_transformers", _FakeSTModule)
    embedder.embed_passages(["фрагмент сметы"])
    embedder.embed_query("какой материал по вилоновской?")
    assert _FakeST.calls[0]["texts"] == ["passage: фрагмент сметы"]
    assert _FakeST.calls[1]["texts"] == ["query: какой материал по вилоновской?"]


def test_prefixes_disabled_for_non_e5(monkeypatch) -> None:
    """Пустые префиксы в конфиге (bge-m3 и др.) — текст без добавок."""
    _set_local(monkeypatch, query_prefix="", passage_prefix="")
    monkeypatch.setitem(sys.modules, "sentence_transformers", _FakeSTModule)
    embedder.embed_passages(["строка ведомости"])
    assert _FakeST.calls[0]["texts"] == ["строка ведомости"]


def test_model_cached_across_calls(monkeypatch) -> None:
    """Модель создаётся ОДИН раз (кэш _st_model), encode вызывается на каждый."""
    _set_local(monkeypatch)
    monkeypatch.setitem(sys.modules, "sentence_transformers", _FakeSTModule)
    embedder.embed_passages(["a"])
    embedder.embed_query("b")
    embedder.embed_passages(["c"])
    assert len(_FakeST.calls) == 3


def test_friendly_error_without_package(monkeypatch) -> None:
    """Без sentence-transformers — понятная ошибка с инструкцией, а не
    голый ModuleNotFoundError."""
    _set_local(monkeypatch)

    import builtins

    real_import = builtins.__import__  # v3.0.3: иначе _raise зовёт сам себя

    def _raise(name: str, *a: Any, **kw: Any) -> Any:
        if name == "sentence_transformers":
            raise ImportError(name)
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", _raise)
    with pytest.raises(RuntimeError, match=r'\.\[ml\]'):
        embedder.embed_passages(["текст"])


def test_expected_dim_local(monkeypatch) -> None:
    """dim локальной модели: override из конфига > фактическая > None."""
    _set_local(monkeypatch, dimensions=0)
    assert embedder.expected_dim() is None  # до загрузки модели неизвестна
    monkeypatch.setattr(embedder, "_st_model", _FakeST("fake-model"))
    assert embedder.expected_dim() == 384  # фактическая у загруженной
    _set_local(monkeypatch, dimensions=1024)
    assert embedder.expected_dim() == 1024  # override сильнее


def test_expected_dim_hashing_unchanged(monkeypatch) -> None:
    """hashing — по-прежнему 384 (ТЗ 5.2)."""

    def fake_load() -> Any:
        s = load_settings()
        s.embeddings.backend = "hashing"
        return s

    monkeypatch.setattr(embedder, "load_settings", fake_load)
    assert embedder.expected_dim() == 384


def test_space_id_differs_by_local_dimensions(monkeypatch) -> None:
    """Смена dimensions локальной модели -> ДРУГАЯ коллекция (нет смешения
    векторов разной размерности)."""
    _set_local(monkeypatch, dimensions=0)
    id_auto = embedder.embedding_space_id()
    _set_local(monkeypatch, dimensions=1024)
    id_1024 = embedder.embedding_space_id()
    assert id_auto != id_1024
    assert "d1024" in id_1024
    assert id_1024.startswith("sentence_transformers-")


def test_resolve_backend_respects_explicit_choice(monkeypatch) -> None:
    """Явный backend: sentence_transformers НЕ подменяется на api/hashing
    (auto — единственный режим автоподбора)."""
    _set_local(monkeypatch)
    assert embedder.resolve_backend() == "sentence_transformers"
