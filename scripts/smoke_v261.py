"""Смоук v2.6.1: точность по сметам на живом uvicorn (кейс пользователя).

Мок OpenAI-совместимого API имитирует glm-4.5-flash (в т.ч. пустой content
и <think>). Сценарий — из реального диалога:
  - «что в сметах по вилоновской?»   -> read_file ГРУППЫ смет (не RAG-каша);
  - «файл сметы …отмостка, нужны материалы» -> чтение файла ЦЕЛИКОМ,
    раздел «Материалы» (конец файла) доходит до LLM;
  - RAG по содержимому находит смету по объекту (преамбула имени в чанках),
    уверенность > 0.3 (раньше 0);
  - «Полная переиндексация» переобрабатывает файлы, поиск продолжает работать;
  - /status 2.6.1.
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

PORT = 8125
MOCK_PORT = 8126
BASE = f"http://127.0.0.1:{PORT}"

results: list[tuple[bool, str]] = []
mock_state = {"chat_calls": 0, "embed_calls": 0, "deep_prompts": 0}


def _catalog_map(prompt: str) -> dict[str, int]:
    """name -> file_id из блока картотеки в промпте планировщика."""
    out: dict[str, int] = {}
    for m in re.finditer(r"• (.+?) \[file_id:(\d+)\]", prompt):
        out[m.group(1).strip()] = int(m.group(2))
    return out


def _plan_for(q: str, prompt: str) -> dict:
    low = q.lower()
    catalog = _catalog_map(prompt)
    if "что в сметах" in low:
        ids = [fid for name, fid in catalog.items()
               if "смет" in name.lower() and "вилоновская" in name.lower()]
        return {"action": "read_file", "doc_type": None, "terms": ["вилоновская", "смета"],
                "file_ids": ids, "search_query": "", "reply": ""}
    if "отмостка" in low and "материал" in low:
        ids = [fid for name, fid in catalog.items()
               if "отмостка" in name.lower()]
        return {"action": "read_file", "doc_type": None, "terms": ["вилоновская", "отмостка"],
                "file_ids": ids, "search_query": "", "reply": ""}
    return {"action": "search_content", "doc_type": None, "terms": ["вилоновская"],
            "file_ids": [], "search_query": "вилоновская материалы", "reply": ""}


def _wrap(text: str, empty_content: bool) -> dict:
    if empty_content:
        return {"choices": [{"message": {"content": "", "reasoning_content": text}}]}
    return {"choices": [{"message": {"content": text, "reasoning_content": ""}}]}


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
        if self.path.endswith("/embeddings"):
            mock_state["embed_calls"] += 1
            inputs = payload.get("input") or []
            data = [{"index": i, "embedding": [float(len(str(t)) % 7 + 1), 0.5]}
                    for i, t in enumerate(inputs)]
            self._send({"data": data})
            return
        mock_state["chat_calls"] += 1
        empty = mock_state["chat_calls"] % 2 == 0
        prompt = (payload.get("messages") or [{}])[0].get("content", "")
        low = prompt.lower()
        if "планировщик" in low:
            plan = _plan_for(_fake_question(prompt), prompt)
            text = "```json\n" + json.dumps(plan, ensure_ascii=False) + "\n```\n"
            self._send(_wrap("<think>думаю…</think>\n" + text, empty))
        elif "полный текст" in low:
            # deep_read: материалы из полного текста сметы
            mock_state["deep_prompts"] += 1
            self._send(_wrap(
                "Материалы по смете Вилоновская: Унифлекс ЭПП, грунтовка "
                "акрилатная, смесь гипсовая. Итого по материалам 98880.",
                empty))
        elif "ты формируешь ответ" in low:
            self._send(_wrap("По смете Вилоновской: Унифлекс ЭПП [file_id:1]", empty))
        else:
            self._send(_wrap("неизвестный промпт", empty))


def start_mock() -> ThreadingHTTPServer:
    srv = ThreadingHTTPServer(("127.0.0.1", MOCK_PORT), MockHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def api(method: str, path: str, token: str | None = None, body: dict | None = None):
    req = urllib.request.Request(BASE + path, method=method)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, data=data, timeout=60) as r:
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


def _estimate_rows() -> list[list[object]]:
    rows: list[list[object]] = [
        ["Приложение №3", "", ""],
        ["к договору подряда №27-07/2026 от 27.07.2026г", "", ""],
        ["г.Самара, ул.Вилоновская,д.2", "", ""],
        ["№", "Вид работ", "Объём"],
        [1, "Насечка поверхности", 584],
        [37, "Итого по работе", 672103.3],
        [38, "Материалы", ""],
        [39, "Унифлекс ЭПП, 10м", "рул; 48"],
        [40, "Грунтовка акрилатная", "л; 116.8"],
        [41, "Смесь гипсовая штукатурная", "кг; 4964"],
        [43, "Итого по материалам", 98880],
    ]
    return rows


def _summary_rows() -> list[list[object]]:
    """Сводная смета — ДРУГОЕ содержимое (иначе sha256-дедуп склеит файлы)."""
    return [
        ["Сводная смета по объекту Вилоновская 23", "", ""],
        ["№", "Раздел", "Сумма"],
        [1, "Работы", 672103.3],
        [2, "Материалы", 98880],
        [3, "Итого по смете", 770983.3],
    ]


def _summary_rows() -> list[list[object]]:
    """Сводная смета — ДРУГОЕ содержимое (иначе sha256-дедуп склеит файлы)."""
    return [
        ["Сводная смета по объекту Вилоновская 23", "", ""],
        ["№", "Раздел", "Сумма"],
        [1, "Работы", 672103.3],
        [2, "Материалы", 98880],
        [3, "Итого по смете", 770983.3],
    ]


def main() -> int:
    from openpyxl import Workbook

    tmp = Path(tempfile.mkdtemp(prefix="smoke_v261_"))
    (tmp / "data").mkdir()
    for sub in ("storage", "sqlite", "chroma", "logs", "inbox"):
        (tmp / "data" / sub).mkdir()
    dump = tmp / "dump"
    dump.mkdir()
    # реальные имена пользователя (двойные пробелы сохранены);
    # содержимое файлов разное — иначе sha256-дедуп оставит один файл
    for name, rows in (("Смета  по стена и отмостка Вилоновская 23 (2).xlsx", _estimate_rows()),
                       ("Сводная смета Вилоновская 23.xlsx", _summary_rows())):
        wb = Workbook()
        ws = wb.active
        ws.title = "Смета"
        for row in rows:
            ws.append(row)
        wb.save(dump / name)

    cfg = {
        "app": {"host": "127.0.0.1", "port": PORT, "secret_key": "s", "data_dir": str(tmp / "data"),
                "admin_username": "admin", "admin_password": "admin"},
        "storage": {"local_paths": [str(tmp / "data" / "storage")], "network_paths": []},
        "watchdog": {"enabled": False, "paths": [], "interval_sec": 30},
        "llm": {"provider": "openai_compatible", "base_url": f"http://127.0.0.1:{MOCK_PORT}",
                "api_key": "test-key", "model_main": "glm-4.5-flash",
                "model_light": "glm-4.5-flash", "timeout_sec": 20, "temperature": 0.0,
                "extra_body": {"thinking": {"type": "disabled"}}},
        "embeddings": {"backend": "hashing", "model": "unused", "batch_size": 8},
        "vector": {"backend": "chroma", "collection": "chunks", "metric": "cosine"},
        "reranker": {"backend": "simple", "model": "x", "top_k": 5},
        "chunking": {"size_tokens": 128, "overlap_tokens": 16},
        "ocr": {"engine": "none", "tesseract_cmd": "", "tesseract_langs": ["rus"],
                "min_confidence": 0.8, "reject_threshold": 0.5,
                "process_embedded_images": False},
        "groundrails": {"enabled": True, "cut_ratio": 0.30, "confidence_top_k": 3},
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
        check("сметы xlsx обработаны (2 файла)", len(scan["file_ids"]) == 2)

        # --- кейс 1: «что в сметах по вилоновской?» ---
        res = api("POST", "/query", tok, {"q": "что в сметах по вилоновской?"})
        check("группа смет -> чтение файлов целиком (не RAG)",
              res.get("intent") == "deep_read" and len(res.get("files") or []) == 2,
              str(res)[:200])
        check("материалы из полного текста в ответе",
              "Унифлекс" in res["answer"] and mock_state["deep_prompts"] >= 1,
              res["answer"][:150])

        # --- кейс 2: «файл сметы по вилоновской отмостка, нужно материалы» ---
        res = api("POST", "/query", tok,
                  {"q": "файл сметы по вилоновской отмостка, нужно материалы"})
        check("названный файл -> read_file",
              res.get("intent") == "deep_read" and len(res.get("files") or []) == 1,
              str(res)[:200])
        check("уверенность глубокого чтения 0.9 (не 0/0.17)",
              res.get("confidence") == 0.9, str(res.get("confidence")))

        # --- кейс 3: RAG по содержимому находит смету по объекту ---
        res = api("POST", "/query", tok, {"q": "какие материалы по вилоновской?"})
        check("RAG цитирует смету (file_id в ответе)",
              "[file_id:" in res["answer"], res["answer"][:150])
        check("уверенность RAG > 0.3 (раньше 0)",
              float(res.get("confidence") or 0) > 0.3, str(res.get("confidence")))

        # --- кейс 4: полная переиндексация продолжает работать ---
        r = api("POST", "/admin/reindex", tok)
        check("reindex_all поставлен", "job_id" in r, str(r)[:120])
        deadline = time.time() + 30
        done = False
        while time.time() < deadline:
            jobs = api("GET", "/admin/jobs", tok).get("jobs") or []
            row = next((j for j in jobs if j["kind"] == "reindex_all"), None)
            if row and row["status"] in {"done", "failed"}:
                done = row["status"] == "done"
                break
            time.sleep(0.4)
        check("reindex_all выполнен", done)

        res = api("POST", "/query", tok, {"q": "что в сметах по вилоновской?"})
        check("после переиндексации ответы работают",
              res.get("intent") == "deep_read" and "Унифлекс" in res["answer"],
              str(res)[:200])

        status = api("GET", "/status", tok)
        v = str(status.get("version") or "")
        def _vkey(s: str) -> tuple[int, ...]:
            try:
                return tuple(int(x) for x in s.split("."))
            except ValueError:
                return (0,)
        check("/status версия >= 2.6.1", _vkey(v) >= (2, 6, 1), v)
        check("мок LLM вызывался", mock_state["chat_calls"] >= 6, str(mock_state))
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
