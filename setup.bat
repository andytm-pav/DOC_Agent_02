@echo off
rem === Первичная настройка проекта (запустить один раз) ===
cd /d "%~dp0"
where py >nul 2>nul && (py -3.12 -m venv .venv || py -3 -m venv .venv) || python -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -e ".[dev]"
copy /y .env.example .env
echo.
echo Готово. Виртуальное окружение .venv создано, зависимости установлены.
echo Отредактируйте файл .env (SECRET_KEY, LLM_API_KEY) и config\config.yaml
echo Запуск: run.bat  (или через PyCharm: src\doc_agent\main.py)
pause
