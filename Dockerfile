FROM python:3.12-slim

RUN apt-get update && apt-get install -y \
    tesseract-ocr tesseract-ocr-rus tesseract-ocr-eng \
    libmagic1 libpango-1.0-0 libcairo2 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir -e .

COPY config ./config
COPY plugins ./plugins
COPY scripts ./scripts

EXPOSE 8000
CMD ["uvicorn", "doc_agent.main:app", "--host", "0.0.0.0", "--port", "8000"]
