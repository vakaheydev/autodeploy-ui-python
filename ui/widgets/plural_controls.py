"""Shared controls for repeated desktop fields, including nested blocks."""
import tkinter as tk

import ui.theme as theme


class PluralControls:
    def __init__(self, field, add, remove):
        self.field = field
        self._add = add
        self._remove = remove
        self._rows = {}

    @property
    def keys(self):
        return list(self._rows)

    def can_add(self):
        return self.field.plural_max is None or len(self._rows) < self.field.plural_max

    def attach(self, key, outer, inner, label_row):
        remove = tk.Button(
            label_row, text="× Удалить", font=theme.F["body"],
            bg=theme.C["surface"], fg=theme.C["error"],
            activebackground=theme.C["chat_error"], activeforeground=theme.C["error"],
            disabledforeground=theme.C["text_muted"],
            relief="flat", bd=0, padx=10, pady=6, cursor="hand2",
            command=lambda: self._remove(self._key_for(outer), outer),
        )
        bottom = theme.plural_add_button(
            inner, self._add, text=f"＋ Добавить блок «{self.field.label}»",
        )
        self._rows[key] = (outer, remove, bottom)
        self.refresh()

    def _key_for(self, outer):
        return next(key for key, row in self._rows.items() if row[0] is outer)

    def detach(self, key):
        """Keep contiguous keys required by BaseForm.collect_plural()."""
        del self._rows[key]
        renamed = {
            old: self.field.key if i == 0 else f"{self.field.key}_{i + 1}"
            for i, old in enumerate(self.keys)
        }
        self._rows = {renamed[k]: row for k, row in self._rows.items()}
        self.refresh()
        return renamed

    def refresh(self):
        keys = self.keys
        for index, key in enumerate(keys):
            outer, remove, bottom = self._rows[key]
            remove.pack_forget()
            bottom.pack_forget()
            state = tk.NORMAL if self.can_add() else tk.DISABLED
            bottom.configure(state=state)
            remove.configure(state=tk.NORMAL if len(keys) > 1 else tk.DISABLED)
            remove.pack(side=tk.RIGHT)
            if index == len(keys) - 1:
                bottom.pack(anchor=tk.W, padx=12, pady=(2, 12))
            # Display the same consecutive positions as the stored plural keys.
            for child in remove.master.winfo_children():
                if isinstance(child, tk.Label):
                    suffix = "  *" if self.field.required else ""
                    child.configure(text=f"{self.field.label} {index + 1}{suffix}")
                    break


def remap_plural_keys(mapping, renamed):
    """Rename in place, preserving iteration order and references to the mapping."""
    items = [(renamed.get(key, key), value) for key, value in mapping.items()]
    mapping.clear()
    mapping.update(items)
