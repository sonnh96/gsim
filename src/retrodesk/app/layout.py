"""Where the game image sits in the window, and window -> libretro pointer mapping."""

from __future__ import annotations

from typing import NamedTuple

from ..libretro.api import POINTER_MAX


class Rect(NamedTuple):
    x: float
    y: float
    w: float
    h: float

    def contains(self, px: float, py: float) -> bool:
        return self.x <= px < self.x + self.w and self.y <= py < self.y + self.h


def fit(area: Rect, aspect: float) -> Rect:
    """Largest rect with the given aspect ratio, centred in `area`."""
    if area.w <= 0 or area.h <= 0 or aspect <= 0:
        return Rect(area.x, area.y, 0, 0)
    w = min(area.w, area.h * aspect)
    h = w / aspect
    return Rect(area.x + (area.w - w) / 2, area.y + (area.h - h) / 2, w, h)


def to_pointer(view: Rect, px: float, py: float) -> tuple[int, int, bool]:
    """Window coordinates -> (x, y, inside) in libretro pointer units (-0x7fff..0x7fff)."""
    if view.w <= 0 or view.h <= 0:
        return 0, 0, False
    inside = view.contains(px, py)

    def axis(v: float, origin: float, size: float) -> int:
        n = (v - origin) / size  # 0..1 across the image
        return max(-POINTER_MAX, min(POINTER_MAX, round(n * 0x10000) - 0x8000))

    return axis(px, view.x, view.w), axis(py, view.y, view.h), inside
