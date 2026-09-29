@echo off
rem === Тесты: ruff + mypy + pytest ===
cd /d "%~dp0"
call .venv\Scripts\activate.bat 2>nul
ruff check . && mypy . && pytest -x
