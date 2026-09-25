"""Test document reconstruction."""

import json
import tempfile
from pathlib import Path


def test_docx_to_xlsx_reconstruction():
    """Test that DOCX with table can be reconstructed to XLSX."""
    from doc_agent.subagents.reconstructor_agent import ReconstructorAgent

    tree = {
        "version": "1.0",
        "meta": {"file_id": 1, "format": "docx", "pages": 1},
        "children": [
            {"type": "paragraph", "text": "Тестовый документ"},
            {
                "type": "table",
                "table": {
                    "name": "Таблица 1",
                    "rows": [
                        ["A1", "B1", "C1"],
                        ["A2", "B2", "C2"],
                        ["A3", "B3", "C3"],
                    ],
                },
            },
        ],
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(tree, f)
        tree_path = f.name

    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
        output_path = f.name

    import asyncio
    agent = ReconstructorAgent()
    result = asyncio.run(agent.run(tree_path, "xlsx", output_path))

    assert Path(result).exists()

    # Verify the XLSX has the table
    from openpyxl import load_workbook
    wb = load_workbook(result)
    ws = wb.active
    assert ws.cell(row=2, column=1).value == "A1"
    assert ws.cell(row=4, column=3).value == "C3"

    # Cleanup
    Path(tree_path).unlink()
    Path(output_path).unlink()
