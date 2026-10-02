"""Эмбеддинги и лексические токены.

- hashing                — офлайн, без загрузок из интернета, детерминированный
                           feature-hashing 384 dims. ЭТО НЕ смысловая модель:
                           похожесть только лексическая.
- api                    — НАСТОЯЩИЕ эмбеддинги через OpenAI-совместимый
                           /embeddings ТОГО ЖЕ провайдера, что и llm
                           (base_url/api_key наследуются из секции llm,
                           если не заданы в embeddings.api) — v2.6.
- sentence_transformers  — ЛОКАЛЬНАЯ модель из embeddings.model без ключа
                           и интернета (extras [ml]): дефолт
                           intfloat/multilingual-e5-small (384 dims,
                           CPU-скорость ~6 чанков/с на 2 старых ядра,
                           на офисном ПК заметно быстрее); device,
                           dimensions, query/passage-префиксы — в конфиге
                           (v2.9).
- auto (v2.7)            — api, если доступен ключ/base_url (llm.* или
                           embeddings.api.*), иначе hashing. Промышленный
                           дефолт: настоящая семантика там, где она возможна.

v2.7: lexical_tokens() — токены + Snowball-стемминг (embeddings.stem_lexical)
для ВСЕХ лексических механизмов: BM25, реранкер, hashing-эмбеддинги,
grounding. Русская флексия («вилоновской»/«Вилоновская») больше не ломает
совпадение. Для api/sentence_transformers стемминг НЕ применяется — модели
понимают морфологию сами.

Размерность: hashing — 384 (ТЗ 5.2); api — embeddings.api.dimensions или
как ответит провайдер; sentence_transformers — embeddings.dimensions,
а если 0 — фактическая размерность загруженной модели. ВАЖНО: смена
backend меняет размерность/пространство векторов — при
vector.auto_collection_suffix: true коллекция подбирается сама
(суффикс backend-модели), иначе смените vector.collection и
переиндексируйте.
"""
from __future__ import annotations

import hashlib
import math
import re
import time
from typing import Any

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
    """Доступна ли конфигурация api-эмбеддингов (ключ + базовый URL).

    v2.7.1: если embeddings.api.base_url И api_key заданы ПОЛНОСТЬЮ,
    api-эмбеддинги работают НЕЗАВИСИМО от llm.* (гибрид: LLM у одного
    провайдера, эмбеддинги у другого). Иначе — наследование из llm
    (требует llm.provider: openai_compatible), как в v2.6-v2.7.
    """
    s = load_settings()
    cfg = s.embeddings.api
    if cfg.base_url and cfg.api_key:
        return True  # эмбеддинги сконфигурированы независимо от llm
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


def _local_embed(texts: list[str], is_query: bool) -> list[list[float]]:
    """Локальная модель sentence_transformers (v2.9).

    embeddings.model — любой каталог HF (e5-small, bge-m3, ...); первый
    запуск качает модель с huggingface.co (медленная сеть — переменная
    окружения HF_ENDPOINT=https://hf-mirror.com), далее офлайн.
    device/batch_size/query_prefix/passage_prefix — из config.yaml.
    E5-модели без префиксов "query: "/"passage: " теряют качество —
    для других моделей префиксы отключаются пустой строкой в конфиге.
    """
    global _st_model
    s = load_settings().embeddings
    prefix = (s.query_prefix if is_query else s.passage_prefix) or ""
    if _st_model is None:
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore[import-untyped]
        except ImportError as exc:
            raise RuntimeError(
                "Локальные эмбеддинги (backend: sentence_transformers): "
                "пакет sentence-transformers не установлен. Выполните "
                'pip install -e ".[ml]" (тянет torch, ~2 ГБ) — либо '
                "используйте backend: api (по ключу) или hashing (офлайн, "
                "без семантики)."
            ) from exc
        _st_model = SentenceTransformer(
            s.model, device=s.device or None
        )
    encoded = _st_model.encode(
        [prefix + t for t in texts], batch_size=max(s.batch_size, 1),
        normalize_embeddings=True,
    )
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
    # v2.7.1: кастомная размерность (Zhipu embedding-3: 256/512/1024/2048;
    # OpenAI text-embedding-3-*: 512/1536...). 0 = не передавать (дефолт
    # провайдера, например 2048 у embedding-3).
    payload_extra: dict[str, Any] = {"dimensions": cfg.dimensions} if cfg.dimensions > 0 else {}
    out: list[list[float]] = []
    batch = max(s.batch_size, 1)
    attempts = max(cfg.rate_limit_retries, 0) + 1
    from doc_agent.llm.ollama_client import _api_error, _retry_after_sec

    with httpx.Client(timeout=cfg.timeout_sec) as client:
        for i in range(0, len(texts), batch):
            last_wait = 0.0
            last_err: RuntimeError | None = None
            for attempt in range(attempts):
                if attempt and last_wait > 0:
                    time.sleep(min(last_wait, 30.0))
                r = client.post(url, json={"model": cfg.model,
                                           "input": texts[i:i + batch], **payload_extra},
                                headers=headers)
                if r.status_code < 400:
                    break
                # v2.8: тело ошибки в исключении — голый «400 Bad Request»
                # не позволял понять причину (у api.z.ai /embeddings маршрут
                # есть, но модели эмбеддингов нет — причина только в теле).
                err = _api_error(r.status_code, url, (r.text or "").strip()[:300])
                if r.status_code == 429 or r.status_code >= 500:
                    last_err = err
                    ra = _retry_after_sec(r.headers.get("retry-after"))
                    last_wait = ra if ra is not None else \
                        cfg.rate_limit_backoff_sec * (2 ** attempt)
                    if attempt < attempts - 1:
                        continue
                raise err
            else:
                raise last_err or RuntimeError(f"API: нет ответа эмбеддингов для {url}")
            data = list(r.json()["data"])
            data.sort(key=lambda d: int(d.get("index", 0)))
            out.extend([list(map(float, d["embedding"])) for d in data])
    return out


def expected_dim() -> int | None:
    """Ожидаемая размерность векторов текущего backend (v2.7.1, v2.9).

    hashing — 384 (алгоритм определён в коде); api — из
    embeddings.api.dimensions, а если не задана (0 = дефолт провайдера) —
    None (станет известна только из ответа API); sentence_transformers —
    из embeddings.dimensions, если переопределена, иначе из загруженной
    модели, а до первой загрузки — None (нечестно обещать 384 для любой
    локальной модели: у bge-m3, например, 1024).
    """
    backend = resolve_backend()
    if backend == "api":
        d = load_settings().embeddings.api.dimensions
        return d if d > 0 else None
    if backend == "sentence_transformers":
        d = load_settings().embeddings.dimensions
        if d > 0:
            return d
        if _st_model is not None:
            # v2.9: в ST 6.x метод переименован (get_embedding_dimension),
            # в 3.x — get_sentence_embedding_dimension; пробуем оба.
            get_dim = (getattr(_st_model, "get_embedding_dimension", None)
                       or getattr(_st_model, "get_sentence_embedding_dimension", None))
            return int(get_dim()) if get_dim else None
        return None
    return DIM


def embed_passages(texts: list[str]) -> list[list[float]]:
    backend = resolve_backend()
    if backend == "sentence_transformers":
        return _local_embed(texts, is_query=False)
    if backend == "api":
        return _api_embed(texts)
    return [_hashing_embed(t) for t in texts]


def embed_query(text: str) -> list[float]:
    backend = resolve_backend()
    if backend == "sentence_transformers":
        return _local_embed([text], is_query=True)[0]
    if backend == "api":
        return _api_embed([text])[0]
    return _hashing_embed(text)


def embedding_space_id() -> str:
    """Идентификатор векторного пространства (backend+модель) — суффикс
    коллекции Chroma (vector.auto_collection_suffix), v2.7.

    v2.7.1: для api в идентификатор входит и размерность (embeddings.api.
    dimensions): одна и та же модель с разными dimensions даёт НЕсовместимые
    векторы — коллекции должны различаться (иначе смешение векторов разных
    размерностей в одной коллекции Chroma).
    v2.9: то же для локальной модели (embeddings.dimensions) — смена
    переопределённой размерности тоже создаёт новую коллекцию.
    """
    backend = resolve_backend()
    dims_suffix = ""
    if backend == "hashing":
        model = "hashing-384"
    elif backend == "api":
        cfg = load_settings().embeddings.api
        model = cfg.model
        dims_suffix = f"-d{cfg.dimensions}" if cfg.dimensions > 0 else ""
    else:
        s = load_settings().embeddings
        model = s.model
        dims_suffix = f"-d{s.dimensions}" if s.dimensions > 0 else ""
    # v2.9: маркер размерности ставится ПОСЛЕ обрезки имени модели: длинные
    # HF-имена (intfloat/multilingual-e5-small = 25+ символов) раньше съедали
    # "-d1024" целиком. Хэш считается по model+dims — имена коллекций api
    # (короткие модели) совпадают с v2.7.1-v2.8.1.
    h = hashlib.md5((model + dims_suffix).encode("utf-8")).hexdigest()[:6]
    safe_model = re.sub(r"[^a-zA-Z0-9-]", "-", model)[:24].strip("-") or "m"
    return f"{backend}-{safe_model}{dims_suffix}-{h}"
