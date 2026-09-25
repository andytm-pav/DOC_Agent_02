"""Test XLSX export."""


def test_export_xlsx(client, auth_headers):
    """Test that /card/export.xlsx returns a valid XLSX file."""
    resp = client.get("/query/card/export.xlsx", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.headers["content-type"] in [
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/octet-stream",
    ]
