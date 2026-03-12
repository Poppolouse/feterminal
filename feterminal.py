#!/usr/bin/env python3

import json
import os
import shlex
import tempfile
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
ACTION_ORDER = [
    "copy",
    "paste",
    "send_interrupt",
    "paste_image",
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
    "reset": ["<Ctrl><Shift>r"],
    "reload_shortcuts": ["F5"],
    "open_preferences": ["<Ctrl>comma"],
    "close_window": ["<Ctrl><Shift>q"],
}


class ShortcutPreferencesWindow(Adw.PreferencesWindow):
    def __init__(self, parent: Gtk.Window, shortcut_values: dict, on_save):
        super().__init__(transient_for=parent, modal=True, title="Preferences")
        self.set_default_size(540, 560)
        self._on_save = on_save
        self.entries = {}

        page = Adw.PreferencesPage()
        group = Adw.PreferencesGroup(
            title="Keyboard Shortcuts",
            description="Use GTK accelerator syntax, for example <Ctrl><Shift>c.",
        )
        page.add(group)

        for action_name in ACTION_ORDER:
            row = Adw.ActionRow(title=ACTION_LABELS[action_name])
            entry = Gtk.Entry(
                text=", ".join(shortcut_values.get(action_name, [])),
                hexpand=True,
            )
            row.add_suffix(entry)
            row.set_activatable_widget(entry)
            group.add(row)
            self.entries[action_name] = entry

        button_row = Adw.ActionRow(title="Apply")
        save_button = Gtk.Button(label="Save")
        save_button.add_css_class("suggested-action")
        save_button.connect("clicked", self.on_save_clicked)
        reset_button = Gtk.Button(label="Defaults")
        reset_button.connect("clicked", self.on_reset_clicked)
        button_row.add_suffix(reset_button)
        button_row.add_suffix(save_button)
        group.add(button_row)

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
        self.set_default_size(980, 640)

        self.shortcut_map = {}
        self.shortcut_values = {}
        self.default_mod_mask = Gtk.accelerator_get_default_mod_mask()
        self.preferences_window = None

        self.terminal = Vte.Terminal()
        self.terminal.set_scrollback_lines(10000)
        self.terminal.set_hexpand(True)
        self.terminal.set_vexpand(True)
        self.terminal.set_mouse_autohide(True)

        self.status_label = Gtk.Label(
            label=f"Shortcuts file: {CONFIG_PATH}",
            xalign=0,
            margin_top=6,
            margin_bottom=6,
            margin_start=12,
            margin_end=12,
        )
        self.status_label.add_css_class("dim-label")

        header = Adw.HeaderBar()
        menu_button = Gtk.MenuButton(icon_name="open-menu-symbolic")
        menu_button.set_menu_model(self.build_menu_model())
        header.pack_end(menu_button)

        toolbar_view = Adw.ToolbarView()
        toolbar_view.add_top_bar(header)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        content.append(self.terminal)
        content.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        content.append(self.status_label)
        toolbar_view.set_content(content)
        self.set_content(toolbar_view)

        controller = Gtk.EventControllerKey()
        controller.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        controller.connect("key-pressed", self.on_key_pressed)
        self.add_controller(controller)

        self.install_actions()
        self.load_shortcuts()
        self.spawn_shell()

    def build_menu_model(self) -> Gio.Menu:
        menu = Gio.Menu()
        menu.append("Preferences", "win.open_preferences")
        menu.append("Reload Shortcuts", "win.reload_shortcuts")
        menu.append("Reset Terminal", "win.reset")
        menu.append("Close Window", "win.close_window")
        return menu

    def install_actions(self) -> None:
        actions = {
            "copy": self.action_copy,
            "paste": self.action_paste,
            "send_interrupt": self.action_send_interrupt,
            "paste_image": self.action_paste_image,
            "reset": self.action_reset,
            "reload_shortcuts": self.action_reload_shortcuts,
            "open_preferences": self.action_open_preferences,
            "close_window": self.action_close_window,
        }
        for name, callback in actions.items():
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", callback)
            self.add_action(action)

    def spawn_shell(self) -> None:
        shell = os.environ.get("SHELL", "/bin/bash")
        self.terminal.spawn_async(
            Vte.PtyFlags.DEFAULT,
            str(Path.home()),
            [shell],
            None,
            GLib.SpawnFlags.DEFAULT,
            None,
            None,
            -1,
            None,
            None,
            None,
        )

    def action_copy(self, *_args) -> None:
        self.terminal.copy_clipboard_format(Vte.Format.TEXT)
        self.set_status("Copied")

    def action_paste(self, *_args) -> None:
        self.terminal.paste_clipboard()
        self.set_status("Pasted text")

    def action_send_interrupt(self, *_args) -> None:
        self.terminal.feed_child_binary(b"\x03")
        self.set_status("Sent SIGINT")

    def action_paste_image(self, *_args) -> None:
        clipboard = self.get_display().get_clipboard()
        clipboard.read_texture_async(None, self.on_texture_ready)

    def on_texture_ready(self, clipboard, result) -> None:
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
        quoted_path = shlex.quote(output_path) + " "
        self.terminal.feed_child(quoted_path.encode("utf-8"))
        self.set_status(f"Saved image to {output_path}")

    def action_reset(self, *_args) -> None:
        self.terminal.reset(True, True)
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

    def set_status(self, message: str) -> None:
        self.status_label.set_text(message)

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

    def save_shortcuts(self, shortcuts: dict) -> None:
        merged = {
            action_name: shortcuts.get(action_name, DEFAULT_SHORTCUTS[action_name])
            for action_name in ACTION_ORDER
        }
        self.write_shortcuts(merged)
        self.load_shortcuts()
        self.set_status("Saved shortcuts")

    def write_shortcuts(self, shortcuts: dict) -> None:
        CONFIG_PATH.write_text(json.dumps(shortcuts, indent=2) + "\n", encoding="utf-8")

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
