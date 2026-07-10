#!/usr/bin/env python3
"""Full-screen TUI for droid-byok (cc-switch inspired, refined)."""

from __future__ import annotations

import asyncio
import os
from typing import Any

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.theme import Theme
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    OptionList,
    SelectionList,
    Select,
    Static,
    TextArea,
)
from textual.widgets.option_list import Option
from textual.widgets.selection_list import Selection

from . import core


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def short(text: str | None, n: int = 42) -> str:
    text = text or "-"
    return text if len(text) <= n else text[: n - 1] + "…"


def provider_matches(profile: core.ProviderProfile, query: str) -> bool:
    """Match a provider against the fields users can see or recognize."""
    needle = query.strip().casefold()
    if not needle:
        return True
    model_text = " ".join(
        f"{model.get('model', '')} {model.get('displayName', '')}"
        for model in (profile.models or [])
    )
    haystack = " ".join(
        (
            profile.id,
            profile.name,
            profile.base_url,
            profile.provider,
            profile.notes,
            model_text,
        )
    ).casefold()
    return needle in haystack


def provider_rows(store: core.Store, query: str = "") -> list[tuple[Any, ...]]:
    active = store.active_id()
    rows: list[tuple[Any, ...]] = []
    for p in store.list_providers():
        if not provider_matches(p, query):
            continue
        is_active = p.id == active
        mark = Text("●", style="bold #22c55e") if is_active else Text("○", style="#64748b")
        name = Text(p.name or p.id, style="bold #86efac" if is_active else "#e2e8f0")
        rows.append(
            (
                mark,
                name,
                Text(p.id, style="#38bdf8"),
                Text(short(p.base_url, 34), style="#94a3b8"),
                Text(str(len(p.models or [])), style="#c084fc"),
                Text(core.mask_secret(p.api_key), style="#64748b"),
                p.id,
            )
        )
    return rows


def live_model_rows(settings: dict[str, Any]) -> list[tuple[Any, ...]]:
    default = core.current_default_model(settings)
    rows: list[tuple[Any, ...]] = []
    for index, m in enumerate(settings.get("customModels") or []):
        mid = str(m.get("id") or "")
        is_def = mid == default
        mark = Text("★", style="bold #facc15") if is_def else Text(" ", style="#334155")
        display = str(m.get("displayName") or m.get("model") or "")
        rows.append(
            (
                mark,
                Text(display, style="bold #fde68a" if is_def else "#e2e8f0"),
                Text(str(m.get("model") or ""), style="#38bdf8"),
                Text(short(str(m.get("baseUrl") or ""), 28), style="#94a3b8"),
                Text(short(str(m.get("provider") or ""), 18), style="#64748b"),
                f"{index}:{mid}",
            )
        )
    return rows


def model_id_from_row_key(row_key: str) -> str:
    """Recover a model ID from the unique key used by live model tables."""
    index, separator, model_id = row_key.partition(":")
    return model_id if separator and index.isdigit() else row_key


def workspace_status(store: core.Store, settings: dict[str, Any]) -> Text:
    """Render the current config state as one dense, scan-friendly line."""
    active = store.active_id() or "Not set"
    default = core.current_default_model(settings) or "Not set"
    provider_count = len(store.list_providers())
    model_count = len(settings.get("customModels") or [])
    invalid_refs = core.invalid_model_refs(settings)

    t = Text()
    t.append("● ", style="bold #34d399")
    t.append("ACTIVE  ", style="#7c8ca3")
    t.append(short(active, 24), style="bold #d8f3e7")
    t.append("   │   ", style="#314158")
    t.append("DEFAULT  ", style="#7c8ca3")
    t.append(short(default, 32), style="bold #f5d76e")
    t.append("   │   ", style="#314158")
    t.append(f"{provider_count} providers", style="#a5c7e8")
    t.append("   ·   ", style="#42526a")
    t.append(f"{model_count} live models", style="#c9b7ed")
    if invalid_refs:
        t.append("   │   ", style="#314158")
        t.append(f"⚠ {len(invalid_refs)} invalid refs", style="bold #fbbf24")
    return t



def detail_render(profile: core.ProviderProfile | None, settings: dict[str, Any], active: str | None) -> Text:
    t = Text()
    if not profile:
        t.append("No provider selected", style="bold #94a3b8")
        return t

    is_active = profile.id == active
    t.append(profile.name or profile.id, style="bold #f8fafc")
    t.append("\n")
    if is_active:
        t.append("● ACTIVE", style="bold #34d399")
        t.append("  ")
    t.append(profile.id, style="#38bdf8")
    t.append("\n\n", style="")

    fields = [
        ("URL", profile.base_url or "-"),
        ("Type", profile.provider),
        ("Key", core.mask_secret(profile.api_key)),
        ("Models", str(len(profile.models or []))),
    ]
    if profile.notes:
        fields.append(("Notes", profile.notes))

    for label, value in fields:
        t.append(f"{label:<8}", style="#64748b")
        t.append(f"{value}\n", style="#e2e8f0")

    t.append("\n")
    t.append("Model list\n", style="bold #94a3b8")
    if not profile.models:
        t.append("  No models configured\n", style="#fbbf24")
    else:
        default = core.current_default_model(settings)
        for i, m in enumerate(profile.models, 1):
            mid_guess = None
            for lm in settings.get("customModels") or []:
                if lm.get("model") == m.get("model") and (
                    not lm.get("baseUrl") or lm.get("baseUrl") == profile.base_url
                ):
                    mid_guess = lm.get("id")
                    break
            is_def = bool(mid_guess and mid_guess == default)
            prefix = "★ " if is_def else "  "
            disp = m.get("displayName") or m.get("model")
            t.append(f"{prefix}{i}. {disp}\n", style="bold #fde68a" if is_def else "#e2e8f0")
            t.append(f"     {m.get('model')}\n", style="#64748b")
    return t


# ---------------------------------------------------------------------------
# modals
# ---------------------------------------------------------------------------

class ProviderDetailModal(ModalScreen[None]):
    """Full provider details for compact terminals and focused inspection."""

    BINDINGS = [Binding("escape", "close", "Close"), Binding("q", "close", "Close")]

    def __init__(
        self,
        profile: core.ProviderProfile,
        settings: dict[str, Any],
        active: str | None,
    ) -> None:
        super().__init__()
        self._profile = profile
        self._settings = settings
        self._active = active

    def compose(self) -> ComposeResult:
        with Vertical(id="modal", classes="detail-modal"):
            yield Label("Provider details", classes="modal-title")
            with VerticalScroll(id="detail-scroll"):
                yield Static(
                    detail_render(self._profile, self._settings, self._active),
                    id="detail-modal-body",
                )
            with Horizontal(classes="modal-actions"):
                yield Button("Close", variant="primary", id="close")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)


class ConfirmModal(ModalScreen[bool]):
    def __init__(self, title: str, message: str) -> None:
        super().__init__()
        self._title = title
        self._message = message

    def compose(self) -> ComposeResult:
        with Vertical(id="modal", classes="confirm-modal"):
            yield Label(self._title, classes="modal-title")
            yield Static(self._message, id="modal-body")
            with Horizontal(classes="modal-actions"):
                yield Button("Cancel", id="cancel")
                yield Button("Confirm", variant="error", id="confirm")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm")

    def on_key(self, event) -> None:  # noqa: ANN001
        if event.key == "escape":
            self.dismiss(False)
        elif event.key == "y":
            self.dismiss(True)
        elif event.key == "n":
            self.dismiss(False)


class SelectModal(ModalScreen[str | None]):
    def __init__(self, title: str, options: list[tuple[str, str]], prompt: str = "Select") -> None:
        super().__init__()
        self._title = title
        self._options = options
        self._prompt = prompt
        self._key_by_opt_id = {f"opt-{i}": key for i, (key, _) in enumerate(options)}

    def compose(self) -> ComposeResult:
        with Vertical(id="modal", classes="select-modal"):
            yield Label(self._title, classes="modal-title")
            yield Static(self._prompt, classes="modal-hint")
            ol = OptionList(id="options")
            for i, (_key, label) in enumerate(self._options):
                ol.add_option(Option(label, id=f"opt-{i}"))
            yield ol
            with Horizontal(classes="modal-actions"):
                yield Button("Cancel", id="cancel")
                yield Button("OK", variant="primary", id="ok")

    def on_mount(self) -> None:
        self.query_one("#options", OptionList).focus()

    def _selected_key(self) -> str | None:
        ol = self.query_one("#options", OptionList)
        if ol.highlighted is None:
            return None
        opt = ol.get_option_at_index(ol.highlighted)
        if not opt or opt.id is None:
            return None
        return self._key_by_opt_id.get(str(opt.id))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
        elif event.button.id == "ok":
            self.dismiss(self._selected_key())

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        oid = str(event.option.id) if event.option.id is not None else None
        self.dismiss(self._key_by_opt_id.get(oid) if oid else None)

    def on_key(self, event) -> None:  # noqa: ANN001
        if event.key == "escape":
            self.dismiss(None)
            event.stop()
        elif event.key == "enter":
            self.dismiss(self._selected_key())
            event.stop()


class FetchModelsModal(ModalScreen[list[dict[str, Any]] | None]):
    """Search and select models fetched from an upstream provider."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("slash", "focus_filter", "Filter", key_display="/"),
    ]

    def __init__(
        self,
        profile: core.ProviderProfile,
        source_url: str,
        models: list[dict[str, Any]],
    ) -> None:
        super().__init__()
        self._profile = profile
        self._source_url = source_url
        self._models = models
        self._models_by_id = {str(model.get("model") or ""): model for model in models}
        self._existing = {
            str(model.get("model") or "") for model in (profile.models or []) if model.get("model")
        }
        self._selected: set[str] = set()
        self._visible_ids: list[str] = []
        self._rebuilding = False

    def compose(self) -> ComposeResult:
        existing_count = sum(1 for model_id in self._models_by_id if model_id in self._existing)
        with Vertical(id="modal", classes="fetch-models-modal"):
            yield Label(f"Fetch models · {self._profile.name}", classes="modal-title")
            yield Static(
                Text.assemble(
                    (f"{len(self._models)} discovered", "bold #7dd3fc"),
                    (f"   {existing_count} configured", "#71848e"),
                    (f"   {short(self._source_url, 58)}", "#52647b"),
                ),
                id="fetch-summary",
            )
            yield Input(placeholder="Filter fetched models", id="fetch-model-filter")
            yield SelectionList(id="fetched-models")
            yield Static("0 selected", id="fetch-selection")
            with Horizontal(classes="modal-actions"):
                yield Button("Cancel", id="cancel")
                yield Button("Clear", id="clear")
                yield Button("Select visible", id="select-visible")
                yield Button("Add selected", variant="primary", id="add-selected", disabled=True)

    def on_mount(self) -> None:
        self._rebuild_options()
        self.query_one("#fetched-models", SelectionList).focus()

    def _capture_visible_selection(self) -> None:
        selection_list = self.query_one("#fetched-models", SelectionList)
        selectable = {model_id for model_id in self._visible_ids if model_id not in self._existing}
        self._selected.difference_update(selectable)
        self._selected.update(str(value) for value in selection_list.selected if str(value) in selectable)

    def _rebuild_options(self) -> None:
        selection_list = self.query_one("#fetched-models", SelectionList)
        query = self.query_one("#fetch-model-filter", Input).value.strip().casefold()
        self._rebuilding = True
        selection_list.clear_options()
        self._visible_ids = []
        for model in self._models:
            model_id = str(model.get("model") or "")
            display_name = str(model.get("displayName") or model_id)
            if query and query not in f"{model_id} {display_name}".casefold():
                continue
            self._visible_ids.append(model_id)
            configured = model_id in self._existing
            prompt = Text(model_id, style="#38bdf8")
            if display_name and display_name != model_id:
                prompt.append(f"   {display_name}", style="#a8bdd2")
            if model.get("maxContextLimit"):
                prompt.append(f"   {model['maxContextLimit']} ctx", style="#64748b")
            if configured:
                prompt.append("   CONFIGURED", style="bold #34d399")
            selection_list.add_option(
                Selection(
                    prompt,
                    model_id,
                    initial_state=model_id in self._selected,
                    disabled=configured,
                )
            )
        if not self._visible_ids:
            selection_list.add_option(Selection("No models match this filter", "__empty__", disabled=True))
        self._rebuilding = False
        self._update_selection_status()

    def _update_selection_status(self) -> None:
        count = len(self._selected)
        self.query_one("#fetch-selection", Static).update(
            Text(f"{count} selected", style="bold #7dd3fc" if count else "#71848e")
        )
        add_button = self.query_one("#add-selected", Button)
        add_button.disabled = count == 0

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "fetch-model-filter":
            return
        self._capture_visible_selection()
        self._rebuild_options()

    def on_selection_list_selected_changed(self, event: SelectionList.SelectedChanged) -> None:
        if self._rebuilding or event.selection_list.id != "fetched-models":
            return
        self._capture_visible_selection()
        self._update_selection_status()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        selection_list = self.query_one("#fetched-models", SelectionList)
        if button_id == "cancel":
            self.dismiss(None)
        elif button_id == "clear":
            self._selected.clear()
            selection_list.deselect_all()
            self._update_selection_status()
        elif button_id == "select-visible":
            for model_id in self._visible_ids:
                if model_id not in self._existing:
                    self._selected.add(model_id)
                    selection_list.select(model_id)
            self._update_selection_status()
        elif button_id == "add-selected":
            selected_models = [
                dict(model)
                for model in self._models
                if str(model.get("model") or "") in self._selected
            ]
            self.dismiss(selected_models)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_focus_filter(self) -> None:
        filter_input = self.query_one("#fetch-model-filter", Input)
        filter_input.focus()
        filter_input.action_select_all()


class ProviderFormModal(ModalScreen[core.ProviderProfile | None]):
    def __init__(self, profile: core.ProviderProfile | None = None) -> None:
        super().__init__()
        self._profile = profile
        self._editing = profile is not None
        self._model_metadata = {
            str(model.get("model") or ""): dict(model)
            for model in (profile.models or [] if profile else [])
            if model.get("model")
        }

    def compose(self) -> ComposeResult:
        p = self._profile
        title = f"Edit · {p.id}" if p else "Add provider"
        with VerticalScroll(id="modal", classes="form-modal"):
            yield Label(title, classes="modal-title")
            yield Label("ID", classes="field-label")
            yield Input(value=(p.id if p else ""), placeholder="doro-us", id="id", disabled=self._editing)
            yield Label("Name", classes="field-label")
            yield Input(value=(p.name if p else ""), placeholder="doro us", id="name")
            yield Label("Base URL", classes="field-label")
            yield Input(
                value=(p.base_url if p else ""),
                placeholder="https://us.doro.lol/v1",
                id="base_url",
            )
            yield Label("API Key (blank keeps current when editing)", classes="field-label")
            yield Input(
                value="",
                placeholder=core.mask_secret(p.api_key) if p else "sk-... or ${ENV}",
                password=True,
                id="api_key",
            )
            yield Label("Provider type", classes="field-label")
            yield Select(
                options=[(x, x) for x in core.PROVIDERS],
                value=(p.provider if p else "generic-chat-completion-api"),
                id="provider",
                allow_blank=False,
            )
            yield Label("Models (one per line: model or model=DisplayName)", classes="field-label")
            models_text = ""
            if p and p.models:
                lines = []
                for m in p.models:
                    mid = str(m.get("model") or "")
                    disp = str(m.get("displayName") or mid)
                    lines.append(f"{mid}={disp}" if disp and disp != mid else mid)
                models_text = "\n".join(lines)
            yield TextArea(models_text, id="models")
            yield Label("Notes", classes="field-label")
            yield Input(value=(p.notes if p else ""), id="notes")
            with Horizontal(classes="modal-actions"):
                yield Button("Cancel", id="cancel")
                yield Button("Fetch models", id="fetch")
                yield Button("Save", variant="primary", id="save")
                yield Button("Save & Default", variant="success", id="save_apply")

    def on_mount(self) -> None:
        self.query_one("#name" if self._editing else "#id", Input).focus()

    def _parse_models(self, text: str) -> list[dict[str, Any]]:
        models: list[dict[str, Any]] = []
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                mid, disp = line.split("=", 1)
            else:
                mid, disp = line, line
            mid, disp = mid.strip(), disp.strip()
            if not mid:
                continue
            model = dict(self._model_metadata.get(mid, {}))
            model.update(
                {
                    "model": mid,
                    "displayName": disp or mid,
                    "maxOutputTokens": int(model.get("maxOutputTokens") or 16384),
                }
            )
            models.append(model)
        return models

    @staticmethod
    def _format_models(models: list[dict[str, Any]]) -> str:
        lines: list[str] = []
        for model in models:
            model_id = str(model.get("model") or "")
            display_name = str(model.get("displayName") or model_id)
            if model_id:
                lines.append(
                    f"{model_id}={display_name}" if display_name and display_name != model_id else model_id
                )
        return "\n".join(lines)

    def _build_profile(self) -> core.ProviderProfile | None:
        pid = self.query_one("#id", Input).value.strip()
        name = self.query_one("#name", Input).value.strip()
        base_url = self.query_one("#base_url", Input).value.strip().rstrip("/")
        api_key_in = self.query_one("#api_key", Input).value.strip()
        provider = str(self.query_one("#provider", Select).value or "generic-chat-completion-api")
        models = self._parse_models(self.query_one("#models", TextArea).text)
        notes = self.query_one("#notes", Input).value.strip()

        if not self._editing and not pid:
            self.notify("ID is required", severity="error")
            return None
        if not name:
            name = pid or (self._profile.name if self._profile else "")
        if not base_url:
            self.notify("Base URL is required", severity="error")
            return None

        if self._editing and self._profile:
            api_key = api_key_in or self._profile.api_key
            pid = self._profile.id
        else:
            if not api_key_in:
                self.notify("API Key is required", severity="error")
                return None
            api_key = api_key_in
            pid = core.slugify(pid)

        return core.ProviderProfile(
            id=pid,
            name=name or pid,
            base_url=base_url,
            api_key=api_key,
            provider=provider,
            models=models,
            notes=notes,
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
            return
        if event.button.id == "fetch":
            self._fetch_models_into_form()
            return
        profile = self._build_profile()
        if not profile:
            return
        profile._apply = event.button.id == "save_apply"  # type: ignore[attr-defined]
        self.dismiss(profile)

    @work
    async def _fetch_models_into_form(self) -> None:
        profile = self._build_profile()
        if not profile:
            return
        self.notify(f"Fetching models from {profile.name}…", severity="information")
        try:
            result = await asyncio.to_thread(core.fetch_upstream_models, profile)
        except core.FetchModelsError as exc:
            self.notify(f"Fetch failed: {exc}", severity="error", timeout=8)
            return
        fetched = list(result.get("models") or [])
        if not fetched:
            self.notify("Upstream returned an empty model catalog", severity="warning")
            return
        selected = await self.app.push_screen_wait(
            FetchModelsModal(profile, str(result.get("url") or profile.base_url), fetched)
        )
        if not selected:
            return

        existing = self._parse_models(self.query_one("#models", TextArea).text)
        existing_ids = {str(model.get("model") or "") for model in existing}
        additions = [
            dict(model)
            for model in selected
            if str(model.get("model") or "") not in existing_ids
        ]
        for model in additions:
            self._model_metadata[str(model.get("model") or "")] = dict(model)
        merged = existing + additions
        self.query_one("#models", TextArea).load_text(self._format_models(merged))
        self.notify(f"Added {len(additions)} model(s) to the form", severity="information")

    def on_key(self, event) -> None:  # noqa: ANN001
        if event.key == "escape":
            self.dismiss(None)


class HelpScreen(ModalScreen[None]):
    BINDINGS = [Binding("escape", "close", "Close"), Binding("q", "close", "Close")]

    def compose(self) -> ComposeResult:
        text = f"""[bold cyan]{core.APP_NAME}[/]  v{core.VERSION}

[bold]Layout[/]
  Top     live configuration status
  Left    providers
  Right   details + live models

[bold]Keys[/]
  ↑/↓ j/k     move
  Enter / u   set default
  a e d       add / edit / delete
  /           filter providers
  v           focused provider details
  f           fetch upstream models
  i m t       import / models / endpoint health
  1-4         quick actions (default/edit/test/fetch)
  r ? q       refresh / help / quit

[bold]Paths[/]
  settings  {core.SETTINGS_PATH}
  store     {core.STORE_PATH}
"""
        with Vertical(id="modal", classes="help-modal"):
            yield Static(text, id="help-body")
            with Horizontal(classes="modal-actions"):
                yield Button("Close", variant="primary", id="close")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)


# ---------------------------------------------------------------------------
# screens
# ---------------------------------------------------------------------------

class ModelsScreen(Screen[None]):
    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back"),
        Binding("q", "app.pop_screen", "Back"),
        Binding("enter", "set_default", "Set default"),
        Binding("r", "refresh", "Refresh"),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="models-wrap"):
            yield Static("", id="models-status", classes="status-bar")
            yield Label("  Live customModels", classes="pane-title")
            yield DataTable(id="models-table", zebra_stripes=True, cursor_type="row")
        yield Footer()

    def on_mount(self) -> None:
        self.action_refresh()
        self.query_one("#models-table", DataTable).focus()

    def action_refresh(self) -> None:
        settings = core.read_settings()
        default = core.current_default_model(settings) or "-"
        self.query_one("#models-status", Static).update(
            Text.from_markup(f"  [bold #facc15]★[/] default  [bold]{default}[/]    Enter = set default")
        )
        table = self.query_one("#models-table", DataTable)
        table.clear(columns=True)
        table.add_columns("", "Display", "Model", "Base URL", "Provider")
        for row in live_model_rows(settings):
            table.add_row(*row[:-1], key=row[-1])

    def action_set_default(self) -> None:
        table = self.query_one("#models-table", DataTable)
        if table.row_count == 0:
            self.notify("No models", severity="warning")
            return
        row_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key
        if row_key is None or row_key.value is None:
            return
        mid = model_id_from_row_key(str(row_key.value))
        if not mid:
            self.notify("Selected model has no ID", severity="error")
            return
        try:
            core.set_session_default(mid)
            self.notify(f"Default → {mid}", severity="information")
            self.action_refresh()
            if isinstance(self.app, DroidByokApp):
                self.app.refresh_all()
        except SystemExit as e:
            self.notify(str(e), severity="error")


class SpeedtestScreen(Screen[None]):
    """Concurrent endpoint probes with progressive, structured results."""

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back"),
        Binding("q", "app.pop_screen", "Back"),
        Binding("r", "refresh", "Run again"),
    ]

    def __init__(self, providers: list[core.ProviderProfile]) -> None:
        super().__init__()
        self._providers = providers

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="speed-wrap"):
            yield Static("", id="speed-status", classes="status-bar")
            with Horizontal(classes="screen-heading"):
                yield Label("Endpoint health", classes="pane-title")
                yield Static(f"{len(self._providers)} targets", id="speed-count")
            yield DataTable(id="speed-table", zebra_stripes=True, cursor_type="row")
        yield Footer()

    def on_mount(self) -> None:
        self.action_refresh()
        self.query_one("#speed-table", DataTable).focus()

    def action_refresh(self) -> None:
        table = self.query_one("#speed-table", DataTable)
        table.clear(columns=True)
        table.add_column("Provider", key="provider", width=18)
        table.add_column("Endpoint", key="endpoint", width=30)
        table.add_column("Health", key="health", width=8)
        table.add_column("HTTP", key="http", width=6)
        table.add_column("Latency", key="latency", width=10)
        table.add_column("Detail", key="detail", width=26)
        for profile in self._providers:
            table.add_row(
                Text(profile.name or profile.id, style="bold #e2e8f0"),
                Text(short(profile.base_url, 42), style="#8ea4bb"),
                Text("QUEUED", style="#64748b"),
                "-",
                "-",
                "Waiting",
                key=profile.id,
            )
        self.query_one("#speed-status", Static).update(
            Text(f"Probing {len(self._providers)} endpoint(s)…", style="#a8bdd2")
        )
        self._run_probes()

    @work(exclusive=True)
    async def _run_probes(self) -> None:
        table = self.query_one("#speed-table", DataTable)
        total = len(self._providers)
        done = 0
        healthy = 0
        fastest: tuple[int, str] | None = None

        async def probe(profile: core.ProviderProfile) -> tuple[core.ProviderProfile, dict[str, Any]]:
            result = await asyncio.to_thread(
                core.probe_endpoint,
                profile.base_url,
                profile.api_key,
            )
            return profile, result

        tasks = [probe(profile) for profile in self._providers]
        for completed in asyncio.as_completed(tasks):
            profile, result = await completed
            done += 1
            ok = bool(result.get("ok"))
            healthy += int(ok)
            latency = result.get("ms")
            if isinstance(latency, int) and (fastest is None or latency < fastest[0]):
                fastest = (latency, profile.name or profile.id)

            health = Text("ONLINE", style="bold #34d399") if ok else Text("FAILED", style="bold #fb7185")
            latency_text = Text("-")
            if isinstance(latency, int):
                latency_color = "#34d399" if latency < 800 else "#fbbf24" if latency < 2000 else "#fb7185"
                latency_text = Text(f"{latency} ms", style=f"bold {latency_color}")
            detail = str(result.get("snippet") or result.get("error") or "-")
            table.update_cell(profile.id, "health", health)
            table.update_cell(profile.id, "http", str(result.get("status") or "-"))
            table.update_cell(profile.id, "latency", latency_text)
            table.update_cell(profile.id, "detail", short(detail.replace("\n", " "), 48))
            self.query_one("#speed-status", Static).update(
                Text.from_markup(
                    f"Completed [bold]{done}/{total}[/]   "
                    f"[bold #34d399]{healthy} online[/]   "
                    f"[bold #fb7185]{done - healthy} failed[/]"
                )
            )

        summary = Text()
        summary.append(f"Completed {total} endpoint(s)   ", style="#a8bdd2")
        summary.append(f"{healthy} online", style="bold #34d399")
        summary.append(f"   {total - healthy} failed", style="bold #fb7185")
        if fastest:
            summary.append("   │   Fastest  ", style="#52647b")
            summary.append(f"{fastest[1]}  {fastest[0]} ms", style="bold #7dd3fc")
        self.query_one("#speed-status", Static).update(summary)


class MainScreen(Screen[None]):
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("question_mark", "help", "Help", key_display="?"),
        Binding("r", "refresh", "Refresh", show=False),
        Binding("a", "add", "Add"),
        Binding("e", "edit", "Edit"),
        Binding("d", "delete", "Delete"),
        Binding("i", "import_live", "Import", show=False),
        Binding("u", "switch", "Default", show=True),
        Binding("enter", "switch", "Default", show=False),
        Binding("m", "models", "Models"),
        Binding("t", "speedtest", "Test"),
        Binding("f", "fetch_models", "Fetch", show=False),
        Binding("v", "view", "Details"),
        Binding("slash", "focus_filter", "Filter", key_display="/"),
        Binding("1", "switch", "Default", show=False),
        Binding("2", "edit", "Edit", show=False),
        Binding("3", "speedtest", "Test", show=False),
        Binding("4", "fetch_models", "Fetch", show=False),
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._selected_pid: str | None = None
        self._filter_query = ""

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="root"):
            yield Static("", id="workspace-status")

            with Horizontal(id="body"):
                with Vertical(id="left-pane", classes="pane"):
                    with Horizontal(classes="pane-heading"):
                        yield Label("Providers", id="providers-title", classes="pane-title")
                        yield Input(placeholder="Filter providers", id="provider-filter")
                    yield DataTable(id="provider-table", zebra_stripes=True, cursor_type="row")
                    yield Static("No providers configured", id="provider-empty", classes="empty-state")
                with Vertical(id="right-pane", classes="pane"):
                    yield Label("Provider details", classes="pane-title right-title")
                    yield Static("", id="detail", classes="detail-card")
                    with Horizontal(id="action-row"):
                        yield Button("Set default", id="btn-default", variant="success", classes="action-btn")
                        yield Button("Edit", id="btn-edit", classes="action-btn")
                        yield Button("Fetch", id="btn-fetch", classes="action-btn")
                        yield Button("Run test", id="btn-test", classes="action-btn")
                    yield Label("Live configuration", id="live-title", classes="pane-title right-title")
                    yield DataTable(id="live-table", zebra_stripes=True, cursor_type="row")
        yield Footer()

    def on_mount(self) -> None:
        self._sync_layout_classes(self.size.width, self.size.height)
        self.action_refresh()
        self.query_one("#provider-table", DataTable).focus()

    def on_resize(self, event) -> None:  # noqa: ANN001
        self._sync_layout_classes(event.size.width, event.size.height)

    def _sync_layout_classes(self, width: int, height: int) -> None:
        self.set_class(width < 112, "compact")
        self.set_class(width < 72, "narrow")
        self.set_class(height < 26, "short")

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "provider-filter":
            return
        self._filter_query = event.value.strip()
        self._refresh_provider_table(core.Store(), self._selected_pid)
        self._update_detail()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "provider-filter":
            self.query_one("#provider-table", DataTable).focus()
            event.stop()

    def on_key(self, event) -> None:  # noqa: ANN001
        if event.key != "escape" or getattr(self.focused, "id", None) != "provider-filter":
            return
        filter_input = self.query_one("#provider-filter", Input)
        if filter_input.value:
            filter_input.value = ""
        else:
            self.query_one("#provider-table", DataTable).focus()
        event.stop()

    def action_cursor_down(self) -> None:
        table = self.query_one("#provider-table", DataTable)
        table.focus()
        table.action_cursor_down()
        self._sync_selection_from_cursor()
        self._update_detail()

    def action_cursor_up(self) -> None:
        table = self.query_one("#provider-table", DataTable)
        table.focus()
        table.action_cursor_up()
        self._sync_selection_from_cursor()
        self._update_detail()

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table.id != "provider-table":
            return
        if event.row_key is not None and event.row_key.value is not None:
            self._selected_pid = str(event.row_key.value)
            self._update_detail()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id != "provider-table":
            return
        if event.row_key is not None and event.row_key.value is not None:
            self._selected_pid = str(event.row_key.value)
        self.action_switch()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "btn-default":
            self.action_switch()
        elif bid == "btn-edit":
            self.action_edit()
        elif bid == "btn-test":
            self.action_speedtest()
        elif bid == "btn-fetch":
            self.action_fetch_models()

    def _sync_selection_from_cursor(self) -> None:
        table = self.query_one("#provider-table", DataTable)
        if table.row_count == 0:
            self._selected_pid = None
            return
        try:
            row_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key
        except Exception:  # noqa: BLE001
            return
        if row_key is not None and row_key.value is not None:
            self._selected_pid = str(row_key.value)

    def _move_cursor_to_pid(self, table: DataTable, pid: str | None) -> None:
        if table.row_count == 0:
            self._selected_pid = None
            return
        if not pid:
            table.move_cursor(row=0, column=0)
            self._sync_selection_from_cursor()
            return
        try:
            keys = list(table.rows.keys())
        except Exception:  # noqa: BLE001
            keys = []
        for idx, key in enumerate(keys):
            val = getattr(key, "value", key)
            if str(val) == pid:
                table.move_cursor(row=idx, column=0)
                self._selected_pid = pid
                return
        table.move_cursor(row=0, column=0)
        self._sync_selection_from_cursor()

    def _refresh_provider_table(self, store: core.Store, keep: str | None) -> None:
        all_providers = store.list_providers()
        rows = provider_rows(store, self._filter_query)
        table = self.query_one("#provider-table", DataTable)
        table.clear(columns=True)
        table.add_columns("", "Name", "ID", "API endpoint", "Models", "Key")
        for row in rows:
            table.add_row(*row[:-1], key=row[-1])

        visible = len(rows)
        total = len(all_providers)
        count = f"{visible}/{total}" if self._filter_query else str(total)
        self.query_one("#providers-title", Label).update(
            Text.assemble(("Providers", "bold #dbeafe"), (f"   {count}", "#64748b"))
        )

        empty = self.query_one("#provider-empty", Static)
        table.display = visible > 0
        empty.display = visible == 0
        if visible == 0:
            message = (
                f'No providers match "{short(self._filter_query, 32)}"'
                if self._filter_query
                else "No providers configured"
            )
            empty.update(message)
        self._move_cursor_to_pid(table, keep)

    def _update_detail(self) -> None:
        store = core.Store()
        settings = core.read_settings()
        pid = self._selected_pid
        profile = store.get(pid) if pid else None
        self.query_one("#detail", Static).update(detail_render(profile, settings, store.active_id()))
        for button_id in ("#btn-default", "#btn-edit", "#btn-fetch", "#btn-test"):
            self.query_one(button_id, Button).disabled = profile is None

    def action_refresh(self) -> None:
        store = core.Store()
        settings = core.read_settings()
        self.query_one("#workspace-status", Static).update(workspace_status(store, settings))

        keep = self._selected_pid or store.active_id()
        self._refresh_provider_table(store, keep)

        ltable = self.query_one("#live-table", DataTable)
        ltable.clear(columns=True)
        ltable.add_columns("", "Display", "Model", "Base URL", "Provider")
        live_rows = live_model_rows(settings)
        for row in live_rows:
            ltable.add_row(*row[:-1], key=row[-1])
        self.query_one("#live-title", Label).update(
            Text.assemble(("Live configuration", "bold #dbeafe"), (f"   {len(live_rows)}", "#64748b"))
        )

        self._update_detail()
        if getattr(self.focused, "id", None) != "provider-filter":
            self.query_one("#provider-table", DataTable).focus()

    def _selected_provider_id(self) -> str | None:
        if self._selected_pid:
            return self._selected_pid
        table = self.query_one("#provider-table", DataTable)
        if table.row_count == 0:
            return None
        try:
            row_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key
        except Exception:  # noqa: BLE001
            return None
        if row_key is None or row_key.value is None:
            return None
        self._selected_pid = str(row_key.value)
        return self._selected_pid

    def action_help(self) -> None:
        self.app.push_screen(HelpScreen())

    def action_focus_filter(self) -> None:
        filter_input = self.query_one("#provider-filter", Input)
        filter_input.focus()
        filter_input.action_select_all()

    def action_view(self) -> None:
        pid = self._selected_provider_id()
        if not pid:
            self.notify("No provider selected", severity="warning")
            return
        store = core.Store()
        profile = store.get(pid)
        if profile:
            self.app.push_screen(
                ProviderDetailModal(profile, core.read_settings(), store.active_id())
            )

    def action_models(self) -> None:
        self.app.push_screen(ModelsScreen())

    def action_quit(self) -> None:
        self.app.exit()

    @work
    async def action_add(self) -> None:
        profile = await self.app.push_screen_wait(ProviderFormModal())
        if not profile:
            return
        store = core.Store()
        if store.get(profile.id):
            self.notify(f"ID exists: {profile.id}", severity="error")
            return
        apply = bool(getattr(profile, "_apply", False))
        try:
            result = core.apply_provider(profile, set_default=apply)
            msg = (
                f"Saved & defaulted {profile.id} · default={result['default']}"
                if apply
                else f"Saved {profile.id} · added={result.get('added')} · updated={result.get('updated')}"
            )
            self._selected_pid = profile.id
            self.notify(msg, severity="information")
        except SystemExit as e:
            self.notify(str(e), severity="error")
        self.action_refresh()

    @work
    async def action_edit(self) -> None:
        pid = self._selected_provider_id()
        if not pid:
            self.notify("No provider selected", severity="warning")
            return
        store = core.Store()
        existing = store.get(pid)
        if not existing:
            self.notify(f"Not found: {pid}", severity="error")
            return
        profile = await self.app.push_screen_wait(ProviderFormModal(existing))
        if not profile:
            return
        apply = bool(getattr(profile, "_apply", False))
        should_apply = apply or store.active_id() == profile.id
        try:
            result = core.apply_provider(profile, set_default=should_apply)
            msg = (
                f"Updated & defaulted {profile.id} · default={result['default']}"
                if should_apply
                else f"Updated {profile.id} · added={result.get('added')} · updated={result.get('updated')}"
            )
            self._selected_pid = profile.id
            self.notify(msg, severity="information")
        except SystemExit as e:
            self.notify(str(e), severity="error")
        self.action_refresh()

    @work
    async def action_fetch_models(self) -> None:
        pid = self._selected_provider_id()
        if not pid:
            self.notify("No provider selected", severity="warning")
            return
        store = core.Store()
        profile = store.get(pid)
        if not profile:
            self.notify(f"Not found: {pid}", severity="error")
            return

        self.notify(f"Fetching models from {profile.name}…", severity="information")
        try:
            result = await asyncio.to_thread(core.fetch_upstream_models, profile)
        except core.FetchModelsError as exc:
            self.notify(f"Fetch failed: {exc}", severity="error", timeout=8)
            return
        fetched = list(result.get("models") or [])
        if not fetched:
            self.notify("Upstream returned an empty model catalog", severity="warning")
            return

        selected = await self.app.push_screen_wait(
            FetchModelsModal(profile, str(result.get("url") or profile.base_url), fetched)
        )
        if not selected:
            return

        latest = core.Store().get(pid)
        if not latest:
            self.notify(f"Not found: {pid}", severity="error")
            return
        existing_ids = {
            str(model.get("model") or "") for model in (latest.models or []) if model.get("model")
        }
        additions = [
            dict(model)
            for model in selected
            if str(model.get("model") or "") not in existing_ids
        ]
        if not additions:
            self.notify("Selected models are already configured", severity="warning")
            return
        latest.models = list(latest.models or []) + additions
        try:
            apply_result = core.apply_provider(latest, set_default=False)
        except (SystemExit, OSError, ValueError) as exc:
            self.notify(f"Unable to add models: {exc}", severity="error")
            return
        self._selected_pid = pid
        self.notify(
            f"Added {len(additions)} model(s) to {pid} · live={apply_result.get('models')}",
            severity="information",
        )
        self.action_refresh()

    @work
    async def action_delete(self) -> None:
        pid = self._selected_provider_id()
        if not pid:
            self.notify("No provider selected", severity="warning")
            return
        ok = await self.app.push_screen_wait(
            ConfirmModal(
                "Delete provider",
                f"Delete provider '{pid}' and remove its models from settings.json?",
            )
        )
        if not ok:
            return
        store = core.Store()
        profile = store.get(pid)
        if not profile:
            self.notify(f"Not found: {pid}", severity="error")
            self.action_refresh()
            return
        result = core.remove_provider_models(profile, delete_store=True)
        if self._selected_pid == pid:
            self._selected_pid = None
        self.notify(f"Deleted {pid} · removed={result.get('removed')}", severity="information")
        self.action_refresh()

    @work
    async def action_switch(self) -> None:
        pid = self._selected_provider_id()
        if not pid:
            self.notify("No provider selected — use ↑/↓ first", severity="warning")
            return
        store = core.Store()
        profile = store.get(pid)
        if not profile:
            self.notify(f"Not found: {pid}", severity="error")
            self.action_refresh()
            return
        if not profile.models:
            self.notify("Provider has no models. Edit it first (e).", severity="error")
            return

        default_model = None
        if len(profile.models) > 1:
            options = [
                (str(m.get("model")), f"{m.get('displayName') or m.get('model')}")
                for m in profile.models
                if m.get("model")
            ]
            default_model = await self.app.push_screen_wait(
                SelectModal("Default model", options, prompt=f"Set default for {pid}")
            )
            if default_model is None:
                self.query_one("#provider-table", DataTable).focus()
                return
        try:
            result = core.apply_provider(profile, default_model=default_model)
            self._selected_pid = pid
            self.notify(
                f"Default → {pid} · models={result.get('models')} · default={result.get('default')}",
                severity="information",
            )
        except SystemExit as e:
            self.notify(str(e) or "default failed", severity="error")
        except Exception as e:  # noqa: BLE001
            self.notify(f"default failed: {e}", severity="error")
        self.action_refresh()

    @work
    async def action_import_live(self) -> None:
        settings = core.read_settings()
        if not settings.get("customModels"):
            self.notify("No customModels in settings.json", severity="warning")
            return
        ok = await self.app.push_screen_wait(
            ConfirmModal(
                "Import live",
                "Import current settings.json customModels as a new provider profile?",
            )
        )
        if not ok:
            return
        try:
            profile = core.import_live_as_provider()
            self._selected_pid = profile.id
            self.notify(
                f"Imported {profile.id} ({len(profile.models or [])} models)",
                severity="information",
            )
        except SystemExit as e:
            self.notify(str(e), severity="error")
        self.action_refresh()

    @work
    async def action_speedtest(self) -> None:
        store = core.Store()
        providers = store.list_providers()
        if not providers:
            self.notify("No providers", severity="warning")
            return
        options = [("__all__", "All providers")] + [
            (p.id, f"{p.name}  ({short(p.base_url, 28)})") for p in providers
        ]
        choice = await self.app.push_screen_wait(
            SelectModal("Speedtest", options, prompt="Probe endpoint")
        )
        if choice is None:
            return
        targets = providers if choice == "__all__" else [store.get(choice)]
        valid_targets = [target for target in targets if target is not None]
        if valid_targets:
            self.app.push_screen(SpeedtestScreen(valid_targets))


class DroidByokApp(App[None]):
    TITLE = "droid-byok"
    SUB_TITLE = f"v{core.VERSION} · BYOK Control Center"
    DROID_THEME = Theme(
        name="droid-console",
        primary="#3b9298",
        secondary="#73868f",
        accent="#58b8b4",
        warning="#d6a84b",
        error="#d45f73",
        success="#37c892",
        foreground="#dbe4ea",
        background="#06162b",
        surface="#0a2038",
        panel="#102a45",
        dark=True,
        variables={
            "footer-background": "#091c30",
            "footer-foreground": "#91a2aa",
            "footer-key-foreground": "#64c6c1",
            "footer-key-background": "#091c30",
            "footer-description-foreground": "#c7d2d8",
            "footer-description-background": "#091c30",
            "footer-item-background": "#091c30",
        },
    )
    CSS = """
    Screen {
        background: #06162b;
        color: #dbe4ea;
    }

    Header {
        background: #091c30;
        color: #eaf2f5;
        text-style: bold;
        dock: top;
        height: 1;
    }

    Footer {
        background: #091c30;
        color: #84959f;
        height: 1;
    }

    Footer > .footer--highlight {
        background: #1f6f78;
        color: #f4fbfb;
    }

    #root {
        height: 1fr;
        padding: 0 1 1 1;
    }

    #workspace-status {
        height: 3;
        padding: 1 1 0 1;
        background: #081d34;
        border-bottom: solid #294d6c;
        overflow: hidden;
    }

    #body {
        height: 1fr;
        layout: horizontal;
        margin-top: 1;
    }

    .pane {
        height: 1fr;
        border: solid #294d6c;
        background: #0a2038;
    }

    #left-pane {
        width: 3fr;
        margin-right: 1;
    }

    #right-pane {
        width: 2fr;
    }

    .pane-heading, .screen-heading {
        height: 3;
        padding: 0 1;
        align: left middle;
        background: #102a45;
        border-bottom: solid #294d6c;
    }

    .pane-title {
        width: 1fr;
        height: 1;
        text-style: bold;
        color: #dbeafe;
    }

    .right-title {
        width: 1fr;
        height: 3;
        padding: 1 1 0 1;
        background: #102a45;
        border-bottom: solid #294d6c;
    }

    #provider-filter {
        width: 30;
        height: 3;
        margin: 0;
        background: #071a2d;
        border: tall #2d5272;
        color: #dbe4ea;
    }

    #provider-filter:focus {
        border: tall #3b9298;
    }

    DataTable {
        height: 1fr;
        background: #0a2038;
        color: #cbd6dc;
        scrollbar-size: 1 1;
        scrollbar-color: #376482;
        scrollbar-color-hover: #4e7f9c;
        scrollbar-background: #0a2038;
    }

    DataTable > .datatable--header {
        background: #122d47;
        color: #87a4ac;
        text-style: bold;
    }

    DataTable > .datatable--cursor {
        background: #164b5b;
        color: #f0faf9;
        text-style: bold;
    }

    DataTable > .datatable--hover {
        background: #14334d;
    }

    .empty-state {
        display: none;
        height: 1fr;
        color: #687981;
        content-align: center middle;
    }

    .detail-card {
        height: auto;
        min-height: 10;
        max-height: 15;
        background: #0a2038;
        border-bottom: solid #24435e;
        padding: 1 2;
        color: #dbe4ea;
    }

    #action-row {
        height: 4;
        padding: 0 1;
        layout: horizontal;
        align: left middle;
        background: #0a2038;
        border-bottom: solid #294d6c;
    }

    .action-btn {
        margin-right: 1;
        min-width: 11;
        height: 3;
    }

    #live-table {
        height: 1fr;
        min-height: 6;
    }

    #provider-table {
        height: 1fr;
        min-height: 8;
    }

    #models-wrap, #speed-wrap {
        padding: 0 1 1 1;
        height: 1fr;
    }

    #models-table, #speed-table {
        height: 1fr;
        border: solid #294d6c;
        background: #0a2038;
    }

    #speed-count {
        width: auto;
        height: 1;
        color: #71848e;
    }

    .status-bar {
        background: #081d34;
        color: #b9c8d0;
        padding: 1 1 0 1;
        height: 3;
        margin: 1 0;
        border-bottom: solid #294d6c;
    }

    ModalScreen {
        background: #000000 68%;
        align: center middle;
    }

    #modal {
        width: 78;
        max-width: 94%;
        height: auto;
        max-height: 90%;
        padding: 1 2;
        border: thick #347f91;
        background: #081b2e;
        margin: 0;
    }

    #modal.form-modal {
        width: 90;
        max-width: 94%;
        height: 90%;
    }

    #modal.fetch-models-modal {
        width: 96;
        max-width: 94%;
        height: 88%;
    }

    #fetch-summary {
        height: 2;
        color: #8fa4ae;
    }

    #fetch-model-filter {
        height: 3;
        margin: 0 0 1 0;
    }

    #fetched-models {
        height: 1fr;
        margin: 0;
        background: #061728;
        border: solid #2d5272;
        scrollbar-size: 1 1;
        scrollbar-color: #376482;
        scrollbar-background: #061728;
    }

    #fetch-selection {
        height: 2;
        padding: 1 0 0 0;
    }

    .help-modal, .select-modal, .confirm-modal, .info-modal, .error-modal,
    .detail-modal {
        width: 76;
        max-width: 100;
    }

    #modal.detail-modal {
        height: 82%;
    }

    #detail-scroll {
        height: 1fr;
        scrollbar-size: 1 1;
        scrollbar-color: #376482;
        scrollbar-background: #081b2e;
    }

    .error-modal {
        border: thick #b94d5e;
    }

    .modal-title {
        text-style: bold;
        color: #e3eef1;
        padding-bottom: 1;
    }

    .modal-hint, .field-label {
        color: #82969f;
        padding-bottom: 0;
    }

    .field-label {
        margin-top: 1;
    }

    .modal-actions {
        height: auto;
        align: right middle;
        padding-top: 1;
    }

    .modal-actions Button {
        margin-left: 1;
        min-width: 12;
    }

    Input, Select, TextArea, OptionList, SelectionList {
        background: #061728;
        color: #dbe4ea;
        border: tall #2d5272;
        margin-bottom: 1;
    }

    Input:focus, Select:focus, TextArea:focus, OptionList:focus {
        border: tall #3b9298;
    }

    TextArea {
        height: 8;
    }

    Button {
        background: #132e48;
        color: #dbe4ea;
        border: tall #315a79;
    }

    Button:hover {
        background: #1b3d59;
        border: tall #477694;
    }

    Button:focus {
        text-style: bold;
        border: tall #4a9ca1;
    }

    Button.-primary {
        background: #226b73;
        color: #f3fbfb;
        text-style: bold;
    }

    Button.-success {
        background: #1d6a52;
        color: #f2fbf7;
        text-style: bold;
    }

    Button.-error {
        background: #983e4c;
        color: #fff5f6;
        text-style: bold;
    }

    Button:disabled {
        background: #0c2135;
        color: #53636a;
        border: tall #213e57;
    }

    #modal-body, #help-body, #detail-modal-body {
        color: #d6e0e5;
    }

    .compact #right-pane {
        display: none;
    }

    .compact #left-pane {
        width: 1fr;
        margin-right: 0;
    }

    .compact #provider-filter {
        width: 26;
    }

    .narrow #provider-filter {
        width: 20;
    }

    .short #root {
        padding-bottom: 0;
    }

    .short #workspace-status {
        height: 1;
        padding: 0 1;
        border-bottom: none;
    }

    .short #body {
        margin-top: 0;
    }
    """

    def on_mount(self) -> None:
        self.register_theme(self.DROID_THEME)
        self.theme = self.DROID_THEME.name
        self.push_screen(MainScreen())
        store = core.Store()
        if not store.list_providers():
            settings = core.read_settings()
            if settings.get("customModels"):
                self.call_after_refresh(self._first_run_import)

    @work
    async def _first_run_import(self) -> None:
        ok = await self.push_screen_wait(
            ConfirmModal(
                "First run",
                "Found live customModels, but no saved providers.\nImport live settings as a provider profile?",
            )
        )
        if ok:
            try:
                profile = core.import_live_as_provider()
                self.notify(f"Imported {profile.id}", severity="information")
            except SystemExit as e:
                self.notify(str(e), severity="error")
            screen = self.screen
            if isinstance(screen, MainScreen):
                screen.action_refresh()

    def refresh_all(self) -> None:
        screen = self.screen
        if isinstance(screen, MainScreen):
            screen.action_refresh()


def _configure_tui_color() -> None:
    """Restore color when an interactive terminal is reported as ``dumb``."""
    color_mode = os.environ.get("DROID_BYOK_COLOR", "auto").strip().casefold()
    if color_mode in {"0", "false", "never", "off"}:
        return

    os.environ.pop("NO_COLOR", None)
    if os.environ.get("TERM", "").casefold() in {"", "dumb", "unknown"}:
        os.environ["TERM"] = "xterm-256color"
    # SSH commonly preserves TERM but drops COLORTERM, which makes Rich reduce
    # dark blue backgrounds to ANSI color 16 (usually rendered as gray/black).
    os.environ["COLORTERM"] = "truecolor"


def run_tui() -> int:
    _configure_tui_color()
    core.STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    app = DroidByokApp()
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(run_tui())
