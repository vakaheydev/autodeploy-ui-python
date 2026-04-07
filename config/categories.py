"""
Категории форм.
"""
from typing import Dict, List

# Ключ → отображаемое название
CATEGORIES: Dict[str, str] = {
    "api":   "АПИ",
    "apps":  "Приложения",
    "other": "Операции",
}

# Порядок отображения категорий в UI
CATEGORY_ORDER: List[str] = ["api", "apps", "other"]
