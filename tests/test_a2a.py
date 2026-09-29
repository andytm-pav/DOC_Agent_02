"""test_a2a.py: JSON-RPC -> result.completed (13.2, DD-8)."""
from __future__ import annotations

from conftest import upload_and_wait


def test_agent_card(client) -> None:
    r = client.get("/.well-known/agent.json")
    assert r.status_code == 200
    card = r.json()
    assert card["name"] == "document-agent"
    assert "skills" in card


def test_a2a_tasks_send_completed(client, user_token: str, sample_files: dict) -> None:
    upload_and_wait(client, user_token, sample_files["pdf"])
    payload = {
        "jsonrpc": "2.0",
        "method": "tasks/send",
        "id": "1",
        "params": {
            "message": {
                "role": "user",
                "parts": [{"type": "text", "text": "Покажи все КС2 по договору 123"}],
            }
        },
    }
    resp = client.post("/a2a", json=payload)
    assert resp.status_code == 200
    result = resp.json()
    assert result["jsonrpc"] == "2.0"
    assert result["id"] == "1"
    assert result["result"]["status"] == "completed"
    artifacts = result["result"]["artifacts"]
    assert artifacts, "должен быть артефакт с ответом"
    text_part = next(p for p in artifacts[0]["parts"] if p["type"] == "text")
    assert "КС-2" in text_part["text"] or "НЕТ ДАННЫХ" not in text_part["text"]
    data_part = next(p for p in artifacts[0]["parts"] if p["type"] == "data")
    assert data_part["data"]["grounded"] is True


def test_a2a_no_data(client) -> None:
    payload = {
        "jsonrpc": "2.0",
        "method": "tasks/send",
        "id": "2",
        "params": {"message": {"role": "user", "parts": [{"type": "text", "text": "Дай ТТН №999"}]}},
    }
    resp = client.post("/a2a", json=payload)
    result = resp.json()
    text_part = next(p for p in result["result"]["artifacts"][0]["parts"] if p["type"] == "text")
    assert "НЕТ ДАННЫХ" in text_part["text"]


def test_a2a_unknown_method(client) -> None:
    resp = client.post("/a2a", json={"jsonrpc": "2.0", "method": "no/such", "id": "3", "params": {}})
    assert "error" in resp.json()
