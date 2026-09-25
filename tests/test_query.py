"""Test query functionality."""

import pytest


@pytest.mark.asyncio
async def test_ks2_query():
    """Test querying for KS2 documents by contract number."""
    from doc_agent.services.query import query_documents

    # This test requires the full pipeline to be set up
    # In CI, it would use mock data
    result = await query_documents("Покажи все КС2 по договору 123")
    assert "answer" in result
    assert "files" in result
    assert "confidence" in result
    assert "grounded" in result
