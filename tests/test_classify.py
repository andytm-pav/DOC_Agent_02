"""test_classify.py: КС2-подобный текст -> doc_type=ks2 (13.2)."""
from __future__ import annotations

from pathlib import Path

from conftest import KS2_TEXT
from doc_agent.subagents.classifier_agent import ClassifierAgent


def test_ks2_text_classified() -> None:
    agent = ClassifierAgent()
    meta = agent.run(KS2_TEXT)
    assert meta["doc_type"] == "ks2"
    assert meta["contract_no"] == "123"
    assert meta["doc_date"] == "2024-03-12"
    assert meta["amount"] == 1234567.89


def test_llm_unavailable_falls_back_to_rules(client, tmp_data_dir: Path) -> None:
    """E004: LLM недоступен -> классификация по правилам, файл не падает."""
    agent = ClassifierAgent()
    meta = agent.run(KS2_TEXT)
    assert meta["doc_type"] == "ks2"
    assert 0.0 <= meta["confidence"] <= 1.0


def test_upload_classified_end_to_end(client, user_token: str, sample_files: dict) -> None:
    from conftest import upload_and_wait

    data = upload_and_wait(client, user_token, sample_files["pdf"])
    assert data["file"]["status"] == "done"
    assert data["file"]["doc_type"] == "ks2"
    assert data["file"]["contract_no"] == "123"
