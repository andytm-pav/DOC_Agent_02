# Пользовательские парсеры (плагины)

Папка для собственных экстракторов. Каждый `*.py` в этой папке автоматически
загружается при старте (см. `src/doc_agent/extractors/registry.py`).

Пример плагина `my_format.py`:

```python
from pathlib import Path

from doc_agent.extractors.base import ExtractResult, node_paragraph
from doc_agent.extractors.registry import register


@register("myext")
def extract_myext(path: Path, out_dir: Path) -> ExtractResult:
    text = path.read_text(encoding="utf-8", errors="ignore")
    tree = {"version": "1.0", "meta": {"format": "myext", "pages": 1},
            "children": [node_paragraph(text)]}
    return ExtractResult(text=text, tree=tree, pages=1)
```

После добавления плагина зарегистрируйте определение формата при необходимости
в `doc_agent/utils/filetype.py` (функция `detect_format`) — либо файлы с нужным
расширением будут попадать в `txt`.
