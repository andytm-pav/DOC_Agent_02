"""Application configuration using pydantic-settings."""

from pathlib import Path
from typing import Any

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppConfig(BaseSettings):
    """Main application configuration."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # App settings
    host: str = "0.0.0.0"
    port: int = 8000
    secret_key: str = "change-me-in-production"
    data_dir: str = "./data"

    # LLM settings
    ollama_url: str = "http://localhost:11434"
    model_main: str = "qwen2.5:1.5b-instruct-q4_K_M"
    model_light: str = "gemma2:2b-instruct-q4_K_M"
    llm_timeout_sec: int = 60

    # Embeddings
    embeddings_model: str = "intfloat/multilingual-e5-small"
    embeddings_batch_size: int = 32

    # Reranker
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    reranker_top_k: int = 5

    # Chunking
    chunk_size_tokens: int = 512
    chunk_overlap_tokens: int = 64

    # OCR
    ocr_tesseract_langs: list[str] = Field(default_factory=lambda: ["rus", "eng"])
    ocr_min_confidence: float = 0.80
    ocr_reject_threshold: float = 0.50

    # Groundrails
    groundrails_enabled: bool = True
    groundrails_cut_ratio: float = 0.30

    # A2A
    a2a_enabled: bool = True
    a2a_agent_name: str = "document-agent"

    # Limits
    max_file_mb: int = 500
    max_query_len: int = 2000


_settings: AppConfig | None = None


def get_settings() -> AppConfig:
    """Get cached application settings."""
    global _settings
    if _settings is None:
        # Load from config.yaml if exists
        config_path = Path("config/config.yaml")
        yaml_config: dict[str, Any] = {}
        if config_path.exists():
            with open(config_path) as f:
                yaml_config = yaml.safe_load(f) or {}

        # Flatten nested config
        flat: dict[str, Any] = {}
        if "app" in yaml_config:
            flat.update(yaml_config["app"])
        if "llm" in yaml_config:
            llm = yaml_config["llm"]
            flat["ollama_url"] = llm.get("base_url", flat.get("ollama_url"))
            flat["model_main"] = llm.get("model_main", flat.get("model_main"))
            flat["model_light"] = llm.get("model_light", flat.get("model_light"))
            flat["llm_timeout_sec"] = llm.get("timeout_sec", flat.get("llm_timeout_sec"))
        if "embeddings" in yaml_config:
            emb = yaml_config["embeddings"]
            flat["embeddings_model"] = emb.get("model", flat.get("embeddings_model"))
            flat["embeddings_batch_size"] = emb.get("batch_size", flat.get("embeddings_batch_size"))
        if "reranker" in yaml_config:
            rr = yaml_config["reranker"]
            flat["reranker_model"] = rr.get("model", flat.get("reranker_model"))
            flat["reranker_top_k"] = rr.get("top_k", flat.get("reranker_top_k"))
        if "chunking" in yaml_config:
            ch = yaml_config["chunking"]
            flat["chunk_size_tokens"] = ch.get("size_tokens", flat.get("chunk_size_tokens"))
            flat["chunk_overlap_tokens"] = ch.get("overlap_tokens", flat.get("chunk_overlap_tokens"))
        if "ocr" in yaml_config:
            ocr = yaml_config["ocr"]
            flat["ocr_tesseract_langs"] = ocr.get("tesseract_langs", flat.get("ocr_tesseract_langs"))
            flat["ocr_min_confidence"] = ocr.get("min_confidence", flat.get("ocr_min_confidence"))
            flat["ocr_reject_threshold"] = ocr.get("reject_threshold", flat.get("ocr_reject_threshold"))
        if "groundrails" in yaml_config:
            gr = yaml_config["groundrails"]
            flat["groundrails_enabled"] = gr.get("enabled", flat.get("groundrails_enabled"))
            flat["groundrails_cut_ratio"] = gr.get("cut_ratio", flat.get("groundrails_cut_ratio"))
        if "a2a" in yaml_config:
            a2a = yaml_config["a2a"]
            flat["a2a_enabled"] = a2a.get("enabled", flat.get("a2a_enabled"))
            flat["a2a_agent_name"] = a2a.get("agent_name", flat.get("a2a_agent_name"))
        if "limits" in yaml_config:
            lim = yaml_config["limits"]
            flat["max_file_mb"] = lim.get("max_file_mb", flat.get("max_file_mb"))
            flat["max_query_len"] = lim.get("max_query_len", flat.get("max_query_len"))

        _settings = AppConfig(**flat)
    return _settings
