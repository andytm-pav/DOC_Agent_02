"""Test hallucination prevention (critical test)."""

import pytest


@pytest.mark.asyncio
async def test_no_fabrication():
    """Test that questions without data return 'НЕТ ДАННЫХ'."""
    from doc_agent.services.query import query_documents

    # Ask about a TTN that doesn't exist
    result = await query_documents("Дай ТТН №999")
    assert "НЕТ ДАННЫХ" in result["answer"]
