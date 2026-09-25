"""Test configuration and fixtures."""

import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="session")
def tmp_data_dir():
    """Create a temporary data directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture(scope="session")
def app(tmp_data_dir):
    """Create the FastAPI application."""
    os.environ["SECRET_KEY"] = "test-secret-key"

    from doc_agent.config import _settings, AppConfig
    import doc_agent.config as config_module

    # Reset settings cache
    config_module._settings = None

    from doc_agent.main import create_app
    from doc_agent.db.session import init_db

    application = create_app()
    init_db(tmp_data_dir)
    return application


@pytest.fixture(scope="session")
def client(app):
    """Create a test client."""
    return TestClient(app)


@pytest.fixture(scope="session")
def admin_token(client):
    """Get admin JWT token."""
    resp = client.post("/auth/login", json={"username": "admin", "password": "admin"})
    assert resp.status_code == 200
    return resp.json()["access_token"]


@pytest.fixture(scope="session")
def auth_headers(admin_token):
    """Get auth headers."""
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture
def sample_pdf(tmp_path):
    """Create a sample PDF file."""
    pdf_path = tmp_path / "test_кс2.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 test content КС-2 Акт о приёмке выполненных работ")
    return str(pdf_path)


@pytest.fixture
def sample_docx(tmp_path):
    """Create a sample DOCX file."""
    from docx import Document
    doc = Document()
    doc.add_paragraph("Тестовый документ")
    table = doc.add_table(rows=3, cols=3)
    for i in range(3):
        for j in range(3):
            table.cell(i, j).text = f"R{i}C{j}"
    docx_path = tmp_path / "test.docx"
    doc.save(str(docx_path))
    return str(docx_path)
