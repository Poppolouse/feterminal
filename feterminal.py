#!/usr/bin/env python3

import json
import os
import re
import shlex
import signal
import subprocess
import sys
import tempfile
import urllib.request
from copy import deepcopy
from pathlib import Path

import gi
from platform_support import build_service_spawn_argv

gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")
gi.require_version("Vte", "3.91")
gi.require_version("GdkPixbuf", "2.0")

from gi.repository import Adw, Gio, GLib, Gdk, GdkPixbuf, Gtk, Vte


APP_ID = "io.poppolouse.feterminal"
APP_DIR = Path(__file__).resolve().parent
PROJECT_FILE_NAME = ".feterminal"
CONFIG_PATH = APP_DIR / "shortcuts.json"
WEBDEV_CONFIG_PATH = APP_DIR / "webdev.json"
BRAND_ICON_DIR = APP_DIR / "assets" / "brand-icons"
AVATAR_CACHE_DIR = Path(GLib.get_user_cache_dir()) / "feterminal"
SIDEBAR_WIDTH = 320
SETTINGS_PANEL_WIDTH = 420
SERVICE_LOG_DIR_NAME = ".feterminal-logs"
ERROR_PATTERN = re.compile(r"(error|exception|traceback|fatal|failed)", re.IGNORECASE)
DEBUG_PATTERN = re.compile(r"(debug|trace|verbose|dbg)", re.IGNORECASE)
ANSI_ESCAPE_PATTERN = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
BACKSPACE_PAIR_PATTERN = re.compile(r".\x08", re.DOTALL)
ERROR_EVENT_START_PATTERN = re.compile(
    r"(unhandled exception|exception in asgi application|traceback \(most recent call last\):|^error[:\s]|^fatal[:\s]|^failed[:\s])",
    re.IGNORECASE,
)
MULTILINE_ERROR_START_PATTERN = re.compile(
    r"(unhandled exception|exception in asgi application|traceback \(most recent call last\):)",
    re.IGNORECASE,
)
AI_TOOL_NAMES = ["codex", "claude_code", "copilot", "gemini"]
AI_LABELS = {
    "codex": "Codex",
    "claude_code": "Claude Code",
    "copilot": "Copilot",
    "gemini": "Gemini",
}
SERVICE_ICONS = {
    "postgres": "database-symbolic",
    "backend": "network-server-symbolic",
    "frontend": "applications-web-browser-symbolic",
    "workers": "system-run-symbolic",
    "tests": "checkmark-symbolic",
    "ai": "applications-engineering-symbolic",
    "terminal": "utilities-terminal-symbolic",
}
AI_ICON_FILES = {
    "codex": BRAND_ICON_DIR / "openai.svg",
    "claude_code": BRAND_ICON_DIR / "claude.svg",
    "copilot": BRAND_ICON_DIR / "copilot.svg",
    "gemini": BRAND_ICON_DIR / "gemini.svg",
}
ACTION_ORDER = [
    "copy",
    "paste",
    "send_interrupt",
    "paste_image",
    "new_terminal_tab",
    "reset",
    "reload_shortcuts",
    "open_preferences",
    "close_window",
]
ACTION_LABELS = {
    "copy": "Copy",
    "paste": "Paste Text",
    "send_interrupt": "Send Interrupt",
    "paste_image": "Paste Image Path",
    "new_terminal_tab": "New Terminal Tab",
    "reset": "Reset Terminal",
    "reload_shortcuts": "Reload Shortcuts",
    "open_preferences": "Open Preferences",
    "close_window": "Close Window",
}
DEFAULT_POSTGRES_CONTAINER = "factory-planner-postgres"
DEFAULT_POSTGRES_HOST = "127.0.0.1"
DEFAULT_POSTGRES_PORT = 5432
DEFAULT_SHORTCUTS = {
    "copy": ["<Ctrl>c"],
    "paste": ["<Ctrl>v"],
    "send_interrupt": ["<Ctrl><Shift>c"],
    "paste_image": ["<Ctrl><Shift>v"],
    "new_terminal_tab": ["<Ctrl><Shift>t"],
    "reset": ["<Ctrl><Shift>r"],
    "reload_shortcuts": ["F5"],
    "open_preferences": ["<Ctrl>comma"],
    "close_window": ["<Ctrl><Shift>q"],
}
DEFAULT_WEBDEV_CONFIG = {
    "postgres": [],
    "backend": {"commands": []},
    "frontend": {"commands": []},
    "workers": [{"id": "worker-1", "name": "Worker 1", "commands": []}],
    "tests": [],
    "ai": {
        "codex": {"commands": []},
        "claude_code": {"commands": []},
        "copilot": {"commands": []},
        "gemini": {"commands": []},
    },
}
DEFAULT_PROJECT_CONFIG = {
    "name": "",
    "postgres": [],
    "backend": {"commands": []},
    "frontend": {"commands": []},
    "workers": [],
    "tests": [],
    "ai": {
        "codex": {"commands": []},
        "claude_code": {"commands": []},
        "copilot": {"commands": []},
        "gemini": {"commands": []},
    },
}


def deep_merge(base: dict, override: dict) -> dict:
    result = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def child_setup_new_session(*_args):
    return None


def normalize_command_list(value) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    return []


def normalize_service_config(value) -> dict:
    if not isinstance(value, dict):
        return {"commands": []}
    commands = normalize_command_list(value.get("commands"))
    if not commands and isinstance(value.get("command"), str) and value["command"].strip():
        commands = [value["command"].strip()]
    return {"commands": commands}


def build_postgres_commands(config: dict) -> list[str]:
    database = str(config.get("database", "")).strip()
    if not database:
        return normalize_service_config(config)["commands"]
    container = str(config.get("container", DEFAULT_POSTGRES_CONTAINER)).strip() or DEFAULT_POSTGRES_CONTAINER
    user = str(config.get("user", "postgres")).strip() or "postgres"
    password = str(config.get("password", "")).strip()
    host = str(config.get("host", DEFAULT_POSTGRES_HOST)).strip() or DEFAULT_POSTGRES_HOST
    port = int(config.get("port", DEFAULT_POSTGRES_PORT))
    helper_path = APP_DIR / "scripts" / "open-postgres-console.sh"
    command = [
        shlex.quote(str(helper_path)),
        "--container",
        shlex.quote(container),
        "--user",
        shlex.quote(user),
        "--database",
        shlex.quote(database),
        "--host",
        shlex.quote(host),
        "--port",
        shlex.quote(str(port)),
    ]
    if password:
        command.extend(["--password", shlex.quote(password)])
    return [" ".join(command)]


def normalize_postgres_entries(value) -> list[dict]:
    raw_entries = value if isinstance(value, list) else [value] if isinstance(value, dict) else []
    entries = []
    for index, entry in enumerate(raw_entries, start=1):
        if not isinstance(entry, dict):
            continue
        database = str(entry.get("database", "")).strip()
        generated_name = database or f"Database {index}"
        commands = normalize_service_config(entry)["commands"]
        if not commands and database:
            commands = build_postgres_commands(entry)
        entries.append(
            {
                "id": str(entry.get("id", f"postgres-{index}")).strip() or f"postgres-{index}",
                "name": str(entry.get("name", generated_name)).strip() or generated_name,
                "database": database,
                "container": str(entry.get("container", DEFAULT_POSTGRES_CONTAINER)).strip() or DEFAULT_POSTGRES_CONTAINER,
                "user": str(entry.get("user", "postgres")).strip() or "postgres",
                "password": str(entry.get("password", "")).strip(),
                "host": str(entry.get("host", DEFAULT_POSTGRES_HOST)).strip() or DEFAULT_POSTGRES_HOST,
                "port": int(entry.get("port", DEFAULT_POSTGRES_PORT)),
                "commands": commands,
            }
        )
    return entries


def normalize_test_entries(value) -> list[dict]:
    raw_entries = value if isinstance(value, list) else [value] if isinstance(value, dict) else []
    entries = []
    for index, entry in enumerate(raw_entries, start=1):
        if not isinstance(entry, dict):
            continue
        commands = normalize_service_config(entry)["commands"]
        entries.append(
            {
                "id": str(entry.get("id", f"test-{index}")).strip() or f"test-{index}",
                "name": str(entry.get("name", f"Test {index}")).strip() or f"Test {index}",
                "commands": commands,
            }
        )
    return entries


def strip_ansi_sequences(value: str) -> str:
    value = ANSI_ESCAPE_PATTERN.sub("", value)
    previous = None
    while previous != value:
        previous = value
        value = BACKSPACE_PAIR_PATTERN.sub("", value)
    return value


def resolve_project_file(
    cli_target: str | None, launch_cwd: str | os.PathLike[str] | None = None
) -> Path | None:
    if cli_target:
        target = Path(cli_target).expanduser().resolve()
        if target.is_file():
            if target.name == PROJECT_FILE_NAME:
                return target
            start_dir = target.parent
        else:
            start_dir = target
    else:
        start_dir = Path(launch_cwd).expanduser().resolve() if launch_cwd else Path.cwd().resolve()

    current = start_dir
    while True:
        candidate = current / PROJECT_FILE_NAME
        if candidate.is_file():
            return candidate
        if current.parent == current:
            return None
        current = current.parent


class ShortcutPreferencesWindow(Adw.PreferencesWindow):
    def __init__(self, parent: Gtk.Window, shortcut_values: dict, on_save):
        super().__init__(transient_for=parent, modal=True, title="Preferences")
        self.set_default_size(540, 580)
        self._on_save = on_save
        self.entries = {}

        page = Adw.PreferencesPage()
        shortcut_group = Adw.PreferencesGroup(
            title="Keyboard Shortcuts",
            description="Use GTK accelerator syntax, for example &lt;Ctrl&gt;&lt;Shift&gt;c.",
        )
        page.add(shortcut_group)

        for action_name in ACTION_ORDER:
            row = Adw.ActionRow(title=ACTION_LABELS[action_name])
            entry = Gtk.Entry(
                text=", ".join(shortcut_values.get(action_name, [])),
                hexpand=True,
            )
            row.add_suffix(entry)
            row.set_activatable_widget(entry)
            shortcut_group.add(row)
            self.entries[action_name] = entry

        info_group = Adw.PreferencesGroup(title="Webdev Mode")
        info_group.add(
            Adw.ActionRow(
                title="Command editor",
                subtitle="Use the gear button next to Webdev in the sidebar to edit commands.",
            )
        )
        page.add(info_group)

        button_group = Adw.PreferencesGroup()
        button_row = Adw.ActionRow(title="Apply")
        save_button = Gtk.Button(label="Save")
        save_button.add_css_class("suggested-action")
        save_button.connect("clicked", self.on_save_clicked)
        reset_button = Gtk.Button(label="Defaults")
        reset_button.connect("clicked", self.on_reset_clicked)
        button_row.add_suffix(reset_button)
        button_row.add_suffix(save_button)
        button_group.add(button_row)
        page.add(button_group)

        self.add(page)

    def on_save_clicked(self, *_args) -> None:
        data = {}
        for action_name, entry in self.entries.items():
            raw_value = entry.get_text().strip()
            data[action_name] = [
                item.strip() for item in raw_value.split(",") if item.strip()
            ]
        self._on_save(data)
        self.close()

    def on_reset_clicked(self, *_args) -> None:
        for action_name, entry in self.entries.items():
            entry.set_text(", ".join(DEFAULT_SHORTCUTS[action_name]))


class FeTerminalWindow(Adw.ApplicationWindow):
    def __init__(
        self,
        app: Adw.Application,
        cli_target: str | None,
        launch_cwd: str | os.PathLike[str] | None = None,
    ):
        super().__init__(application=app, title="feterminal")
        self.set_default_size(1360, 820)
        self.install_css()

        launch_root = Path(launch_cwd).expanduser().resolve() if launch_cwd else Path.cwd().resolve()
        self.project_file_path = resolve_project_file(cli_target, launch_root)
        self.project_root = (
            self.project_file_path.parent if self.project_file_path else launch_root
        )
        self.project_name = ""
        self.project_config = deepcopy(DEFAULT_PROJECT_CONFIG)

        self.shortcut_map = {}
        self.shortcut_values = {}
        self.webdev_config = {}
        self.default_mod_mask = Gtk.accelerator_get_default_mod_mask()
        self.preferences_window = None
        self.settings_row_inputs = {}
        self.webdev_view_mode = "consoles"

        self.tab_counter = 0
        self.active_page_name = None
        self.terminal_tabs = {}
        self.service_sessions = {}
        self.service_rows = {}
        self.error_pages = {}
        self.debug_pages = {}
        self.category_revealers = {}
        self.category_arrow_images = {}
        self.sidebar_visible = True
        self.settings_visible = False
        self.bootstrap_files = []
        self.ai_footer_buttons = {}

        self.status_label = Gtk.Label(
            label="Ready",
            xalign=0,
            margin_top=6,
            margin_bottom=6,
            margin_start=12,
            margin_end=12,
        )
        self.status_label.add_css_class("dim-label")
        self.git_status_label = Gtk.Label(
            label="",
            xalign=1,
            margin_top=6,
            margin_bottom=6,
            margin_start=12,
            margin_end=4,
        )
        self.git_status_label.add_css_class("dim-label")
        self.github_user_label = Gtk.Label(
            label="",
            xalign=1,
            margin_top=6,
            margin_bottom=6,
            margin_start=0,
            margin_end=12,
        )
        self.github_user_label.add_css_class("dim-label")
        self.github_avatar_image = Adw.Avatar.new(16, "", False)
        self.github_avatar_image.set_size_request(16, 16)
        self.github_avatar_image.set_hexpand(False)
        self.github_avatar_image.set_vexpand(False)
        self.github_avatar_image.set_halign(Gtk.Align.CENTER)
        self.github_avatar_image.set_valign(Gtk.Align.CENTER)
        self.github_avatar_image.set_margin_top(6)
        self.github_avatar_image.set_margin_bottom(6)
        self.github_avatar_image.set_margin_end(6)

        header = Adw.HeaderBar()
        new_tab_button = Gtk.Button(icon_name="tab-new-symbolic")
        new_tab_button.set_tooltip_text("New terminal tab")
        new_tab_button.connect("clicked", self.on_add_terminal_tab_clicked)
        header.pack_start(new_tab_button)

        sidebar_button = Gtk.Button(label="Sidebar")
        sidebar_button.add_css_class("flat")
        sidebar_button.connect("clicked", self.on_toggle_sidebar_clicked)
        header.pack_end(sidebar_button)

        menu_button = Gtk.MenuButton(icon_name="open-menu-symbolic")
        menu_button.set_menu_model(self.build_menu_model())
        header.pack_end(menu_button)

        self.content_stack = Gtk.Stack(
            transition_type=Gtk.StackTransitionType.CROSSFADE,
            hexpand=True,
            vexpand=True,
        )

        self.settings_revealer = Gtk.Revealer(
            transition_type=Gtk.RevealerTransitionType.SLIDE_LEFT
        )
        self.settings_revealer.set_reveal_child(False)
        self.settings_revealer.set_child(self.build_settings_panel())
        self.settings_revealer.connect("notify::child-revealed", self.on_settings_child_revealed)
        self.settings_shell = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self.settings_shell.add_css_class("floating-panel")
        self.settings_shell.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        self.settings_shell.append(self.settings_revealer)
        self.settings_shell.set_visible(False)

        center_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        center_box.set_hexpand(True)
        center_box.append(self.content_stack)
        center_box.append(self.settings_shell)

        sidebar = self.build_sidebar()
        self.sidebar_revealer = Gtk.Revealer(
            transition_type=Gtk.RevealerTransitionType.SLIDE_LEFT
        )
        self.sidebar_revealer.set_reveal_child(True)
        self.sidebar_revealer.set_child(sidebar)
        self.sidebar_revealer.connect("notify::child-revealed", self.on_sidebar_child_revealed)
        self.sidebar_shell = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self.sidebar_shell.add_css_class("floating-panel")
        self.sidebar_shell.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        self.sidebar_shell.append(self.sidebar_revealer)
        self.sidebar_shell.set_visible(True)

        content_overlay = Gtk.Overlay()
        content_overlay.set_child(center_box)
        self.sidebar_shell.set_halign(Gtk.Align.END)
        self.sidebar_shell.set_valign(Gtk.Align.FILL)
        content_overlay.add_overlay(self.sidebar_shell)

        root_content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        root_content.append(content_overlay)

        toolbar_view = Adw.ToolbarView()
        toolbar_view.add_top_bar(header)

        outer_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        outer_box.append(root_content)
        outer_box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        status_bar = Gtk.CenterBox(orientation=Gtk.Orientation.HORIZONTAL)

        left_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        left_box.append(self.status_label)
        status_bar.set_start_widget(left_box)

        ai_switcher = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        ai_switcher.set_margin_top(3)
        ai_switcher.set_margin_bottom(3)
        for tool_name in AI_TOOL_NAMES:
            btn = Gtk.Button()
            btn.add_css_class("flat")
            btn_inner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
            icon_path = AI_ICON_FILES[tool_name]
            if icon_path.exists():
                img = Gtk.Image.new_from_file(str(icon_path))
                img.set_pixel_size(14)
                btn_inner.append(img)
            else:
                btn_inner.append(Gtk.Image.new_from_icon_name("applications-engineering-symbolic"))
            lbl = Gtk.Label(label=AI_LABELS[tool_name])
            lbl.add_css_class("caption")
            btn_inner.append(lbl)
            btn.set_child(btn_inner)
            btn.set_tooltip_text(f"Switch to {AI_LABELS[tool_name]} console")
            btn.connect("clicked", self.on_ai_footer_button_clicked, tool_name)
            ai_switcher.append(btn)
            self.ai_footer_buttons[tool_name] = btn
        status_bar.set_center_widget(ai_switcher)

        right_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        right_box.append(self.git_status_label)
        right_box.append(self.github_avatar_image)
        right_box.append(self.github_user_label)
        status_bar.set_end_widget(right_box)

        outer_box.append(status_bar)
        toolbar_view.set_content(outer_box)
        self.set_content(toolbar_view)

        controller = Gtk.EventControllerKey()
        controller.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        controller.connect("key-pressed", self.on_key_pressed)
        self.add_controller(controller)

        self.connect("close-request", self.on_close_request)
        self.install_actions()
        self.load_shortcuts()
        self.load_webdev_config()
        self.load_project_config()
        self.apply_project_metadata()
        self.refresh_git_status()
        self.rebuild_settings_panel()
        self.rebuild_webdev_sidebar()
        self.add_terminal_tab()
        GLib.timeout_add_seconds(1, self.refresh_service_statuses)

    def build_menu_model(self) -> Gio.Menu:
        menu = Gio.Menu()
        menu.append("New Terminal Tab", "win.new_terminal_tab")
        menu.append("Preferences", "win.open_preferences")
        menu.append("Reload Shortcuts", "win.reload_shortcuts")
        menu.append("Reset Terminal", "win.reset")
        menu.append("Close Window", "win.close_window")
        return menu

    def install_css(self) -> None:
        provider = Gtk.CssProvider()
        provider.load_from_data(
            b"""
            .floating-panel {
                background-color: @window_bg_color;
            }
            """
        )
        Gtk.StyleContext.add_provider_for_display(
            self.get_display(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

    def build_sidebar(self) -> Gtk.Box:
        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        sidebar.set_size_request(SIDEBAR_WIDTH, -1)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        content.set_margin_top(10)
        content.set_margin_bottom(10)
        content.set_margin_start(8)
        content.set_margin_end(8)

        terminals_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        terminals_label = Gtk.Label(label="Terminals", xalign=0)
        terminals_label.add_css_class("heading")
        add_button = Gtk.Button(icon_name="list-add-symbolic")
        add_button.add_css_class("flat")
        add_button.connect("clicked", self.on_add_terminal_tab_clicked)
        terminals_header.append(terminals_label)
        terminals_header.append(Gtk.Box(hexpand=True))
        terminals_header.append(add_button)
        content.append(terminals_header)

        self.terminal_listbox = Gtk.ListBox()
        self.terminal_listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.terminal_listbox.add_css_class("boxed-list")
        self.terminal_listbox.connect("row-selected", self.on_terminal_row_selected)
        content.append(self.terminal_listbox)

        webdev_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        webdev_toggle = Gtk.Button(label="Webdev")
        webdev_toggle.add_css_class("flat")
        webdev_toggle.connect("clicked", self.on_webdev_toggle_clicked)
        webdev_header.append(webdev_toggle)
        webdev_header.append(Gtk.Box(hexpand=True))
        webdev_settings_button = Gtk.Button(icon_name="emblem-system-symbolic")
        webdev_settings_button.add_css_class("flat")
        webdev_settings_button.set_tooltip_text("Open Webdev command settings")
        webdev_settings_button.connect("clicked", self.on_toggle_settings_clicked)
        webdev_header.append(webdev_settings_button)
        content.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        content.append(webdev_header)

        webdev_tabs = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.webdev_consoles_button = Gtk.Button(label="Consoles")
        self.webdev_consoles_button.add_css_class("suggested-action")
        self.webdev_consoles_button.connect("clicked", self.on_webdev_view_mode_clicked, "consoles")
        self.webdev_errors_button = Gtk.Button(label="Errors")
        self.webdev_errors_button.add_css_class("flat")
        self.webdev_errors_button.connect("clicked", self.on_webdev_view_mode_clicked, "errors")
        self.webdev_debug_button = Gtk.Button(label="Debug")
        self.webdev_debug_button.add_css_class("flat")
        self.webdev_debug_button.connect("clicked", self.on_webdev_view_mode_clicked, "debug")
        self.webdev_tests_button = Gtk.Button(label="Tests")
        self.webdev_tests_button.add_css_class("flat")
        self.webdev_tests_button.connect("clicked", self.on_webdev_view_mode_clicked, "tests")
        webdev_tabs.append(self.webdev_consoles_button)
        webdev_tabs.append(self.webdev_errors_button)
        webdev_tabs.append(self.webdev_debug_button)
        webdev_tabs.append(self.webdev_tests_button)
        content.append(webdev_tabs)

        self.webdev_revealer = Gtk.Revealer(
            transition_type=Gtk.RevealerTransitionType.SLIDE_DOWN
        )
        self.webdev_revealer.set_reveal_child(True)
        self.webdev_tree_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=4,
            margin_top=4,
            margin_bottom=4,
            margin_start=0,
            margin_end=0,
        )
        self.webdev_revealer.set_child(self.webdev_tree_box)
        content.append(self.webdev_revealer)
        content.append(Gtk.Box(vexpand=True))

        scroller = Gtk.ScrolledWindow(
            hscrollbar_policy=Gtk.PolicyType.NEVER,
            vscrollbar_policy=Gtk.PolicyType.AUTOMATIC,
        )
        scroller.set_vexpand(True)
        scroller.set_child(content)
        sidebar.append(scroller)
        return sidebar

    def build_settings_panel(self) -> Gtk.ScrolledWindow:
        container = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=14,
            margin_top=14,
            margin_bottom=14,
            margin_start=14,
            margin_end=14,
        )
        container.set_size_request(SETTINGS_PANEL_WIDTH, -1)
        self.settings_container = container

        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroller.set_child(container)
        return scroller

    def rebuild_settings_panel(self) -> None:
        self.clear_box(self.settings_container)
        self.settings_row_inputs = {}

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        title = Gtk.Label(label="Webdev Commands", xalign=0)
        title.add_css_class("title-3")
        close_button = Gtk.Button(icon_name="window-close-symbolic")
        close_button.add_css_class("flat")
        close_button.connect("clicked", self.on_toggle_settings_clicked)
        header.append(title)
        header.append(Gtk.Box(hexpand=True))
        header.append(close_button)
        self.settings_container.append(header)

        description_text = (
            "Commands stay hidden until you open this panel from the Webdev gear button."
        )
        if self.project_file_path:
            description_text += f"\nProject file: {self.project_file_path}"
        description = Gtk.Label(label=description_text, wrap=True, xalign=0)
        description.add_css_class("dim-label")
        self.settings_container.append(description)

        self.settings_container.append(
            self.build_settings_group(
                "Postgres",
                [(entry["id"], entry["name"]) for entry in self.webdev_config["postgres"]],
            )
        )
        self.settings_container.append(
            self.build_settings_group("Backend", [("backend", "Backend")])
        )
        self.settings_container.append(
            self.build_settings_group("Frontend", [("frontend", "Frontend")])
        )

        workers_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        workers_label = Gtk.Label(label="Workers", xalign=0)
        workers_label.add_css_class("title-4")
        add_worker_button = Gtk.Button(label="Add Worker")
        add_worker_button.connect("clicked", self.on_add_worker_clicked)
        workers_header.append(workers_label)
        workers_header.append(Gtk.Box(hexpand=True))
        workers_header.append(add_worker_button)
        self.settings_container.append(workers_header)
        worker_ids = [(worker["id"], worker["name"]) for worker in self.webdev_config["workers"]]
        self.settings_container.append(
            self.build_settings_group("", worker_ids, removable=True)
        )

        test_items = [(test["id"], test["name"]) for test in self.webdev_config["tests"]]
        if test_items:
            self.settings_container.append(self.build_settings_group("Tests", test_items))

        ai_items = [(f"ai:{tool_name}", AI_LABELS[tool_name]) for tool_name in AI_TOOL_NAMES]
        self.settings_container.append(self.build_settings_group("AI", ai_items))

    def build_settings_group(self, title: str, items: list, removable: bool = False) -> Gtk.Box:
        group = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        if title:
            label = Gtk.Label(label=title, xalign=0)
            label.add_css_class("title-4")
            group.append(label)

        for service_id, label_text in items:
            frame = Gtk.Frame()
            box = Gtk.Box(
                orientation=Gtk.Orientation.VERTICAL,
                spacing=8,
                margin_top=10,
                margin_bottom=10,
                margin_start=10,
                margin_end=10,
            )
            title_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            title_label = Gtk.Label(label=label_text, xalign=0)
            title_label.add_css_class("heading")
            title_row.append(title_label)
            title_row.append(Gtk.Box(hexpand=True))
            if removable:
                remove_button = Gtk.Button(icon_name="user-trash-symbolic")
                remove_button.add_css_class("flat")
                remove_button.connect("clicked", self.on_remove_worker_clicked, service_id)
                title_row.append(remove_button)
            box.append(title_row)

            editor = self.build_commands_editor(service_id)
            box.append(editor)

            hint = Gtk.Label(
                label="One command per line. They run in order.",
                wrap=True,
                xalign=0,
            )
            hint.add_css_class("caption")
            box.append(hint)

            button_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            save_button = Gtk.Button(label="Save")
            save_button.add_css_class("suggested-action")
            save_button.connect("clicked", self.on_save_service_clicked, service_id)
            button_row.append(save_button)
            box.append(button_row)

            frame.set_child(box)
            group.append(frame)

        return group

    def build_commands_editor(self, service_id: str) -> Gtk.ScrolledWindow:
        text_view = Gtk.TextView()
        text_view.set_monospace(True)
        text_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        text_view.set_top_margin(8)
        text_view.set_bottom_margin(8)
        text_view.set_left_margin(8)
        text_view.set_right_margin(8)
        buffer_ = text_view.get_buffer()
        buffer_.set_text("\n".join(self.service_config_by_id(service_id)["commands"]))
        self.settings_row_inputs[service_id] = text_view

        scroller = Gtk.ScrolledWindow()
        scroller.set_min_content_height(92)
        scroller.set_child(text_view)
        return scroller

    def install_actions(self) -> None:
        actions = {
            "copy": self.action_copy,
            "paste": self.action_paste,
            "send_interrupt": self.action_send_interrupt,
            "paste_image": self.action_paste_image,
            "new_terminal_tab": self.action_new_terminal_tab,
            "reset": self.action_reset,
            "reload_shortcuts": self.action_reload_shortcuts,
            "open_preferences": self.action_open_preferences,
            "close_window": self.action_close_window,
        }
        for name, callback in actions.items():
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", callback)
            self.add_action(action)

    def clear_box(self, box: Gtk.Box) -> None:
        child = box.get_first_child()
        while child is not None:
            next_child = child.get_next_sibling()
            box.remove(child)
            child = next_child

    def load_shortcuts(self) -> None:
        if not CONFIG_PATH.exists():
            self.write_shortcuts(DEFAULT_SHORTCUTS)
        try:
            raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception as exc:
            self.shortcut_values = DEFAULT_SHORTCUTS.copy()
            self.shortcut_map = self.build_shortcut_map(self.shortcut_values)
            self.set_status(f"Shortcut file error: {exc}")
            return

        merged = {
            action_name: raw.get(action_name, DEFAULT_SHORTCUTS[action_name])
            for action_name in ACTION_ORDER
        }
        self.shortcut_values = merged
        self.shortcut_map = self.build_shortcut_map(merged)

    def load_webdev_config(self) -> None:
        if not WEBDEV_CONFIG_PATH.exists():
            self.write_webdev_config(DEFAULT_WEBDEV_CONFIG)
        try:
            raw = json.loads(WEBDEV_CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception as exc:
            self.webdev_config = deepcopy(DEFAULT_WEBDEV_CONFIG)
            self.set_status(f"Webdev file error: {exc}")
            return

        self.webdev_config = self.normalize_webdev_config(raw)

    def load_project_config(self) -> None:
        if not self.project_file_path:
            return
        try:
            raw = json.loads(self.project_file_path.read_text(encoding="utf-8"))
        except Exception as exc:
            self.set_status(f"Project file error: {exc}")
            return

        self.project_config = self.normalize_project_config(raw)
        self.project_name = self.project_config["name"] or self.project_root.name

        self.webdev_config["postgres"] = deepcopy(
            self.project_config["postgres"] or self.webdev_config["postgres"]
        )
        self.webdev_config["backend"] = deepcopy(self.project_config["backend"])
        self.webdev_config["frontend"] = deepcopy(self.project_config["frontend"])
        self.webdev_config["workers"] = deepcopy(
            self.project_config["workers"] or self.webdev_config["workers"]
        )
        self.webdev_config["tests"] = deepcopy(self.project_config["tests"])
        for tool_name in AI_TOOL_NAMES:
            self.webdev_config["ai"][tool_name] = deepcopy(
                self.project_config["ai"][tool_name]
            )

    def apply_project_metadata(self) -> None:
        title = "feterminal"
        if self.project_name:
            title = f"{title} - {self.project_name}"
            self.set_status(f"Loaded project: {self.project_name}")
        self.set_title(title)

    def normalize_webdev_config(self, raw: dict) -> dict:
        merged = deep_merge(DEFAULT_WEBDEV_CONFIG, raw if isinstance(raw, dict) else {})
        config = {
            "postgres": normalize_postgres_entries(merged.get("postgres", [])),
            "backend": normalize_service_config(merged.get("backend", {})),
            "frontend": normalize_service_config(merged.get("frontend", {})),
            "workers": [],
            "tests": normalize_test_entries(merged.get("tests", [])),
            "ai": {},
        }
        for index, worker in enumerate(merged.get("workers", []), start=1):
            config["workers"].append(
                {
                    "id": worker.get("id", f"worker-{index}"),
                    "name": worker.get("name", f"Worker {index}"),
                    "commands": normalize_service_config(worker)["commands"],
                }
            )
        if not config["workers"]:
            config["workers"] = deepcopy(DEFAULT_WEBDEV_CONFIG["workers"])
        for tool_name in AI_TOOL_NAMES:
            config["ai"][tool_name] = normalize_service_config(
                merged.get("ai", {}).get(tool_name, {})
            )
        if not config["postgres"]:
            config["postgres"] = [
                {
                    "id": "postgres-1",
                    "name": "Postgres",
                    "database": "",
                    "container": DEFAULT_POSTGRES_CONTAINER,
                    "user": "postgres",
                    "password": "",
                    "host": DEFAULT_POSTGRES_HOST,
                    "port": DEFAULT_POSTGRES_PORT,
                    "commands": [],
                }
            ]
        return config

    def normalize_project_config(self, raw: dict) -> dict:
        merged = deep_merge(DEFAULT_PROJECT_CONFIG, raw if isinstance(raw, dict) else {})
        config = {
            "name": str(merged.get("name", "")).strip(),
            "postgres": normalize_postgres_entries(merged.get("postgres", [])),
            "backend": normalize_service_config(merged.get("backend", {})),
            "frontend": normalize_service_config(merged.get("frontend", {})),
            "workers": [],
            "tests": normalize_test_entries(merged.get("tests", [])),
            "ai": {},
        }
        for index, worker in enumerate(merged.get("workers", []), start=1):
            config["workers"].append(
                {
                    "id": worker.get("id", f"worker-{index}"),
                    "name": worker.get("name", f"Worker {index}"),
                    "commands": normalize_service_config(worker)["commands"],
                }
            )
        for tool_name in AI_TOOL_NAMES:
            config["ai"][tool_name] = normalize_service_config(
                merged.get("ai", {}).get(tool_name, {})
            )
        return config

    def write_shortcuts(self, shortcuts: dict) -> None:
        CONFIG_PATH.write_text(json.dumps(shortcuts, indent=2) + "\n", encoding="utf-8")

    def write_webdev_config(self, config: dict) -> None:
        WEBDEV_CONFIG_PATH.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")

    def write_project_config(self) -> None:
        if not self.project_file_path:
            return
        payload = {
            "name": self.project_name or self.project_root.name,
            "postgres": deepcopy(self.webdev_config["postgres"]),
            "backend": deepcopy(self.webdev_config["backend"]),
            "frontend": deepcopy(self.webdev_config["frontend"]),
            "workers": deepcopy(self.webdev_config["workers"]),
            "tests": deepcopy(self.webdev_config["tests"]),
            "ai": deepcopy(self.webdev_config["ai"]),
        }
        self.project_file_path.write_text(
            json.dumps(payload, indent=2) + "\n",
            encoding="utf-8",
        )

    def save_shortcuts(self, shortcuts: dict) -> None:
        merged = {
            action_name: shortcuts.get(action_name, DEFAULT_SHORTCUTS[action_name])
            for action_name in ACTION_ORDER
        }
        self.write_shortcuts(merged)
        self.load_shortcuts()
        self.set_status("Saved shortcuts")

    def build_shortcut_map(self, shortcuts: dict) -> dict:
        parsed = {}
        for action_name, bindings in shortcuts.items():
            for accel in bindings:
                ok, keyval, mods = Gtk.accelerator_parse(accel)
                if ok:
                    key = (
                        Gdk.keyval_to_lower(keyval),
                        int(mods) & int(self.default_mod_mask),
                    )
                    parsed[key] = action_name
        return parsed

    def set_status(self, message: str) -> None:
        self.status_label.set_text(message)

    def run_capture(self, args: list[str], cwd: Path | None = None) -> str | None:
        try:
            completed = subprocess.run(
                args,
                cwd=str(cwd) if cwd else None,
                check=True,
                capture_output=True,
                text=True,
                timeout=2,
            )
        except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return None
        return completed.stdout.strip()

    def github_account_label(self) -> str:
        gh_status = self.run_capture(["gh", "auth", "status"], self.project_root)
        if gh_status:
            for line in gh_status.splitlines():
                if "Logged in to github.com account " in line:
                    return line.split("Logged in to github.com account ", 1)[1].split(" ", 1)[0]
        git_user = self.run_capture(["git", "config", "--get", "user.name"], self.project_root)
        if git_user:
            return git_user
        return "unknown"

    def github_avatar_path(self, github_user: str) -> Path | None:
        if not github_user or github_user == "unknown":
            return None
        AVATAR_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        avatar_path = AVATAR_CACHE_DIR / f"{github_user}.png"
        try:
            urllib.request.urlretrieve(f"https://github.com/{github_user}.png", avatar_path)
        except OSError:
            return None
        return avatar_path

    def refresh_git_status(self) -> None:
        branch = self.run_capture(["git", "branch", "--show-current"], self.project_root)
        commit = self.run_capture(["git", "rev-parse", "--short", "HEAD"], self.project_root)
        if not branch or not commit:
            self.git_status_label.set_text("")
            return
        github_user = self.github_account_label()
        self.github_avatar_image.set_text(github_user[:1].upper() if github_user and github_user != "unknown" else "?")
        avatar_path = self.github_avatar_path(github_user)
        if avatar_path and avatar_path.exists():
            try:
                pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(
                    str(avatar_path),
                    16,
                    16,
                    True,
                )
            except GLib.Error:
                self.github_avatar_image.set_custom_image(None)
            else:
                texture = Gdk.Texture.new_for_pixbuf(pixbuf)
                self.github_avatar_image.set_custom_image(texture)
        self.git_status_label.set_text(f"{branch}@{commit} |")
        self.github_user_label.set_text(github_user)

    def default_working_directory(self) -> str:
        return str(self.project_root if self.project_file_path else Path.home())

    def service_working_directory(self, _service_id: str) -> str:
        return self.default_working_directory()

    def service_log_directory(self) -> Path:
        log_dir = self.project_root / SERVICE_LOG_DIR_NAME
        log_dir.mkdir(parents=True, exist_ok=True)
        return log_dir

    def service_log_path(self, service_id: str) -> Path:
        safe_service_id = service_id.replace(":", "-").replace("/", "-")
        return self.service_log_directory() / f"{safe_service_id}.log"

    def service_error_count(self, service_id: str) -> int:
        return len(self.service_error_entries(service_id))

    def service_error_entries(self, service_id: str) -> list[str]:
        log_path = self.service_log_path(service_id)
        if not log_path.exists():
            return []
        try:
            text = strip_ansi_sequences(
                log_path.read_text(encoding="utf-8", errors="ignore").replace("\r", "\n")
            )
        except OSError:
            return []
        lines = text.splitlines()
        entries: list[str] = []
        current: list[str] = []
        current_multiline = False

        def flush_current() -> None:
            nonlocal current, current_multiline
            if not current:
                return
            block = "\n".join(line.rstrip() for line in current).strip()
            if block:
                entries.append(block)
            current = []
            current_multiline = False

        for line in lines:
            stripped = line.rstrip()
            is_event_start = bool(ERROR_EVENT_START_PATTERN.search(stripped))
            has_error_signal = bool(ERROR_PATTERN.search(stripped))
            is_multiline_start = bool(MULTILINE_ERROR_START_PATTERN.search(stripped))

            if is_event_start and current:
                flush_current()

            if is_event_start:
                current.append(stripped)
                current_multiline = is_multiline_start
                if not current_multiline:
                    flush_current()
                continue

            if current:
                if not current_multiline:
                    flush_current()
                elif not stripped:
                    flush_current()
                else:
                    current.append(stripped)
                continue

            if has_error_signal:
                entries.append(stripped)

        flush_current()
        return entries

    def service_debug_entries(self, service_id: str) -> list[str]:
        log_path = self.service_log_path(service_id)
        if not log_path.exists():
            return []
        try:
            text = strip_ansi_sequences(
                log_path.read_text(encoding="utf-8", errors="ignore").replace("\r", "\n")
            )
        except OSError:
            return []
        return [line.strip() for line in text.splitlines() if DEBUG_PATTERN.search(line)]

    def service_debug_count(self, service_id: str) -> int:
        return len(self.service_debug_entries(service_id))

    def initial_terminal_banner_script(self) -> str:
        lines = [
            "clear",
            "printf '\\033[38;5;183m╭──────────────────────────────────────────────────────────────╮\\033[0m\\n'",
            "printf '\\033[38;5;183m│\\033[0m \\033[1;35mfeterminal\\033[0m                                              \\033[38;5;183m│\\033[0m\\n'",
            "printf '\\033[38;5;183m│\\033[0m Right-side terminals, Webdev processes, and project files   \\033[38;5;183m│\\033[0m\\n'",
            "printf '\\033[38;5;183m╰──────────────────────────────────────────────────────────────╯\\033[0m\\n\\n'",
        ]
        if self.project_name:
            lines.append(
                f"printf '  \\033[1;37mProject\\033[0m    {self.project_name}\\n'"
            )
        lines.extend(
            [
                "printf '  \\033[1;37mSidebar\\033[0m    Terminal tabs and Webdev tree live on the right\\n'",
                "printf '  \\033[1;37mSettings\\033[0m   Use the Webdev gear button to edit commands\\n'",
                "printf '  \\033[1;37mProject file\\033[0m .feterminal loads project-specific commands\\n\\n'",
                "printf '  \\033[38;5;117mGitHub\\033[0m     https://github.com/Poppolouse/feterminal\\n'",
                "printf '  \\033[38;5;117mRelease\\033[0m    v0.4.0\\n\\n'",
            ]
        )
        return "\n".join(lines) + "\n"

    def shell_argv_for_terminal(self) -> list[str]:
        shell = os.environ.get("SHELL", "/bin/bash")
        if Path(shell).name == "bash":
            fd, rc_path = tempfile.mkstemp(prefix="feterminal-bashrc-", suffix=".sh")
            os.close(fd)
            rcfile = Path(rc_path)
            rcfile.write_text(
                "if [ -f ~/.bashrc ]; then . ~/.bashrc; fi\n"
                + self.initial_terminal_banner_script(),
                encoding="utf-8",
            )
            self.bootstrap_files.append(rcfile)
            return [shell, "--rcfile", str(rcfile), "-i"]
        return [shell]

    def make_terminal_page(self, page_name: str) -> Vte.Terminal:
        terminal = Vte.Terminal()
        terminal.set_scrollback_lines(10000)
        terminal.set_hexpand(True)
        terminal.set_vexpand(True)
        terminal.set_mouse_autohide(True)
        self.content_stack.add_named(terminal, page_name)
        return terminal

    def spawn_shell_terminal(self, terminal: Vte.Terminal) -> int:
        _ok, child_pid = terminal.spawn_sync(
            Vte.PtyFlags.DEFAULT,
            self.default_working_directory(),
            self.shell_argv_for_terminal(),
            None,
            GLib.SpawnFlags.DEFAULT,
            None,
            None,
            None,
        )
        return child_pid

    def add_terminal_tab(self) -> None:
        self.tab_counter += 1
        page_name = f"terminal:{self.tab_counter}"
        title = f"Terminal {self.tab_counter}"
        terminal = self.make_terminal_page(page_name)
        terminal.connect("child-exited", self.on_terminal_child_exited, page_name)
        child_pid = self.spawn_shell_terminal(terminal)
        self.terminal_tabs[page_name] = {"title": title, "terminal": terminal, "child_pid": child_pid}
        self.add_terminal_row(page_name, title)
        self.select_page(page_name)

    def add_terminal_row(self, page_name: str, title: str) -> None:
        row = Gtk.ListBoxRow()
        row.page_name = page_name
        row_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=8,
            margin_top=8,
            margin_bottom=8,
            margin_start=10,
            margin_end=10,
        )
        row_box.append(Gtk.Image.new_from_icon_name(SERVICE_ICONS["terminal"]))
        row_box.append(Gtk.Label(label=title, xalign=0, hexpand=True))
        close_button = Gtk.Button(icon_name="window-close-symbolic")
        close_button.add_css_class("flat")
        close_button.connect("clicked", self.on_close_terminal_clicked, page_name)
        row_box.append(close_button)
        row.set_child(row_box)
        self.terminal_listbox.append(row)

    def rebuild_webdev_sidebar(self) -> None:
        self.clear_box(self.webdev_tree_box)
        self.service_rows = {}
        self.category_revealers = {}
        self.category_arrow_images = {}
        self.webdev_consoles_button.remove_css_class("suggested-action")
        self.webdev_consoles_button.remove_css_class("flat")
        self.webdev_errors_button.remove_css_class("suggested-action")
        self.webdev_errors_button.remove_css_class("flat")
        self.webdev_debug_button.remove_css_class("suggested-action")
        self.webdev_debug_button.remove_css_class("flat")
        self.webdev_tests_button.remove_css_class("suggested-action")
        self.webdev_tests_button.remove_css_class("flat")
        if self.webdev_view_mode == "consoles":
            self.webdev_consoles_button.add_css_class("suggested-action")
            self.webdev_errors_button.add_css_class("flat")
            self.webdev_debug_button.add_css_class("flat")
            self.webdev_tests_button.add_css_class("flat")
        elif self.webdev_view_mode == "errors":
            self.webdev_errors_button.add_css_class("suggested-action")
            self.webdev_consoles_button.add_css_class("flat")
            self.webdev_debug_button.add_css_class("flat")
            self.webdev_tests_button.add_css_class("flat")
        elif self.webdev_view_mode == "debug":
            self.webdev_debug_button.add_css_class("suggested-action")
            self.webdev_consoles_button.add_css_class("flat")
            self.webdev_errors_button.add_css_class("flat")
            self.webdev_tests_button.add_css_class("flat")
        else:
            self.webdev_consoles_button.add_css_class("flat")
            self.webdev_errors_button.add_css_class("flat")
            self.webdev_debug_button.add_css_class("flat")
            self.webdev_tests_button.add_css_class("suggested-action")

        if self.webdev_view_mode == "tests":
            test_items = [
                (test["id"], test["name"], "tests")
                for test in self.webdev_config["tests"]
            ]
            self.webdev_tree_box.append(
                self.build_category_section("tests", "Tests", test_items)
            )
            return

        self.webdev_tree_box.append(
            self.build_category_section(
                "postgres",
                "Postgres",
                [(entry["id"], entry["name"], "postgres") for entry in self.webdev_config["postgres"]],
            )
        )
        self.webdev_tree_box.append(
            self.build_category_section("backend", "Backend", [("backend", "Backend", "backend")])
        )
        self.webdev_tree_box.append(
            self.build_category_section("frontend", "Frontend", [("frontend", "Frontend", "frontend")])
        )
        worker_items = [
            (worker["id"], worker["name"], "workers")
            for worker in self.webdev_config["workers"]
        ]
        self.webdev_tree_box.append(
            self.build_category_section("workers", "Workers", worker_items)
        )
        if self.webdev_view_mode == "consoles":
            ai_items = [
                (f"ai:{tool_name}", AI_LABELS[tool_name], "ai")
                for tool_name in AI_TOOL_NAMES
            ]
            self.webdev_tree_box.append(self.build_category_section("ai", "AI", ai_items))

    def build_category_section(self, category_id: str, title: str, items: list) -> Gtk.Box:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        header_button = Gtk.Button()
        header_button.add_css_class("flat")
        header_button.set_halign(Gtk.Align.FILL)
        header_button.connect("clicked", self.on_toggle_category_clicked, category_id)

        header_row = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=6,
            margin_top=4,
            margin_bottom=4,
            margin_start=2,
            margin_end=2,
        )
        arrow = Gtk.Image.new_from_icon_name("pan-down-symbolic")
        self.category_arrow_images[category_id] = arrow
        header_row.append(arrow)
        label = Gtk.Label(label=title, xalign=0)
        label.add_css_class("heading")
        header_row.append(label)
        header_row.append(Gtk.Box(hexpand=True))
        header_button.set_child(header_row)
        box.append(header_button)

        content = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=4,
            margin_top=0,
            margin_bottom=4,
            margin_start=12,
            margin_end=0,
        )
        for service_id, label, icon_group in items:
            content.append(self.build_service_row(service_id, label, SERVICE_ICONS[icon_group], self.webdev_view_mode))
        revealer = Gtk.Revealer(
            transition_type=Gtk.RevealerTransitionType.SLIDE_DOWN
        )
        revealer.set_reveal_child(True)
        revealer.set_child(content)
        self.category_revealers[category_id] = revealer
        box.append(revealer)
        return box

    def build_service_row(self, service_id: str, label_text: str, icon_name: str, mode: str) -> Gtk.Box:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.set_margin_top(2)
        row.set_margin_bottom(2)
        row.set_hexpand(True)

        open_button = Gtk.Button()
        open_button.add_css_class("flat")
        open_button.set_hexpand(True)

        content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        content.set_hexpand(True)
        content.append(self.make_service_icon(service_id, icon_name))
        title = Gtk.Label(label=label_text, xalign=0)
        title.set_hexpand(True)
        content.append(title)
        if mode == "errors":
            status_text = "0 errors"
        elif mode == "debug":
            status_text = "0 debug"
        else:
            status_text = "idle"
        status = Gtk.Label(label=status_text, xalign=0)
        status.add_css_class("caption")
        content.append(status)
        open_button.set_child(content)
        open_button.connect("clicked", self.on_service_open_clicked, service_id, mode)

        start_button = Gtk.Button(icon_name="media-playback-start-symbolic")
        start_button.add_css_class("flat")
        start_button.set_tooltip_text("Start")
        start_button.connect("clicked", self.on_start_service_clicked, service_id)
        stop_button = Gtk.Button(icon_name="media-playback-stop-symbolic")
        stop_button.add_css_class("flat")
        stop_button.set_tooltip_text("Stop")
        stop_button.connect("clicked", self.on_stop_service_clicked, service_id)

        row.append(open_button)
        row.append(start_button)
        row.append(stop_button)

        self.service_rows[service_id] = {
            "status": status,
            "start_button": start_button,
            "stop_button": stop_button,
            "mode": mode,
        }
        self.update_service_row(service_id)
        return row

    def make_service_icon(self, service_id: str, fallback_icon_name: str):
        if service_id.startswith("ai:"):
            icon_path = AI_ICON_FILES[service_id.split(":", 1)[1]]
            if icon_path.exists():
                image = Gtk.Image.new_from_file(str(icon_path))
                image.set_pixel_size(16)
                return image
        return Gtk.Image.new_from_icon_name(fallback_icon_name)

    def service_config_by_id(self, service_id: str) -> dict:
        for postgres_entry in self.webdev_config["postgres"]:
            if postgres_entry["id"] == service_id:
                return postgres_entry
        if service_id == "backend":
            return self.webdev_config["backend"]
        if service_id == "frontend":
            return self.webdev_config["frontend"]
        if service_id.startswith("ai:"):
            return self.webdev_config["ai"][service_id.split(":", 1)[1]]
        for test in self.webdev_config["tests"]:
            if test["id"] == service_id:
                return test
        for worker in self.webdev_config["workers"]:
            if worker["id"] == service_id:
                return worker
        raise KeyError(service_id)

    def service_label(self, service_id: str) -> str:
        for postgres_entry in self.webdev_config["postgres"]:
            if postgres_entry["id"] == service_id:
                return postgres_entry["name"]
        if service_id == "backend":
            return "Backend"
        if service_id == "frontend":
            return "Frontend"
        if service_id.startswith("ai:"):
            return AI_LABELS[service_id.split(":", 1)[1]]
        for test in self.webdev_config["tests"]:
            if test["id"] == service_id:
                return test["name"]
        return self.service_config_by_id(service_id)["name"]

    def service_page_name(self, service_id: str) -> str:
        return f"service:{service_id}"

    def service_error_page_name(self, service_id: str) -> str:
        return f"service-errors:{service_id}"

    def service_debug_page_name(self, service_id: str) -> str:
        return f"service-debug:{service_id}"

    def current_terminal(self):
        if self.active_page_name in self.terminal_tabs:
            return self.terminal_tabs[self.active_page_name]["terminal"]
        service_id = self.active_page_name.removeprefix("service:") if self.active_page_name else ""
        session = self.service_sessions.get(service_id)
        if session:
            return session["terminal"]
        self.set_status("Active page is not a terminal")
        return None

    def select_page(self, page_name: str) -> None:
        self.active_page_name = page_name
        self.content_stack.set_visible_child_name(page_name)
        if page_name in self.terminal_tabs:
            for row in self.iter_listbox_rows(self.terminal_listbox):
                if getattr(row, "page_name", None) == page_name:
                    self.terminal_listbox.select_row(row)
                    break
        else:
            self.terminal_listbox.unselect_all()
        self._update_ai_footer_buttons()

    def _update_ai_footer_buttons(self) -> None:
        for tool_name, btn in self.ai_footer_buttons.items():
            service_id = f"ai:{tool_name}"
            is_active = self.active_page_name == self.service_page_name(service_id)
            btn.remove_css_class("suggested-action")
            btn.remove_css_class("flat")
            if is_active:
                btn.add_css_class("suggested-action")
            else:
                btn.add_css_class("flat")

    def iter_listbox_rows(self, listbox: Gtk.ListBox):
        row = listbox.get_first_child()
        while row is not None:
            yield row
            row = row.get_next_sibling()

    def commands_for_service(self, service_id: str) -> list[str]:
        return self.service_config_by_id(service_id)["commands"]

    def commands_script(self, service_id: str) -> str:
        return "\n".join(self.commands_for_service(service_id))

    def service_spawn_argv(self, service_id: str) -> list[str]:
        log_path = self.service_log_path(service_id)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("", encoding="utf-8")
        return build_service_spawn_argv(self.commands_script(service_id), log_path)

    def action_copy(self, *_args) -> None:
        terminal = self.current_terminal()
        if terminal is None:
            return
        terminal.copy_clipboard_format(Vte.Format.TEXT)
        self.set_status("Copied")

    def action_paste(self, *_args) -> None:
        terminal = self.current_terminal()
        if terminal is None:
            return
        terminal.paste_clipboard()
        self.set_status("Pasted text")

    def action_send_interrupt(self, *_args) -> None:
        terminal = self.current_terminal()
        if terminal is None:
            return
        terminal.feed_child_binary(b"\x03")
        self.set_status("Sent SIGINT")

    def action_paste_image(self, *_args) -> None:
        terminal = self.current_terminal()
        if terminal is None:
            return
        clipboard = self.get_display().get_clipboard()
        clipboard.read_texture_async(None, self.on_texture_ready, terminal)

    def on_texture_ready(self, clipboard, result, terminal) -> None:
        try:
            texture = clipboard.read_texture_finish(result)
        except GLib.Error as exc:
            self.set_status(f"Image read failed: {exc.message}")
            return
        if texture is None:
            self.set_status("Clipboard has no image")
            return
        handle, output_path = tempfile.mkstemp(
            prefix="feterminal-image-",
            suffix=".png",
            dir=GLib.get_tmp_dir(),
        )
        os.close(handle)
        texture.save_to_png(output_path)
        terminal.feed_child((shlex.quote(output_path) + " ").encode("utf-8"))
        self.set_status(f"Saved image to {output_path}")

    def action_new_terminal_tab(self, *_args) -> None:
        self.add_terminal_tab()
        self.set_status("Opened a new terminal tab")

    def action_reset(self, *_args) -> None:
        terminal = self.current_terminal()
        if terminal is None:
            return
        terminal.reset(True, True)
        self.set_status("Terminal reset")

    def action_reload_shortcuts(self, *_args) -> None:
        self.load_shortcuts()
        self.set_status("Reloaded shortcuts")

    def action_open_preferences(self, *_args) -> None:
        if self.preferences_window is None:
            self.preferences_window = ShortcutPreferencesWindow(
                self,
                self.shortcut_values,
                self.save_shortcuts,
            )
            self.preferences_window.connect("close-request", self.on_preferences_close)
        self.preferences_window.present()

    def on_preferences_close(self, *_args):
        self.preferences_window = None
        return False

    def action_close_window(self, *_args) -> None:
        self.close()

    def on_key_pressed(self, _controller, keyval, _keycode, state):
        key = (
            Gdk.keyval_to_lower(keyval),
            int(state) & int(self.default_mod_mask),
        )
        action_name = self.shortcut_map.get(key)
        if not action_name:
            return False
        self.activate_action(f"win.{action_name}", None)
        return True

    def on_add_terminal_tab_clicked(self, *_args) -> None:
        self.add_terminal_tab()
        self.set_status("Opened a new terminal tab")

    def close_terminal_tab(self, page_name: str, *, terminate_process: bool = True) -> None:
        if page_name not in self.terminal_tabs:
            return
        tab = self.terminal_tabs[page_name]
        if terminate_process:
            try:
                os.kill(tab["child_pid"], signal.SIGTERM)
            except ProcessLookupError:
                pass
        terminal = tab["terminal"]
        self.content_stack.remove(terminal)
        del self.terminal_tabs[page_name]
        for row in list(self.iter_listbox_rows(self.terminal_listbox)):
            if getattr(row, "page_name", None) == page_name:
                self.terminal_listbox.remove(row)
                break
        next_page = next(iter(self.terminal_tabs), None)
        if next_page:
            self.select_page(next_page)

    def on_close_terminal_clicked(self, _button, page_name: str) -> None:
        self.close_terminal_tab(page_name)
        self.set_status("Closed terminal tab")

    def on_terminal_child_exited(self, _terminal, _status, page_name: str) -> None:
        if page_name not in self.terminal_tabs:
            return
        self.close_terminal_tab(page_name, terminate_process=False)
        self.set_status("Terminal tab exited")

    def on_terminal_row_selected(self, _listbox, row) -> None:
        if row is None:
            return
        self.select_page(row.page_name)

    def on_webdev_toggle_clicked(self, *_args) -> None:
        self.webdev_revealer.set_reveal_child(not self.webdev_revealer.get_reveal_child())

    def on_webdev_view_mode_clicked(self, _button, mode: str) -> None:
        if self.webdev_view_mode == mode:
            return
        self.webdev_view_mode = mode
        self.rebuild_webdev_sidebar()

    def on_ai_footer_button_clicked(self, _button, tool_name: str) -> None:
        service_id = f"ai:{tool_name}"
        session = self.service_sessions.get(service_id)
        if session is None:
            self.set_status(f"{AI_LABELS[tool_name]} is not running — press Start in the sidebar first")
            return
        self.select_page(session["page_name"])
        self.set_status(f"Switched to {AI_LABELS[tool_name]}")

    def on_toggle_sidebar_clicked(self, *_args) -> None:
        self.sidebar_visible = not self.sidebar_visible
        if self.sidebar_visible:
            self.sidebar_shell.set_visible(True)
        self.sidebar_revealer.set_reveal_child(self.sidebar_visible)

    def on_toggle_category_clicked(self, _button, category_id: str) -> None:
        revealer = self.category_revealers[category_id]
        expanded = not revealer.get_reveal_child()
        revealer.set_reveal_child(expanded)
        self.category_arrow_images[category_id].set_from_icon_name(
            "pan-down-symbolic" if expanded else "pan-end-symbolic"
        )

    def on_toggle_settings_clicked(self, *_args) -> None:
        reveal = not self.settings_visible
        self.settings_visible = reveal
        self.rebuild_settings_panel()
        if reveal:
            self.settings_shell.set_visible(True)
        self.settings_revealer.set_reveal_child(reveal)

    def on_sidebar_child_revealed(self, _revealer, _pspec) -> None:
        if not self.sidebar_visible and not self.sidebar_revealer.get_child_revealed():
            self.sidebar_shell.set_visible(False)

    def on_settings_child_revealed(self, _revealer, _pspec) -> None:
        if not self.settings_visible and not self.settings_revealer.get_child_revealed():
            self.settings_shell.set_visible(False)

    def commands_from_editor(self, service_id: str) -> list[str]:
        text_view = self.settings_row_inputs[service_id]
        buffer_ = text_view.get_buffer()
        raw_text = buffer_.get_text(buffer_.get_start_iter(), buffer_.get_end_iter(), True)
        return [line.strip() for line in raw_text.splitlines() if line.strip()]

    def persist_webdev_state(self) -> None:
        if self.project_file_path:
            self.write_project_config()
        else:
            self.write_webdev_config(self.webdev_config)

    def on_save_service_clicked(self, _button, service_id: str) -> None:
        self.service_config_by_id(service_id)["commands"] = self.commands_from_editor(service_id)
        self.persist_webdev_state()
        self.update_service_row(service_id)
        self.set_status(f"Saved commands for {self.service_label(service_id)}")

    def start_service(self, service_id: str) -> None:
        commands = self.commands_for_service(service_id)
        if not commands:
            self.set_status(f"No commands set for {self.service_label(service_id)}")
            return

        session = self.service_sessions.get(service_id)
        if session:
            if session["running"]:
                self.select_page(self.service_page_name(service_id))
                self.set_status(f"{self.service_label(service_id)} is already running")
                return
            self.remove_service_page(service_id)

        page_name = self.service_page_name(service_id)
        terminal = self.make_terminal_page(page_name)
        terminal.connect("child-exited", self.on_service_child_exited, service_id)
        _ok, child_pid = terminal.spawn_sync(
            Vte.PtyFlags.DEFAULT,
            self.service_working_directory(service_id),
            self.service_spawn_argv(service_id),
            None,
            GLib.SpawnFlags.DEFAULT,
            None,
            None,
            None,
        )
        self.service_sessions[service_id] = {
            "terminal": terminal,
            "child_pid": child_pid,
            "page_name": page_name,
            "running": True,
        }
        self.select_page(page_name)
        self.update_service_row(service_id)
        self.set_status(f"Started {self.service_label(service_id)}")

    def stop_service(self, service_id: str) -> None:
        session = self.service_sessions.get(service_id)
        if session is None:
            self.update_service_row(service_id)
            self.set_status(f"{self.service_label(service_id)} is not running")
            return
        if not session["running"]:
            self.remove_service_page(service_id)
            self.update_service_row(service_id)
            self.set_status(f"Closed {self.service_label(service_id)}")
            return
        try:
            os.kill(session["child_pid"], signal.SIGTERM)
        except ProcessLookupError:
            pass
        self.set_status(f"Stopping {self.service_label(service_id)}")

    def remove_service_page(self, service_id: str) -> None:
        session = self.service_sessions.pop(service_id, None)
        if session is None:
            return
        self.content_stack.remove(session["terminal"])
        if self.active_page_name == session["page_name"]:
            fallback = next(iter(self.terminal_tabs), None)
            if fallback:
                self.select_page(fallback)

    def on_service_child_exited(self, _terminal, _status, service_id: str) -> None:
        session = self.service_sessions.get(service_id)
        if session is None:
            return
        session["running"] = False
        session["child_pid"] = 0
        self.update_service_row(service_id)
        self.refresh_error_page(service_id)
        self.refresh_debug_page(service_id)
        self.set_status(f"{self.service_label(service_id)} exited. Press stop to close the terminal.")

    def ensure_error_page(self, service_id: str) -> str:
        existing = self.error_pages.get(service_id)
        if existing:
            return existing["page_name"]
        page_name = self.service_error_page_name(service_id)
        text_view = Gtk.TextView(editable=False, monospace=True, cursor_visible=False, wrap_mode=Gtk.WrapMode.WORD_CHAR)
        text_view.set_top_margin(8)
        text_view.set_bottom_margin(8)
        text_view.set_left_margin(8)
        text_view.set_right_margin(8)
        scroller = Gtk.ScrolledWindow()
        scroller.set_child(text_view)
        self.content_stack.add_named(scroller, page_name)
        self.error_pages[service_id] = {"page_name": page_name, "view": text_view, "container": scroller}
        self.refresh_error_page(service_id)
        return page_name

    def ensure_debug_page(self, service_id: str) -> str:
        existing = self.debug_pages.get(service_id)
        if existing:
            return existing["page_name"]
        page_name = self.service_debug_page_name(service_id)
        text_view = Gtk.TextView(editable=False, monospace=True, cursor_visible=False, wrap_mode=Gtk.WrapMode.WORD_CHAR)
        text_view.set_top_margin(8)
        text_view.set_bottom_margin(8)
        text_view.set_left_margin(8)
        text_view.set_right_margin(8)
        scroller = Gtk.ScrolledWindow()
        scroller.set_child(text_view)
        self.content_stack.add_named(scroller, page_name)
        self.debug_pages[service_id] = {"page_name": page_name, "view": text_view, "container": scroller}
        self.refresh_debug_page(service_id)
        return page_name

    def refresh_error_page(self, service_id: str) -> None:
        page = self.error_pages.get(service_id)
        if not page:
            return
        entries = self.service_error_entries(service_id)
        if entries:
            chunks = [f"{entry}\n\n----------------------------------------" for entry in entries]
            text = "\n\n".join(chunks)
        else:
            text = "No errors captured."
        buffer_ = page["view"].get_buffer()
        current_text = buffer_.get_text(buffer_.get_start_iter(), buffer_.get_end_iter(), True)
        if current_text != text:
            buffer_.set_text(text)

    def refresh_debug_page(self, service_id: str) -> None:
        page = self.debug_pages.get(service_id)
        if not page:
            return
        entries = self.service_debug_entries(service_id)
        if entries:
            chunks = [f"{entry}\n\n----------------------------------------" for entry in entries]
            text = "\n\n".join(chunks)
        else:
            text = "No debug lines captured."
        buffer_ = page["view"].get_buffer()
        current_text = buffer_.get_text(buffer_.get_start_iter(), buffer_.get_end_iter(), True)
        if current_text != text:
            buffer_.set_text(text)

    def on_service_open_clicked(self, _button, service_id: str, mode: str) -> None:
        if mode == "errors":
            self.select_page(self.ensure_error_page(service_id))
            return
        if mode == "debug":
            self.select_page(self.ensure_debug_page(service_id))
            return
        session = self.service_sessions.get(service_id)
        if session is None:
            self.set_status(f"{self.service_label(service_id)} is not running")
            return
        self.select_page(session["page_name"])

    def on_start_service_clicked(self, _button, service_id: str) -> None:
        self.start_service(service_id)
        if self.webdev_view_mode == "errors":
            self.select_page(self.ensure_error_page(service_id))
        elif self.webdev_view_mode == "debug":
            self.select_page(self.ensure_debug_page(service_id))

    def on_stop_service_clicked(self, _button, service_id: str) -> None:
        self.stop_service(service_id)

    def on_add_worker_clicked(self, *_args) -> None:
        next_index = len(self.webdev_config["workers"]) + 1
        while any(worker["id"] == f"worker-{next_index}" for worker in self.webdev_config["workers"]):
            next_index += 1
        self.webdev_config["workers"].append(
            {"id": f"worker-{next_index}", "name": f"Worker {next_index}", "commands": []}
        )
        self.persist_webdev_state()
        self.rebuild_settings_panel()
        self.rebuild_webdev_sidebar()
        self.set_status("Added worker slot")

    def on_remove_worker_clicked(self, _button, service_id: str) -> None:
        self.stop_service(service_id)
        self.remove_service_page(service_id)
        self.webdev_config["workers"] = [
            worker for worker in self.webdev_config["workers"] if worker["id"] != service_id
        ]
        self.persist_webdev_state()
        self.rebuild_settings_panel()
        self.rebuild_webdev_sidebar()
        self.set_status("Removed worker slot")

    def update_service_row(self, service_id: str) -> None:
        row = self.service_rows.get(service_id)
        if row is None:
            return
        session = self.service_sessions.get(service_id)
        running = bool(session and session["running"])
        if row["mode"] == "errors":
            error_count = self.service_error_count(service_id)
            row["status"].set_text(f"{error_count} errors")
        elif row["mode"] == "debug":
            debug_count = self.service_debug_count(service_id)
            row["status"].set_text(f"{debug_count} debug")
        else:
            row["status"].set_text("running" if running else "stopped")
        row["start_button"].set_sensitive(not running)
        row["stop_button"].set_sensitive(session is not None)

    def refresh_service_statuses(self) -> bool:
        for service_id in list(self.service_rows):
            self.update_service_row(service_id)
        for service_id in list(self.error_pages):
            self.refresh_error_page(service_id)
        for service_id in list(self.debug_pages):
            self.refresh_debug_page(service_id)
        return True

    def on_close_request(self, *_args):
        for service_id in list(self.service_sessions):
            self.stop_service(service_id)
        for page_name in list(self.terminal_tabs):
            self.close_terminal_tab(page_name)
        for path in self.bootstrap_files:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        return False


class FeTerminalApp(Adw.Application):
    def __init__(self, cli_target: str | None):
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE | Gio.ApplicationFlags.NON_UNIQUE,
        )
        self.window = None
        self.cli_target = cli_target

    def open_window(
        self,
        cli_target: str | None,
        launch_cwd: str | os.PathLike[str] | None = None,
        *,
        new_window: bool = False,
    ) -> FeTerminalWindow:
        self.window = FeTerminalWindow(self, cli_target, launch_cwd)
        self.window.present()
        return self.window

    def do_activate(self):
        self.open_window(self.cli_target)

    def do_command_line(self, command_line: Gio.ApplicationCommandLine) -> int:
        arguments = command_line.get_arguments()
        cli_target = arguments[1] if len(arguments) > 1 else None
        launch_cwd = command_line.get_cwd() or None

        if cli_target is None and launch_cwd:
            cli_target = launch_cwd

        self.open_window(cli_target, launch_cwd, new_window=self.window is not None)
        return 0


def main() -> int:
    cli_target = sys.argv[1] if len(sys.argv) > 1 else None
    app = FeTerminalApp(cli_target)
    return app.run(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
