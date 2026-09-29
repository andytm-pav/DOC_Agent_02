"""test_query.py: «КС2 по договору 123» -> правильный file_id (13.2, DD-4)."""
from __future__ import annotations

from conftest import upload_and_wait


def test_ks2_by_contract(client, user_token: str, sample_files: dict) -> None:
    data = upload_and_wait(client, user_token, sample_files["pdf"])
    file_id = data["file"]["id"]

    r = client.post(
        "/query",
        json={"q": "Покажи все КС2 по договору 123", "limit": 20},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert r.status_code == 200, r.text
    result = r.json()
    ids = [f["file_id"] for f in result["files"]]
    assert file_id in ids
    assert result["grounded"] is True
    assert "НЕТ ДАННЫХ" != result["answer"].strip()
    assert "[file_id:" in result["answer"]


def test_filters_extracted(client, user_token: str) -> None:
    r = client.post(
        "/query",
        json={"q": "Покажи все КС2 по договору 123"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    result = r.json()
    assert result["filters"].get("doc_type") == "ks2"
    assert result["filters"].get("contract_no") == "123"


def test_query_requires_auth(client) -> None:
    r = client.post("/query", json={"q": "тест"})
    assert r.status_code == 401
