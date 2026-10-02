"""ReporterAgent: ответ по промпту reporter.txt; экстрактивный fallback без LLM.
Если фактов нет — ровно «НЕТ ДАННЫХ» (DD-5)."""
from __future__ import annotations

import re

from doc_agent.config import load_settings
from doc_agent.llm.ollama_client import get_llm
from doc_agent.llm.prompts import get_prompt
from doc_agent.logging import get_logger

log = get_logger("subagent.reporter")

NO_DATA = "НЕТ ДАННЫХ"


class ReporterAgent:
    name = "reporter"

    def run(
        self, question: str, fragments: list[dict],
        context: str | None = None, catalog: str = "",
        known_answers: str = "",
    ) -> str:
        """context — текст актуального контекста беседы (может быть пустым):
        учитывается, если вопрос ссылается на прошлые сообщения; факты
        по-прежнему только из фрагментов (DD-5). catalog — картотека файлов
        (services.intents.catalog_block): агент «знает», что загружено,
        но фактами из неё ответ не наполняет. known_answers (v3.0.0) —
        блок проверенных ответов из обратной связи (services.feedback):
        репортер использует его как эталон на похожем вопросе."""
        if not fragments:
            return NO_DATA
        settings = load_settings()
        if settings.llm.provider == "none":
            return self.extractive(fragments)
        frag_block = "\n\n".join(
            f"[file_id:{f['file_id']}] ({f['file_name']}, стр. {f.get('page') or 1}):\n{f['text'][:1200]}"
            for f in fragments[:5]
        )
        prompt = get_prompt(
            "reporter", question=question, fragments=frag_block,
            context=(context or "").strip(), catalog=(catalog or "").strip(),
            known_answers=(known_answers or "").strip(),
        )
        try:
            answer = get_llm().chat(prompt, model=settings.llm.model_main)
            return answer.strip() or NO_DATA
        except Exception as exc:  # noqa: BLE001
            log.warning("reporter_llm_failed_extractive", error=str(exc))
            return self.extractive(fragments)

    def extractive(self, fragments: list[dict]) -> str:
        """Офлайн-ответ: только подтверждённые цитаты с [file_id:N]."""
        lines = ["По найденным документам:"]
        for f in fragments[:5]:
            sentences = re.split(r"(?<=[.!?])\s+", f["text"].strip())
            cite = " ".join(sentences[:2]).strip()
            if len(cite) > 300:
                cite = cite[:297] + "…"
            if cite:
                lines.append(f"- {cite} [file_id:{f['file_id']}]")
        if len(lines) == 1:
            return NO_DATA
        return "\n".join(lines)
