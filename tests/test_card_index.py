"""Test card index export."""


def test_card_index_columns(client, auth_headers):
    """Test that card index export has 15 columns."""
    from openpyxl import load_workbook
    from doc_agent.services.card_index import export_card_index_xlsx

    path = export_card_index_xlsx()
    wb = load_workbook(path)
    ws = wb.active

    # Check headers (15 columns)
    headers = [ws.cell(row=1, column=i).value for i in range(1, 16)]
    assert len(headers) == 15
    assert "ID" in headers
    assert "Имя файла" in headers
    assert "Сумма" in headers

    # Check auto-filter
    assert ws.auto_filter.ref is not None


def test_card_index_api(client, auth_headers):
    """Test card index API endpoint."""
    resp = client.get("/query/card", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "total" in data
    assert "items" in data
