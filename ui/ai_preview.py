"""Редактируемый preview AI-предложений до изменения основной формы."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, Dict, Iterable, Mapping, Optional

import ui.theme as theme
from forms.base_form import BaseForm
from opencode_integration.response_validator import (
    ResponseValidator,
    ValidatedResponse,
    display_value,
    parse_edited_value,
)


class AIAutofillPreview:
    """Модальный diff editor. `result` появляется только после явного Apply."""

    def __init__(
        self,
        parent: tk.Widget,
        *,
        response: ValidatedResponse,
        form: BaseForm,
        reference_values: Mapping[str, Iterable[Any]],
    ) -> None:
        self._parent = parent
        self._response = response
        self._form = form
        self._reference_values = reference_values
        self._validator = ResponseValidator()
        self._fields = {field.key: field for field in form.fields}
        self._ai_values = dict(response.form_data)
        self._current_values = {
            row.key: row.current_value for row in response.preview_fields
        }
        self._entries: Dict[str, tk.Text] = {}
        self._selected: Dict[str, tk.BooleanVar] = {}
        self._error_labels: Dict[str, tk.Label] = {}
        self._validate_after_id: Optional[str] = None
        self.result: Optional[Dict[str, Any]] = None

        self._dlg = tk.Toplevel(parent)
        self._dlg.title("AI-автозаполнение — предварительный просмотр")
        self._dlg.configure(bg=theme.C["bg"])
        self._dlg.minsize(980, 580)
        self._dlg.geometry("1120x680")
        self._dlg.transient(parent.winfo_toplevel())
        self._dlg.protocol("WM_DELETE_WINDOW", self._cancel)
        self._build()

    def show(self) -> Optional[Dict[str, Any]]:
        self._dlg.grab_set()
        self._center()
        self._dlg.wait_window()
        return self.result

    def _build(self) -> None:
        header = tk.Frame(self._dlg, bg=theme.C["bg"])
        header.pack(fill=tk.X, padx=16, pady=(14, 8))
        tk.Label(
            header,
            text="Предложения OpenCode",
            font=theme.F["h1"],
            bg=theme.C["bg"],
            fg=theme.C["text"],
        ).pack(anchor=tk.W)
        tk.Label(
            header,
            text="Основная форма не изменится, пока вы не нажмёте кнопку применения.",
            font=theme.F["small"],
            bg=theme.C["bg"],
            fg=theme.C["text_muted"],
        ).pack(anchor=tk.W, pady=(2, 0))

        if self._response.warnings:
            warning = tk.Frame(self._dlg, bg="#FEF3C7")
            warning.pack(fill=tk.X, padx=16, pady=(0, 8))
            tk.Label(
                warning,
                text="⚠  " + "\n⚠  ".join(self._response.warnings),
                justify=tk.LEFT,
                wraplength=1050,
                font=theme.F["small"],
                bg="#FEF3C7",
                fg=theme.C["warning"],
            ).pack(fill=tk.X, padx=10, pady=7)

        container = tk.Frame(self._dlg, bg=theme.C["bg"])
        container.pack(fill=tk.BOTH, expand=True, padx=16)
        canvas = tk.Canvas(container, bg=theme.C["bg"], highlightthickness=0)
        scrollbar = ttk.Scrollbar(container, orient=tk.VERTICAL, command=canvas.yview)
        rows = tk.Frame(canvas, bg=theme.C["bg"])
        window_id = canvas.create_window((0, 0), window=rows, anchor="nw")
        rows.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(window_id, width=e.width))
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        canvas.bind("<MouseWheel>", lambda e: canvas.yview_scroll(int(-e.delta / 120), "units"))

        table_header = tk.Frame(rows, bg=theme.C["border"])
        table_header.pack(fill=tk.X, pady=(0, 3))
        for text, width in (
            ("✓", 3), ("Поле / текущее значение", 28), ("Предлагаемое значение", 42),
            ("Confidence", 12), ("Источник / причина", 32),
        ):
            tk.Label(
                table_header, text=text, width=width, anchor="w",
                font=theme.F["small"], bg=theme.C["border"], fg=theme.C["text_label"],
            ).pack(side=tk.LEFT, padx=4, pady=5)

        for row in self._response.preview_fields:
            self._build_row(rows, row)

        # Учитываем комбинацию выбранных по умолчанию изменений сразу.
        self._validate_entries()

        footer = tk.Frame(self._dlg, bg=theme.C["bg"])
        footer.pack(fill=tk.X, padx=16, pady=12)
        ttk.Button(
            footer, text="Применить выбранные", style="Primary.TButton",
            command=lambda: self._apply(selected_only=True),
        ).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(
            footer, text="Применить все валидные", style="Secondary.TButton",
            command=lambda: self._apply(selected_only=False),
        ).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(
            footer, text="Сбросить изменения", style="Secondary.TButton",
            command=self._reset,
        ).pack(side=tk.LEFT)
        ttk.Button(
            footer, text="Отмена", style="Ghost.TButton", command=self._cancel,
        ).pack(side=tk.RIGHT)

    def _build_row(self, parent: tk.Frame, row: Any) -> None:
        changed = row.proposed_value != row.current_value and row.proposed_value is not None
        conflict = bool(row.conflict)
        bg = "#FFF7ED" if conflict else ("#EFF6FF" if changed else theme.C["surface"])
        outer = tk.Frame(parent, bg=theme.C["border"])
        outer.pack(fill=tk.X, pady=2)
        frame = tk.Frame(outer, bg=bg)
        frame.pack(fill=tk.X, padx=1, pady=1)

        selected_default = changed and row.confidence in {"high", "medium"}
        selected = tk.BooleanVar(value=selected_default)
        self._selected[row.key] = selected
        ttk.Checkbutton(
            frame, variable=selected, command=self._validate_entries,
        ).pack(side=tk.LEFT, padx=(5, 2), anchor="n", pady=10)

        field_col = tk.Frame(frame, bg=bg, width=245, height=118)
        field_col.pack(side=tk.LEFT, fill=tk.Y, padx=4, pady=6)
        field_col.pack_propagate(False)
        tk.Label(
            field_col, text=row.label, anchor="w", font=theme.F["h3"],
            bg=bg, fg=theme.C["text"],
        ).pack(fill=tk.X)
        current_text = display_value(row.current_value) or "— пусто —"
        tk.Label(
            field_col, text=f"Сейчас: {current_text}", anchor="w", justify=tk.LEFT,
            wraplength=230, font=theme.F["small"], bg=bg, fg=theme.C["text_muted"],
        ).pack(fill=tk.X, pady=(2, 0))

        edit_col = tk.Frame(frame, bg=bg, width=365, height=118)
        edit_col.pack(side=tk.LEFT, fill=tk.Y, padx=4, pady=6)
        edit_col.pack_propagate(False)
        entry = tk.Text(
            edit_col, height=2, wrap=tk.WORD, font=theme.F["small"],
            bg=theme.C["input_bg"], fg=theme.C["text"], relief="solid", bd=1,
            insertbackground=theme.C["text"], highlightthickness=1,
            highlightbackground=theme.C["input_border"],
            highlightcolor=theme.C["border_focus"],
        )
        entry.insert("1.0", display_value(row.proposed_value))
        entry.pack(fill=tk.X)
        entry.bind(
            "<KeyRelease>",
            lambda event, key=row.key: self._schedule_validation(event, key),
        )
        entry.bind("<FocusOut>", lambda _e: self._validate_entries())
        self._entries[row.key] = entry

        row_actions = tk.Frame(edit_col, bg=bg)
        row_actions.pack(fill=tk.X, pady=(2, 0))
        for label, command in (
            ("AI", lambda k=row.key: self._set_entry(k, self._ai_values[k], True)),
            ("Текущее", lambda k=row.key: self._set_entry(k, self._current_values[k], False)),
            ("Очистить", lambda k=row.key: self._set_entry(k, None, True)),
        ):
            tk.Button(
                row_actions, text=label, command=command,
                font=("Segoe UI", 8), bg=bg, fg=theme.C["primary"],
                activebackground=theme.C["ghost_h"], relief="flat", bd=0, cursor="hand2",
            ).pack(side=tk.LEFT, padx=(0, 5))
        error_label = tk.Label(
            edit_col, text="", anchor="w", justify=tk.LEFT, wraplength=350,
            font=("Segoe UI", 8), bg=bg, fg=theme.C["error"],
        )
        error_label.pack(fill=tk.X)
        self._error_labels[row.key] = error_label

        confidence_colors = {
            "high": theme.C["success"],
            "medium": theme.C["warning"],
            "low": theme.C["error"],
            "unknown": theme.C["text_muted"],
        }
        tk.Label(
            frame, text=row.confidence, width=11, anchor="w",
            font=theme.F["small"], bg=bg,
            fg=confidence_colors.get(row.confidence, theme.C["text_muted"]),
        ).pack(side=tk.LEFT, padx=4, pady=9, anchor="n")

        detail_parts = []
        if row.source:
            detail_parts.append(f"Источник: {row.source}")
        if row.reason:
            detail_parts.append(f"Причина: {row.reason}")
        if row.conflict:
            detail_parts.append(f"Конфликт: {row.conflict}")
        if not detail_parts:
            detail_parts.append("—")
        tk.Label(
            frame, text="\n".join(detail_parts), width=32, anchor="nw",
            justify=tk.LEFT, wraplength=265, font=theme.F["small"], bg=bg,
            fg=theme.C["error"] if conflict else theme.C["text_muted"],
        ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4, pady=7)

    def _set_entry(self, key: str, value: Any, selected: bool) -> None:
        entry = self._entries[key]
        entry.delete("1.0", tk.END)
        entry.insert("1.0", display_value(value))
        self._selected[key].set(selected)
        self._validate_entries()

    def _schedule_validation(self, _event: tk.Event, key: str) -> None:
        # Ручное редактирование автоматически делает поле выбранным.
        self._selected[key].set(True)
        if self._validate_after_id is not None:
            self._dlg.after_cancel(self._validate_after_id)
        self._validate_after_id = self._dlg.after(250, self._validate_entries)

    def _read_values(self) -> tuple[Dict[str, Any], Dict[str, list[str]]]:
        values: Dict[str, Any] = {}
        parse_errors: Dict[str, list[str]] = {}
        for key, entry in self._entries.items():
            raw = entry.get("1.0", "end-1c")
            try:
                values[key] = parse_edited_value(raw, self._fields[key].field_type)
            except ValueError as exc:
                parse_errors[key] = [str(exc)]
        validation_errors = self._validator.validate_manual_values(
            values,
            form=self._form,
            reference_values=self._reference_values,
            check_domain=False,
        )
        for key, messages in validation_errors.items():
            parse_errors.setdefault(key, []).extend(messages)
        return values, parse_errors

    def _validate_entries(self) -> Dict[str, list[str]]:
        self._validate_after_id = None
        values, errors = self._read_values()
        candidate_keys = [key for key, selected in self._selected.items() if selected.get()]
        domain_errors = self._domain_errors(values, candidate_keys, errors)
        self._merge_errors(errors, domain_errors)
        for key, label in self._error_labels.items():
            label.config(text="; ".join(errors.get(key, [])))
        return errors

    def _apply(self, *, selected_only: bool) -> None:
        values, errors = self._read_values()
        if selected_only:
            candidate_keys = [key for key, selected in self._selected.items() if selected.get()]
        else:
            # AI-null не очищает форму массово; явно выбранная ручная очистка — очищает.
            candidate_keys = [
                key for key, value in values.items()
                if key not in errors
                and (value is not None or self._selected[key].get())
            ]
        domain_errors = self._domain_errors(values, candidate_keys, errors)
        self._merge_errors(errors, domain_errors)
        blocking = {
            key: messages for key, messages in errors.items()
            if key in candidate_keys or key in domain_errors
        }
        for key, label in self._error_labels.items():
            label.config(text="; ".join(errors.get(key, [])))
        if blocking:
            first = next(iter(blocking))
            self._entries[first].focus_set()
            return
        self.result = {key: values[key] for key in candidate_keys}
        self._dlg.destroy()

    def _domain_errors(
        self,
        values: Mapping[str, Any],
        candidate_keys: Iterable[str],
        field_errors: Mapping[str, list[str]],
    ) -> Dict[str, list[str]]:
        candidate_set = set(candidate_keys)
        baseline_errors = self._validator.validate_domain_values(
            self._current_values, form=self._form
        )
        effective = dict(self._current_values)
        for key in candidate_set:
            if key in values and key not in field_errors:
                effective[key] = values[key]
        effective_errors = self._validator.validate_domain_values(effective, form=self._form)
        return {
            key: [
                message for message in messages
                if key in candidate_set or message not in baseline_errors.get(key, [])
            ]
            for key, messages in effective_errors.items()
            if key in candidate_set
            or any(message not in baseline_errors.get(key, []) for message in messages)
        }

    @staticmethod
    def _merge_errors(
        target: Dict[str, list[str]],
        extra: Mapping[str, Iterable[str]],
    ) -> None:
        for key, messages in extra.items():
            target.setdefault(key, []).extend(
                message for message in messages if message not in target.get(key, [])
            )

    def _reset(self) -> None:
        for row in self._response.preview_fields:
            entry = self._entries[row.key]
            entry.delete("1.0", tk.END)
            entry.insert("1.0", display_value(self._ai_values[row.key]))
            changed = row.proposed_value != row.current_value and row.proposed_value is not None
            self._selected[row.key].set(changed and row.confidence in {"high", "medium"})
        self._validate_entries()

    def _cancel(self) -> None:
        self.result = None
        self._dlg.destroy()

    def _center(self) -> None:
        self._dlg.update_idletasks()
        root = self._parent.winfo_toplevel()
        width = min(max(self._dlg.winfo_reqwidth(), 980), max(root.winfo_screenwidth() - 80, 980))
        height = min(max(self._dlg.winfo_reqheight(), 580), max(root.winfo_screenheight() - 100, 580))
        x = max(0, root.winfo_rootx() + (root.winfo_width() - width) // 2)
        y = max(0, root.winfo_rooty() + (root.winfo_height() - height) // 2)
        self._dlg.geometry(f"{width}x{height}+{x}+{y}")


def show_ai_preview(
    parent: tk.Widget,
    *,
    response: ValidatedResponse,
    form: BaseForm,
    reference_values: Mapping[str, Iterable[Any]],
) -> Optional[Dict[str, Any]]:
    return AIAutofillPreview(
        parent,
        response=response,
        form=form,
        reference_values=reference_values,
    ).show()
