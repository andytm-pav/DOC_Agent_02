"""Orchestrator that coordinates subagents."""

import structlog

from doc_agent.subagents.classifier_agent import ClassifierAgent
from doc_agent.subagents.extractor_agent import ExtractorAgent
from doc_agent.subagents.retriever_agent import RetrieverAgent
from doc_agent.subagents.reporter_agent import ReporterAgent
from doc_agent.subagents.reconstructor_agent import ReconstructorAgent
from doc_agent.subagents.validator_agent import ValidatorAgent

logger = structlog.get_logger()


class Orchestrator:
    """Coordinates subagent execution."""

    def __init__(self) -> None:
        self.classifier = ClassifierAgent()
        self.extractor = ExtractorAgent()
        self.retriever = RetrieverAgent()
        self.reporter = ReporterAgent()
        self.reconstructor = ReconstructorAgent()
        self.validator = ValidatorAgent()

    async def ingest(self, file_id: int, file_path: str, format: str) -> dict:
        """Run the ingest pipeline."""
        # Extract
        extraction = await self.extractor.run(file_path=file_path, format=format)

        # Classify
        classification = await self.classifier.run(text=extraction["text"])

        return {
            "extraction": extraction,
            "classification": classification,
        }

    async def query(self, question: str, limit: int = 20) -> dict:
        """Run the query pipeline."""
        # Retrieve relevant chunks
        retrieval = await self.retriever.run(question=question, limit=limit)

        # Generate answer
        answer = await self.reporter.run(
            question=question,
            fragments=retrieval["fragments"],
        )

        # Validate
        validated = await self.validator.run(
            answer=answer,
            fragments=retrieval["fragments"],
        )

        return {
            "answer": validated["answer"],
            "files": retrieval["files"],
            "confidence": retrieval["confidence"],
            "grounded": validated["grounded"],
        }
