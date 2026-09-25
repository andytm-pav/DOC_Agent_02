"""Test offline functionality."""


def test_offline_health(client):
    """Test that health check works without external dependencies."""
    resp = client.get("/health")
    assert resp.status_code == 200
    # DB should always be OK (local SQLite)
    data = resp.json()
    assert data["db"] == "ok"
