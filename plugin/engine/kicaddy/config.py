"""kicaddy user config, `${XDG_CONFIG_HOME:-~/.config}/kicaddy/config.json`, and the KiCad choice precedence.

Stdlib only. A KiCad choice is `system`, `flatpak` / `flatpak:<APP_ID>`, or a filesystem path.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .bootstrap import SetupError


def config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "kicaddy" / "config.json"


def read() -> dict:
    path = config_path()
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as err:
        raise SetupError(f"cannot read {path}: {err}; fix or delete it") from None
    if not isinstance(data, dict):
        raise SetupError(f"cannot read {path}: not a JSON object; fix or delete it")
    return data


def write_kicad(value: str) -> Path:
    """Set `kicad`, keeping other keys; atomic replace."""
    path = config_path()
    data = read()
    data["kicad"] = value
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    os.replace(tmp, path)
    return path


def normalize(value: str) -> str:
    """`system` and `flatpak[:APP_ID]` as typed; anything else is a path, made absolute."""
    if value == "system" or value == "flatpak" or value.startswith("flatpak:"):
        return value
    return os.path.abspath(os.path.expanduser(value))


def kicad_choice(cli_value: str | None) -> tuple[str, str]:
    """(choice, source): `doctor --kicad` > KICADDY_KICAD > config file > system."""
    if cli_value:
        return cli_value, "cli"
    if os.environ.get("KICADDY_KICAD"):
        return os.environ["KICADDY_KICAD"], "env"
    value = read().get("kicad")
    if value is not None and not isinstance(value, str):
        raise SetupError(f"cannot read {config_path()}: `kicad` must be a string; fix or delete it")
    if value:
        return value, "config"
    return "system", "default"
