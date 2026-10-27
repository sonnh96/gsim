"""Save-state slots on disk: state bytes, a PNG preview, and when each was written."""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np

SLOTS = 10


@dataclass(frozen=True)
class SlotInfo:
    slot: int
    saved_at: datetime | None  # None: slot is empty

    @property
    def empty(self) -> bool:
        return self.saved_at is None

    def describe(self) -> str:
        if self.saved_at is None:
            return f"slot {self.slot}: empty"
        return f"slot {self.slot}: saved {self.saved_at:%d/%m %H:%M}"


class StateSlots:
    def __init__(self, directory: Path) -> None:
        self.dir = directory

    def path(self, slot: int) -> Path:
        return self.dir / f"slot{slot}.state"

    def preview_path(self, slot: int) -> Path:
        return self.dir / f"slot{slot}.png"

    def info(self, slot: int) -> SlotInfo:
        try:
            mtime = self.path(slot).stat().st_mtime
        except FileNotFoundError:
            return SlotInfo(slot, None)
        return SlotInfo(slot, datetime.fromtimestamp(mtime))

    def all(self) -> list[SlotInfo]:
        return [self.info(slot) for slot in range(SLOTS)]

    def latest(self) -> int | None:
        """The most recently written slot, or None when there are no states."""
        used = [i for i in self.all() if not i.empty]
        return max(used, key=lambda i: i.saved_at).slot if used else None

    def write(self, slot: int, data: bytes, preview: np.ndarray | None = None) -> Path:
        path = self.path(slot)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".state.tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
        if preview is not None:
            write_png(self.preview_path(slot), preview)
        else:
            self.preview_path(slot).unlink(missing_ok=True)  # never show a stale picture
        return path

    def read(self, slot: int) -> bytes:
        return self.path(slot).read_bytes()

    def preview(self, slot: int) -> np.ndarray | None:
        try:
            return read_png(self.preview_path(slot))
        except (FileNotFoundError, ValueError, zlib.error):
            return None


def _chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def write_png(path: Path, rgba: np.ndarray) -> None:
    """8-bit RGBA PNG with no row filtering; small enough for thumbnails."""
    h, w, _ = rgba.shape
    rows = np.zeros((h, 1 + w * 4), np.uint8)
    rows[:, 1:] = np.ascontiguousarray(rgba, np.uint8).reshape(h, w * 4)
    data = (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + _chunk(b"IDAT", zlib.compress(rows.tobytes(), 6)) + _chunk(b"IEND", b""))
    tmp = path.with_suffix(".png.tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def read_png(path: Path) -> np.ndarray:
    """Read back a PNG written by write_png (8-bit RGBA, filter 0 rows only)."""
    raw = path.read_bytes()
    if raw[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG")
    pos, idat, size = 8, b"", None
    while pos < len(raw):
        length, kind = struct.unpack(">I4s", raw[pos:pos + 8])
        body = raw[pos + 8:pos + 8 + length]
        if kind == b"IHDR":
            w, h, depth, color = struct.unpack(">IIBB", body[:10])
            if (depth, color) != (8, 6):
                raise ValueError("only 8-bit RGBA previews are supported")
            size = (w, h)
        elif kind == b"IDAT":
            idat += body
        pos += 12 + length
    if size is None:
        raise ValueError("PNG has no header")
    w, h = size
    rows = np.frombuffer(zlib.decompress(idat), np.uint8).reshape(h, 1 + w * 4)
    if rows[:, 0].any():
        raise ValueError("filtered PNG rows are not supported")
    return rows[:, 1:].reshape(h, w, 4).copy()
