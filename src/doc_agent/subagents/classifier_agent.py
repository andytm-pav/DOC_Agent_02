"""Classifier subagent using LLM."""

import json
from pathlib import Path

import structlog

from doc_agent.llm.ollama_client import generate

logger = structlog.get_logger()


class ClassifierAgent:
    """Classifies documents using LLM."""

    def __init__(self) -> None:
        prompt_path = Path("config/prompts/classifier.txt")
        self.prompt_template = prompt_path.read_text(encoding="utf-8")

    async def run(self, text: str) -> dict:
        """Classify a document."""
        prompt = self.prompt_template.replace("{text}", text[:4000])

        try:
            response = await generate(prompt, model_type="light")
            # Parse JSON response
            result = json.loads(response)
            return result
        except json.JSONDecodeError:
            logger.error("Classifier returned invalid JSON", response=response[:200])
            return {
                "doc_type": "other",
                "city": None,
                "customer": None,
                "contract_no": None,
                "contract_date": None,
                "doc_number": None,
                "doc_date": None,
                "amount": None,
                "confidence": 0.0,
            }
        except Exception as e:
            logger.error("Classifier failed", error=str(e))
            return {
                "doc_type": "other",
                "confidence": 0.0,
            }
