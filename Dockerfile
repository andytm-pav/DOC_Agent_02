FROM python:3.12-slim

RUN apt-get update && apt-get install -y \
    tesseract-ocr tesseract-ocr-rus tesseract-ocr-eng \
    libmagic1 libpango-1.0-0 libcairo2 \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --no-cache-dir -e ".[dev]"

COPY . .

EXPOSE 8000

CMD ["uvicorn", "doc_agent.main:app", "--host", "0.0.0.0", "--port", "8000"]
