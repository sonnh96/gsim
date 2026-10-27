"""Per-core option overrides: system defaults, then the user's saved choices."""

from __future__ import annotations

import json
from pathlib import Path

from .paths import data_dir
from .systems import System


class OptionStore:
    """User-chosen core options for one core, stored as JSON."""

    def __init__(self, core_path: str | Path, root: Path | None = None) -> None:
        name = Path(core_path).stem  # e.g. melonds_libretro
        self.path = (root or data_dir() / "options") / f"{name}.json"

    def load(self) -> dict[str, str]:
        try:
            data = json.loads(self.path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return {}
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}

    def set(self, key: str, value: str) -> None:
        data = self.load()
        data[key] = value
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True))
        tmp.replace(self.path)

    def effective(self, system: System) -> dict[str, str]:
        return {**dict(system.options), **self.load()}
