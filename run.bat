@echo off
rem === Запуск агента (http://localhost:8000) ===
cd /d "%~dp0"
if not exist .venv\Scripts\activate.bat (
    echo Сначала запустите setup.bat
    pause
    exit /b 1
)
call .venv\Scripts\activate.bat
uvicorn doc_agent.main:app --host 0.0.0.0 --port 8000
