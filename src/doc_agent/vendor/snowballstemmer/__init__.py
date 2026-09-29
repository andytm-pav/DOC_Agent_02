"""Vendored Snowball stemmer (только русский; полный пакет — PyPI
«snowballstemmer», BSD-3-Clause, https://snowballstem.org/).

Вендоринг (v2.7): русской морфологии не было нигде в конвейере — BM25,
реранкер и hashing-эмбеддинги не могли сопоставить «вилоновской» и
«Вилоновская», «материалов» и «материал». Чистый Python, без новых
зависимостей и без обращений в интернет; Windows-совместимо.

Использование: from doc_agent.vendor.snowballstemmer import stemmer
"""

from .russian_stemmer import RussianStemmer

__all__ = ("RussianStemmer", "stemmer")


def stemmer(lang: str) -> RussianStemmer:
    lang = lang.lower()
    if lang == "russian":
        return RussianStemmer()
    raise KeyError("Stemming algorithm '%s' not found (vendored: russian only)" % lang)
