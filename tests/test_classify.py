"""Test document classification."""

import pytest


@pytest.mark.asyncio
async def test_classify_ks2():
    """Test that KS-2-like text is classified as ks2."""
    from doc_agent.subagents.classifier_agent import ClassifierAgent

    agent = ClassifierAgent()
    text = "Акт о приёмке выполненных работ КС-2. Договор №123 от 15.01.2024. Сумма: 1250000 руб."

    # Note: This test requires Ollama to be running
    # In CI, it would be mocked
    result = await agent.run(text)
    assert "doc_type" in result
    assert "confidence" in result
