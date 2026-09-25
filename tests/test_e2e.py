"""End-to-end tests."""


def test_health(client):
    """Test health endpoint."""
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data
    assert "db" in data


def test_login(client):
    """Test login flow."""
    resp = client.post("/auth/login", json={"username": "admin", "password": "admin"})
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["role"] == "admin"


def test_me(client, auth_headers):
    """Test /auth/me endpoint."""
    resp = client.get("/auth/me", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["username"] == "admin"
    assert data["role"] == "admin"


def test_unauthorized(client):
    """Test that protected endpoints require auth."""
    resp = client.get("/auth/me")
    assert resp.status_code in [401, 403]
