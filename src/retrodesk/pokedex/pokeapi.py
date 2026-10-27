"""Small PokeAPI client with an on-disk JSON cache, so lookups work offline once fetched."""

from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import dataclass
from pathlib import Path

BASE_URL = "https://pokeapi.co/api/v2"
USER_AGENT = "retrodesk-pokedex/0.1"


def default_cache_dir() -> Path:
    root = os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache"
    return Path(root) / "retrodesk" / "pokeapi"


@dataclass(frozen=True)
class DexEntry:
    id: int
    name: str
    types: list[str]
    stats: dict[str, int]
    abilities: list[str]
    height_dm: int
    weight_hg: int
    flavor: str
    sprite_url: str | None


class PokeApi:
    def __init__(self, cache_dir: Path | None = None, timeout: float = 10.0) -> None:
        self.cache_dir = cache_dir or default_cache_dir()
        self.timeout = timeout

    def _get(self, path: str) -> dict:
        cache = self.cache_dir / (path.strip("/").replace("/", "_") + ".json")
        if cache.exists():
            return json.loads(cache.read_text())
        req = urllib.request.Request(f"{BASE_URL}/{path.strip('/')}/", headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            data = json.load(resp)
        cache.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache.with_suffix(".tmp")
        tmp.write_text(json.dumps(data))
        tmp.replace(cache)
        return data

    def entry(self, key: int | str) -> DexEntry:
        """Look up by national dex number or English name."""
        ident = str(key).strip().lower()
        mon = self._get(f"pokemon/{ident}")
        species = self._get(f"pokemon-species/{mon['id']}")
        flavor = next((f["flavor_text"] for f in species.get("flavor_text_entries", [])
                       if f["language"]["name"] == "en"), "")
        return DexEntry(
            id=mon["id"],
            name=mon["name"],
            types=[t["type"]["name"] for t in sorted(mon["types"], key=lambda t: t["slot"])],
            stats={s["stat"]["name"]: s["base_stat"] for s in mon["stats"]},
            abilities=[a["ability"]["name"] for a in mon["abilities"]],
            height_dm=mon["height"],
            weight_hg=mon["weight"],
            flavor=" ".join(flavor.split()),
            sprite_url=mon.get("sprites", {}).get("front_default"),
        )
