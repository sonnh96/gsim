"""Download the libretro cores and pret symbol tables retrodesk uses.

Neither is redistributed in this repository: cores come from the libretro
buildbot and symbols from the pret decompilation projects' `symbols` branches.
"""

from __future__ import annotations

import argparse
import io
import platform
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Phase 1 (software-rendered, work with the ctypes bridge) + the DS core.
CORES = ["mgba", "gambatte", "mesen", "fceumm", "snes9x", "fbneo", "mame2003_plus", "pcsx_rearmed", "melondsds", "melonds"]
# Phase 3: need RETRO_ENVIRONMENT_SET_HW_RENDER before they are useful.
HW_CORES = ["ppsspp", "citra", "play"]
SYMBOLS = {
    "emerald.sym": "https://raw.githubusercontent.com/pret/pokeemerald/symbols/pokeemerald.sym",
    "firered.sym": "https://raw.githubusercontent.com/pret/pokefirered/symbols/pokefirered.sym",
    "ruby.sym": "https://raw.githubusercontent.com/pret/pokeruby/symbols/pokeruby.sym",
}


def buildbot_dir() -> tuple[str, str]:
    machine = platform.machine().lower()
    if sys.platform == "darwin":
        arch = "arm64" if machine in ("arm64", "aarch64") else "x86_64"
        return f"https://buildbot.libretro.com/nightly/apple/osx/{arch}/latest", ".dylib"
    if sys.platform.startswith("linux"):
        arch = "aarch64" if machine in ("arm64", "aarch64") else "x86_64"
        return f"https://buildbot.libretro.com/nightly/linux/{arch}/latest", ".so"
    raise SystemExit(f"unsupported platform: {sys.platform}")


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "retrodesk-fetch/0.1"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="re-download existing files")
    parser.add_argument("--hw", action="store_true", help="also fetch the hardware-rendered cores")
    parser.add_argument("--cores", nargs="*", help="only these cores")
    args = parser.parse_args()
    cores = args.cores or (CORES + HW_CORES if args.hw else CORES)

    base, suffix = buildbot_dir()
    cores_dir = ROOT / "cores"
    cores_dir.mkdir(exist_ok=True)
    failed = []
    for core in cores:
        target = cores_dir / f"{core}_libretro{suffix}"
        if target.exists() and not args.force:
            print(f"have {target.name}")
            continue
        print(f"fetch {core} from {base}")
        try:
            with zipfile.ZipFile(io.BytesIO(fetch(f"{base}/{core}_libretro{suffix}.zip"))) as zf:
                target.write_bytes(zf.read(target.name))
            target.chmod(0o755)
        except Exception as exc:  # a missing core on the buildbot must not block the rest
            print(f"  failed: {exc}")
            failed.append(core)

    sym_dir = ROOT / "data" / "sym"
    sym_dir.mkdir(parents=True, exist_ok=True)
    for name, url in SYMBOLS.items():
        target = sym_dir / name
        if target.exists() and not args.force:
            print(f"have {name}")
            continue
        print(f"fetch {name}")
        target.write_bytes(fetch(url))
    if failed:
        print(f"not available on this buildbot: {', '.join(failed)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
