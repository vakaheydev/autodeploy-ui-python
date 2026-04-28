"""
Декларативные определения полей формы.

Добавить новый тип поля:
  1. Добавить значение в FieldType
  2. Добавить обработку в ui/widgets/field_factory.py
"""
from dataclasses import dataclass, field as dc_field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional


class FieldType(Enum):
    TEXT        = "text"        # однострочный ввод
    TEXTAREA    = "textarea"    # многострочный ввод
    SELECT      = "select"      # выпадающий список из справочника
    MULTISELECT = "multiselect" # список с чекбоксами (множественный выбор)
    CHECKBOX    = "checkbox"    # одиночный чекбокс (bool)
    NUMBER      = "number"      # числовой ввод
    FILE        = "file"        # выбор файла + ручной ввод содержимого
    BLOCK       = "block"       # группа вложенных полей


@dataclass(frozen=True)
class ReferenceConfig:
    """
    Конфигурация справочника для SELECT / MULTISELECT.

    source:      "local"  — данные из config/references/<resource>
                 "http"   — данные загружаются с сервера
    resource:    для local — имя JSON файла (напр. "api_categories.json")
                 для http  — ключ из маппинга URL в HttpReferenceHandler
    value_key:   поле объекта, которое используется как значение (ID)
    label_key:   поле объекта, которое отображается пользователю
    search_keys: кортеж полей, по которым работает поиск в MULTISELECT.
                 Если задан — все эти поля объединяются в отображаемую строку
                 и участвуют в live-фильтрации. Например: ("name", "azp").
    """
    source:      str
    resource:    str
    value_key:   str             = "id"
    label_key:   str             = "name"
    search_keys: tuple[str, ...] = ()
    detail_keys: tuple[str, ...] = ()   # поля для детальной карточки; () — показать все


Condition = Callable[[Dict[str, Any]], bool]


@dataclass
class FieldDefinition:
    """
    Полное описание одного поля формы.
    Является единственным источником правды о поле —
    используется и для отрисовки UI, и для валидации, и для payload.
    """
    key:        str
    label:      str
    field_type: FieldType

    required:    bool                      = True
    placeholder: str                       = ""
    default:     Any                       = None
    reference:   Optional[ReferenceConfig] = None
    condition:   Optional[Condition]        = None  # если задано — поле условное
    width:       int                       = 42
    hint:        str                       = ""
    file_type:   str                       = ""    # для FILE: расширение, напр. ".json"
    plural:      bool                      = False  # включить кнопку "+" для дублирования
    plural_max:  Optional[int]             = None   # макс. кол-во экземпляров (None = без лимита)
    block_fields: List['FieldDefinition']  = dc_field(default_factory=list)  # вложенные поля для BLOCK
