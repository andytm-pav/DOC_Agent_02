"""test_hallucination.py — КРИТИЧНЫЙ: вопрос без ответа -> «НЕТ ДАННЫХ» (13.3, DD-5)."""
from __future__ import annotations


def test_no_fabrication(client, user_token: str, sample_files: dict) -> None:
    # Загружаем только КС2, спрашиваем про ТТН, которой нет
    from conftest import upload_and_wait

    upload_and_wait(client, user_token, sample_files["pdf"])
    resp = client.post(
        "/query",
        json={"q": "Дай ТТН №999"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 200
    assert "НЕТ ДАННЫХ" in resp.json()["answer"]


def test_unknown_fact_no_data(client, user_token: str, sample_files: dict) -> None:
    from conftest import upload_and_wait

    upload_and_wait(client, user_token, sample_files["pdf"])
    resp = client.post(
        "/query",
        json={"q": "Какая сумма по договору 777777?"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["answer"].strip() == "НЕТ ДАННЫХ" or "НЕТ ДАННЫХ" in body["answer"]
    assert body["grounded"] is False


def test_numeric_validation_blocks_invented_numbers(client, user_token: str, sample_files: dict) -> None:
    """Числа не из источника не проходят валидацию (8.2 шаг 6)."""
    from conftest import upload_and_wait

    upload_and_wait(client, user_token, sample_files["pdf"])
    resp = client.post(
        "/query",
        json={"q": "Договор 123: сумма 999999999 руб?"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    body = resp.json()
    # 999999999 отсутствует в документе -> либо НЕТ ДАННЫХ, либо утверждение вырезано
    answer = body["answer"]
    assert "999999999" not in answer.replace(" ", "") or "НЕТ ДАННЫХ" in answer
