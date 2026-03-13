import os
import shlex
import shutil
import sys
from pathlib import Path


IS_MACOS = sys.platform == "darwin"
SUPPORTED_COMMAND_SHELLS = {"bash", "zsh", "sh"}


def preferred_command_shell() -> str:
    shell = os.environ.get("SHELL", "")
    if shell:
        shell_path = Path(shell)
        if shell_path.name in SUPPORTED_COMMAND_SHELLS and shell_path.exists() and os.access(shell, os.X_OK):
            return shell

    candidates = ["/bin/zsh", "/bin/bash", "/bin/sh"] if IS_MACOS else ["/bin/bash", "/bin/sh", "/bin/zsh"]
    for candidate in candidates:
        candidate_path = Path(candidate)
        if candidate_path.exists() and os.access(candidate, os.X_OK):
            return candidate

    return "/bin/sh"


def build_service_spawn_argv(command_script: str, log_path: Path) -> list[str]:
    shell = preferred_command_shell()
    script_bin = shutil.which("script")
    if not script_bin:
        return [shell, "-lc", command_script]

    if IS_MACOS:
        return [script_bin, "-q", str(log_path), shell, "-lc", command_script]

    shell_command = f"{shlex.quote(shell)} -lc {shlex.quote(command_script)}"
    return [script_bin, "-qef", "-c", shell_command, str(log_path)]
