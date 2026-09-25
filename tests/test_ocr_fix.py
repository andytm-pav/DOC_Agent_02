"""Test OCR fix functionality."""


def test_ocr_reject_low_confidence():
    """Test that very different corrections are rejected."""
    from doc_agent.services.ocr_fix import _edit_distance

    original = "123-А"
    corrected = "完全不同的文本"

    edit_dist = _edit_distance(original, corrected)
    ratio = edit_dist / max(len(original), 1)
    assert ratio > 0.5


def test_ocr_accept_similar_correction():
    """Test that similar corrections are accepted."""
    from doc_agent.services.ocr_fix import _edit_distance

    original = "123-А"
    corrected = "123-Λ"  # One character difference

    edit_dist = _edit_distance(original, corrected)
    ratio = edit_dist / max(len(original), 1)
    assert ratio <= 0.5
