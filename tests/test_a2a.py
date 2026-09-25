"""Test A2A protocol."""

import pytest


def test_agent_card(client):
    """Test that agent card is returned."""
    resp = client.get("/.well-known/agent.json")
    assert resp.status_code == 200
    data = resp.json()
    assert "name" in data
    assert "version" in data
    assert data["version"] == "2.0.0"


def test_a2a_jsonrpc(client):
    """Test A2A JSON-RPC endpoint."""
    resp = client.post(
        "/a2a",
        json={
            "jsonrpc": "2.0",
            "method": "tasks/send",
            "id": "1",
            "params": {
                "message": {
                    "role": "user",
                    "parts": [{"type": "text", "text": "Покажи все документы"}],
                }
            },
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["jsonrpc"] == "2.0"
    assert data["id"] == "1"
    assert "result" in data or "error" in data
