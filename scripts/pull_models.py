"""Загрузка моделей в локальный Ollama (только если llm.provider: ollama)."""
from __future__ import annotations

import os
import sys

import httpx


def main() -> int:
    base = os.environ.get("OLLAMA_URL", "http://localhost:11434").rstrip("/")
    models = [
        os.environ.get("DOC_AGENT_MODEL_MAIN", "qwen2.5:1.5b-instruct-q4_K_M"),
        os.environ.get("DOC_AGENT_MODEL_LIGHT", "gemma2:2b-instruct-q4_K_M"),
    ]
    failed = False
    for model in models:
        print(f"Pull {model} ...")
        try:
            with httpx.stream("POST", f"{base}/api/pull", json={"name": model}, timeout=3600) as r:
                for line in r.iter_lines():
                    if line and '"error"' in line:
                        print(line)
                        failed = True
                r.raise_for_status()
            print(f"OK: {model}")
        except Exception as exc:  # noqa: BLE001
            print(f"FAIL: {model}: {exc}")
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
