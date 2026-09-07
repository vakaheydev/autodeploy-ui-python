"""
FormScreen — экран заполнения и отправки формы.
Поддерживает условные поля (condition): поля динамически появляются/скрываются
в зависимости от предиката condition(values_dict) -> bool.
"""
import json
import logging
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk
from typing import Any, Dict, List, Optional

import ui.theme as theme
from forms.base_form import BaseForm
from forms.fields import FieldDefinition, FieldType
from forms.registry import FormRegistry
from config.environments import (
    OPENCODE_ALLOWED_MCP_KEY,
    OPENCODE_MAX_CONTEXT_CHARS_KEY,
    OPENCODE_MODEL_ID_KEY,
    OPENCODE_PROVIDER_ID_KEY,
    OPENCODE_REFERENCE_INLINE_MAX_BYTES_KEY,
    OPENCODE_REFERENCE_INLINE_MAX_ITEMS_KEY,
    OPENCODE_REFERENCE_INLINE_TOTAL_BYTES_KEY,
    OPENCODE_REPOSITORY_GIT_PULL_KEY,
    OPENCODE_REPOSITORY_MCP_KEY,
)
from config.mcp_profiles import setting_enabled
from opencode_integration.agent import ConversationEvent, FormExtractorAgent
from opencode_integration.context_builder import BuiltContext
from opencode_integration.workflow import ExtractionDirective
from opencode_integration.reference_resolver import (
    DEFAULT_INLINE_REFERENCE_MAX_BYTES,
    DEFAULT_INLINE_REFERENCE_MAX_ITEMS,
    DEFAULT_INLINE_REFERENCE_TOTAL_BYTES,
)
from opencode_integration.client import (
    OpenCodeCancelled,
    OpenCodeStructuredOutputError,
    opencode_message_duration,
    opencode_text_generation_duration,
)
from opencode_integration.response_validator import (
    ResponseValidator,
    ValidatedResponse,
    display_value,
)
from ui.ai_assistant import AIAssistantDialog
from ui.dialogs import (
    ask_text,
    ask_ticket_id,
    show_error,
    show_info,
    show_loading,
    show_refresh_confirm,
    show_submit_confirm,
    show_text_viewer,
    show_warning,
)
from ui.inline_ai_review import ACCEPTED, REJECTED, InlineReviewState
from ui.screens.base_screen import BaseScreen
from ui.widgets.field_factory import FieldFactory, FieldWidget


_log = logging.getLogger("opencode.form_ui")


class FormScreen(BaseScreen):

    def __init__(
        self,
        master: tk.Widget,
        app,
        form_id: str,
        initial_data: Optional[Dict[str, Any]] = None,
        ai_autostart: bool = False,
        plan_id: str = "",
        plan_step_id: str = "",
        **kwargs,
    ) -> None:
        self._form_id = form_id
        self._initial_data = initial_data
        self._ai_handoff = app.consume_ai_handoff(form_id) if ai_autostart else None
        self._ai_prepared_context: Optional[BuiltContext] = (
            self._ai_handoff.context if self._ai_handoff is not None else None
        )
        self._ai_plan_id = self._ai_handoff.plan_id if self._ai_handoff else plan_id
        self._ai_plan_step_id = (
            self._ai_handoff.step_id if self._ai_handoff else plan_step_id
        )
        self._ai_plan_guidance = self._ai_handoff.guidance if self._ai_handoff else ""
        self._ai_extraction: Optional[ExtractionDirective] = (
            self._ai_handoff.extraction if self._ai_handoff else None
        )
        self._ai_provider_id = self._ai_handoff.provider_id if self._ai_handoff else ""
        self._ai_model_id = self._ai_handoff.model_id if self._ai_handoff else ""
        self._ai_variant = self._ai_handoff.variant if self._ai_handoff else ""
        self._ai_thinking_auto = (
            self._ai_handoff.thinking_auto if self._ai_handoff else False
        )
        self._ai_autostart_pending = self._ai_prepared_context is not None
        self._field_widgets: Dict[str, FieldWidget] = {}
        # Внешние контейнеры (border-frame) каждого поля — для show/hide
        self._field_containers: Dict[str, tk.Frame] = {}
        # Внутренние surface-фреймы — для пересоздания виджетов при reload
        self._field_inner_frames: Dict[str, tk.Frame] = {}
        self._field_label_rows: Dict[str, tk.Frame] = {}
        # Порядок ключей для правильной вставки при показе
        self._field_order: List[str] = []
        # Plural: кол-во экземпляров и кнопка "+" для каждого базового ключа
        self._plural_counts: Dict[str, int] = {}
        self._plural_add_btns: Dict[str, tk.Button] = {}
        # Plural: последний созданный контейнер в группе (для pack after=)
        self._plural_last_containers: Dict[str, tk.Frame] = {}
        self._factory = FieldFactory()
        # parent_key → [child_field_defs] для зависимых справочников (верхний уровень)
        self._dependent_fields: Dict[str, List[FieldDefinition]] = {}
        # parent_key → [(block_field_def, sub_field_def)] для зависимых sub-полей BLOCK
        self._block_dependent_fields: Dict[str, List] = {}
        self._ready = False
        self._ai_cancel_event: Optional[threading.Event] = None
        self._ai_session_id: Optional[str] = None
        self._ai_queue: Optional["queue.Queue[tuple[str, Any]]"] = None
        self._ai_poll_id: Optional[str] = None
        self._ai_assistant: Optional[AIAssistantDialog] = None
        self._ai_agent: Optional[FormExtractorAgent] = None
        self._ai_busy = False
        self._ai_inline_review: Optional[InlineReviewState] = None
        self._ai_inline_response: Optional[ValidatedResponse] = None
        self._ai_inline_reference_values: Dict[str, List[str]] = {}
        self._ai_inline_baseline_values: Dict[str, Any] = {}
        self._ai_inline_field_controls: Dict[str, tk.Frame] = {}
        self._ai_inline_badges: Dict[str, tk.Label] = {}
        self._ai_inline_buttons: Dict[str, tuple[tk.Button, tk.Button]] = {}
        self._ai_inline_footer: Optional[tk.Frame] = None
        self._ai_inline_approve_all_btn: Optional[ttk.Button] = None
        self._ai_inline_reject_all_btn: Optional[ttk.Button] = None
        self._ai_inline_refine_btn: Optional[ttk.Button] = None
        self._ai_inline_warnings_btn: Optional[ttk.Button] = None
        self._last_submit_failure: Optional[Dict[str, Any]] = None
        super().__init__(master, app, **kwargs)

    # ------------------------------------------------------------------
    # Построение
    # ------------------------------------------------------------------

    def _build(self) -> None:
        self._form: BaseForm = FormRegistry().get(self._form_id)
        self._form.tfs_service      = self.app.tfs_service
        self._form.itsm_service     = self.app.itsm_service
        self._form.gravitee_service = self.app.gravitee_service
        self._form.screen           = self
        self._form.current_environment = self.app.current_environment.get()

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
        canvas.bind("<Configure>", self._centered_resize(canvas, _win, max_width=760))
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
        """Возвращает поля (включая sub-поля BLOCK), для которых потребуется HTTP-запрос."""
        from config.reference_cache_config import CACHE_TTL, TTL_INFINITE
        result = []

        def _check(field: FieldDefinition) -> None:
            if field.field_type not in (FieldType.SELECT, FieldType.MULTISELECT):
                return
            if field.reference is None or field.reference.source != "http":
                return
            if field.depends_on:  # зависимые справочники загружаются лениво
                return
            resource = field.reference.resource
            ttl = CACHE_TTL.get(resource)
            if ttl is None:
                result.append(field)
                return
            ts = self.app.reference_cache.get_timestamp(resource, env)
            if ts is None:
                result.append(field)
                return
            if ttl != TTL_INFINITE and time.time() - ts > ttl:
                result.append(field)

        for field in self._form.fields:
            _check(field)
            if field.field_type == FieldType.BLOCK:
                for sf in field.block_fields:
                    _check(sf)
        return result

    def _render_with_loading(self, env: str, to_load: List[FieldDefinition]) -> None:
        """Прогревает кеш HTTP-справочников в фоне, затем рендерит поля."""
        def _worker() -> None:
            for field in to_load:
                try:
                    self.app.reference_resolver.resolve(field.reference, env)  # type: ignore[arg-type]
                except Exception as exc:
                    print(f"[FormScreen] Ошибка предзагрузки '{field.key}': {exc}")

        show_loading(
            self, "Загрузка справочников…",
            worker=_worker,
            on_done=lambda _: self._render_fields(self._fields_frame),
        )

    def _route_mousewheel(self, event: tk.Event) -> Optional[str]:
        """
        Глобальный обработчик колеса мыши.
        Если курсор над виджетом с меткой _scroll_target — скроллим его,
        иначе скроллим основной канвас формы.
        """
        try:
            # bind_all видит также события дочерних Toplevel. Они принадлежат
            # собственным диалогам и не должны прокручивать форму под ними.
            if str(event.widget.winfo_toplevel()) != str(self.winfo_toplevel()):
                return "break"
        except (AttributeError, tk.TclError):
            return None
        delta = getattr(event, "delta", 0)
        if not delta:
            return None
        units = int(-1 * (delta / 120))
        if units == 0:
            units = -1 if delta > 0 else 1
        w = event.widget
        while w is not None:
            target = getattr(w, "_scroll_target", None)
            if target is not None:
                target.yview_scroll(units, "units")
                return "break"
            try:
                w = w.master
            except AttributeError:
                break
        self._scroll_canvas.yview_scroll(units, "units")
        return "break"

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
            self._field_label_rows[field_def.key] = label_row

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
                    text=" ↻ ",
                    font=theme.F["body"],
                    bg=theme.C["surface"],
                    fg=theme.C["primary"],
                    activebackground=theme.C["ghost_h"],
                    activeforeground=theme.C["primary"],
                    relief="flat", bd=0,
                    cursor="hand2",
                    padx=2,
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
                    text=" + ",
                    font=theme.F["body"],
                    bg=theme.C["surface"],
                    fg=theme.C["primary"],
                    activebackground=theme.C["ghost_h"],
                    activeforeground=theme.C["primary"],
                    relief="flat", bd=0,
                    cursor="hand2",
                    padx=4,
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

        # Восстановление сохранённых данных (до расчёта условий)
        if self._initial_data:
            self.apply_form_data(self._initial_data)

        # Настраиваем условную видимость и зависимые справочники
        self._setup_conditional_fields()
        self._setup_dependent_fields()
        self._ready = True
        if self._ai_autostart_pending:
            self._ai_autostart_pending = False
            self.after(100, self._start_routed_ai_autofill)

    def _build_footer(self) -> None:
        theme.separator(self, pady=6)

        foot = tk.Frame(self, bg=theme.C["bg"])
        foot.pack(fill=tk.X)
        self._footer = foot
        normal = tk.Frame(foot, bg=theme.C["bg"])
        normal.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._normal_footer = normal

        self._submit_button = ttk.Button(
            normal, text="  Отправить  →",
            style="Primary.TButton",
            command=self._on_submit,
        )
        self._submit_button.pack(side=tk.LEFT, padx=(0, 8))

        self._json_preview_button = ttk.Button(
            normal, text="{ } Просмотр JSON",
            style="Secondary.TButton",
            command=self._preview_payload,
        )
        self._json_preview_button.pack(side=tk.LEFT)

        if hasattr(self.app, "opencode_manager"):
            ttk.Button(
                normal, text="✨ Подтянуть данные из заявки",
                style="Secondary.TButton",
                command=self._on_ai_autofill,
            ).pack(side=tk.LEFT, padx=(8, 0))
        elif self._form.itsm_support:
            # Совместимость для встраиваний, которые ещё не создают OpenCodeManager.
            ttk.Button(
                normal, text="⬇ Подтянуть из заявки", style="Secondary.TButton",
                command=self._on_fetch_from_itsm,
            ).pack(side=tk.LEFT, padx=(8, 0))

        for btn_def in self._form.get_custom_buttons():
            style = "Primary.TButton" if btn_def.style.lower() == "primary" else "Secondary.TButton"
            ttk.Button(
                normal,
                text=btn_def.label,
                style=style,
                command=lambda h=btn_def.handler: h(
                    self.app.current_environment.get(),
                ),
            ).pack(side=tk.LEFT, padx=(8, 0))

        self._diagnose_submit_btn = ttk.Button(
            normal,
            text="✨ Разобрать ошибку с AI",
            style="Secondary.TButton",
            command=self._open_submit_diagnostics,
        )

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
        self._refresh_conditional_fields()

    def _refresh_conditional_fields(self) -> None:
        """Пересчитывает видимость условных полей при изменении любого поля."""
        values = {key: fw.get() for key, fw in self._field_widgets.items()}

        # Вычисляем целевую видимость для условных полей
        visibility: Dict[str, bool] = {}
        changed = False
        for field_def in self._form.fields:
            if field_def.condition is None:
                continue
            outer = self._field_containers.get(field_def.key)
            should_show = field_def.condition(values)
            visibility[field_def.key] = should_show
            if outer and should_show != bool(outer.winfo_manager()):
                changed = True

        if not changed:
            return

        # Перепакуем все контейнеры в правильном порядке.
        # Для условных полей — используем visibility; для остальных — всегда видимы.
        for key in self._field_order:
            outer = self._field_containers.get(key)
            if outer is None:
                continue
            outer.pack_forget()
            if visibility.get(key, True):
                outer.pack(fill=tk.X, pady=3, padx=2)

    # ------------------------------------------------------------------
    # Справочники
    # ------------------------------------------------------------------

    def _on_destroy(self, event: tk.Event) -> None:
        if event.widget is self:
            self._cancel_ai_operation()
            self.app.release_execution_plan_step(
                self._ai_plan_id,
                self._ai_plan_step_id,
            )
            if self._ai_poll_id is not None:
                try:
                    self.after_cancel(self._ai_poll_id)
                except tk.TclError:
                    pass
            if self._ai_assistant is not None:
                self._ai_assistant.close()
            try:
                self.app.current_environment.trace_remove("write", self._env_trace_id)
            except Exception:
                pass

    def _on_env_changed(self) -> None:
        """Вызывается при смене окружения. Перезагружает HTTP-справочники."""
        new_env = self.app.current_environment.get()
        self._form.current_environment = new_env
        if not self._ready:
            return
        if self._ai_inline_review is not None:
            self._clear_inline_ai_review(restore=True)
            self._close_ai_agent_session()
            self.app.mark_execution_plan_step(
                self._ai_plan_id,
                self._ai_plan_step_id,
                "pending",
            )
            self._set_status(
                "AI-предложения сброшены: окружение формы изменилось.",
                "muted",
            )
        # Верхнеуровневые HTTP SELECT/MULTISELECT
        direct_http = [
            f for f in self._form.fields
            if f.field_type in (FieldType.SELECT, FieldType.MULTISELECT)
            and f.reference is not None
            and f.reference.source == "http"
        ]
        # BLOCK-поля с HTTP sub-полями (перестраиваем блок целиком)
        block_with_http = [
            f for f in self._form.fields
            if f.field_type == FieldType.BLOCK
            and any(
                sf.field_type in (FieldType.SELECT, FieldType.MULTISELECT)
                and sf.reference is not None
                and sf.reference.source == "http"
                for sf in f.block_fields
            )
        ]

        # Зависимые поля перегружаем отдельно — только если родитель уже выбран.
        # _rebuild_reference_widget автоматически подхватит текущее значение родителя.
        for f in direct_http:
            if f.depends_on:
                parent_fw = self._field_widgets.get(f.depends_on)
                if parent_fw and parent_fw.get():
                    self._rebuild_reference_widget(f)

        all_to_rebuild = [f for f in direct_http if not f.depends_on] + block_with_http
        if not all_to_rebuild:
            return

        to_load = self._fields_needing_http(new_env)
        if to_load:
            self._reload_env_with_loading(new_env, to_load, all_to_rebuild)
        else:
            for field in all_to_rebuild:
                self._rebuild_reference_widget(field)

    def _rebuild_reference_widget(
        self,
        field_def: FieldDefinition,
        extra_params: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Пересоздаёт виджет справочника (данные уже в кеше — без диалога)."""
        # Зависимый справочник: если extra_params не передан явно,
        # берём нужное поле из текущего выбранного элемента родителя
        if extra_params is None and field_def.depends_on:
            parent_fw = self._field_widgets.get(field_def.depends_on)
            if parent_fw:
                if field_def.depends_on_field:
                    val = parent_fw.get_extra(field_def.depends_on_field)
                else:
                    val = parent_fw.get()
                if val:
                    extra_params = {field_def.depends_on: val}

        key = field_def.key
        old_fw = self._field_widgets.get(key)
        if old_fw is not None:
            old_fw.widget.destroy()
        inner = self._field_inner_frames.get(key)
        if inner is None:
            return
        new_items = self._load_reference(field_def, extra_params)
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
        # Переподписываем зависимых детей, если этот виджет является родителем
        self._subscribe_dependent_children(key, fw)

    def _subscribe_dependent_children(self, parent_key: str, fw: "FieldWidget") -> None:
        """Подписывает fw на перезагрузку зависимых справочников при смене его значения.
        Обрабатывает как верхнеуровневые поля, так и sub-поля внутри BLOCK."""
        children = self._dependent_fields.get(parent_key, [])
        block_children = self._block_dependent_fields.get(parent_key, [])

        if not children and not block_children:
            return

        def _on_change() -> None:
            pfw = self._field_widgets.get(parent_key)
            if pfw is None:
                return
            # Верхнеуровневые зависимые поля
            for child in children:
                if child.depends_on_field:
                    val = pfw.get_extra(child.depends_on_field)
                else:
                    val = pfw.get()
                ep = {parent_key: val} if val else None
                self._rebuild_reference_widget(child, ep)
            # Sub-поля BLOCK с зависимым справочником
            for block_def, sub_def in block_children:
                if sub_def.depends_on_field:
                    val = pfw.get_extra(sub_def.depends_on_field)
                else:
                    val = pfw.get()
                ep = {parent_key: val} if val else None
                new_items = self._load_reference(sub_def, ep)
                block_fw = self._field_widgets.get(block_def.key)
                if block_fw:
                    block_fw.refresh_sub_ref(sub_def.key, new_items)

        widget = fw.widget
        if isinstance(widget, ttk.Combobox):
            widget.bind("<<ComboboxSelected>>", lambda *_: _on_change())
        else:
            fw.bind_change(_on_change)

    def _setup_dependent_fields(self) -> None:
        """
        Строит таблицу зависимостей и подписывается на изменения родительских полей.
        Зависимое поле объявляется через depends_on="parent_key" в FieldDefinition.
        Поддерживаются как верхнеуровневые поля, так и sub-поля внутри BLOCK.
        Вызывается один раз после рендера всех полей.
        """
        from collections import defaultdict
        dep_map: Dict[str, List[FieldDefinition]] = defaultdict(list)
        block_dep_map: Dict[str, List] = defaultdict(list)

        for f in self._form.fields:
            if f.depends_on and f.field_type in (FieldType.SELECT, FieldType.MULTISELECT):
                dep_map[f.depends_on].append(f)
            if f.field_type == FieldType.BLOCK:
                for sf in f.block_fields:
                    if sf.depends_on and sf.field_type in (FieldType.SELECT, FieldType.MULTISELECT):
                        block_dep_map[sf.depends_on].append((f, sf))

        if not dep_map and not block_dep_map:
            return

        self._dependent_fields = dict(dep_map)
        self._block_dependent_fields = dict(block_dep_map)

        all_parents = set(list(dep_map.keys()) + list(block_dep_map.keys()))
        for parent_key in all_parents:
            parent_fw = self._field_widgets.get(parent_key)
            if parent_fw is not None:
                self._subscribe_dependent_children(parent_key, parent_fw)

    def _reload_env_with_loading(
        self,
        env: str,
        to_load: List[FieldDefinition],
        all_http: List[FieldDefinition],
    ) -> None:
        """Грузит промахи кеша в фоне, затем перестраивает все HTTP-поля."""
        def _worker() -> None:
            for field in to_load:
                try:
                    self.app.reference_resolver.resolve(field.reference, env)  # type: ignore[arg-type]
                except Exception as exc:
                    print(f"[FormScreen] Ошибка предзагрузки '{field.key}': {exc}")

        show_loading(
            self, "Загрузка справочников…",
            worker=_worker,
            on_done=lambda _: [self._rebuild_reference_widget(f) for f in all_http],
        )

    def _load_reference(
        self,
        field_def: FieldDefinition,
        extra_params: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        if field_def.field_type not in (FieldType.SELECT, FieldType.MULTISELECT):
            return []
        if field_def.reference is None:
            return []
        # Зависимый справочник без значения родителя — возвращаем пустой список,
        # не делаем запрос с незаполненным URL-шаблоном
        if field_def.depends_on and not extra_params:
            return []
        try:
            env = self.app.current_environment.get()
            return self.app.reference_resolver.resolve(field_def.reference, env, extra_params)
        except Exception as exc:
            print(f"[FormScreen] Ошибка загрузки справочника '{field_def.key}': {exc}")
            return []

    def _reload_reference_field(self, field_def: FieldDefinition, btn: tk.Button) -> None:
        """Показывает диалог подтверждения, затем инвалидирует кеш и перезагружает справочник."""
        assert field_def.reference is not None
        resource = field_def.reference.resource
        env = self.app.current_environment.get()

        cached_ts = self.app.reference_cache.get_timestamp(resource, env)
        if not show_refresh_confirm(self, field_def.label, {env: cached_ts}):
            return

        btn.config(state=tk.DISABLED, fg=theme.C["text_muted"])

        def _worker() -> List[Dict[str, Any]]:
            self.app.reference_cache.invalidate(resource, env)
            ref = field_def.reference
            assert ref is not None
            return self.app.reference_resolver.resolve(ref, env)

        show_loading(
            self, f"Обновляется «{field_def.label}»…",
            worker=_worker,
            on_done=lambda items: self._finish_reload(field_def, btn, items, None),
            on_error=lambda exc: self._finish_reload(field_def, btn, [], str(exc)),
        )

    def _finish_reload(
        self,
        field_def: FieldDefinition,
        btn: tk.Button,
        new_items: List[Dict[str, Any]],
        error: str | None,
    ) -> None:
        """Вызывается в главном потоке: пересоздаёт виджет справочника."""
        def _restore_btn() -> None:
            try:
                if btn.winfo_exists():
                    btn.config(state=tk.NORMAL, fg=theme.C["primary"])
            except tk.TclError:
                pass

        if error:
            _restore_btn()
            show_error(
                self,
                "Ошибка обновления",
                f"Не удалось обновить справочник «{field_def.label}»:\n{error}",
            )
            return

        key = field_def.key

        # Sub-поле внутри BLOCK: пересоздаём весь блок, сохранив значения
        if key not in self._field_inner_frames:
            parent_block = next(
                (f for f in self._form.fields
                 if f.field_type == FieldType.BLOCK
                 and any(sf.key == key for sf in f.block_fields)),
                None,
            )
            if parent_block is not None:
                bkey = parent_block.key
                block_fw = self._field_widgets.get(bkey)
                saved = block_fw.get() if block_fw else {}
                if block_fw is not None:
                    block_fw.widget.destroy()
                inner = self._field_inner_frames.get(bkey)
                if inner is not None:
                    new_block_fw = self._factory.create(
                        inner, parent_block, [],
                        ref_loader=self._load_reference,
                        on_refresh=self._reload_reference_field,
                    )
                    new_block_fw.widget.pack(fill=tk.X, padx=12, pady=(0, 10))
                    self._field_widgets[bkey] = new_block_fw
                    if saved:
                        new_block_fw.set(saved)
            _restore_btn()
            show_info(
                self,
                "Обновление завершено",
                f"Справочник «{field_def.label}» успешно обновлён.\n"
                f"Загружено элементов: {len(new_items)}.",
            )
            return

        # Top-level поле: пересоздаём виджет напрямую
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
        # Переподписываем зависимых детей, если этот виджет является родителем
        self._subscribe_dependent_children(key, fw)

        _restore_btn()

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
        if self._ai_inline_review is not None:
            show_warning(
                self,
                "Проверьте AI-предложения",
                "Перед отправкой подтвердите или отклоните предложенные значения.",
            )
            return
        form_data = self._collect_form_data()
        environment = self.app.current_environment.get()

        # Предварительная валидация — до диалога подтверждения
        errors = self._form.validate(form_data)
        if errors:
            self._set_status(f"✗  {errors[0]}", "error")
            show_error(
                self,
                "Ошибка заполнения",
                "\n".join(str(error) for error in errors),
            )
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

        def _worker():
            return self.app.submit_service.submit(self._form, form_data, environment)

        def _done(result) -> None:
            if result.success:
                self._set_status(f"✓  {result.message}", "success")
                fields_snapshot = {f.key: f.field_type.value for f in self._form.fields}
                self.app.run_storage.save(
                    form_id=self._form.form_id,
                    environment=environment,
                    form_data=form_data,
                    fields_snapshot=fields_snapshot,
                )
                self.app.mark_execution_plan_step(
                    self._ai_plan_id,
                    self._ai_plan_step_id,
                    "completed",
                )
                from ui.screens.result_screen import ResultScreen
                self.app.navigate_to(
                    ResultScreen,
                    form=self._form,
                    environment=environment,
                    initial_response=result.raw_response,
                    submit_payload=result.payload,
                )
            else:
                self._remember_submit_failure(
                    error=result.message,
                    response=result.raw_response,
                    form_data=form_data,
                )
                self.app.mark_execution_plan_step(
                    self._ai_plan_id,
                    self._ai_plan_step_id,
                    "failed",
                    result.message,
                )
                self._set_status(f"✗  {result.message.splitlines()[0]}", "error")
                show_error(self, "Ошибка отправки", result.message)

        show_loading(
            self, "Отправка…",
            worker=_worker,
            on_done=_done,
            on_error=self._handle_submit_exception,
        )

    def _remember_submit_failure(
        self,
        *,
        error: Any,
        response: Any,
        form_data: Dict[str, Any],
    ) -> None:
        try:
            payload = self._form.build_payload(form_data)
        except Exception as exc:
            payload = {"_payload_build_error": type(exc).__name__}
        self._last_submit_failure = {
            "error": error,
            "response": response,
            "payload": payload,
        }
        if hasattr(self, "_diagnose_submit_btn"):
            self._diagnose_submit_btn.pack(side=tk.RIGHT, padx=(8, 0))

    def _handle_submit_exception(self, exc: Exception) -> None:
        form_data = self._collect_form_data()
        self._remember_submit_failure(
            error=str(exc), response=None, form_data=form_data
        )
        self.app.mark_execution_plan_step(
            self._ai_plan_id,
            self._ai_plan_step_id,
            "failed",
            str(exc),
        )
        self._set_status(f"✗  {exc}", "error")
        show_error(self, "Ошибка отправки", str(exc))

    def _open_submit_diagnostics(self) -> None:
        failure = self._last_submit_failure
        if not failure:
            return
        self.app.open_ai_diagnostics(
            form_id=self._form.form_id,
            environment=self.app.current_environment.get(),
            error=failure["error"],
            response=failure["response"],
            payload=failure["payload"],
        )

    def _preview_payload(self) -> None:
        if self._ai_inline_review is not None:
            show_warning(
                self,
                "Проверьте AI-предложения",
                "Сначала подтвердите или отклоните предложенные значения.",
            )
            return
        form_data = self._collect_form_data()
        errors = self._form.validate(form_data)
        if errors:
            show_warning(
                self,
                "Валидация",
                "\n".join(str(error) for error in errors),
            )
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
        self._field_label_rows[new_key] = label_row

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
        self._field_label_rows.pop(key, None)
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
    # AI ITSM + Azure DevOps интеграция
    # ------------------------------------------------------------------

    def _start_routed_ai_autofill(self) -> None:
        context = self._ai_prepared_context
        self._ai_prepared_context = None
        if context is not None:
            self._on_ai_autofill(
                ticket_id=context.ticket_id,
                prepared_context=context,
            )

    def _on_ai_autofill(
        self,
        ticket_id: Optional[str] = None,
        prepared_context: Optional[BuiltContext] = None,
    ) -> None:
        """Открывает управляемую chat-session; форма пока не меняется."""
        if self._ai_agent is not None:
            show_warning(
                self,
                "AI-автозаполнение",
                "Предыдущая OpenCode session ещё открыта.",
            )
            return
        if not self._ready:
            show_warning(self, "AI-автозаполнение", "Дождитесь загрузки полей формы.")
            return
        client = self.app.opencode_manager.client
        if client is None:
            status = self.app.opencode_manager.status
            show_error(
                self,
                "OpenCode недоступен",
                f"AI-автозаполнение сейчас отключено.\n\n{status.message}\n\n"
                "Откройте OpenCode на главном экране и подключитесь к серверу.",
            )
            return
        if ticket_id is None:
            ticket_id = ask_ticket_id(self)
            if ticket_id is None:
                return

        settings = self.app.env_manager.load()
        provider_id = (
            self._ai_provider_id
            or settings.get(OPENCODE_PROVIDER_ID_KEY, "").strip()
        )
        model_id = (
            self._ai_model_id
            or settings.get(OPENCODE_MODEL_ID_KEY, "").strip()
        )
        variant = self._ai_variant if self._ai_model_id else ""
        try:
            max_context = int(
                settings.get(OPENCODE_MAX_CONTEXT_CHARS_KEY, "120000")
            )
        except ValueError:
            max_context = 120_000
        try:
            inline_max_items = int(settings.get(
                OPENCODE_REFERENCE_INLINE_MAX_ITEMS_KEY,
                str(DEFAULT_INLINE_REFERENCE_MAX_ITEMS),
            ))
            inline_max_bytes = int(settings.get(
                OPENCODE_REFERENCE_INLINE_MAX_BYTES_KEY,
                str(DEFAULT_INLINE_REFERENCE_MAX_BYTES),
            ))
            inline_total_bytes = int(settings.get(
                OPENCODE_REFERENCE_INLINE_TOTAL_BYTES_KEY,
                str(DEFAULT_INLINE_REFERENCE_TOTAL_BYTES),
            ))
            if not 1 <= inline_max_items <= 10_000:
                raise ValueError
            if not 256 <= inline_max_bytes <= 2 * 1024 * 1024:
                raise ValueError
            if not inline_max_bytes <= inline_total_bytes <= 4 * 1024 * 1024:
                raise ValueError
        except (TypeError, ValueError):
            inline_max_items = DEFAULT_INLINE_REFERENCE_MAX_ITEMS
            inline_max_bytes = DEFAULT_INLINE_REFERENCE_MAX_BYTES
            inline_total_bytes = DEFAULT_INLINE_REFERENCE_TOTAL_BYTES
        allowed_mcp = self._parse_allowed_mcp(
            settings.get(OPENCODE_ALLOWED_MCP_KEY, "")
        )
        repository_mcp = settings.get(OPENCODE_REPOSITORY_MCP_KEY, "").strip()
        allow_repository_git_pull = setting_enabled(
            settings.get(OPENCODE_REPOSITORY_GIT_PULL_KEY, "true")
        )
        environment = self.app.current_environment.get()
        current_values = self._collect_form_data()
        extraction = self._ai_extraction
        self._ai_extraction = None
        if extraction is not None and extraction.form_id != self._form.form_id:
            _log.warning(
                "ignored extractor directive form=%s current_form=%s",
                extraction.form_id,
                self._form.form_id,
            )
            extraction = None
        extractor_mode = extraction.mode if extraction is not None else "research"
        field_proposals = [
            {
                "field_key": item.field_key,
                "value": item.value,
                "source": item.source,
                "confidence": item.confidence,
            }
            for item in (extraction.field_proposals if extraction else ())
        ]
        plan_guidance = self._ai_plan_guidance
        if extraction is not None and extraction.mode == "research":
            directive_guidance = {
                "mode": extraction.mode,
                "known_field_values": field_proposals,
                "missing_information": list(extraction.missing_information),
                "research_goal": extraction.research_goal,
            }
            plan_guidance = (
                f"{plan_guidance}\n" if plan_guidance else ""
            ) + (
                "Validated Copilot extraction directive:\n"
                + json.dumps(directive_guidance, ensure_ascii=False)
            )
        cancel_event = threading.Event()
        result_queue: "queue.Queue[tuple[str, Any]]" = queue.Queue()
        agent = FormExtractorAgent(
            client,
            self.app.itsm_service,
            self.app.tfs_service,
            reference_resolver=self.app.reference_resolver,
            max_context_chars=max_context,
            inline_reference_max_items=inline_max_items,
            inline_reference_max_bytes=inline_max_bytes,
            inline_reference_total_bytes=inline_total_bytes,
        )
        self._ai_cancel_event = cancel_event
        self._ai_queue = result_queue
        self._ai_agent = agent
        self._ai_session_id = None
        self._ai_busy = True
        self._ai_assistant = AIAssistantDialog(
            self,
            mode=extractor_mode,
            thinking_level=variant,
            thinking_auto=self._ai_thinking_auto,
            on_send=self._send_ai_guidance,
            on_finalize=self._finalize_ai_session,
            on_stop=self._stop_ai_request,
            on_cancel=self._cancel_ai_operation,
            on_permission=self._answer_ai_permission,
        )

        def progress(message: str) -> None:
            result_queue.put(("progress", message))

        def conversation_event(event: ConversationEvent) -> None:
            result_queue.put(("conversation", event))

        def session_changed(session_id: Optional[str]) -> None:
            result_queue.put(("session", session_id))

        if extractor_mode == "fill_only":
            self._start_ai_worker(
                "fast_final",
                lambda: agent.fill_only(
                    form=self._form,
                    ticket_id=ticket_id,
                    environment=environment,
                    current_values=current_values,
                    field_proposals=field_proposals,
                    provider_id=provider_id,
                    model_id=model_id,
                    variant=variant,
                    cancel_event=cancel_event,
                    prepared_context=prepared_context,
                    on_progress=progress,
                    on_event=conversation_event,
                    on_session=session_changed,
                ),
            )
        else:
            self._start_ai_worker(
                "begin",
                lambda: agent.begin(
                    form=self._form,
                    ticket_id=ticket_id,
                    environment=environment,
                    current_values=current_values,
                    allowed_mcp=allowed_mcp,
                    repository_mcp=repository_mcp,
                    allow_repository_git_pull=allow_repository_git_pull,
                    plan_guidance=plan_guidance,
                    provider_id=provider_id,
                    model_id=model_id,
                    variant=variant,
                    cancel_event=cancel_event,
                    prepared_context=prepared_context,
                    on_progress=progress,
                    on_event=conversation_event,
                    on_session=session_changed,
                ),
            )
        self._poll_ai_queue()

    def _start_ai_worker(
        self,
        action: str,
        operation,
    ) -> None:
        result_queue = self._ai_queue
        dialog = self._ai_assistant
        if result_queue is None or (
            dialog is None and self._ai_inline_review is None
        ):
            return
        self._ai_busy = True
        if self._ai_cancel_event is not None:
            self._ai_cancel_event.clear()
        if dialog is not None:
            dialog.set_busy(True)
        self._set_inline_review_busy(True)

        def worker() -> None:
            try:
                value = operation()
            except Exception as exc:
                result_queue.put(("error", (action, exc)))
            else:
                result_queue.put((action, value))

        threading.Thread(
            target=worker,
            name=f"opencode-form-{action}",
            daemon=True,
        ).start()

    def _send_ai_guidance(self, message: str) -> None:
        if self._ai_busy or self._ai_agent is None:
            return
        self._start_ai_worker(
            "guidance",
            lambda: self._ai_agent.send_guidance(message),
        )

    def _finalize_ai_session(self) -> None:
        if self._ai_busy or self._ai_agent is None:
            return
        self._start_ai_worker("final", self._ai_agent.finalize)

    def _stop_ai_request(self) -> None:
        if not self._ai_busy or self._ai_agent is None:
            return
        if self._ai_cancel_event is not None:
            self._ai_cancel_event.set()
        if self._ai_assistant is not None:
            self._ai_assistant.set_status("Останавливаю текущий запрос…")

        agent = self._ai_agent
        threading.Thread(
            target=agent.cancel,
            name="opencode-form-abort",
            daemon=True,
        ).start()

    def _answer_ai_permission(self, permission_id: str, allow: bool) -> None:
        agent = self._ai_agent
        result_queue = self._ai_queue
        if agent is None or result_queue is None:
            return

        def worker() -> None:
            try:
                agent.approve_permission(permission_id, allow=allow)
            except Exception as exc:
                result_queue.put(("permission_error", (permission_id, allow, exc)))
            else:
                result_queue.put(("permission_answered", (permission_id, allow)))

        threading.Thread(
            target=worker,
            name="opencode-permission-response",
            daemon=True,
        ).start()

    def _cancel_ai_operation(self) -> None:
        """Закрывает всю AI-session; ни одно значение формы не применяется."""
        agent = self._ai_agent
        if agent is None:
            return
        if self._ai_cancel_event is not None:
            self._ai_cancel_event.set()
        dialog = self._ai_assistant
        if dialog is not None:
            dialog.close()
        self._set_status("AI-предложения не применены", "muted")
        self.app.mark_execution_plan_step(
            self._ai_plan_id,
            self._ai_plan_step_id,
            "pending",
        )
        self._clear_ai_state()

        def cleanup() -> None:
            agent.cancel()
            agent.close()

        threading.Thread(
            target=cleanup,
            name="opencode-form-cancel",
            daemon=True,
        ).start()

    def detach_ai_for_shutdown(self) -> Optional[FormExtractorAgent]:
        """Отделяет session от Tk; сетевую очистку выполнит shutdown-worker."""
        agent = self._ai_agent
        if agent is None:
            return None
        if self._ai_cancel_event is not None:
            self._ai_cancel_event.set()
        if self._ai_assistant is not None:
            self._ai_assistant.close()
        self._clear_ai_state()
        return agent

    def _poll_ai_queue(self) -> None:
        result_queue = self._ai_queue
        if result_queue is None:
            return
        final_payload: Optional[tuple[Any, Dict[str, List[str]]]] = None
        try:
            while True:
                event, payload = result_queue.get_nowait()
                dialog = self._ai_assistant
                if event == "progress":
                    if dialog is not None:
                        dialog.set_status(str(payload))
                    elif self._ai_inline_review is not None:
                        self._set_status(f"✨  {payload}", "muted")
                elif event == "conversation" and dialog is not None:
                    dialog.append_event(payload)
                elif event == "session":
                    self._ai_session_id = (
                        str(payload) if payload is not None else None
                    )
                    if dialog is not None:
                        dialog.set_session(self._ai_session_id)
                elif event in {"begin", "guidance"}:
                    self._ai_busy = False
                    if dialog is not None:
                        dialog.append_message(
                            "assistant",
                            payload.text,
                            opencode_seconds=opencode_message_duration(payload.info),
                            generation_seconds=opencode_text_generation_duration(
                                payload.parts
                            ),
                        )
                        dialog.set_status(
                            "Готов к уточнениям или переносу предложений в форму."
                        )
                        dialog.set_busy(False)
                elif event in {"final", "fast_final", "refine"}:
                    agent = self._ai_agent
                    refs = agent.reference_values if agent is not None else {}
                    final_payload = (payload, refs)
                elif event == "permission_answered" and dialog is not None:
                    permission_id, allow = payload
                    dialog.permission_answered(str(permission_id), bool(allow))
                elif event == "permission_error" and dialog is not None:
                    permission_id, allow, error = payload
                    dialog.permission_answered(
                        str(permission_id), bool(allow), str(error)
                    )
                elif event == "error":
                    action, error = payload
                    self._handle_ai_error(str(action), error)
        except queue.Empty:
            pass

        if final_payload is not None:
            self._finish_ai_result(*final_payload)
            return
        if self._ai_queue is not None:
            try:
                self._ai_poll_id = self.after(100, self._poll_ai_queue)
            except tk.TclError:
                pass

    def _handle_ai_error(self, action: str, error: Exception) -> None:
        dialog = self._ai_assistant
        self._ai_busy = False
        self._set_inline_review_busy(False)
        if self._ai_cancel_event is not None:
            self._ai_cancel_event.clear()
        if isinstance(error, OpenCodeCancelled):
            if self._ai_inline_review is not None:
                self._set_status(
                    "Уточнение остановлено. Предыдущие AI-предложения сохранены.",
                    "muted",
                )
                return
            if dialog is None:
                return
            if action in {"begin", "fast_final"} and (
                self._ai_agent is None or self._ai_agent.session_id is None
            ):
                dialog.close()
                self._clear_ai_state()
                self._set_status("Операция AI-автозаполнения отменена", "muted")
                return
            dialog.append_event(ConversationEvent(
                "warning",
                "Запрос остановлен",
                "Сессия сохранена: можно отправить уточнение или повторить результат.",
            ))
            dialog.set_status("Текущий запрос остановлен.")
            dialog.set_busy(False)
            return
        _log.error(
            "form assistant failed action=%s error_type=%s",
            action,
            type(error).__name__,
        )
        if self._ai_inline_review is not None:
            self._set_status(
                f"✗  Не удалось уточнить предложения: {str(error).splitlines()[0]}",
                "error",
            )
            show_error(self, "Ошибка AI-уточнения", str(error))
            return
        if dialog is None:
            return
        if action in {"begin", "fast_final"} and (
            self._ai_agent is None or self._ai_agent.session_id is None
        ):
            dialog.close()
            self._clear_ai_state()
            show_error(self, "Ошибка AI-автозаполнения", str(error))
            self._set_status(f"✗  {str(error).splitlines()[0]}", "error")
            return
        title = (
            "Ошибка JSON-ответа"
            if isinstance(error, OpenCodeStructuredOutputError)
            else f"Ошибка этапа {action}"
        )
        dialog.append_event(ConversationEvent("error", title, str(error)))
        dialog.set_status(str(error).splitlines()[0], error=True)
        dialog.set_busy(False)

    def _finish_ai_result(
        self,
        result: ValidatedResponse,
        reference_values: Dict[str, List[str]],
    ) -> None:
        dialog = self._ai_assistant
        if dialog is not None:
            dialog.close()
            self._ai_assistant = None
        self._ai_busy = False
        if self._ai_cancel_event is not None:
            self._ai_cancel_event.clear()
        self._show_inline_ai_review(result, reference_values)

    def _show_inline_ai_review(
        self,
        result: ValidatedResponse,
        reference_values: Dict[str, List[str]],
    ) -> None:
        if self._ai_inline_review is not None:
            self._clear_inline_ai_review(restore=True)

        current_values = self._collect_form_data()
        review = InlineReviewState(result.preview_fields, current_values)
        if not review.items:
            self._close_ai_agent_session()
            self.app.mark_execution_plan_step(
                self._ai_plan_id,
                self._ai_plan_step_id,
                "pending",
            )
            self._set_status(
                "OpenCode не предложил изменений относительно текущей формы.",
                "muted",
            )
            return

        self._ai_inline_review = review
        self._ai_inline_response = result
        self._ai_inline_reference_values = {
            key: list(values) for key, values in reference_values.items()
        }
        self._ai_inline_baseline_values = dict(current_values)

        # The values become visible in the real widgets, but submission stays
        # disabled until every proposal has an explicit decision.
        self.apply_form_data({
            item.field.key: item.proposed_value for item in review.items
        })
        for item in review.items:
            self._build_inline_field_controls(item.field.key)
        self._build_inline_review_footer()
        warning_suffix = (
            f" · предупреждений: {len(result.warnings)}"
            if result.warnings
            else ""
        )
        self._set_status(
            f"✨  AI подставил {len(review.items)} значений{warning_suffix}. "
            "Подтвердите ✓ или отклоните ✕.",
            "muted",
        )
        _log.info(
            "inline review opened form=%s session=%s fields=%d warnings=%d",
            self._form.form_id,
            self._ai_session_id or "none",
            len(review.items),
            len(result.warnings),
        )

    def _build_inline_field_controls(self, key: str) -> None:
        review = self._ai_inline_review
        label_row = self._field_label_rows.get(key)
        if review is None or label_row is None:
            return
        item = review.get(key)
        controls = tk.Frame(label_row, bg=theme.C["surface"])
        controls.pack(side=tk.RIGHT, padx=(8, 0))

        reject = tk.Button(
            controls,
            text="✕",
            width=3,
            font=("Segoe UI", 10, "bold"),
            bg=theme.C["chat_error"],
            fg=theme.C["error"],
            activebackground="#FECACA",
            activeforeground=theme.C["error"],
            relief="flat",
            bd=0,
            cursor="hand2",
            command=lambda field_key=key: self._decide_inline_field(
                field_key, False
            ),
        )
        reject.pack(side=tk.RIGHT, padx=(3, 0))
        approve = tk.Button(
            controls,
            text="✓",
            width=3,
            font=("Segoe UI", 10, "bold"),
            bg=theme.C["success_soft"],
            fg=theme.C["success"],
            activebackground="#BBF7D0",
            activeforeground=theme.C["success"],
            relief="flat",
            bd=0,
            cursor="hand2",
            command=lambda field_key=key: self._decide_inline_field(
                field_key, True
            ),
        )
        approve.pack(side=tk.RIGHT, padx=(3, 0))
        source = (item.field.source or "источник не указан").strip()
        compact_source = source if len(source) <= 34 else source[:31] + "…"
        badge = tk.Label(
            controls,
            text=f"AI · {item.field.confidence.upper()} · {compact_source}",
            font=("Segoe UI", 8, "bold"),
            bg=theme.C["surface_alt"],
            fg=theme.C["text_label"],
            padx=6,
            pady=3,
            cursor="hand2",
        )
        badge.pack(side=tk.RIGHT, padx=(0, 2))
        badge.bind(
            "<Button-1>",
            lambda _event, field_key=key: self._show_inline_field_details(
                field_key
            ),
        )
        self._ai_inline_field_controls[key] = controls
        self._ai_inline_badges[key] = badge
        self._ai_inline_buttons[key] = (approve, reject)
        self._refresh_inline_field_controls(key)

    def _build_inline_review_footer(self) -> None:
        if self._ai_inline_footer is not None:
            self._ai_inline_footer.destroy()
        self._normal_footer.pack_forget()
        footer = tk.Frame(self._footer, bg=theme.C["bg"])
        footer.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._ai_inline_footer = footer
        self._ai_inline_approve_all_btn = ttk.Button(
            footer,
            text="✓  Принять все",
            style="Approve.TButton",
            command=self._approve_all_inline_fields,
        )
        self._ai_inline_approve_all_btn.pack(side=tk.LEFT, padx=(0, 7))
        self._ai_inline_reject_all_btn = ttk.Button(
            footer,
            text="✕  Отклонить все",
            style="Reject.TButton",
            command=self._reject_all_inline_fields,
        )
        self._ai_inline_reject_all_btn.pack(side=tk.LEFT, padx=(0, 7))
        self._ai_inline_refine_btn = ttk.Button(
            footer,
            text="✨  Уточнить",
            style="Secondary.TButton",
            command=self._ask_inline_clarification,
        )
        self._ai_inline_refine_btn.pack(side=tk.LEFT)
        response = self._ai_inline_response
        if response is not None and response.warnings:
            self._ai_inline_warnings_btn = ttk.Button(
                footer,
                text=f"⚠  Предупреждения: {len(response.warnings)}",
                style="DangerGhost.TButton",
                command=self._show_inline_warnings,
            )
            self._ai_inline_warnings_btn.pack(side=tk.RIGHT)
        self._submit_button.config(state=tk.DISABLED)
        self._json_preview_button.config(state=tk.DISABLED)

    def _decide_inline_field(self, key: str, approve: bool) -> None:
        review = self._ai_inline_review
        if review is None or self._ai_busy:
            return
        field_widget = self._field_widgets.get(key)
        if field_widget is None:
            return
        if approve:
            errors = ResponseValidator().validate_manual_values(
                {key: field_widget.get()},
                form=self._form,
                reference_values=self._ai_inline_reference_values,
                check_domain=False,
            )
            if errors.get(key):
                self._set_status(
                    f"✗  {key}: {'; '.join(errors[key])}",
                    "error",
                )
                return
            value_to_restore = review.accept(key)
            if value_to_restore is not None:
                field_widget.set(value_to_restore)
        else:
            field_widget.set(review.reject(key))
        if self._ready and any(field.condition for field in self._form.fields):
            self._refresh_conditional_fields()
        self._refresh_inline_field_controls(key)
        _log.info(
            "inline review field decision form=%s field=%s decision=%s",
            self._form.form_id,
            key,
            "accepted" if approve else "rejected",
        )
        if not review.pending_keys:
            self._commit_inline_review()
        else:
            self._set_status(
                f"Осталось проверить полей: {len(review.pending_keys)}",
                "muted",
            )

    def _refresh_inline_field_controls(self, key: str) -> None:
        review = self._ai_inline_review
        badge = self._ai_inline_badges.get(key)
        buttons = self._ai_inline_buttons.get(key)
        outer = self._field_containers.get(key)
        if review is None or badge is None or buttons is None:
            return
        item = review.get(key)
        approve, reject = buttons
        if item.decision == ACCEPTED:
            badge.config(
                text="✓  AI-значение принято",
                bg="#DCFCE7",
                fg=theme.C["success"],
            )
            approve.config(bg=theme.C["success"], fg="#FFFFFF")
            reject.config(bg=theme.C["chat_error"], fg=theme.C["error"])
            border = theme.C["success"]
        elif item.decision == REJECTED:
            badge.config(
                text="✕  AI-значение отклонено",
                bg=theme.C["chat_error"],
                fg=theme.C["error"],
            )
            approve.config(bg=theme.C["success_soft"], fg=theme.C["success"])
            reject.config(bg=theme.C["error"], fg="#FFFFFF")
            border = theme.C["error"]
        else:
            source = (item.field.source or "источник не указан").strip()
            compact = source if len(source) <= 34 else source[:31] + "…"
            badge.config(
                text=f"AI · {item.field.confidence.upper()} · {compact}",
                bg=theme.C["surface_alt"],
                fg=(
                    theme.C["error"]
                    if item.field.confidence == "low" or item.field.conflict
                    else theme.C["warning"]
                    if item.field.confidence == "medium"
                    else theme.C["text_label"]
                ),
            )
            approve.config(bg=theme.C["success_soft"], fg=theme.C["success"])
            reject.config(bg=theme.C["chat_error"], fg=theme.C["error"])
            border = (
                theme.C["error"]
                if item.field.confidence == "low" or item.field.conflict
                else theme.C["warning"]
                if item.field.confidence == "medium"
                else theme.C["border_focus"]
            )
        if outer is not None:
            outer.config(bg=border)

    def _show_inline_field_details(self, key: str) -> None:
        review = self._ai_inline_review
        if review is None:
            return
        field = review.get(key).field
        details = [
            f"Предложение: {display_value(field.proposed_value) or '—'}",
            f"Confidence: {field.confidence}",
            f"Источник: {field.source or '—'}",
            f"Причина: {field.reason or '—'}",
        ]
        if field.conflict:
            details.append(f"Конфликт: {field.conflict}")
        show_info(self, field.label, "\n".join(details))

    def _show_inline_warnings(self) -> None:
        response = self._ai_inline_response
        if response is None or not response.warnings:
            return
        show_warning(
            self,
            "Предупреждения OpenCode",
            "\n".join(f"• {message}" for message in response.warnings),
        )

    def _approve_all_inline_fields(self) -> None:
        review = self._ai_inline_review
        if review is None or self._ai_busy:
            return
        patch = review.accept_all()
        if patch:
            self.apply_form_data(patch)
        for key in review.keys:
            self._refresh_inline_field_controls(key)
        self._commit_inline_review()

    def _reject_all_inline_fields(self) -> None:
        review = self._ai_inline_review
        if review is None or self._ai_busy:
            return
        self.apply_form_data(review.reject_all())
        rejected = len(review.items)
        self._clear_inline_ai_review(restore=False)
        self._close_ai_agent_session()
        self.app.mark_execution_plan_step(
            self._ai_plan_id,
            self._ai_plan_step_id,
            "pending",
        )
        self._set_status(
            f"✕  AI-предложения отклонены: {rejected}",
            "muted",
        )
        _log.info(
            "inline review rejected form=%s fields=%d",
            self._form.form_id,
            rejected,
        )

    def _commit_inline_review(self) -> None:
        review = self._ai_inline_review
        if review is None:
            return
        if review.pending_keys:
            self._set_status(
                f"Сначала проверьте оставшиеся поля: {len(review.pending_keys)}",
                "muted",
            )
            return
        errors = self._validate_inline_decisions(review.accepted_keys)
        if errors:
            summary = "\n".join(
                f"{key}: {'; '.join(messages)}"
                for key, messages in list(errors.items())[:8]
            )
            self._set_status(
                "✗  Принятая комбинация значений не прошла проверку.",
                "error",
            )
            show_error(self, "Проверьте AI-значения", summary)
            return
        accepted = len(review.accepted_keys)
        self._clear_inline_ai_review(restore=False)
        self._close_ai_agent_session()
        self.app.mark_execution_plan_step(
            self._ai_plan_id,
            self._ai_plan_step_id,
            "prepared" if accepted else "pending",
            form_data=self._collect_form_data() if accepted else None,
        )
        self._set_status(
            f"✓  Подтверждено AI-предложений: {accepted}"
            if accepted
            else "AI-предложения отклонены",
            "success" if accepted else "muted",
        )
        _log.info(
            "inline review completed form=%s accepted=%d rejected=%d",
            self._form.form_id,
            accepted,
            len(review.items) - accepted,
        )

    def _validate_inline_decisions(
        self,
        accepted_keys: tuple[str, ...],
    ) -> Dict[str, List[str]]:
        current = self._collect_form_data()
        selected = {key: current.get(key) for key in accepted_keys}
        validator = ResponseValidator()
        errors = validator.validate_manual_values(
            selected,
            form=self._form,
            reference_values=self._ai_inline_reference_values,
            check_domain=False,
        )
        baseline_errors = validator.validate_domain_values(
            self._ai_inline_baseline_values,
            form=self._form,
        )
        effective_errors = validator.validate_domain_values(
            current,
            form=self._form,
        )
        accepted = set(accepted_keys)
        for key, messages in effective_errors.items():
            relevant = [
                message
                for message in messages
                if key in accepted
                or message not in baseline_errors.get(key, [])
            ]
            if relevant:
                errors.setdefault(key, []).extend(
                    message
                    for message in relevant
                    if message not in errors.get(key, [])
                )
        return errors

    def _ask_inline_clarification(self) -> None:
        review = self._ai_inline_review
        agent = self._ai_agent
        if review is None or agent is None:
            return
        if self._ai_busy:
            self._stop_ai_request()
            return
        message = ask_text(
            self,
            "Уточнить AI-предложения",
            "Опишите, что агент должен изменить. Он сохранит контекст текущей "
            "OpenCode session и вернёт обновлённые предложения.",
            confirm_text="✨ Отправить агенту",
        )
        if not message:
            return
        _log.info(
            "inline review clarification requested form=%s session=%s chars=%d",
            self._form.form_id,
            self._ai_session_id or "none",
            len(message),
        )

        def refine() -> ValidatedResponse:
            agent.send_guidance(
                "Уточнение оператора к предложениям формы:\n" + message
            )
            return agent.finalize()

        self._start_ai_worker("refine", refine)
        self._poll_ai_queue()

    def _set_inline_review_busy(self, busy: bool) -> None:
        state = tk.DISABLED if busy else tk.NORMAL
        for approve, reject in self._ai_inline_buttons.values():
            try:
                approve.config(state=state)
                reject.config(state=state)
            except tk.TclError:
                pass
        for button in (
            self._ai_inline_approve_all_btn,
            self._ai_inline_reject_all_btn,
        ):
            if button is not None:
                button.config(state=state)
        if self._ai_inline_refine_btn is not None:
            self._ai_inline_refine_btn.config(
                state=tk.NORMAL,
                text="■  Остановить" if busy else "✨  Уточнить",
                command=self._stop_ai_request if busy else self._ask_inline_clarification,
            )

    def _clear_inline_ai_review(self, *, restore: bool) -> None:
        review = self._ai_inline_review
        if restore and review is not None:
            self.apply_form_data(review.originals())
        for key, controls in tuple(self._ai_inline_field_controls.items()):
            try:
                controls.destroy()
            except tk.TclError:
                pass
            outer = self._field_containers.get(key)
            if outer is not None:
                outer.config(bg=theme.C["border"])
        self._ai_inline_field_controls.clear()
        self._ai_inline_badges.clear()
        self._ai_inline_buttons.clear()
        if self._ai_inline_footer is not None:
            self._ai_inline_footer.destroy()
        self._ai_inline_footer = None
        self._ai_inline_approve_all_btn = None
        self._ai_inline_reject_all_btn = None
        self._ai_inline_refine_btn = None
        self._ai_inline_warnings_btn = None
        if not self._normal_footer.winfo_manager():
            self._normal_footer.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._submit_button.config(state=tk.NORMAL)
        self._json_preview_button.config(state=tk.NORMAL)
        self._ai_inline_review = None
        self._ai_inline_response = None
        self._ai_inline_reference_values = {}
        self._ai_inline_baseline_values = {}

    def _close_ai_agent_session(self) -> None:
        agent = self._ai_agent
        self._clear_ai_state()
        if agent is not None:
            threading.Thread(
                target=agent.close,
                name="opencode-form-session-cleanup",
                daemon=True,
            ).start()

    def _clear_ai_state(self) -> None:
        if self._ai_poll_id is not None:
            try:
                self.after_cancel(self._ai_poll_id)
            except tk.TclError:
                pass
        self._ai_poll_id = None
        self._ai_assistant = None
        self._ai_agent = None
        self._ai_cancel_event = None
        self._ai_session_id = None
        self._ai_queue = None
        self._ai_busy = False

    @staticmethod
    def _parse_allowed_mcp(value: str) -> List[str]:
        try:
            parsed = json.loads(value or "[]")
        except json.JSONDecodeError:
            parsed = value.split(",")
        if not isinstance(parsed, list):
            return []
        return list(dict.fromkeys(
            str(item).strip() for item in parsed if str(item).strip()
        ))

    def _on_fetch_from_itsm(self) -> None:
        """Запрашивает номер заявки, затем запускает fetch_from_itsm() в фоне."""
        ticket_id = ask_ticket_id(self)
        if ticket_id is None:
            return

        environment = self.app.current_environment.get()

        def _worker():
            return self._form.fetch_from_itsm(environment, ticket_id)

        def _done(data) -> None:
            filled = self.apply_form_data(data or {})
            if filled:
                fields_text = "\n".join(f"  • {k}" for k in filled)
                show_info(self, "Данные получены",
                          f"Данные из заявки успешно подтянуты.\n\nЗаполнено полей: {len(filled)}\n{fields_text}")
            else:
                show_info(self, "Данные получены",
                          "Ответ получен, но ни одно из полей формы не было обновлено.\n"
                          "Проверьте, что ключи в ответе совпадают с ключами полей формы.")

        show_loading(
            self, "Подтягиваем данные из заявки…",
            worker=_worker,
            on_done=_done,
            on_error=lambda exc: show_error(self, "Ошибка получения данных", str(exc)),
        )

    def apply_form_data(self, data: Dict[str, Any]) -> List[str]:
        """
        Заполняет поля формы из словаря {field_key: value}.

        Ключи словаря должны совпадать с field.key полей формы.
        Лишние ключи (нет соответствующего виджета) молча пропускаются.
        Для каждого найденного виджета вызывается fw.set(value) — типы value
        должны соответствовать типу поля (str для TEXT/SELECT, bool для CHECKBOX,
        int для NUMBER, List[str] для MULTISELECT, Dict[str,Any] для BLOCK).

        Plural-поля: если data содержит ключи вида «base_2», «base_3» и т.п.,
        недостающие экземпляры создаются автоматически перед установкой значений.

        Возвращает список ключей, для которых виджет был найден и значение применено.
        Ключи из data, для которых виджета нет, в список не попадают.

        Вызывается автоматически в двух случаях:
          - при открытии FormScreen с initial_data= (восстановление из истории)
          - после успешного fetch_from_itsm() (заполнение из ITSM-заявки)
        Можно вызывать вручную из кастомных кнопок формы через screen.apply_form_data().
        """
        import re
        _plural_re = re.compile(r"^(.+)_(\d+)$")

        # Создаём недостающие plural-экземпляры (напр. cert_2, plan_3)
        needed: Dict[str, List[int]] = {}
        for key in data:
            if key not in self._field_widgets:
                m = _plural_re.match(key)
                if m:
                    base_key, n = m.group(1), int(m.group(2))
                    if base_key in self._plural_counts:
                        needed.setdefault(base_key, []).append(n)

        for base_key, indices in needed.items():
            for n in sorted(indices):
                while self._plural_counts.get(base_key, 1) < n:
                    self._add_plural_field(base_key)

        filled: List[str] = []
        for key, value in data.items():
            fw = self._field_widgets.get(key)
            if fw is None:
                continue
            fw.set(value)
            filled.append(key)

        # SELECT-виджеты не генерируют событие изменения при программной установке,
        # поэтому пересчитываем условные поля явно.
        # _ready=False означает, что _setup_conditional_fields ещё не вызывался —
        # он сам вызовет _refresh_conditional_fields после.
        if self._ready and any(f.condition for f in self._form.fields):
            self._refresh_conditional_fields()

        return filled

    # ------------------------------------------------------------------
    # Утилиты
    # ------------------------------------------------------------------

    def get_field_item(self, key: str) -> Optional[Dict[str, Any]]:
        """
        Возвращает полный словарь выбранного элемента для SELECT-поля.
        None если поле не найдено, не является SELECT или ничего не выбрано.
        """
        fw = self._field_widgets.get(key)
        return fw.get_item() if fw else None

    def get_field_items(self, key: str) -> List[Dict[str, Any]]:
        """
        Возвращает список полных словарей выбранных элементов для MULTISELECT-поля.
        Пустой список если поле не найдено, не является MULTISELECT или ничего не выбрано.
        """
        fw = self._field_widgets.get(key)
        return fw.get_items() if fw else []

    def _set_status(self, text: str, kind: str = "muted") -> None:
        self._status_var.set(text)
        colors = {"muted": theme.C["text_muted"], "success": theme.C["success"],
                  "error": theme.C["error"]}
        self._status_lbl.config(foreground=colors.get(kind, theme.C["text_muted"]))
