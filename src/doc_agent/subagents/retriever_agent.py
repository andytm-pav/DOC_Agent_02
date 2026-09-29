"""RetrieverAgent: гибридный поиск (8.2), v2.7 — промышленные практики.

    SQL-фильтры -> BM25 + ChromaDB -> порог отсева вектора -> RRF-слияние
    (с весами и filename-бустом) -> реранкер -> top-K.

Исправления v2.7 (кейс «агент не видит и галлюцинирует»):
  - БЫЛО: молчаливый LIMIT 4000 БЕЗ ORDER BY — BM25 считался по
    произвольному подмножеству чанков, файлы, добавленные позже, не
    участвовали в поиске вообще. СТАЛО: все чанки кандидатов потоком
    (yield_per, защита retrieval.max_chunks).
  - Морфология: BM25/реранкер работают по стеммам (lexical_tokens) —
    «вилоновской» находит «Вилоновская», «материалов» — «материал».
  - Отсев мусора: векторные хиты слабее retrieval.vector_relative_cutoff
    от лучшего score выкидываются ДО слияния (раньше Chroma отдавала
    top-N с похожестью 0.05-0.11, и этот шум шёл в промпт LLM).
  - filename-boost: файлы, чьё ИМЯ содержит термы запроса, получают
    буст RRF-score (retrieval.filename_boost) — общий контекстуальный
    сигнал, без привязок к конкретным фразам.
  - Реранкер: фрагменты с нулевым лексическим перекрытием выбрасываются,
    если есть хоть один с перекрытием (retrieval.rerank_drop_zero_overlap).
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from doc_agent.config import load_settings
from doc_agent.db.models import Chunk, File
from doc_agent.logging import get_logger
from doc_agent.vector.chroma_client import get_vector_store
from doc_agent.vector.embedder import embed_query, lexical_tokens, tokenize
from doc_agent.vector.stemmer import compat_hits, stem_token, stems_compatible

log = get_logger("subagent.retriever")

STOPWORDS = {"и", "в", "на", "по", "с", "для", "как", "что", "это", "все", "покажи", "дай",
             "найди", "the", "a", "of", "или", "к", "у", "за", "из", "от", "до",
             "какой", "какая", "какие", "где", "чего", "чем", "нужно", "нужны",
             "есть", "быть", "мне", "меня", "моя", "мой", "сегодня", "еще", "уже"}


def _query_terms(query: str) -> list[str]:
    """Термы запроса для BM25/реранкера: стоп-слова режутся по СЫРЫМ
    токенам, морфология применяется к остатку («какая» -> сырой токен
    в стоп-листе; «вилоновской» -> «вилоновск»)."""
    raw = [t for t in tokenize(query) if t not in STOPWORDS]
    if load_settings().embeddings.stem_lexical:
        return [stem_token(t) for t in raw]
    return raw


def _rrf(rankings: list[tuple[list[str], float]], k: int = 60) -> dict[str, float]:
    """RRF-слияние ранжированных списков с весами (практика Elastic/Qdrant)."""
    scores: dict[str, float] = {}
    for ranking, weight in rankings:
        for pos, key in enumerate(ranking):
            scores[key] = scores.get(key, 0.0) + weight / (k + pos + 1)
    return scores


def _expand_terms(q_terms: list[str], vocab: set[str]) -> list[str]:
    """Расширение термов запроса по словарю корпуса (v2.7).

    Snowball RU без словаря иногда пережимает отдельные формы («материал»
    -> «материа», а «материалов» -> «материал»). Промышленная компенсация —
    префиксная совместимость: к запросу добавляются стеммы корпуса,
    совместимые с термом запроса. BM25 при этом матчит точными строками.
    """
    if not q_terms or not vocab:
        return list(q_terms)
    out = list(q_terms)
    seen = set(q_terms)
    for q in q_terms:
        for v in vocab:
            if v not in seen and stems_compatible(q, v):
                out.append(v)
                seen.add(v)
    return out


class RetrieverAgent:
    name = "retriever"

    def sql_candidates(self, db: Session, filters: dict, limit: int = 500) -> list[File]:
        stmt = select(File).where(File.status.in_(["done", "description_only"]))
        if filters.get("doc_type"):
            stmt = stmt.where(File.doc_type == filters["doc_type"])
        if filters.get("contract_no"):
            stmt = stmt.where(File.contract_no == filters["contract_no"])
        if filters.get("city"):
            stmt = stmt.where(File.city == filters["city"])
        if filters.get("date_from"):
            stmt = stmt.where(File.doc_date >= filters["date_from"])
        if filters.get("date_to"):
            stmt = stmt.where(File.doc_date <= filters["date_to"])
        stmt = stmt.order_by(File.id).limit(limit)
        return list(db.execute(stmt).scalars().all())

    def bm25_top(self, chunks: list[Chunk], query: str, n: int) -> list[tuple[int, float]]:
        corpus_tokens = [lexical_tokens(c.text) for c in chunks]
        q_terms = _query_terms(query)
        if not corpus_tokens or not q_terms:
            return []
        # v2.7: расширение термов по словарю корпуса (префиксная
        # совместимость стеммов — см. _expand_terms)
        vocab: set[str] = set()
        for toks in corpus_tokens:
            vocab.update(toks)
        q_tokens = _expand_terms(q_terms, vocab)
        try:
            from rank_bm25 import BM25Okapi

            bm25 = BM25Okapi(corpus_tokens)
        except Exception as exc:  # noqa: BLE001
            log.warning("bm25_failed", error=str(exc))
            return []
        scores = bm25.get_scores(q_tokens)
        ranked = sorted(zip([c.id for c in chunks], scores), key=lambda x: x[1], reverse=True)
        max_s = max((s for _, s in ranked), default=1.0) or 1.0
        return [(cid, float(s) / max_s) for cid, s in ranked[:n] if s > 0]

    def vector_top(self, chunks: list[Chunk], query: str, n: int) -> list[tuple[int, float]]:
        """Векторные хиты с отсевом слабых (retrieval.vector_relative_cutoff)."""
        file_ids = sorted({c.file_id for c in chunks})
        if not file_ids:
            return []
        try:
            store = get_vector_store()
            emb = embed_query(query)
            hits = store.query(emb, n=n, file_ids=file_ids)
            out = []
            chunk_index_to_id = {(c.file_id, c.chunk_index): c.id for c in chunks}
            for h in hits:
                cid = chunk_index_to_id.get((h["file_id"], h["chunk_index"]))
                if cid is not None:
                    out.append((cid, float(h["score"])))
            # v2.7: relative cutoff — хиты слабее доли от лучшего score
            # (0.55 по умолчанию) не участвуют в слиянии. У косинуса
            # настоящий релевант существенно выше случайного перекрытия
            # служебных слов; хвост top-N без порога и был источником шума.
            cutoff = load_settings().retrieval.vector_relative_cutoff
            if out and cutoff > 0:
                best = max(s for _, s in out)
                if best > 0:
                    out = [(cid, s) for cid, s in out if s >= best * cutoff]
            return out
        except Exception as exc:  # noqa: BLE001
            log.warning("vector_failed_fallback_bm25", error=str(exc))
            return []

    def _name_matched_files(self, query: str, candidates: list[File]) -> set[int]:
        """Файлы, чьё имя содержит термы запроса (по стеммам) — для буста."""
        q_terms = [t for t in _query_terms(query) if len(t) >= 3]
        if not q_terms:
            return set()
        matched: set[int] = set()
        for f in candidates:
            name_stems = set(lexical_tokens(f.original_name))
            if any(t in name_stems or any(stems_compatible(t, s) for s in name_stems)
                   for t in q_terms):
                matched.add(f.id)
        return matched

    def rerank(self, query: str, fragments: list[dict], top_k: int | None = None) -> list[dict]:
        """Реранкер: cross_encoder (extras [ml]) или лексический офлайн."""
        s = load_settings().reranker
        k = top_k or s.top_k
        if not fragments:
            return []
        if s.backend == "cross_encoder":
            try:
                from sentence_transformers import CrossEncoder  # type: ignore[import-untyped]

                model = CrossEncoder(s.model)
                pairs = [(query, f["text"][:1500]) for f in fragments]
                scores = model.predict(pairs)
                for f, sc in zip(fragments, scores):
                    f["score"] = float(sc)
                fragments.sort(key=lambda x: x["score"], reverse=True)
                return fragments[:k]
            except Exception as exc:  # noqa: BLE001
                log.warning("cross_encoder_unavailable", error=str(exc))
        q_tokens = _query_terms(query)
        for f in fragments:
            f_tokens = set(lexical_tokens(f["text"]))
            # v2.7: перекрытие с префиксной совместимостью стеммов —
            # «материал» терма матчит «материалов» фрагмента
            f["score"] = compat_hits(q_tokens, f_tokens) / max(len(q_tokens), 1)
        fragments.sort(key=lambda x: x["score"], reverse=True)
        # v2.7: нулевое перекрытие = фрагмент не про вопрос. Если есть хоть
        # один содержательный — хвост из нулей в промпт не идёт (раньше
        # именно он давал LLM «повод» галлюцинировать по чужим файлам).
        if load_settings().retrieval.rerank_drop_zero_overlap:
            positive = [f for f in fragments if f["score"] > 0]
            if positive:
                return positive[:k]
        return fragments[:k]

    def run(self, db: Session, query: str, filters: dict, limit: int = 20) -> tuple[list[dict], list[File]]:
        """Возвращает (фрагменты top-K, файлы-кандидаты)."""
        s = load_settings().retrieval
        candidates = self.sql_candidates(db, filters)
        if not candidates:
            return [], []
        cand_ids = [f.id for f in candidates]
        # v2.7: ВЕСЬ корпус кандидатов в детерминированном порядке (было
        # LIMIT 4000 без ORDER BY — чанки поздних файлов выпадали из поиска).
        chunks: list[Chunk] = []
        rows = db.execute(
            select(Chunk)
            .where(Chunk.file_id.in_(cand_ids))
            .order_by(Chunk.file_id, Chunk.chunk_index)
        ).scalars().yield_per(2000)
        for row in rows:
            chunks.append(row)
            if len(chunks) >= s.max_chunks:
                log.warning("retrieval_chunks_capped", cap=s.max_chunks)
                break
        chunk_by_id = {c.id: c for c in chunks}
        log.info("retrieval_corpus", files=len(cand_ids), chunks=len(chunks))

        bm25_hits = self.bm25_top(chunks, query, limit)
        vec_hits = self.vector_top(chunks, query, limit)

        bm25_rank = [str(cid) for cid, _ in bm25_hits]
        vec_rank = [str(cid) for cid, _ in vec_hits]
        rankings = [(r, w) for r, w in ((bm25_rank, s.bm25_weight), (vec_rank, s.vector_weight)) if r]
        fused = _rrf(rankings)
        fused_scores = {int(k): v for k, v in fused.items() if int(k) in chunk_by_id}

        # filename-boost: имя файла совпало с термами запроса -> буст всем
        # его чанкам (общий сигнал, LLM-first совместим: это ранжирование,
        # а не выбор механизма).
        boosted_files = self._name_matched_files(query, candidates) if s.filename_boost > 0 else set()
        if boosted_files:
            file_by_chunk = {c.id: c.file_id for c in chunks}
            for cid, sc in list(fused_scores.items()):
                if file_by_chunk.get(cid) in boosted_files:
                    fused_scores[cid] = sc * (1.0 + s.filename_boost)
            log.info("filename_boost_applied", files=sorted(boosted_files))

        ordered_ids = sorted(fused_scores, key=lambda cid: fused_scores[cid], reverse=True)[: limit * 3]
        raw_score = dict(bm25_hits) | dict(vec_hits)
        fragments: list[dict] = []
        file_map = {f.id: f for f in candidates}
        for cid in ordered_ids:
            chunk = chunk_by_id[cid]
            fragments.append({
                "chunk_id": chunk.id,
                "file_id": chunk.file_id,
                "file_name": file_map[chunk.file_id].original_name,
                "doc_type": file_map[chunk.file_id].doc_type or "other",
                "page": chunk.page,
                "text": chunk.text,
                "score": float(raw_score.get(cid, 0.0)),
            })
        top = self.rerank(query, fragments)
        return top, candidates

    def run_metadata(self, db: Session, filters: dict) -> list[File]:
        return self.sql_candidates(db, filters)
