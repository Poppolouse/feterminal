#!/usr/bin/env python3

import json
import os
import shlex
import tempfile
from pathlib import Path

import gi

gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")
gi.require_version("Vte", "3.91")

from gi.repository import Gio, GLib, Gdk, Gtk, Vte


APP_ID = "io.poppolouse.feterminal"
APP_DIR = Path(__file__).resolve().parent
CONFIG_PATH = APP_DIR / "shortcuts.json"
DEFAULT_SHORTCUTS = {
    "copy": ["<Ctrl>c"],
    "paste": ["<Ctrl>v"],
    "send_interrupt": ["<Ctrl><Shift>c"],
    "paste_image": ["<Ctrl><Shift>v"],
    "reset": ["<Ctrl><Shift>r"],
    "reload_shortcuts": ["F5"],
    "close_window": ["<Ctrl><Shift>q"],
}


class FeTerminalWindow(Gtk.ApplicationWindow):
    def __init__(self, app: Gtk.Application):
        super().__init__(application=app, title="feterminal")
        self.set_default_size(980, 640)

        self.shortcut_map = {}
        self.default_mod_mask = Gtk.accelerator_get_default_mod_mask()

        self.terminal = Vte.Terminal()
        self.terminal.set_scrollback_lines(10000)
        self.terminal.set_hexpand(True)
        self.terminal.set_vexpand(True)
        self.terminal.set_mouse_autohide(True)

        self.status_label = Gtk.Label(
            label=f"Kisayol dosyasi: {CONFIG_PATH}",
            xalign=0,
        )

        header = Gtk.HeaderBar()
        header.set_title_widget(Gtk.Label(label="feterminal"))
        self.set_titlebar(header)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        box.append(self.terminal)
        box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        box.append(self.status_label)
        self.set_child(box)

        controller = Gtk.EventControllerKey()
        controller.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        controller.connect("key-pressed", self.on_key_pressed)
        self.add_controller(controller)

        self.connect("close-request", self.on_close_request)
        self.install_actions()
        self.load_shortcuts()
        self.spawn_shell()

    def install_actions(self) -> None:
        actions = {
            "copy": self.action_copy,
            "paste": self.action_paste,
            "send_interrupt": self.action_send_interrupt,
            "paste_image": self.action_paste_image,
            "reset": self.action_reset,
            "reload_shortcuts": self.action_reload_shortcuts,
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

    def on_close_request(self, *_args):
        if self.terminal.get_pty() is not None:
            self.terminal.feed_child_binary(b"exit\n")
        return False

    def action_copy(self, *_args) -> None:
        self.terminal.copy_clipboard_format(Vte.Format.TEXT)
        self.status_label.set_text("Kopyalandi")

    def action_paste(self, *_args) -> None:
        self.terminal.paste_clipboard()
        self.status_label.set_text("Yapistirildi")

    def action_send_interrupt(self, *_args) -> None:
        # Send Ctrl+C to the child process even if copy is rebound elsewhere.
        self.terminal.feed_child_binary(b"\x03")
        self.status_label.set_text("SIGINT gonderildi")

    def action_paste_image(self, *_args) -> None:
        clipboard = self.get_display().get_clipboard()
        clipboard.read_texture_async(None, self.on_texture_ready)

    def on_texture_ready(self, clipboard, result) -> None:
        try:
            texture = clipboard.read_texture_finish(result)
        except GLib.Error as exc:
            self.status_label.set_text(f"Gorsel okunamadi: {exc.message}")
            return

        if texture is None:
            self.status_label.set_text("Panoda gorsel yok")
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
        self.status_label.set_text(f"Gorsel kaydedildi: {output_path}")

    def action_reset(self, *_args) -> None:
        self.terminal.reset(True, True)
        self.status_label.set_text("Terminal sifirlandi")

    def action_reload_shortcuts(self, *_args) -> None:
        self.load_shortcuts()
        self.status_label.set_text(f"Kisayollar yeniden yuklendi: {CONFIG_PATH}")

    def action_close_window(self, *_args) -> None:
        self.close()

    def load_shortcuts(self) -> None:
        if not CONFIG_PATH.exists():
            CONFIG_PATH.write_text(
                json.dumps(DEFAULT_SHORTCUTS, indent=2) + "\n",
                encoding="utf-8",
            )

        try:
            raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception as exc:
            self.shortcut_map = self.build_shortcut_map(DEFAULT_SHORTCUTS)
            self.status_label.set_text(f"Kisayol dosyasi okunamadi: {exc}")
            return

        merged = DEFAULT_SHORTCUTS | raw
        self.shortcut_map = self.build_shortcut_map(merged)

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


class FeTerminalApp(Gtk.Application):
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
