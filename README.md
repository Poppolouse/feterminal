# feterminal

A lightweight GTK4 + VTE terminal application that uses Adwaita styling and lets you change shortcuts either from the UI or from `shortcuts.json`.

<p align="center">
  <img src="assets/feterminal.svg" alt="feterminal icon" width="128">
</p>

<p align="center">
  <img src="assets/feterminal-screenshot.svg" alt="feterminal screenshot">
</p>

## Run

```bash
python3 /var/home/poppolouse/feterminal/feterminal.py
```

## Layout

- Terminal tabs live in the right sidebar instead of the top edge.
- You can open multiple terminal tabs.
- The same sidebar includes an expandable `Webdev` tree.
- Clicking `Webdev` does not replace the main terminal area.
- The command editor opens only from the gear button next to `Webdev`.

## Webdev mode

`Webdev` mode groups commands into separate categories in the right sidebar:

- Backend
- Frontend
- Workers
- AI: Codex, Claude Code, Copilot, Gemini

Each slot can:

- `Start`
- `Stop`
- open its running terminal in the main area

The command editor lives in the collapsible settings panel and includes:

- a command field
- `Save`
- dynamic worker management

Workers are dynamic, so you can add more than one worker slot from the UI. Commands are stored in [webdev.json](/var/home/poppolouse/feterminal/webdev.json).

## Default shortcuts

- `Ctrl+C`: copy
- `Ctrl+V`: paste text
- `Ctrl+Shift+C`: send `Ctrl+C` to the active process
- `Ctrl+Shift+V`: save the clipboard image as a PNG under `/tmp` and paste its path
- `Ctrl+Shift+T`: open a new terminal tab
- `Ctrl+Shift+R`: reset the terminal
- `F5`: reload `shortcuts.json`
- `Ctrl+,`: open preferences
- `Ctrl+Shift+Q`: close the window

## Changing shortcuts

You can open `Preferences` from the app menu or press `Ctrl+,`. You can also edit `/var/home/poppolouse/feterminal/shortcuts.json` manually. Example:

```json
{
  "copy": ["<Ctrl>c"],
  "send_interrupt": ["<Ctrl><Shift>c"],
  "paste": ["<Ctrl>v"],
  "paste_image": ["<Ctrl><Shift>v"],
  "open_preferences": ["<Ctrl>comma"]
}
```

Note: terminals do not have a universal standard for pasting images directly into the session. This app handles `Ctrl+Shift+V` by converting the image into a file and inserting the file path into the command line.

## Desktop entry

Application file:

- `/var/home/poppolouse/feterminal/io.poppolouse.feterminal.desktop`
