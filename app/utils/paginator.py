from typing import Any, List
import re

def validate_lead_name(name: str) -> bool:
    """Валидация названия источника лидов с поддержкой кириллицы."""
    return 3 <= len(name) <= 50 and bool(re.match(r"^[a-zA-Zа-яА-ЯёЁ0-9_-]+$", name))



def paginate(items: List[Any], page: int, per_page: int = 5) -> dict:
    """
    Простая пагинация.
    Возвращает: {'items': [...], 'page': 1, 'pages': 3, 'has_next': True}
    """
    total_pages = (len(items) + per_page - 1) // per_page
    start = (page - 1) * per_page
    end = start + per_page
    
    return {
        'items': items[start:end],
        'page': page,
        'pages': total_pages,
        'has_next': page < total_pages,
        'has_prev': page > 1
    }