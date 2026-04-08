"""
FormScreen — экран заполнения и отправки формы.
Поддерживает условные поля (FieldCondition): поля, которые динамически
появляются/скрываются в зависимости от значения другого поля.
"""
import json
import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk
from typing import Any, Dict, List

import ui.theme as theme
from forms.base_form import BaseForm
from forms.fields import FieldDefinition, FieldType
from forms.registry import FormRegistry
from ui.screens.base_screen import BaseScreen
from ui.widgets.field_factory import FieldFactory, FieldWidget


class FormScreen(BaseScreen):

    def __init__(self, master: tk.Widget, app, form_id: str, **kwargs) -> None:
        self._form_id = form_id
        self._field_widgets: Dict[str, FieldWidget] = {}
        # Внешние контейнеры (border-frame) каждого поля — для show/hide
        self._field_containers: Dict[str, tk.Frame] = {}
        # Внутренние surface-фреймы — для пересоздания виджетов при reload
        self._field_inner_frames: Dict[str, tk.Frame] = {}
        # Порядок ключей для правильной вставки при показе
        self._field_order: List[str] = []
        self._factory = FieldFactory()
        super().__init__(master, app, **kwargs)

    # ------------------------------------------------------------------
    # Построение
    # ------------------------------------------------------------------

    def _build(self) -> None:
        self._form: BaseForm = FormRegistry().get(self._form_id)

        self._add_back_button()

        # Заголовок + бейдж категории
        header = tk.Frame(self, bg=theme.C["bg"])
        header.pack(fill=tk.X, pady=(0, 8))

        tk.Label(
            header, text=self._form.title,
            font=theme.F["h1"], bg=theme.C["bg"], fg=theme.C["text"],
        ).pack(side=tk.LEFT)

        from config.categories import CATEGORIES
        cat_label = CATEGORIES.get(self._form.category, self._form.category)
        theme.badge(header, cat_label, theme.C["badge_other"]).pack(
            side=tk.LEFT, padx=(10, 0), pady=(4, 0), anchor="s"
        )

        self._build_env_bar()
        theme.separator(self, pady=6)
        self._build_scrollable_fields()
        self._build_footer()

    def _build_env_bar(self) -> None:
        from config.environments import ENVIRONMENTS
        bar = theme.card(self, pady=4)
        bar_inner = tk.Frame(bar, bg=theme.C["surface"])
        bar_inner.pack(fill=tk.X, padx=10, pady=6)

        tk.Label(
            bar_inner, text="Окружение:",
            font=theme.F["small"], bg=theme.C["surface"], fg=theme.C["text_muted"],
        ).pack(side=tk.LEFT, padx=(0, 10))

        for env in ENVIRONMENTS:
            ttk.Radiobutton(
                bar_inner,
                text=env.label,
                variable=self.app.current_environment,
                value=env.key,
                style="TRadiobutton",
            ).pack(side=tk.LEFT, padx=(0, 14))

    def _build_scrollable_fields(self) -> None:
        container = tk.Frame(self, bg=theme.C["bg"])
        container.pack(fill=tk.BOTH, expand=True)

        canvas = tk.Canvas(container, bg=theme.C["bg"], highlightthickness=0)
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)

        self._fields_frame = tk.Frame(canvas, bg=theme.C["bg"])
        self._fields_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.create_window((0, 0), window=self._fields_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._scroll_canvas = canvas
        canvas.bind_all("<MouseWheel>", self._route_mousewheel)

        self._render_fields(self._fields_frame)

    def _route_mousewheel(self, event: tk.Event) -> None:
        """
        Глобальный обработчик колеса мыши.
        Если курсор над виджетом с меткой _scroll_target — скроллим его,
        иначе скроллим основной канвас формы.
        """
        w = event.widget
        while w is not None:
            target = getattr(w, "_scroll_target", None)
            if target is not None:
                target.yview_scroll(int(-1 * (event.delta / 120)), "units")
                return
            try:
                w = w.master
            except AttributeError:
                break
        self._scroll_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _render_fields(self, parent: tk.Frame) -> None:
        """
        Строит все поля формы.
        Условные поля (field.condition != None) изначально скрыты.
        """
        self._field_order = [f.key for f in self._form.fields]

        for field_def in self._form.fields:
            # Внешний border-frame — его показываем/скрываем
            outer = tk.Frame(parent, bg=theme.C["border"])
            outer.pack(fill=tk.X, pady=3, padx=2)
            inner = tk.Frame(outer, bg=theme.C["surface"])
            inner.pack(fill=tk.BOTH, padx=1, pady=1)

            self._field_containers[field_def.key] = outer
            self._field_inner_frames[field_def.key] = inner

            # Строка с меткой (и кнопкой обновления для HTTP-справочников)
            label_row = tk.Frame(inner, bg=theme.C["surface"])
            label_row.pack(fill=tk.X, padx=12, pady=(8, 3))

            req = "  *" if field_def.required else ""
            tk.Label(
                label_row,
                text=f"{field_def.label}{req}",
                font=theme.F["small"],
                bg=theme.C["surface"],
                fg=theme.C["text_label"] if field_def.required else theme.C["text_muted"],
            ).pack(side=tk.LEFT)

            if (field_def.reference is not None
                    and field_def.reference.source == "http"):
                refresh_btn = tk.Button(
                    label_row,
                    text="↻",
                    font=theme.F["body"],
                    bg=theme.C["surface"],
                    fg=theme.C["primary"],
                    activebackground=theme.C["surface"],
                    activeforeground=theme.C["primary"],
                    relief="flat", bd=0,
                    cursor="hand2",
                )
                refresh_btn.config(
                    command=lambda fd=field_def, b=refresh_btn: (
                        self._reload_reference_field(fd, b)
                    )
                )
                refresh_btn.pack(side=tk.RIGHT)

            # Виджет ввода
            ref_items = self._load_reference(field_def)
            fw = self._factory.create(inner, field_def, ref_items)
            fw.widget.pack(fill=tk.X, padx=12, pady=(0, 10))
            self._field_widgets[field_def.key] = fw

        # Настраиваем условную видимость
        self._setup_conditional_fields()

    def _build_footer(self) -> None:
        theme.separator(self, pady=6)

        foot = tk.Frame(self, bg=theme.C["bg"])
        foot.pack(fill=tk.X)

        ttk.Button(
            foot, text="  Отправить  →",
            style="Primary.TButton",
            command=self._on_submit,
        ).pack(side=tk.LEFT, padx=(0, 8))

        ttk.Button(
            foot, text="{ } Просмотр JSON",
            style="Secondary.TButton",
            command=self._preview_payload,
        ).pack(side=tk.LEFT)

        self._status_var = tk.StringVar()
        self._status_lbl = ttk.Label(self, textvariable=self._status_var, style="Muted.TLabel")
        self._status_lbl.pack(anchor=tk.W, pady=(6, 0))

    # ------------------------------------------------------------------
    # Условные поля
    # ------------------------------------------------------------------

    def _setup_conditional_fields(self) -> None:
        """
        Скрывает поля с условием и подписывается на изменения триггеров.
        Вызывается один раз после рендера всех полей.
        """
        trigger_keys: set[str] = set()

        for field_def in self._form.fields:
            if field_def.condition is None:
                continue
            # Изначально скрыть
            outer = self._field_containers.get(field_def.key)
            if outer:
                outer.pack_forget()
            trigger_keys.add(field_def.condition.field_key)

        # Подписываемся на изменения полей-триггеров
        for key in trigger_keys:
            fw = self._field_widgets.get(key)
            if fw is None:
                continue
            widget = fw.widget
            if isinstance(widget, ttk.Combobox):
                widget.bind("<<ComboboxSelected>>",
                            lambda *_: self._refresh_conditional_fields())
            else:
                fw.bind_change(self._refresh_conditional_fields)

    def _refresh_conditional_fields(self) -> None:
        """Пересчитывает видимость условных полей при изменении триггера."""
        for field_def in self._form.fields:
            if field_def.condition is None:
                continue

            outer = self._field_containers.get(field_def.key)
            if outer is None:
                continue

            trigger_fw = self._field_widgets.get(field_def.condition.field_key)
            if trigger_fw is None:
                continue

            should_show = trigger_fw.get() == field_def.condition.value
            is_visible = bool(outer.winfo_manager())  # "" если скрыто

            if should_show and not is_visible:
                self._show_field(field_def.key, outer)
            elif not should_show and is_visible:
                outer.pack_forget()

    def _show_field(self, key: str, outer: tk.Frame) -> None:
        """Показывает поле, сохраняя порядок среди остальных полей."""
        idx = self._field_order.index(key)
        # Ищем ближайшего предшественника, который сейчас видим
        prev_container = None
        for i in range(idx - 1, -1, -1):
            prev = self._field_containers.get(self._field_order[i])
            if prev and prev.winfo_manager():
                prev_container = prev
                break

        if prev_container:
            outer.pack(fill=tk.X, pady=3, padx=2, after=prev_container)
        else:
            outer.pack(fill=tk.X, pady=3, padx=2)

    # ------------------------------------------------------------------
    # Справочники
    # ------------------------------------------------------------------

    def _load_reference(self, field_def: FieldDefinition) -> List[Dict[str, Any]]:
        if field_def.field_type not in (FieldType.SELECT, FieldType.MULTISELECT):
            return []
        if field_def.reference is None:
            return []
        try:
            env = self.app.current_environment.get()
            return self.app.reference_resolver.resolve(field_def.reference, env)
        except Exception as exc:
            print(f"[FormScreen] Ошибка загрузки справочника '{field_def.key}': {exc}")
            return []

    def _reload_reference_field(self, field_def: FieldDefinition, btn: tk.Button) -> None:
        """Инвалидирует кеш и перезагружает справочник в отдельном потоке."""
        assert field_def.reference is not None
        resource = field_def.reference.resource
        env = self.app.current_environment.get()

        btn.config(state=tk.DISABLED, fg=theme.C["text_muted"])

        # Окно «В процессе»
        loading = tk.Toplevel(self)
        loading.title("Обновление справочника")
        loading.resizable(False, False)
        loading.grab_set()
        loading.transient(self.winfo_toplevel())

        tk.Label(
            loading,
            text=f"Обновляется справочник\n«{field_def.label}»…",
            font=theme.F["body"],
            padx=28, pady=20,
        ).pack()
        loading.update()

        def _worker():
            try:
                self.app.reference_cache.invalidate(resource, env)
                ref = field_def.reference
                assert ref is not None
                new_items = self.app.reference_resolver.resolve(ref, env)
                error = None
            except Exception as exc:
                new_items = []
                error = str(exc)
            self.after(0, lambda: self._finish_reload(field_def, btn, new_items, loading, error))

        threading.Thread(target=_worker, daemon=True).start()

    def _finish_reload(
        self,
        field_def: FieldDefinition,
        btn: tk.Button,
        new_items: List[Dict[str, Any]],
        loading: tk.Toplevel,
        error: str | None,
    ) -> None:
        """Вызывается в главном потоке: пересоздаёт виджет, закрывает окна."""
        loading.destroy()

        if error:
            btn.config(state=tk.NORMAL, fg=theme.C["primary"])
            messagebox.showerror(
                "Ошибка обновления",
                f"Не удалось обновить справочник «{field_def.label}»:\n{error}",
            )
            return

        # Пересоздаём виджет с новыми данными
        key = field_def.key
        old_fw = self._field_widgets.get(key)
        if old_fw is not None:
            old_fw.widget.destroy()

        inner = self._field_inner_frames[key]
        fw = self._factory.create(inner, field_def, new_items)
        fw.widget.pack(fill=tk.X, padx=12, pady=(0, 10))
        self._field_widgets[key] = fw

        # Восстанавливаем подписку на изменения если поле является триггером
        trigger_dependent = [
            f for f in self._form.fields
            if f.condition and f.condition.field_key == key
        ]
        if trigger_dependent:
            widget = fw.widget
            if isinstance(widget, ttk.Combobox):
                widget.bind("<<ComboboxSelected>>",
                            lambda *_: self._refresh_conditional_fields())
            else:
                fw.bind_change(self._refresh_conditional_fields)

        btn.config(state=tk.NORMAL, fg=theme.C["primary"])

        messagebox.showinfo(
            "Обновление завершено",
            f"Справочник «{field_def.label}» успешно обновлён.\n"
            f"Загружено элементов: {len(new_items)}.",
        )

    # ------------------------------------------------------------------
    # Данные формы
    # ------------------------------------------------------------------

    def _collect_form_data(self) -> Dict[str, Any]:
        """Возвращает данные только видимых полей (скрытые условные — пропускаются)."""
        data: Dict[str, Any] = {}
        for key, fw in self._field_widgets.items():
            outer = self._field_containers.get(key)
            if outer is not None and not outer.winfo_manager():
                continue  # поле скрыто — не включаем в payload
            data[key] = fw.get()
        return data

    # ------------------------------------------------------------------
    # Кнопки
    # ------------------------------------------------------------------

    def _on_submit(self) -> None:
        form_data = self._collect_form_data()
        environment = self.app.current_environment.get()

        self._set_status("Отправка...", "muted")
        self.update_idletasks()

        result = self.app.submit_service.submit(self._form, form_data, environment)

        if result.success:
            self._set_status(f"✓  {result.message}", "success")
            self._show_response_dialog(result.raw_response)
        else:
            self._set_status(f"✗  {result.message.splitlines()[0]}", "error")
            messagebox.showerror("Ошибка отправки", result.message)

    def _preview_payload(self) -> None:
        form_data = self._collect_form_data()
        errors = self._form.validate(form_data)
        if errors:
            messagebox.showwarning("Валидация", "\n".join(errors))
            return
        payload = self._form.build_payload(form_data)
        self._open_text_dialog("Предварительный просмотр JSON",
                               json.dumps(payload, ensure_ascii=False, indent=2))

    # ------------------------------------------------------------------
    # Диалоги
    # ------------------------------------------------------------------

    def _show_response_dialog(self, response: Any) -> None:
        if response is None:
            messagebox.showinfo("Успех", "Форма успешно отправлена.")
            return
        self._open_text_dialog("Ответ сервера",
                               json.dumps(response, ensure_ascii=False, indent=2))

    def _open_text_dialog(self, title: str, text: str) -> None:
        dialog = tk.Toplevel(self)
        dialog.title(title)
        dialog.configure(bg=theme.C["bg"])
        dialog.grab_set()
        dialog.minsize(540, 400)

        tk.Label(
            dialog, text=title,
            font=theme.F["h2"], bg=theme.C["bg"], fg=theme.C["text"],
        ).pack(anchor=tk.W, padx=14, pady=(12, 6))

        st = scrolledtext.ScrolledText(
            dialog, width=68, height=22, wrap=tk.WORD,
            font=theme.F["mono"],
            bg=theme.C["surface"], fg=theme.C["text"],
            relief="flat", bd=0, padx=10, pady=8,
        )
        st.insert("1.0", text)
        st.config(state=tk.DISABLED)
        st.pack(padx=12, pady=(0, 8), fill=tk.BOTH, expand=True)

        ttk.Button(
            dialog, text="Закрыть", style="Secondary.TButton", command=dialog.destroy,
        ).pack(pady=(0, 12))

    # ------------------------------------------------------------------
    # Утилиты
    # ------------------------------------------------------------------

    def _set_status(self, text: str, kind: str = "muted") -> None:
        self._status_var.set(text)
        colors = {"muted": theme.C["text_muted"], "success": theme.C["success"],
                  "error": theme.C["error"]}
        self._status_lbl.config(foreground=colors.get(kind, theme.C["text_muted"]))
