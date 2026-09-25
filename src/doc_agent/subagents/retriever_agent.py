"""Retriever subagent with hybrid search."""

import structlog
from rank_bm25 import BM25Okapi

from doc_agent.config import get_settings
from doc_agent.db.session import get_session
from doc_agent.db.models import Chunk, File
from doc_agent.vector.embedder import embed_query
from doc_agent.vector.chroma_client import query_chunks

logger = structlog.get_logger()


class RetrieverAgent:
    """Hybrid retrieval using BM25 + ChromaDB + reranker."""

    async def run(self, question: str, limit: int = 20) -> dict:
        """Retrieve relevant chunks for a question."""
        settings = get_settings()

        with get_session() as session:
            # Get all chunks
            all_chunks = session.query(Chunk).all()
            if not all_chunks:
                return {"fragments": [], "files": [], "confidence": 0.0}

            # BM25 search
            corpus = [c.text for c in all_chunks]
            tokenized = [doc.split() for doc in corpus]
            bm25 = BM25Okapi(tokenized)
            scores = bm25.get_scores(question.split())

            # Get top candidates by BM25
            top_bm25_idx = scores.argsort()[-20:][::-1]
            bm25_candidates = {all_chunks[i].id: scores[i] for i in top_bm25_idx}

            # ChromaDB search
            query_emb = embed_query(question)
            chroma_results = query_chunks(query_emb, n_results=20)

            # Combine with RRF (Reciprocal Rank Fusion)
            combined_scores: dict[int, float] = {}
            k = 60  # RRF constant

            for rank, chunk_id in enumerate(bm25_candidates.keys()):
                combined_scores[chunk_id] = combined_scores.get(chunk_id, 0) + 1.0 / (k + rank + 1)

            if chroma_results["ids"] and chroma_results["ids"][0]:
                for rank, meta in enumerate(chroma_results.get("metadatas", [{}])[0] if chroma_results.get("metadatas") else []):
                    chunk_id = meta.get("chunk_db_id")
                    if chunk_id:
                        combined_scores[chunk_id] = combined_scores.get(chunk_id, 0) + 1.0 / (k + rank + 1)

            # Sort by combined score
            sorted_ids = sorted(combined_scores.keys(), key=lambda x: combined_scores[x], reverse=True)[:limit]

            # Fetch actual chunks
            fragments = []
            file_ids = set()
            for chunk_id in sorted_ids:
                chunk = session.query(Chunk).filter(Chunk.id == chunk_id).first()
                if chunk:
                    fragments.append({
                        "chunk_id": chunk.id,
                        "file_id": chunk.file_id,
                        "text": chunk.text,
                        "page": chunk.page,
                        "score": combined_scores[chunk_id],
                    })
                    file_ids.add(chunk.file_id)

            # Fetch file info
            files = []
            for fid in file_ids:
                f = session.query(File).filter(File.id == fid).first()
                if f:
                    files.append({
                        "id": f.id,
                        "original_name": f.original_name,
                        "doc_type": f.doc_type,
                    })

            confidence = max(combined_scores.values()) if combined_scores else 0.0

            return {
                "fragments": fragments,
                "files": files,
                "confidence": min(confidence, 1.0),
            }
