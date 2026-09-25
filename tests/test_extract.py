"""Test document extraction."""


def test_pdf_extraction(sample_pdf):
    """Test that PDF extraction returns non-empty text."""
    from doc_agent.extractors.registry import extract
    result = extract(sample_pdf, "pdf")
    assert result.text
    assert len(result.text) > 0


def test_docx_extraction(sample_docx):
    """Test that DOCX extraction returns non-empty text."""
    from doc_agent.extractors.registry import extract
    result = extract(sample_docx, "docx")
    assert result.text
    assert len(result.text) > 0
    assert len(result.tables) > 0


def test_extractor_registry():
    """Test that extractors are properly registered."""
    from doc_agent.extractors.registry import auto_register, get_extractor
    auto_register()

    assert get_extractor("pdf") is not None
    assert get_extractor("docx") is not None
    assert get_extractor("xlsx") is not None
    assert get_extractor("jpg") is not None
    assert get_extractor("eml") is not None
    assert get_extractor("unknown") is None
