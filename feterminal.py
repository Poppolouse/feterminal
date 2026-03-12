#!/usr/bin/env python3

import json
import os
import shlex
import signal
import tempfile
from copy import deepcopy
from pathlib import Path

import gi

gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")
gi.require_version("Vte", "3.91")

from gi.repository import Adw, Gio, GLib, Gdk, Gtk, Vte


APP_ID = "io.poppolouse.feterminal"
APP_DIR = Path(__file__).resolve().parent
CONFIG_PATH = APP_DIR / "shortcuts.json"
WEBDEV_CONFIG_PATH = APP_DIR / "webdev.json"
BRAND_ICON_DIR = APP_DIR / "assets" / "brand-icons"
AI_TOOL_NAMES = ["codex", "claude_code", "copilot", "gemini"]
AI_LABELS = {
    "codex": "Codex",
    "claude_code": "Claude Code",
    "copilot": "Copilot",
    "gemini": "Gemini",
}
SERVICE_ICONS = {
    "backend": "network-server-symbolic",
    "frontend": "applications-internet-symbolic",
    "workers": "folder-download-symbolic",
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
    "backend": {"command": ""},
    "frontend": {"command": ""},
    "workers": [{"id": "worker-1", "name": "Worker 1", "command": ""}],
    "ai": {
        "codex": {"command": ""},
        "claude_code": {"command": ""},
        "copilot": {"command": ""},
        "gemini": {"command": ""},
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


def child_setup_new_session():
    os.setsid()


class ShortcutPreferencesWindow(Adw.PreferencesWindow):
    def __init__(self, parent: Gtk.Window, shortcut_values: dict, on_save):
        super().__init__(transient_for=parent, modal=True, title="Preferences")
        self.set_default_size(540, 580)
        self._on_save = on_save
        self.entries = {}

        page = Adw.PreferencesPage()
        shortcut_group = Adw.PreferencesGroup(
            title="Keyboard Shortcuts",
            description="Use GTK accelerator syntax, for example <Ctrl><Shift>c.",
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
    def __init__(self, app: Adw.Application):
        super().__init__(application=app, title="feterminal")
        self.set_default_size(1360, 820)

        self.shortcut_map = {}
        self.shortcut_values = {}
        self.webdev_config = {}
        self.default_mod_mask = Gtk.accelerator_get_default_mod_mask()
        self.preferences_window = None
        self.settings_row_inputs = {}

        self.tab_counter = 0
        self.active_page_name = None
        self.terminal_tabs = {}
        self.service_sessions = {}
        self.service_rows = {}
        self.service_row_boxes = {}
        self.category_revealers = {}
        self.category_arrow_images = {}

        self.status_label = Gtk.Label(
            label="Ready",
            xalign=0,
            margin_top=6,
            margin_bottom=6,
            margin_start=12,
            margin_end=12,
        )
        self.status_label.add_css_class("dim-label")

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

        center_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        center_box.append(self.content_stack)
        center_box.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        center_box.append(self.settings_revealer)

        sidebar = self.build_sidebar()
        self.sidebar_revealer = Gtk.Revealer(
            transition_type=Gtk.RevealerTransitionType.SLIDE_LEFT
        )
        self.sidebar_revealer.set_reveal_child(True)
        sidebar_shell = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        sidebar_shell.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        sidebar_shell.append(sidebar)
        self.sidebar_revealer.set_child(sidebar_shell)

        root_content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        center_box.set_hexpand(True)
        root_content.append(center_box)
        root_content.append(self.sidebar_revealer)

        toolbar_view = Adw.ToolbarView()
        toolbar_view.add_top_bar(header)

        outer_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        outer_box.append(root_content)
        outer_box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        outer_box.append(self.status_label)
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

    def build_sidebar(self) -> Gtk.Box:
        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        sidebar.set_size_request(320, -1)
        sidebar.set_margin_top(10)
        sidebar.set_margin_bottom(10)
        sidebar.set_margin_start(8)
        sidebar.set_margin_end(8)

        terminals_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        terminals_label = Gtk.Label(label="Terminals", xalign=0)
        terminals_label.add_css_class("heading")
        add_button = Gtk.Button(icon_name="list-add-symbolic")
        add_button.add_css_class("flat")
        add_button.connect("clicked", self.on_add_terminal_tab_clicked)
        terminals_header.append(terminals_label)
        terminals_header.append(Gtk.Box(hexpand=True))
        terminals_header.append(add_button)
        sidebar.append(terminals_header)

        self.terminal_listbox = Gtk.ListBox()
        self.terminal_listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.terminal_listbox.add_css_class("boxed-list")
        self.terminal_listbox.connect("row-selected", self.on_terminal_row_selected)
        sidebar.append(self.terminal_listbox)

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
        sidebar.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        sidebar.append(webdev_header)

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
        sidebar.append(self.webdev_revealer)
        sidebar.append(Gtk.Box(vexpand=True))
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
        container.set_size_request(420, -1)
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

        description = Gtk.Label(
            label="Commands stay hidden until you open this panel from the Webdev gear button.",
            wrap=True,
            xalign=0,
        )
        description.add_css_class("dim-label")
        self.settings_container.append(description)

        self.settings_container.append(self.build_settings_group("Backend", [("backend", "Backend")]))
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
        self.settings_container.append(self.build_settings_group("", worker_ids, removable=True))

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

            entry = Gtk.Entry(
                text=self.service_config_by_id(service_id)["command"],
                placeholder_text="Command to run",
            )
            box.append(entry)
            self.settings_row_inputs[service_id] = entry

            button_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            save_button = Gtk.Button(label="Save")
            save_button.add_css_class("suggested-action")
            save_button.connect("clicked", self.on_save_service_clicked, service_id)
            button_row.append(save_button)
            box.append(button_row)

            frame.set_child(box)
            group.append(frame)

        return group

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

        merged = deep_merge(DEFAULT_WEBDEV_CONFIG, raw)
        workers = []
        for index, worker in enumerate(merged.get("workers", []), start=1):
            workers.append(
                {
                    "id": worker.get("id", f"worker-{index}"),
                    "name": worker.get("name", f"Worker {index}"),
                    "command": worker.get("command", ""),
                }
            )
        merged["workers"] = workers or deepcopy(DEFAULT_WEBDEV_CONFIG["workers"])
        for tool_name in AI_TOOL_NAMES:
            merged["ai"][tool_name] = merged["ai"].get(tool_name, {"command": ""})
        self.webdev_config = merged

    def write_shortcuts(self, shortcuts: dict) -> None:
        CONFIG_PATH.write_text(json.dumps(shortcuts, indent=2) + "\n", encoding="utf-8")

    def write_webdev_config(self, config: dict) -> None:
        WEBDEV_CONFIG_PATH.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")

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

    def make_terminal_page(self, title: str, page_name: str) -> Vte.Terminal:
        terminal = Vte.Terminal()
        terminal.set_scrollback_lines(10000)
        terminal.set_hexpand(True)
        terminal.set_vexpand(True)
        terminal.set_mouse_autohide(True)
        self.content_stack.add_named(terminal, page_name)
        return terminal

    def spawn_shell_terminal(self, terminal: Vte.Terminal) -> None:
        terminal.spawn_async(
            Vte.PtyFlags.DEFAULT,
            str(Path.home()),
            [os.environ.get("SHELL", "/bin/bash")],
            None,
            GLib.SpawnFlags.DEFAULT,
            None,
            None,
            -1,
            None,
            None,
            None,
        )

    def add_terminal_tab(self) -> None:
        self.tab_counter += 1
        page_name = f"terminal:{self.tab_counter}"
        title = f"Terminal {self.tab_counter}"
        terminal = self.make_terminal_page(title, page_name)
        self.spawn_shell_terminal(terminal)
        self.terminal_tabs[page_name] = {"title": title, "terminal": terminal}
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
        self.service_row_boxes = {}
        self.category_revealers = {}
        self.category_arrow_images = {}

        self.webdev_tree_box.append(
            self.build_category_section(
                "backend",
                "Backend",
                [("backend", "Backend", "backend")],
            )
        )
        self.webdev_tree_box.append(
            self.build_category_section(
                "frontend",
                "Frontend",
                [("frontend", "Frontend", "frontend")],
            )
        )
        worker_items = [
            (worker["id"], worker["name"], "workers")
            for worker in self.webdev_config["workers"]
        ]
        self.webdev_tree_box.append(
            self.build_category_section("workers", "Workers", worker_items)
        )
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
            row = self.build_service_row(service_id, label, SERVICE_ICONS[icon_group])
            content.append(row)
        revealer = Gtk.Revealer(
            transition_type=Gtk.RevealerTransitionType.SLIDE_DOWN
        )
        revealer.set_reveal_child(True)
        revealer.set_child(content)
        self.category_revealers[category_id] = revealer
        box.append(revealer)
        return box

    def build_service_row(self, service_id: str, label_text: str, icon_name: str) -> Gtk.Box:
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
        status = Gtk.Label(label="idle", xalign=0)
        status.add_css_class("caption")
        content.append(status)
        open_button.set_child(content)
        open_button.connect("clicked", self.on_service_open_clicked, service_id)

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
            "open_button": open_button,
            "label": title,
        }
        self.service_row_boxes[service_id] = row
        self.update_service_row(service_id)
        return row

    def make_service_icon(self, service_id: str, fallback_icon_name: str):
        if service_id.startswith("ai:"):
            icon_path = AI_ICON_FILES[service_id.split(":", 1)[1]]
            if icon_path.exists():
                picture = Gtk.Picture.new_for_filename(str(icon_path))
                picture.set_size_request(16, 16)
                picture.set_can_shrink(True)
                return picture
        return Gtk.Image.new_from_icon_name(fallback_icon_name)

    def service_config_by_id(self, service_id: str) -> dict:
        if service_id == "backend":
            return self.webdev_config["backend"]
        if service_id == "frontend":
            return self.webdev_config["frontend"]
        if service_id.startswith("ai:"):
            return self.webdev_config["ai"][service_id.split(":", 1)[1]]
        for worker in self.webdev_config["workers"]:
            if worker["id"] == service_id:
                return worker
        raise KeyError(service_id)

    def service_label(self, service_id: str) -> str:
        if service_id == "backend":
            return "Backend"
        if service_id == "frontend":
            return "Frontend"
        if service_id.startswith("ai:"):
            return AI_LABELS[service_id.split(":", 1)[1]]
        return self.service_config_by_id(service_id)["name"]

    def service_page_name(self, service_id: str) -> str:
        return f"service:{service_id}"

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

    def iter_listbox_rows(self, listbox: Gtk.ListBox):
        row = listbox.get_first_child()
        while row is not None:
            yield row
            row = row.get_next_sibling()

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

    def on_close_terminal_clicked(self, _button, page_name: str) -> None:
        if page_name not in self.terminal_tabs:
            return
        terminal = self.terminal_tabs[page_name]["terminal"]
        self.content_stack.remove(terminal)
        del self.terminal_tabs[page_name]
        for row in list(self.iter_listbox_rows(self.terminal_listbox)):
            if getattr(row, "page_name", None) == page_name:
                self.terminal_listbox.remove(row)
                break
        next_page = next(iter(self.terminal_tabs), None)
        if next_page is None:
            running_service = next(iter(self.service_sessions), None)
            if running_service is not None:
                self.select_page(self.service_page_name(running_service))
        else:
            self.select_page(next_page)
        self.set_status("Closed terminal tab")

    def on_terminal_row_selected(self, _listbox, row) -> None:
        if row is None:
            return
        self.select_page(row.page_name)

    def on_webdev_toggle_clicked(self, *_args) -> None:
        self.webdev_revealer.set_reveal_child(not self.webdev_revealer.get_reveal_child())

    def on_toggle_sidebar_clicked(self, *_args) -> None:
        self.sidebar_revealer.set_reveal_child(not self.sidebar_revealer.get_reveal_child())

    def on_toggle_category_clicked(self, _button, category_id: str) -> None:
        revealer = self.category_revealers[category_id]
        expanded = not revealer.get_reveal_child()
        revealer.set_reveal_child(expanded)
        self.category_arrow_images[category_id].set_from_icon_name(
            "pan-down-symbolic" if expanded else "pan-end-symbolic"
        )

    def on_toggle_settings_clicked(self, *_args) -> None:
        reveal = not self.settings_revealer.get_reveal_child()
        self.rebuild_settings_panel()
        self.settings_revealer.set_reveal_child(reveal)

    def on_save_service_clicked(self, _button, service_id: str) -> None:
        entry = self.settings_row_inputs[service_id]
        config_ref = self.service_config_by_id(service_id)
        config_ref["command"] = entry.get_text().strip()
        self.write_webdev_config(self.webdev_config)
        self.update_service_row(service_id)
        self.set_status(f"Saved command for {self.service_label(service_id)}")

    def start_service(self, service_id: str) -> None:
        config_ref = self.service_config_by_id(service_id)
        command = config_ref.get("command", "").strip()
        if not command:
            self.set_status(f"No command set for {self.service_label(service_id)}")
            return

        session = self.service_sessions.get(service_id)
        if session and session["child_pid"] > 0:
            self.select_page(self.service_page_name(service_id))
            self.set_status(f"{self.service_label(service_id)} is already running")
            return

        page_name = self.service_page_name(service_id)
        title = self.service_label(service_id)
        terminal = self.make_terminal_page(title, page_name)
        terminal.connect("child-exited", self.on_service_child_exited, service_id)
        _, child_pid = terminal.spawn_sync(
            Vte.PtyFlags.DEFAULT,
            str(Path.home()),
            ["/bin/bash", "-lc", command],
            None,
            GLib.SpawnFlags.DEFAULT,
            child_setup_new_session,
            None,
            None,
        )
        self.service_sessions[service_id] = {
            "terminal": terminal,
            "child_pid": child_pid,
            "page_name": page_name,
        }
        self.select_page(page_name)
        self.update_service_row(service_id)
        self.set_status(f"Started {title}")

    def stop_service(self, service_id: str) -> None:
        session = self.service_sessions.get(service_id)
        if session is None:
            self.update_service_row(service_id)
            self.set_status(f"{self.service_label(service_id)} is not running")
            return
        try:
            os.killpg(session["child_pid"], signal.SIGTERM)
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
            if fallback is not None:
                self.select_page(fallback)

    def on_service_child_exited(self, _terminal, _status, service_id: str) -> None:
        self.remove_service_page(service_id)
        self.update_service_row(service_id)
        self.set_status(f"{self.service_label(service_id)} stopped")

    def on_service_open_clicked(self, _button, service_id: str) -> None:
        session = self.service_sessions.get(service_id)
        if session is None:
            self.set_status(f"{self.service_label(service_id)} is not running")
            return
        self.select_page(session["page_name"])

    def on_start_service_clicked(self, _button, service_id: str) -> None:
        self.start_service(service_id)

    def on_stop_service_clicked(self, _button, service_id: str) -> None:
        self.stop_service(service_id)

    def on_add_worker_clicked(self, *_args) -> None:
        next_index = len(self.webdev_config["workers"]) + 1
        while any(worker["id"] == f"worker-{next_index}" for worker in self.webdev_config["workers"]):
            next_index += 1
        self.webdev_config["workers"].append(
            {"id": f"worker-{next_index}", "name": f"Worker {next_index}", "command": ""}
        )
        self.write_webdev_config(self.webdev_config)
        self.rebuild_settings_panel()
        self.rebuild_webdev_sidebar()
        self.set_status("Added worker slot")

    def on_remove_worker_clicked(self, _button, service_id: str) -> None:
        self.stop_service(service_id)
        self.remove_service_page(service_id)
        self.webdev_config["workers"] = [
            worker for worker in self.webdev_config["workers"] if worker["id"] != service_id
        ]
        self.write_webdev_config(self.webdev_config)
        self.rebuild_settings_panel()
        self.rebuild_webdev_sidebar()
        self.set_status("Removed worker slot")

    def update_service_row(self, service_id: str) -> None:
        row = self.service_rows.get(service_id)
        if row is None:
            return
        session = self.service_sessions.get(service_id)
        running = session is not None
        row["status"].set_text("running" if running else "idle")
        row["start_button"].set_sensitive(not running)
        row["stop_button"].set_sensitive(running)

    def refresh_service_statuses(self) -> bool:
        for service_id in list(self.service_rows):
            self.update_service_row(service_id)
        return True

    def on_close_request(self, *_args):
        for service_id in list(self.service_sessions):
            self.stop_service(service_id)
        return False


class FeTerminalApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)
        self.window = None

    def do_activate(self):
        if self.window is None:
            self.window = FeTerminalWindow(self)
        self.window.present()


def main() -> int:
    app = FeTerminalApp()
    return app.run(None)


if __name__ == "__main__":
    raise SystemExit(main())
