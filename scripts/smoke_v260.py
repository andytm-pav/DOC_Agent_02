"""Смоук v2.6.0: LLM-first чат на живом uvicorn.

Мок OpenAI-совместимого API имитирует glm-4.5-flash:
  - каждый ответ обёрнут в <think>…</think> и ```json-ограждения (для JSON-ов);
  - у ПОЛОВИНЫ ответов content пуст, ответ лежит в reasoning_content;
  - extra_body thinking disabled принимается.

Проверяет: планировщик понимает естественные формулировки (подсчёт, поиск
по типу, чтение файла, поиск по содержимому, help, прямой ответ), синтез
списков LLM, сквозные API-эмбеддинги (backend: api), /status 2.6.0.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

PORT = 8123
MOCK_PORT = 8124
BASE = f"http://127.0.0.1:{PORT}"

results: list[tuple[bool, str]] = []
mock_state = {"chat_calls": 0, "synth_calls": 0, "embed_calls": 0,
              "thinking_disabled": 0}


# ---------- мок LLM (glm-4.5-flash стиль) ----------

def _plan_for(q: str, prompt: str) -> dict:
    low = q.lower()
    if "привет" in low or "как дела" in low:
        return {"action": "direct", "doc_type": None, "terms": [], "file_ids": [],
                "search_query": "", "reply": "Здравствуйте! Я «Документовед». Загрузите документы — и спрашивайте."}
    if "что ты умеешь" in low or "что ты можешь" in low:
        return {"action": "help", "doc_type": None, "terms": [], "file_ids": [],
                "search_query": "", "reply": ""}
    if "посчитай" in low or low.startswith("сколько"):
        terms = ["вилоновская"] if "вилоновск" in low else []
        return {"action": "count_files", "doc_type": None, "terms": terms,
                "file_ids": [], "search_query": "", "reply": ""}
    if "открой" in low or ("расскажи" in low and "смет" in low):
        # выбор файла из картотеки промпта: смета по вилоновской
        m = re.search(r"• \S*Смета\S* \[file_id:(\d+)\]", prompt)
        ids = [int(m.group(1))] if m else []
        return {"action": "read_file", "doc_type": None, "terms": [],
                "file_ids": ids, "search_query": "", "reply": ""}
    if "есть ли" in low and "старого города" in low:
        return {"action": "find_files", "doc_type": "ks2", "terms": ["старый", "город"],
                "file_ids": [], "search_query": "", "reply": ""}
    return {"action": "search_content", "doc_type": "ks2", "terms": ["вилоновская"],
            "file_ids": [], "search_query": "Вилоновская 23 КС-2 итоговая сумма", "reply": ""}


def _wrap(text: str, as_json: bool, empty_content: bool) -> dict:
    if empty_content:
        body = ""  # ответ в reasoning_content (поведение glm-4.5-flash)
        reasoning = text
    else:
        body = text
        reasoning = ""
    return {"choices": [{"message": {"content": body, "reasoning_content": reasoning}}]}


def _fake_question(prompt: str) -> str:
    m = re.search(r"Вопрос пользователя: (.+)", prompt)
    return m.group(1).strip() if m else ""


class MockHandler(BaseHTTPRequestHandler):
    def log_message(self, *a) -> None:  # noqa: ANN002
        pass

    def _send(self, payload: dict) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length) or b"{}")
        if payload.get("thinking") == {"type": "disabled"} or (
            isinstance(payload.get("thinking"), dict)
        ):
            mock_state["thinking_disabled"] += 1
        if self.path.endswith("/embeddings"):
            mock_state["embed_calls"] += 1
            inputs = payload.get("input") or []
            data = [{"index": i, "embedding": [float(len(str(t)) % 7 + 1), 0.5]}
                    for i, t in enumerate(inputs)]
            self._send({"data": data})
            return
        mock_state["chat_calls"] += 1
        empty = mock_state["chat_calls"] % 2 == 0  # половина — пустой content
        prompt = (payload.get("messages") or [{}])[0].get("content", "")
        low = prompt.lower()
        if "планировщик" in low:
            q = _fake_question(prompt)
            plan = _plan_for(q, prompt)
            text = "```json\n" + json.dumps(plan, ensure_ascii=False) + "\n```\nВот план."
            self._send(_wrap("<think>думаю…</think>\n" + text, True, empty))
        elif "данные картотеки" in low:
            # корректное поведение LLM-синтеза: факты из блока копируются
            # ДОСЛОВНО (числа и [file_id:N] без изменений)
            mock_state["synth_calls"] += 1
            facts = prompt.split("Данные картотеки:", 1)[1].strip()
            self._send(_wrap(facts, False, empty))
        elif "полный текст документа" in low or "полный текст" in low:
            self._send(_wrap("Смета по объекту Вилоновская: работы и материалы, итог 100000 руб.",
                             False, empty))
        elif "ты формируешь ответ" in low:
            self._send(_wrap("По актам: Итого 50000 руб. [file_id:2]", False, empty))
        else:
            self._send(_wrap("неизвестный промпт", False, empty))


def start_mock() -> ThreadingHTTPServer:
    srv = ThreadingHTTPServer(("127.0.0.1", MOCK_PORT), MockHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


# ---------- утилиты ----------

def api(method: str, path: str, token: str | None = None, body: dict | None = None):
    req = urllib.request.Request(BASE + path, method=method)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, data=data, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def check(name: str, cond: bool, extra: str = "") -> None:
    results.append((bool(cond), name))
    print(("PASS " if cond else "FAIL ") + name + (f" | {extra}" if extra and not cond else ""))


def wait_file(token: str, fid: int, timeout: float = 30.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        data = api("GET", f"/files/{fid}", token)
        if data["file"]["status"] in {"done", "failed", "description_only"}:
            return data
        time.sleep(0.3)
    raise TimeoutError(f"file {fid} not processed")


# ---------- сценарий ----------

def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="smoke_v260_"))
    (tmp / "data").mkdir()
    for sub in ("storage", "sqlite", "chroma", "logs", "inbox"):
        (tmp / "data" / sub).mkdir()
    dump = tmp / "dump"
    dump.mkdir()
    (dump / "Вилоновская_смета.txt").write_text(
        "Смета по объекту Вилоновская. Работы и материалы. Итого 100000 руб.", encoding="utf-8")
    (dump / "КС2_акт_Вилоновская_23.txt").write_text(
        "Акт КС-2 № 5. Объект Вилоновская 23. Итого 50000 руб.", encoding="utf-8")
    (dump / "КС2_акт_Старый_город.txt").write_text(
        "Акт КС-2 № 6. Объект Старый город. Итого 60000 руб.", encoding="utf-8")
    (dump / "Договор_подряда_27-07-2026_Старый_город.txt").write_text(
        "Договор подряда № 27-07-2026. Объект Старый город. Сумма 900000 руб.", encoding="utf-8")

    cfg = {
        "app": {"host": "127.0.0.1", "port": PORT, "secret_key": "s", "data_dir": str(tmp / "data"),
                "admin_username": "admin", "admin_password": "admin"},
        "storage": {"local_paths": [str(tmp / "data" / "storage")], "network_paths": []},
        "watchdog": {"enabled": False, "paths": [], "interval_sec": 30},
        "llm": {"provider": "openai_compatible", "base_url": f"http://127.0.0.1:{MOCK_PORT}",
                "api_key": "test-key", "model_main": "glm-4.5-flash",
                "model_light": "glm-4.5-flash", "timeout_sec": 20, "temperature": 0.0,
                "extra_body": {"thinking": {"type": "disabled"}}},
        "embeddings": {"backend": "api", "model": "unused", "batch_size": 8,
                       "api": {"model": "embedding-3", "base_url": "", "api_key": "",
                               "api_path": "/embeddings", "timeout_sec": 20}},
        "vector": {"backend": "chroma", "collection": "chunks", "metric": "cosine"},
        "reranker": {"backend": "simple", "model": "x", "top_k": 5},
        "chunking": {"size_tokens": 128, "overlap_tokens": 16},
        "ocr": {"engine": "none", "tesseract_cmd": "", "tesseract_langs": ["rus"],
                "min_confidence": 0.8, "reject_threshold": 0.5,
                "process_embedded_images": False},
        "groundrails": {"enabled": True, "cut_ratio": 0.30},
        "a2a": {"enabled": True, "agent_name": "document-agent", "auth_required": False},
        "limits": {"max_file_mb": 100, "max_query_len": 2000},
        "auth": {"token_expire_minutes": 60, "api_keys": []},
    }
    cfg_path = tmp / "config.yaml"
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")

    env = dict(os.environ, DOC_AGENT_CONFIG=str(cfg_path))
    mock = start_mock()
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "doc_agent.main:app",
         "--host", "127.0.0.1", "--port", str(PORT)],
        cwd=str(REPO), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    try:
        for _ in range(60):
            try:
                api("GET", "/health")
                break
            except Exception:
                time.sleep(0.5)
        else:
            print("uvicorn не поднялся")
            return 1

        tok = api("POST", "/auth/login", body={"username": "admin", "password": "admin"})["access_token"]
        scan = api("POST", "/files/scan-folder", tok, {"path": str(dump)})
        for fid in scan["file_ids"]:
            wait_file(tok, fid)
        check("импорт свалки обработан (4 файла)", len(scan["file_ids"]) == 4)

        res = api("POST", "/query", tok, {"q": "привет, как дела?"})
        check("прямой ответ на приветствие (не НЕТ ДАННЫХ)",
              res.get("intent") == "direct" and "Здравствуйте" in res["answer"], str(res)[:200])

        res = api("POST", "/query", tok, {"q": "посчитай мне всё по вилоновской, пжт"})
        check("естественная формулировка -> подсчёт",
              res.get("intent") == "count_files", str(res)[:200])
        check("синтез LLM скопировал числа из данных без изменений",
              "нашлось: 2" in res["answer"] and mock_state["synth_calls"] >= 1,
              res["answer"][:150])
        check("подсчёт: найдено 2 файла по вилоновской", len(res.get("files") or []) == 2,
              json.dumps(res.get("files"), ensure_ascii=False))

        res = api("POST", "/query", tok, {"q": "сколько штук файлов ты обработал?"})
        check("«сколько обработано» считает",
              "Сейчас загружено файлов: 4" in res["answer"] and
              res.get("intent") == "count_files", res["answer"][:150])

        res = api("POST", "/query", tok, {"q": "есть ли у нас что-нибудь от старого города, типа акта?"})
        check("естественная формулировка -> поиск по типу",
              res.get("intent") == "find_files" and len(res.get("files") or []) == 1,
              str(res)[:200])

        res = api("POST", "/query", tok, {"q": "открой пожалуйста смету по вилоновской и расскажи, что там"})
        check("естественная просьба -> чтение файла целиком",
              res.get("intent") == "deep_read" and "100000" in res["answer"], str(res)[:200])

        res = api("POST", "/query", tok, {"q": "какая итоговая сумма в акте по вилоновской?"})
        check("вопрос по содержимому -> RAG с цитатой",
              "50000" in res["answer"] and "[file_id:" in res["answer"], str(res)[:200])

        res = api("POST", "/query", tok, {"q": "что ты умеешь?"})
        check("подсказка о возможностях", res.get("intent") == "help", str(res)[:120])

        status = api("GET", "/status", tok)
        from doc_agent import __version__ as _ver

        check("/status версия совпадает с пакетом", status.get("version") == _ver,
              f"{status.get('version')} != {_ver}")

        check("мок LLM вызывался (планировщик+синтез+репортер)", mock_state["chat_calls"] >= 8,
              str(mock_state))
        check("API-эмбеддинги использовались при импорте", mock_state["embed_calls"] >= 1,
              str(mock_state))
        check("extra_body thinking disabled дошёл до API", mock_state["thinking_disabled"] >= 3,
              str(mock_state))
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        mock.shutdown()
        shutil.rmtree(tmp, ignore_errors=True)

    ok = sum(1 for s, _ in results if s)
    print(f"\nИтог: {ok}/{len(results)}")
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
