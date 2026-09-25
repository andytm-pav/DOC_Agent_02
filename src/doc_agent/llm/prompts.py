"""Prompt loading utilities."""

from pathlib import Path


def load_prompt(name: str) -> str:
    """Load a prompt template from config/prompts/."""
    prompt_path = Path("config/prompts") / f"{name}.txt"
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt not found: {prompt_path}")
    return prompt_path.read_text(encoding="utf-8")
