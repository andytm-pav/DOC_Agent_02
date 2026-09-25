"""Validator subagent using groundrails."""

import structlog

from doc_agent.config import get_settings

logger = structlog.get_logger()


class ValidatorAgent:
    """Validates answers against source fragments."""

    async def run(self, answer: str, fragments: list[dict]) -> dict:
        """Validate an answer against source fragments."""
        settings = get_settings()

        if not settings.groundrails_enabled:
            return {"answer": answer, "grounded": True}

        if answer.strip() == "НЕТ ДАННЫХ":
            return {"answer": answer, "grounded": True}

        # Simple grounding check: verify that key phrases from the answer
        # appear in at least one fragment
        fragments_text = " ".join(f["text"] for f in fragments)

        # Split answer into sentences
        sentences = [s.strip() for s in answer.split(".") if s.strip()]
        if not sentences:
            return {"answer": answer, "grounded": True}

        supported = 0
        for sentence in sentences:
            # Check if key words from the sentence appear in fragments
            words = sentence.split()
            key_words = [w for w in words if len(w) > 3]
            if not key_words:
                supported += 1
                continue

            matches = sum(1 for w in key_words if w.lower() in fragments_text.lower())
            if matches >= len(key_words) * 0.5:
                supported += 1

        ratio = supported / len(sentences) if sentences else 1.0

        if ratio < (1.0 - settings.groundrails_cut_ratio):
            logger.warning(
                "Grounding check failed",
                ratio=ratio,
                threshold=settings.groundrails_cut_ratio,
            )
            return {"answer": "НЕТ ДАННЫХ", "grounded": False}

        return {"answer": answer, "grounded": True}
