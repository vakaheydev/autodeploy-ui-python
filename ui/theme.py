"""
Тема приложения — цвета, шрифты, ttk-стили.

Вся визуальная конфигурация сосредоточена здесь.
Чтобы изменить внешний вид — менять только этот файл.
"""
import tkinter as tk
from tkinter import ttk

# ------------------------------------------------------------------
# Палитра
# ------------------------------------------------------------------
C = {
    "bg":           "#F1F5F9",   # фон окна (slate-100)
    "surface":      "#FFFFFF",   # фон карточек / панелей
    "surface_alt":  "#F8FAFC",   # немного темнее surface (для полосок)
    "border":       "#CBD5E1",   # граница карточек (slate-300)
    "border_focus": "#3B82F6",   # граница в фокусе (blue-500)

    "primary":      "#2563EB",   # основная кнопка (blue-600)
    "primary_h":    "#1D4ED8",   # hover (blue-700)
    "primary_fg":   "#FFFFFF",   # текст на основной кнопке

    "ghost_h":      "#E2E8F0",   # hover на ghost-кнопке

    "text":         "#0F172A",   # основной текст (slate-900)
    "text_muted":   "#64748B",   # второстепенный (slate-500)
    "text_label":   "#334155",   # метки полей (slate-700)

    "success":      "#16A34A",   # зелёный
    "error":        "#DC2626",   # красный
    "warning":      "#D97706",   # оранжевый

    "input_bg":     "#FFFFFF",
    "input_border": "#94A3B8",   # slate-400

    "badge_api":    "#DBEAFE",   # синяя пилюля
    "badge_apps":   "#D1FAE5",   # зелёная
    "badge_other":  "#FEF3C7",   # жёлтая
}

# ------------------------------------------------------------------
# Шрифты (Segoe UI — нативный шрифт Windows 11)
# ------------------------------------------------------------------
F = {
    "h1":    ("Segoe UI", 16, "bold"),
    "h2":    ("Segoe UI", 13, "bold"),
    "h3":    ("Segoe UI", 11, "bold"),
    "body":  ("Segoe UI", 11),
    "small": ("Segoe UI", 10),
    "mono":  ("Consolas", 11),
}

# ------------------------------------------------------------------
# Отступы
# ------------------------------------------------------------------
PAD = {"xs": 3, "sm": 6, "md": 10, "lg": 16, "xl": 24}


# ------------------------------------------------------------------
# Главная функция — вызывается при старте Application
# ------------------------------------------------------------------
def apply(root: tk.Tk) -> None:
    """Применяет тему к приложению: настраивает ttk.Style и цвет окна."""
    root.configure(bg=C["bg"])

    s = ttk.Style(root)
    s.theme_use("clam")

    # --- Общие ---
    s.configure(".", background=C["bg"], foreground=C["text"], font=F["body"])

    # --- TFrame ---
    s.configure("TFrame", background=C["bg"])
    s.configure("Surface.TFrame", background=C["surface"])

    # --- TLabel ---
    s.configure("TLabel", background=C["bg"], foreground=C["text"], font=F["body"])
    s.configure("H1.TLabel",     font=F["h1"],  background=C["bg"], foreground=C["text"])
    s.configure("H2.TLabel",     font=F["h2"],  background=C["bg"], foreground=C["text"])
    s.configure("H3.TLabel",     font=F["h3"],  background=C["bg"], foreground=C["text"])
    s.configure("Muted.TLabel",  font=F["small"],background=C["bg"],foreground=C["text_muted"])
    s.configure("Label.TLabel",  font=F["small"],background=C["surface"],foreground=C["text_label"])
    s.configure("Success.TLabel",font=F["body"], background=C["bg"], foreground=C["success"])
    s.configure("Error.TLabel",  font=F["body"], background=C["bg"], foreground=C["error"])

    # --- Кнопка Primary (синяя, заливка) ---
    s.configure(
        "Primary.TButton",
        background=C["primary"],
        foreground=C["primary_fg"],
        font=F["body"],
        padding=(14, 7),
        relief="flat",
        borderwidth=0,
        focusthickness=0,
    )
    s.map("Primary.TButton",
          background=[("active", C["primary_h"]), ("disabled", C["border"])],
          foreground=[("disabled", C["text_muted"])])

    # --- Кнопка Secondary (контурная) ---
    s.configure(
        "Secondary.TButton",
        background=C["surface"],
        foreground=C["primary"],
        font=F["body"],
        padding=(12, 6),
        relief="solid",
        borderwidth=1,
        focusthickness=0,
    )
    s.map("Secondary.TButton",
          background=[("active", C["ghost_h"])],
          bordercolor=[("active", C["primary"])])

    # --- Кнопка Ghost (текстовая, «< Назад») ---
    s.configure(
        "Ghost.TButton",
        background=C["bg"],
        foreground=C["text_muted"],
        font=F["small"],
        padding=(6, 4),
        relief="flat",
        borderwidth=0,
        focusthickness=0,
    )
    s.map("Ghost.TButton",
          background=[("active", C["ghost_h"])],
          foreground=[("active", C["text"])])

    # --- Кнопка-строка списка (категория/форма) ---
    s.configure(
        "Row.TButton",
        background=C["surface"],
        foreground=C["text"],
        font=F["body"],
        padding=(14, 10),
        relief="flat",
        borderwidth=0,
        focusthickness=0,
        anchor="w",
    )
    s.map("Row.TButton",
          background=[("active", C["ghost_h"])],
          foreground=[("active", C["primary"])])

    # --- TRadiobutton ---
    s.configure(
        "TRadiobutton",
        background=C["surface"],
        foreground=C["text"],
        font=F["body"],
        focusthickness=0,
    )
    s.map("TRadiobutton", background=[("active", C["ghost_h"])])

    # --- TCheckbutton ---
    s.configure(
        "TCheckbutton",
        background=C["surface"],
        foreground=C["text_muted"],
        font=F["small"],
        focusthickness=0,
    )
    s.map("TCheckbutton", background=[("active", C["ghost_h"])])

    # --- TCombobox ---
    s.configure(
        "TCombobox",
        fieldbackground=C["input_bg"],
        background=C["surface"],
        foreground=C["text"],
        # selectbackground совпадает с фоном поля — текст не "подсвечивается"
        # синим ни до, ни после выбора (актуально для state=readonly на Windows)
        selectbackground=C["input_bg"],
        selectforeground=C["text"],
        bordercolor=C["input_border"],
        lightcolor=C["input_border"],
        darkcolor=C["input_border"],
        arrowcolor=C["text_muted"],
        padding=(6, 5),
        font=F["body"],
    )
    s.map(
        "TCombobox",
        # явно фиксируем цвет для readonly-состояния (Windows меняет его по-своему)
        fieldbackground=[("readonly", C["input_bg"]),
                         ("disabled", C["ghost_h"])],
        foreground=[("readonly", C["text"]),
                    ("disabled", C["text_muted"])],
        selectbackground=[("readonly", C["input_bg"])],
        selectforeground=[("readonly", C["text"])],
        bordercolor=[("focus", C["border_focus"])],
        lightcolor=[("focus", C["border_focus"])],
        darkcolor=[("focus", C["border_focus"])],
    )

    # --- TScrollbar ---
    s.configure(
        "TScrollbar",
        background=C["ghost_h"],
        troughcolor=C["bg"],
        arrowcolor=C["text_muted"],
        relief="flat",
        borderwidth=0,
    )
    s.map("TScrollbar", background=[("active", C["border"])])

    # --- TLabelframe ---
    s.configure(
        "TLabelframe",
        background=C["surface"],
        bordercolor=C["border"],
        relief="solid",
        borderwidth=1,
        padding=10,
    )
    s.configure(
        "TLabelframe.Label",
        background=C["surface"],
        foreground=C["text_muted"],
        font=F["small"],
    )


# ------------------------------------------------------------------
# Вспомогательные функции создания типовых элементов
# ------------------------------------------------------------------

def card(parent: tk.Widget, pady: int = 6) -> tk.Frame:
    """
    Возвращает белую панель-карточку с тонкой границей.
    Добавляет себя через pack(). Возвращает внутренний Frame для наполнения.
    """
    border = tk.Frame(parent, bg=C["border"])
    border.pack(fill=tk.X, pady=pady, padx=2)
    inner = tk.Frame(border, bg=C["surface"])
    inner.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)
    return inner


def separator(parent: tk.Misc, pady: int = 8) -> None:
    """Горизонтальный разделитель."""
    tk.Frame(parent, bg=C["border"], height=1).pack(fill=tk.X, pady=pady)


def badge(parent: tk.Widget, text: str, bg: str) -> tk.Label:
    """Маленькая цветная пилюля-бейдж."""
    return tk.Label(
        parent, text=text, bg=bg, fg=C["text"],
        font=F["small"], padx=6, pady=1,
    )
