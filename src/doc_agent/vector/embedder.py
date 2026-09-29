"""Эмбеддинги и лексические токены.

- hashing                — офлайн, без загрузок из интернета, детерминированный
                           feature-hashing 384 dims. ЭТО НЕ смысловая модель:
                           похожесть только лексическая.
- api                    — НАСТОЯЩИЕ эмбеддинги через OpenAI-совместимый
                           /embeddings ТОГО ЖЕ провайдера, что и llm
                           (base_url/api_key наследуются из секции llm,
                           если не заданы в embeddings.api) — v2.6.
- sentence_transformers  — intfloat/multilingual-e5-small (extras [ml]).
- auto (v2.7)            — api, если доступен ключ/base_url (llm.* или
                           embeddings.api.*), иначе hashing. Промышленный
                           дефолт: настоящая семантика там, где она возможна.

v2.7: lexical_tokens() — токены + Snowball-стемминг (embeddings.stem_lexical)
для ВСЕХ лексических механизмов: BM25, реранкер, hashing-эмбеддинги,
grounding. Русская флексия («вилоновской»/«Вилоновская») больше не ломает
совпадение. Для api/sentence_transformers стемминг НЕ применяется — модели
понимают морфологию сами.

Размерность: hashing — 384 (ТЗ 5.2); api/sentence_transformers — как у
модели. ВАЖНО: смена backend меняет размерность/пространство векторов —
при vector.auto_collection_suffix: true коллекция подбирается сама
(суффикс backend-модели), иначе смените vector.collection и
переиндексируйте.
"""
from __future__ import annotations

import hashlib
import math
import re

import httpx

from doc_agent.config import load_settings

DIM = 384
_TOKEN_RE = re.compile(r"[\w]+", re.UNICODE)

_st_model = None


def tokenize(text: str) -> list[str]:
    """Сырые токены нижнего регистра (без морфологии) — для ссылок/имён."""
    return [t for t in _TOKEN_RE.findall(text.lower()) if len(t) <= 32]


def lexical_tokens(text: str) -> list[str]:
    """Токены для лексического поиска: tokenize + опциональный стемминг.

    Кэш стеммера делает повторные вызовы дешёвыми; конфиг
    embeddings.stem_lexical позволяет выключить морфологию.
    """
    tokens = tokenize(text)
    if load_settings().embeddings.stem_lexical:
        from doc_agent.vector.stemmer import stem_all

        return stem_all(tokens)
    return tokens


def api_available() -> bool:
    """Доступна ли конфигурация api-эмбеддингов (ключ + базовый URL)."""
    s = load_settings()
    cfg = s.embeddings.api
    llm_s = s.llm
    base = cfg.base_url or llm_s.base_url
    key = cfg.api_key or llm_s.api_key
    return bool(base and key and s.llm.provider == "openai_compatible")


def resolve_backend() -> str:
    """Фактический backend: auto -> api (если настроен) | hashing."""
    backend = load_settings().embeddings.backend
    if backend == "auto":
        return "api" if api_available() else "hashing"
    return backend


def _hash_bucket(token: str) -> tuple[int, int]:
    h = hashlib.md5(token.encode("utf-8")).digest()
    idx = int.from_bytes(h[:4], "little") % DIM
    sign = 1 if h[4] % 2 == 0 else -1
    return idx, sign


def _hashing_embed(text: str) -> list[float]:
    vec = [0.0] * DIM
    # v2.7: стеммированные токены (и у пассажа, и у запроса) — «вилоновской»
    # и «Вилоновская» дают одинаковый бакет.
    tokens = lexical_tokens(text)
    for tok in tokens:
        idx, sign = _hash_bucket(tok)
        vec[idx] += sign
    for a, b in zip(tokens, tokens[1:]):
        idx, sign = _hash_bucket(a + "_" + b)
        vec[idx] += 0.5 * sign
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _e5_embed(texts: list[str], is_query: bool) -> list[list[float]]:
    global _st_model
    prefix = "query: " if is_query else "passage: "
    if _st_model is None:
        from sentence_transformers import SentenceTransformer  # type: ignore[import-untyped]

        _st_model = SentenceTransformer(load_settings().embeddings.model)
    encoded = _st_model.encode([prefix + t for t in texts], normalize_embeddings=True)
    return [list(map(float, row)) for row in encoded]


def _api_embed(texts: list[str]) -> list[list[float]]:
    """OpenAI-совместимый POST {base_url}/embeddings (v2.6).

    base_url/api_key наследуются из секции llm (тот же провайдер и тот же
    ключ, что у основной модели), если в embeddings.api не переопределено.
    Батчи — embeddings.batch_size; порядок результатов восстанавливается
    по полю index ответа API.
    """
    s = load_settings().embeddings
    cfg = s.api
    llm_s = load_settings().llm
    base = (cfg.base_url or llm_s.base_url).rstrip("/")
    url = base + (cfg.api_path or "/embeddings")
    key = cfg.api_key or llm_s.api_key
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    out: list[list[float]] = []
    batch = max(s.batch_size, 1)
    with httpx.Client(timeout=cfg.timeout_sec) as client:
        for i in range(0, len(texts), batch):
            r = client.post(url, json={"model": cfg.model, "input": texts[i:i + batch]},
                            headers=headers)
            r.raise_for_status()
            data = list(r.json()["data"])
            data.sort(key=lambda d: int(d.get("index", 0)))
            out.extend([list(map(float, d["embedding"])) for d in data])
    return out


def embed_passages(texts: list[str]) -> list[list[float]]:
    backend = resolve_backend()
    if backend == "sentence_transformers":
        return _e5_embed(texts, is_query=False)
    if backend == "api":
        return _api_embed(texts)
    return [_hashing_embed(t) for t in texts]


def embed_query(text: str) -> list[float]:
    backend = resolve_backend()
    if backend == "sentence_transformers":
        return _e5_embed([text], is_query=True)[0]
    if backend == "api":
        return _api_embed([text])[0]
    return _hashing_embed(text)


def embedding_space_id() -> str:
    """Идентификатор векторного пространства (backend+модель) — суффикс
    коллекции Chroma (vector.auto_collection_suffix), v2.7."""
    backend = resolve_backend()
    if backend == "hashing":
        model = "hashing-384"
    elif backend == "api":
        model = load_settings().embeddings.api.model
    else:
        model = load_settings().embeddings.model
    h = hashlib.md5(model.encode("utf-8")).hexdigest()[:6]
    safe_model = re.sub(r"[^a-zA-Z0-9-]", "-", model)[:24].strip("-") or "m"
    return f"{backend}-{safe_model}-{h}"
