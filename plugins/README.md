# Плагины

Пользовательские парсеры для дополнительных форматов документов.

## Создание плагина

1. Создайте файл в этой директории, например `my_parser.py`
2. Реализуйте протокол `Extractor` из `doc_agent.extractors.base`
3. Зарегистрируйте в `doc_agent.extractors.registry`

## Пример

```python
from doc_agent.extractors.base import Extractor, ExtractionResult

class MyParser:
    def supports(self, format: str) -> bool:
        return format == "myformat"

    def extract(self, file_path: str, format: str) -> ExtractionResult:
        # Ваш код парсинга
        return ExtractionResult(text="...", tree=[])
```
