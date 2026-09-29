"""Оркестратор: координирует конвейер обработки файла (ингест → классификация → индексация).

Фактические шаги реализованы в services/ingest.py; оркестратор даёт единый фасад
и уровни деградации (E003, E004).
"""
from __future__ import annotations

from doc_agent.logging import get_logger
from doc_agent.services import ingest
from doc_agent.subagents.classifier_agent import ClassifierAgent
from doc_agent.subagents.extractor_agent import ExtractorAgent
from doc_agent.subagents.reconstructor_agent import ReconstructorAgent
from doc_agent.subagents.reporter_agent import ReporterAgent
from doc_agent.subagents.retriever_agent import RetrieverAgent
from doc_agent.subagents.validator_agent import ValidatorAgent

log = get_logger("orchestrator")


class Orchestrator:
    def __init__(self) -> None:
        self.extractor = ExtractorAgent()
        self.classifier = ClassifierAgent()
        self.retriever = RetrieverAgent()
        self.reporter = ReporterAgent()
        self.validator = ValidatorAgent()
        self.reconstructor = ReconstructorAgent()

    def process_file(self, file_id: int) -> None:
        ingest.process_file(file_id)

    def query(self, question: str, limit: int = 20) -> dict:
        from doc_agent.services import query as query_service

        return query_service.run_query(question, limit=limit)


orchestrator = Orchestrator()
