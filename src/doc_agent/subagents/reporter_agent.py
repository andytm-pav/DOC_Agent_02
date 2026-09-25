"""Reporter subagent that generates answers."""

from pathlib import Path

import structlog

from doc_agent.llm.ollama_client import generate

logger = structlog.get_logger()


class ReporterAgent:
    """Generates answers using LLM with grounding."""

    def __init__(self) -> None:
        prompt_path = Path("config/prompts/reporter.txt")
        self.prompt_template = prompt_path.read_text(encoding="utf-8")

    async def run(self, question: str, fragments: list[dict]) -> str:
        """Generate an answer to a question."""
        if not fragments:
            return "НЕТ ДАННЫХ"

        fragments_text = "\n---\n".join(
            f"[file_id:{f['file_id']}] {f['text']}" for f in fragments
        )

        prompt = self.prompt_template.replace("{question}", question)
        prompt = prompt.replace("{fragments}", fragments_text)

        try:
            response = await generate(prompt, model_type="main")
            return response.strip()
        except Exception as e:
            logger.error("Reporter failed", error=str(e))
            return "НЕТ ДАННЫХ"
