"""Convert libretro software frames to RGBA arrays (no OpenGL needed)."""

from __future__ import annotations

import numpy as np

from .libretro import api
from .libretro.core import Frame


def frame_to_rgba(frame: Frame) -> np.ndarray:
    """Convert any libretro software pixel format to a tightly packed RGBA array."""
    if frame.pixel_format == api.PIXEL_XRGB8888:
        px = np.frombuffer(frame.data, np.uint8).reshape(frame.height, frame.pitch // 4, 4)[:, :frame.width]
        out = px[..., [2, 1, 0, 3]].copy()
        out[..., 3] = 255
        return out
    px = np.frombuffer(frame.data, np.uint16).reshape(frame.height, frame.pitch // 2)[:, :frame.width]
    if frame.pixel_format == api.PIXEL_RGB565:
        r, g, b = (px >> 11) & 0x1F, (px >> 5) & 0x3F, px & 0x1F
        g8 = (g << 2) | (g >> 4)
    else:  # 0RGB1555
        r, g, b = (px >> 10) & 0x1F, (px >> 5) & 0x1F, px & 0x1F
        g8 = (g << 3) | (g >> 2)
    out = np.empty((frame.height, frame.width, 4), np.uint8)
    out[..., 0] = (r << 3) | (r >> 2)
    out[..., 1] = g8
    out[..., 2] = (b << 3) | (b >> 2)
    out[..., 3] = 255
    return out
