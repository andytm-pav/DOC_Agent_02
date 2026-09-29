"""ValidatorAgent: обёртка groundrails (CPU, без LLM) + вычисление confidence."""
from __future__ import annotations

from doc_agent.config import load_settings
from doc_agent.services.groundrails import validate_answer


class ValidatorAgent:
    name = "validator"

    def run(self, answer: str, fragments: list[dict]) -> dict:
        s = load_settings().groundrails
        if not s.enabled:
            return {"answer": answer, "cut_ratio": 0.0, "partial": False, "grounded": bool(fragments)}
        return validate_answer(answer, fragments, cut_ratio=s.cut_ratio)

    @staticmethod
    def confidence(fragments: list[dict], grounding_ratio: float | None = None) -> float:
        """v2.7: КАЛИБРОВАННАЯ уверенность [0..1]:

            w_retrieval * среднее TOP-K score ретрива
          + w_grounding * доля переживших grounding-валидацию утверждений

        История: до v2.6.1 — минимум из 5 score (один слабый фрагмент давал
        «уверенность: 0»); в v2.6.1 — среднее TOP-K, но сырые score
        ретрива не откалиброваны (мусорная выдача давала 0.11, точные
        ответы по картотеке — 1.0 при том же качестве оснований).
        Смесь retrieval+grounding даёт осмысленную шкалу: полезный ответ
        по найденным файлам — выше ~0.5, «нашёл не то» — низкая.
        """
        s = load_settings().groundrails
        k = max(s.confidence_top_k, 1)
        scores = sorted(
            (f.get("score", 0.0) for f in fragments[:k]), reverse=True
        )
        if not scores:
            return 0.0
        retrieval_avg = max(0.0, min(1.0, sum(scores) / len(scores)))
        if grounding_ratio is None:
            return round(retrieval_avg, 2)
        w_r = s.confidence_retrieval_weight
        w_g = s.confidence_grounding_weight
        total = w_r + w_g
        if total <= 0:
            return round(retrieval_avg, 2)
        g = max(0.0, min(1.0, grounding_ratio))
        return round(max(0.0, min(1.0, (w_r * retrieval_avg + w_g * g) / total)), 2)
