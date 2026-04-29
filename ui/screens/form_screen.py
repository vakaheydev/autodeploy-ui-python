"""
FormScreen — экран заполнения и отправки формы.
Поддерживает условные поля (condition): поля динамически появляются/скрываются
в зависимости от предиката condition(values_dict) -> bool.
"""
import json
import threading
import time
import tkinter as tk
from tkinter import ttk
from typing import Any, Dict, List

import ui.theme as theme
from forms.base_form import BaseForm
from forms.fields import FieldDefinition, FieldType
from forms.registry import FormRegistry
from ui.dialogs import show_error, show_info, show_refresh_confirm, show_submit_confirm, show_text_viewer, show_warning
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
        # Plural: кол-во экземпляров и кнопка "+" для каждого базового ключа
        self._plural_counts: Dict[str, int] = {}
        self._plural_add_btns: Dict[str, tk.Button] = {}
        # Plural: последний созданный контейнер в группе (для pack after=)
        self._plural_last_containers: Dict[str, tk.Frame] = {}
        self._factory = FieldFactory()
        self._ready = False
        super().__init__(master, app, **kwargs)

    # ------------------------------------------------------------------
    # Построение
    # ------------------------------------------------------------------

    def _build(self) -> None:
        self._form: BaseForm = FormRegistry().get(self._form_id)
        self._form.tfs_service  = self.app.tfs_service
        self._form.itsm_service = self.app.itsm_service

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

        self._env_trace_id = self.app.current_environment.trace_add(
            "write", lambda *_: self._on_env_changed()
        )
        self.bind("<Destroy>", self._on_destroy)

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
        _win = canvas.create_window((0, 0), window=self._fields_frame, anchor="nw")
        canvas.bind(
            "<Configure>",
            lambda e: canvas.itemconfig(_win, width=e.width - 8),
        )
        canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._scroll_canvas = canvas
        canvas.bind_all("<MouseWheel>", self._route_mousewheel)

        env = self.app.current_environment.get()
        to_load = self._fields_needing_http(env)

        if to_load:
            self._render_with_loading(env, to_load)
        else:
            self._render_fields(self._fields_frame)

    def _fields_needing_http(self, env: str) -> List[FieldDefinition]:
        """Возвращает поля, для которых потребуется реальный HTTP-запрос (промах кеша)."""
        from config.reference_cache_config import CACHE_TTL, TTL_INFINITE
        result = []
        for field in self._form.fields:
            if field.field_type not in (FieldType.SELECT, FieldType.MULTISELECT):
                continue
            if field.reference is None or field.reference.source != "http":
                continue
            resource = field.reference.resource
            ttl = CACHE_TTL.get(resource)
            if ttl is None:
                result.append(field)   # кеш отключён — всегда HTTP
                continue
            ts = self.app.reference_cache.get_timestamp(resource, env)
            if ts is None:
                result.append(field)   # кеша нет
                continue
            if ttl != TTL_INFINITE and time.time() - ts > ttl:
                result.append(field)   # кеш протух
        return result

    def _render_with_loading(self, env: str, to_load: List[FieldDefinition]) -> None:
        """
        Показывает окно загрузки, прогревает кеш в фоне для каждого
        HTTP-справочника, затем рендерит поля на главном потоке.
        """
        loading = tk.Toplevel(self)
        loading.title("Загрузка данных")
        loading.configure(bg=theme.C["bg"])
        loading.resizable(False, False)
        loading.transient(self.winfo_toplevel())
        loading.grab_set()

        pad = tk.Frame(loading, bg=theme.C["bg"])
        pad.pack(padx=28, pady=(18, 14))

        tk.Label(
            pad, text="Загрузка справочников…",
            font=theme.F["h3"], bg=theme.C["bg"], fg=theme.C["text"],
        ).pack(pady=(0, 10))

        _label_var = tk.StringVar(value="")
        tk.Label(
            pad, textvariable=_label_var,
            font=theme.F["small"], bg=theme.C["bg"], fg=theme.C["text_muted"],
            width=36,
        ).pack()

        loading.update()

        def _worker() -> None:
            for field in to_load:
                self.after(0, lambda lbl=field.label: _label_var.set(lbl))
                try:
                    self.app.reference_resolver.resolve(field.reference, env)  # type: ignore[arg-type]
                except Exception as exc:
                    print(f"[FormScreen] Ошибка предзагрузки '{field.key}': {exc}")
            self.after(0, _finish)

        def _finish() -> None:
            try:
                loading.destroy()
            except Exception:
                pass
            self._render_fields(self._fields_frame)

        threading.Thread(target=_worker, daemon=True).start()

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

            if field_def.plural:
                self._plural_counts[field_def.key] = 1
                plus_btn = tk.Button(
                    label_row,
                    text="  +  ",
                    font=theme.F["small"],
                    bg=theme.C["surface"],
                    fg=theme.C["primary"],
                    activebackground=theme.C["ghost_h"],
                    activeforeground=theme.C["primary"],
                    relief="flat", bd=0,
                    cursor="hand2",
                )
                plus_btn.config(
                    command=lambda k=field_def.key: self._add_plural_field(k)
                )
                plus_btn.pack(side=tk.RIGHT, padx=(0, 4))
                self._plural_add_btns[field_def.key] = plus_btn
                self._plural_last_containers[field_def.key] = outer

            # Виджет ввода
            ref_items = self._load_reference(field_def)
            fw = self._factory.create(inner, field_def, ref_items, ref_loader=self._load_reference, on_refresh=self._reload_reference_field)
            fw.widget.pack(fill=tk.X, padx=12, pady=(0, 10))
            self._field_widgets[field_def.key] = fw

        # Настраиваем условную видимость
        self._setup_conditional_fields()
        self._ready = True

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

        if self._form.itsm_support:
            ttk.Button(
                foot, text="⬇ Подтянуть из заявки",
                style="Secondary.TButton",
                command=self._on_fetch_from_itsm,
            ).pack(side=tk.LEFT, padx=(8, 0))

        self._status_var = tk.StringVar()
        self._status_lbl = ttk.Label(self, textvariable=self._status_var, style="Muted.TLabel")
        self._status_lbl.pack(anchor=tk.W, pady=(6, 0))

    # ------------------------------------------------------------------
    # Условные поля
    # ------------------------------------------------------------------

    def _setup_conditional_fields(self) -> None:
        """
        Скрывает поля с условием и подписывается на изменения всех полей.
        Вызывается один раз после рендера всех полей.
        """
        has_conditional = False

        for field_def in self._form.fields:
            if field_def.condition is None:
                continue
            has_conditional = True
            outer = self._field_containers.get(field_def.key)
            if outer:
                outer.pack_forget()

        if not has_conditional:
            return

        # Подписываемся на изменения всех полей
        for key, fw in self._field_widgets.items():
            widget = fw.widget
            if isinstance(widget, ttk.Combobox):
                widget.bind("<<ComboboxSelected>>",
                            lambda *_: self._refresh_conditional_fields())
            else:
                fw.bind_change(self._refresh_conditional_fields)

    def _refresh_conditional_fields(self) -> None:
        """Пересчитывает видимость условных полей при изменении любого поля."""
        values = {key: fw.get() for key, fw in self._field_widgets.items()}

        for field_def in self._form.fields:
            if field_def.condition is None:
                continue

            outer = self._field_containers.get(field_def.key)
            if outer is None:
                continue

            should_show = field_def.condition(values)
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

    def _on_destroy(self, event: tk.Event) -> None:
        if event.widget is self:
            try:
                self.app.current_environment.trace_remove("write", self._env_trace_id)
            except Exception:
                pass

    def _on_env_changed(self) -> None:
        """Вызывается при смене окружения. Перезагружает HTTP-справочники."""
        if not self._ready:
            return
        new_env = self.app.current_environment.get()
        http_fields = [
            f for f in self._form.fields
            if f.field_type in (FieldType.SELECT, FieldType.MULTISELECT)
            and f.reference is not None
            and f.reference.source == "http"
        ]
        if not http_fields:
            return
        to_load = self._fields_needing_http(new_env)
        if to_load:
            self._reload_env_with_loading(new_env, to_load, http_fields)
        else:
            for field in http_fields:
                self._rebuild_reference_widget(field)

    def _rebuild_reference_widget(self, field_def: FieldDefinition) -> None:
        """Пересоздаёт виджет справочника (данные уже в кеше — без диалога)."""
        key = field_def.key
        old_fw = self._field_widgets.get(key)
        if old_fw is not None:
            old_fw.widget.destroy()
        inner = self._field_inner_frames.get(key)
        if inner is None:
            return
        new_items = self._load_reference(field_def)
        fw = self._factory.create(inner, field_def, new_items, ref_loader=self._load_reference, on_refresh=self._reload_reference_field)
        fw.widget.pack(fill=tk.X, padx=12, pady=(0, 10))
        self._field_widgets[key] = fw
        has_conditional = any(f.condition for f in self._form.fields)
        if has_conditional:
            widget = fw.widget
            if isinstance(widget, ttk.Combobox):
                widget.bind("<<ComboboxSelected>>", lambda *_: self._refresh_conditional_fields())
            else:
                fw.bind_change(self._refresh_conditional_fields)

    def _reload_env_with_loading(
        self,
        env: str,
        to_load: List[FieldDefinition],
        all_http: List[FieldDefinition],
    ) -> None:
        """Показывает диалог загрузки, грузит промахи кеша, затем перестраивает все HTTP-поля."""
        loading = tk.Toplevel(self)
        loading.title("Загрузка данных")
        loading.configure(bg=theme.C["bg"])
        loading.resizable(False, False)
        loading.transient(self.winfo_toplevel())
        loading.grab_set()

        pad = tk.Frame(loading, bg=theme.C["bg"])
        pad.pack(padx=28, pady=(18, 14))

        tk.Label(
            pad, text="Загрузка справочников…",
            font=theme.F["h3"], bg=theme.C["bg"], fg=theme.C["text"],
        ).pack(pady=(0, 10))

        _label_var = tk.StringVar(value="")
        tk.Label(
            pad, textvariable=_label_var,
            font=theme.F["small"], bg=theme.C["bg"], fg=theme.C["text_muted"],
            width=36,
        ).pack()

        loading.update()

        def _worker() -> None:
            for field in to_load:
                self.after(0, lambda lbl=field.label: _label_var.set(lbl))
                try:
                    self.app.reference_resolver.resolve(field.reference, env)  # type: ignore[arg-type]
                except Exception as exc:
                    print(f"[FormScreen] Ошибка предзагрузки '{field.key}': {exc}")
            self.after(0, _finish)

        def _finish() -> None:
            try:
                loading.destroy()
            except Exception:
                pass
            for field in all_http:
                self._rebuild_reference_widget(field)

        threading.Thread(target=_worker, daemon=True).start()

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
        """Показывает диалог подтверждения, затем инвалидирует кеш и перезагружает справочник."""
        assert field_def.reference is not None
        resource = field_def.reference.resource
        env = self.app.current_environment.get()

        # Показываем дату последнего обновления и просим подтверждение
        cached_ts = self.app.reference_cache.get_timestamp(resource, env)
        if not show_refresh_confirm(self, field_def.label, {env: cached_ts}):
            return  # пользователь отменил

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
            show_error(
                self,
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
        fw = self._factory.create(inner, field_def, new_items, ref_loader=self._load_reference, on_refresh=self._reload_reference_field)
        fw.widget.pack(fill=tk.X, padx=12, pady=(0, 10))
        self._field_widgets[key] = fw

        # Восстанавливаем подписку если в форме есть условные поля
        has_conditional = any(f.condition for f in self._form.fields)
        if has_conditional:
            widget = fw.widget
            if isinstance(widget, ttk.Combobox):
                widget.bind("<<ComboboxSelected>>",
                            lambda *_: self._refresh_conditional_fields())
            else:
                fw.bind_change(self._refresh_conditional_fields)

        btn.config(state=tk.NORMAL, fg=theme.C["primary"])

        show_info(
            self,
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

        # Предварительная валидация — до диалога подтверждения
        errors = self._form.validate(form_data)
        if errors:
            self._set_status(f"✗  {errors[0]}", "error")
            show_error(self, "Ошибка заполнения", "\n".join(errors))
            return

        # Диалог подтверждения (если форма его требует)
        if self._form.confirm_submit():
            endpoint = self._form.get_submit_endpoint(environment)
            method   = self._form.get_http_method()
            payload  = self._form.build_payload(form_data)
            text     = self._form.build_confirm_text(environment, endpoint, method, payload)
            if not show_submit_confirm(self, self._form.title, text):
                self._set_status("", "muted")
                return

        self._set_status("Отправка...", "muted")
        self.update_idletasks()

        result = self.app.submit_service.submit(self._form, form_data, environment)

        if result.success:
            self._set_status(f"✓  {result.message}", "success")
            from ui.screens.result_screen import ResultScreen
            self.app.navigate_to(
                ResultScreen,
                form=self._form,
                environment=environment,
                initial_response=result.raw_response,
            )
        else:
            self._set_status(f"✗  {result.message.splitlines()[0]}", "error")
            show_error(self, "Ошибка отправки", result.message)

    def _preview_payload(self) -> None:
        form_data = self._collect_form_data()
        errors = self._form.validate(form_data)
        if errors:
            show_warning(self, "Валидация", "\n".join(errors))
            return
        payload = self._form.build_payload(form_data)
        show_text_viewer(self, "Предварительный просмотр JSON",
                         json.dumps(payload, ensure_ascii=False, indent=2))

    # ------------------------------------------------------------------
    # Plural-поля
    # ------------------------------------------------------------------

    def _add_plural_field(self, base_key: str) -> None:
        """Добавляет ещё один экземпляр plural-поля с ключом {base_key}_{N}."""
        base_def = next(f for f in self._form.fields if f.key == base_key)
        new_count = self._plural_counts[base_key] + 1
        self._plural_counts[base_key] = new_count
        new_key = f"{base_key}_{new_count}"

        # Вставить в field_order сразу после последнего элемента группы
        last_pos = max(
            i for i, k in enumerate(self._field_order)
            if k == base_key or k.startswith(f"{base_key}_")
        )
        self._field_order.insert(last_pos + 1, new_key)

        # Создать контейнеры
        outer = tk.Frame(self._fields_frame, bg=theme.C["border"])
        inner = tk.Frame(outer, bg=theme.C["surface"])
        inner.pack(fill=tk.BOTH, padx=1, pady=1)

        self._field_containers[new_key] = outer
        self._field_inner_frames[new_key] = inner

        # Label row с номером и кнопкой удаления
        label_row = tk.Frame(inner, bg=theme.C["surface"])
        label_row.pack(fill=tk.X, padx=12, pady=(8, 3))

        req = "  *" if base_def.required else ""
        tk.Label(
            label_row,
            text=f"{base_def.label} {new_count}{req}",
            font=theme.F["small"],
            bg=theme.C["surface"],
            fg=theme.C["text_label"] if base_def.required else theme.C["text_muted"],
        ).pack(side=tk.LEFT)

        # Кнопка удаления этого экземпляра
        tk.Button(
            label_row,
            text="  ×  ",
            font=theme.F["small"],
            bg=theme.C["surface"],
            fg=theme.C["error"],
            activebackground=theme.C["ghost_h"],
            activeforeground=theme.C["error"],
            relief="flat", bd=0, cursor="hand2",
            command=lambda k=new_key, bk=base_key, o=outer: self._remove_plural_field(bk, k, o),
        ).pack(side=tk.RIGHT, padx=(0, 4))

        # Виджет
        ref_items = self._load_reference(base_def)
        fw = self._factory.create(inner, base_def, ref_items, ref_loader=self._load_reference, on_refresh=self._reload_reference_field)
        fw.widget.pack(fill=tk.X, padx=12, pady=(0, 10))
        self._field_widgets[new_key] = fw

        # Разместить после последнего контейнера группы
        prev = self._plural_last_containers.get(base_key)
        if prev and prev.winfo_manager():
            outer.pack(fill=tk.X, pady=3, padx=2, after=prev)
        else:
            outer.pack(fill=tk.X, pady=3, padx=2)
        self._plural_last_containers[base_key] = outer

        # Скрыть "+" если достигнут лимит
        if base_def.plural_max is not None and new_count >= base_def.plural_max:
            btn = self._plural_add_btns.get(base_key)
            if btn:
                btn.pack_forget()

    def _remove_plural_field(self, base_key: str, key: str, outer: tk.Frame) -> None:
        """Удаляет экземпляр plural-поля и возвращает кнопку '+' если она была скрыта."""
        outer.pack_forget()
        outer.destroy()
        self._field_widgets.pop(key, None)
        self._field_containers.pop(key, None)
        self._field_inner_frames.pop(key, None)
        if key in self._field_order:
            self._field_order.remove(key)

        # Обновить _plural_last_containers на предыдущий живой контейнер группы
        last = None
        for k in self._field_order:
            if k == base_key or k.startswith(f"{base_key}_"):
                c = self._field_containers.get(k)
                if c:
                    last = c
        if last is not None:
            self._plural_last_containers[base_key] = last

        # Вернуть "+" если лимит больше не достигнут
        base_def = next((f for f in self._form.fields if f.key == base_key), None)
        if base_def and base_def.plural_max is not None:
            current = self._plural_counts[base_key]
            # Считаем реально живые экземпляры (base + copies в field_order)
            alive = sum(
                1 for k in self._field_order
                if k == base_key or k.startswith(f"{base_key}_")
            )
            if alive < base_def.plural_max:
                btn = self._plural_add_btns.get(base_key)
                if btn:
                    btn.pack(side=tk.RIGHT, padx=(0, 4))
                    _ = current  # подавить предупреждение

    # ------------------------------------------------------------------
    # ITSM-интеграция
    # ------------------------------------------------------------------

    def _on_fetch_from_itsm(self) -> None:
        """Запускает fetch_from_itsm() в фоне, показывает диалог прогресса."""
        environment = self.app.current_environment.get()

        # Диалог «В процессе»
        progress = tk.Toplevel(self)
        progress.title("Подтягиваем данные")
        progress.configure(bg=theme.C["bg"])
        progress.resizable(False, False)
        progress.transient(self.winfo_toplevel())
        progress.grab_set()
        progress.protocol("WM_DELETE_WINDOW", lambda: None)  # запрет закрытия

        pad = tk.Frame(progress, bg=theme.C["bg"])
        pad.pack(padx=32, pady=(20, 16))

        tk.Label(
            pad, text="⬇",
            font=("Segoe UI", 24), bg=theme.C["bg"], fg=theme.C["primary"],
        ).pack(pady=(0, 6))

        tk.Label(
            pad, text="Подтягиваем данные из заявки…",
            font=theme.F["h3"], bg=theme.C["bg"], fg=theme.C["text"],
        ).pack()

        tk.Label(
            pad, text="Пожалуйста, подождите",
            font=theme.F["small"], bg=theme.C["bg"], fg=theme.C["text_muted"],
        ).pack(pady=(4, 0))

        progress.update()

        def _worker() -> None:
            try:
                data = self._form.fetch_from_itsm(environment)
                self.after(0, lambda: _finish(data, None))
            except Exception as exc:
                self.after(0, lambda: _finish(None, str(exc)))

        def _finish(data, error: str | None) -> None:
            try:
                progress.destroy()
            except Exception:
                pass
            if error:
                show_error(self, "Ошибка получения данных", error)
                return
            filled = self._apply_itsm_data(data or {})
            if filled:
                fields_text = "\n".join(f"  • {k}" for k in filled)
                show_info(
                    self,
                    "Данные получены",
                    f"Данные из заявки успешно подтянуты.\n\nЗаполнено полей: {len(filled)}\n{fields_text}",
                )
            else:
                show_info(
                    self,
                    "Данные получены",
                    "Ответ получен, но ни одно из полей формы не было обновлено.\n"
                    "Проверьте, что ключи в ответе совпадают с ключами полей формы.",
                )

        threading.Thread(target=_worker, daemon=True).start()

    def _apply_itsm_data(self, data: dict) -> list[str]:
        """Применяет данные из ITSM к виджетам формы. Возвращает список заполненных ключей."""
        filled: list[str] = []
        for key, value in data.items():
            fw = self._field_widgets.get(key)
            if fw is None:
                continue
            fw.set(value)
            filled.append(key)
        return filled

    # ------------------------------------------------------------------
    # Утилиты
    # ------------------------------------------------------------------

    def _set_status(self, text: str, kind: str = "muted") -> None:
        self._status_var.set(text)
        colors = {"muted": theme.C["text_muted"], "success": theme.C["success"],
                  "error": theme.C["error"]}
        self._status_lbl.config(foreground=colors.get(kind, theme.C["text_muted"]))
