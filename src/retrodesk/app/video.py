"""Upload libretro frames into an OpenGL texture."""

from __future__ import annotations

import numpy as np
import OpenGL.GL as gl

from ..frames import frame_to_rgba
from ..libretro.core import Frame

__all__ = ["FrameTexture", "frame_to_rgba"]


class FrameTexture:
    def __init__(self) -> None:
        self.id = int(gl.glGenTextures(1))
        self.width = self.height = 0
        gl.glBindTexture(gl.GL_TEXTURE_2D, self.id)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_NEAREST)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_NEAREST)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_S, gl.GL_CLAMP_TO_EDGE)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_T, gl.GL_CLAMP_TO_EDGE)

    def upload(self, frame: Frame) -> None:
        self.upload_rgba(frame_to_rgba(frame))

    def upload_rgba(self, rgba: np.ndarray) -> None:
        height, width = rgba.shape[:2]
        rgba = np.ascontiguousarray(rgba)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self.id)
        gl.glPixelStorei(gl.GL_UNPACK_ALIGNMENT, 1)
        if (width, height) != (self.width, self.height):
            self.width, self.height = width, height
            gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGBA8, self.width, self.height, 0,
                            gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, rgba)
        else:
            gl.glTexSubImage2D(gl.GL_TEXTURE_2D, 0, 0, 0, self.width, self.height,
                               gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, rgba)

    def delete(self) -> None:
        gl.glDeleteTextures([self.id])
