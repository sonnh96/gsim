"""Keyboard and game controller state as a libretro joypad bitmask."""

from __future__ import annotations

import sdl2

from ..libretro.api import JOYPAD

KEYBOARD = {
    sdl2.SDL_SCANCODE_X: "A",
    sdl2.SDL_SCANCODE_Z: "B",
    sdl2.SDL_SCANCODE_S: "X",
    sdl2.SDL_SCANCODE_A: "Y",
    sdl2.SDL_SCANCODE_Q: "L",
    sdl2.SDL_SCANCODE_W: "R",
    sdl2.SDL_SCANCODE_E: "L2",
    sdl2.SDL_SCANCODE_R: "R2",
    sdl2.SDL_SCANCODE_D: "L3",
    sdl2.SDL_SCANCODE_F: "R3",
    sdl2.SDL_SCANCODE_RETURN: "START",
    sdl2.SDL_SCANCODE_RSHIFT: "SELECT",
    sdl2.SDL_SCANCODE_BACKSPACE: "SELECT",
    sdl2.SDL_SCANCODE_UP: "UP",
    sdl2.SDL_SCANCODE_DOWN: "DOWN",
    sdl2.SDL_SCANCODE_LEFT: "LEFT",
    sdl2.SDL_SCANCODE_RIGHT: "RIGHT",
}

# SDL's GameController layout is Xbox-style; libretro's is SNES-style, so the
# face buttons are mapped by position (south = B, east = A).
CONTROLLER = {
    sdl2.SDL_CONTROLLER_BUTTON_A: "B",
    sdl2.SDL_CONTROLLER_BUTTON_B: "A",
    sdl2.SDL_CONTROLLER_BUTTON_X: "Y",
    sdl2.SDL_CONTROLLER_BUTTON_Y: "X",
    sdl2.SDL_CONTROLLER_BUTTON_LEFTSHOULDER: "L",
    sdl2.SDL_CONTROLLER_BUTTON_RIGHTSHOULDER: "R",
    sdl2.SDL_CONTROLLER_BUTTON_LEFTSTICK: "L3",
    sdl2.SDL_CONTROLLER_BUTTON_RIGHTSTICK: "R3",
    sdl2.SDL_CONTROLLER_BUTTON_START: "START",
    sdl2.SDL_CONTROLLER_BUTTON_BACK: "SELECT",
    sdl2.SDL_CONTROLLER_BUTTON_DPAD_UP: "UP",
    sdl2.SDL_CONTROLLER_BUTTON_DPAD_DOWN: "DOWN",
    sdl2.SDL_CONTROLLER_BUTTON_DPAD_LEFT: "LEFT",
    sdl2.SDL_CONTROLLER_BUTTON_DPAD_RIGHT: "RIGHT",
}
AXIS_DEADZONE = 16000
TRIGGER_THRESHOLD = 12000


class InputState:
    def __init__(self) -> None:
        self._controllers: dict[int, object] = {}

    def open_controller(self, device_index: int) -> None:
        if not sdl2.SDL_IsGameController(device_index):
            return
        pad = sdl2.SDL_GameControllerOpen(device_index)
        if pad:
            joy = sdl2.SDL_GameControllerGetJoystick(pad)
            self._controllers[sdl2.SDL_JoystickInstanceID(joy)] = pad

    def close_controller(self, instance_id: int) -> None:
        pad = self._controllers.pop(instance_id, None)
        if pad:
            sdl2.SDL_GameControllerClose(pad)

    @staticmethod
    def _pad_mask(pad: object) -> int:
        m = 0
        for sdl_button, button in CONTROLLER.items():
            if sdl2.SDL_GameControllerGetButton(pad, sdl_button):
                m |= 1 << JOYPAD[button]
        if sdl2.SDL_GameControllerGetAxis(pad, sdl2.SDL_CONTROLLER_AXIS_TRIGGERLEFT) > TRIGGER_THRESHOLD:
            m |= 1 << JOYPAD["L2"]
        if sdl2.SDL_GameControllerGetAxis(pad, sdl2.SDL_CONTROLLER_AXIS_TRIGGERRIGHT) > TRIGGER_THRESHOLD:
            m |= 1 << JOYPAD["R2"]
        x = sdl2.SDL_GameControllerGetAxis(pad, sdl2.SDL_CONTROLLER_AXIS_LEFTX)
        y = sdl2.SDL_GameControllerGetAxis(pad, sdl2.SDL_CONTROLLER_AXIS_LEFTY)
        if x < -AXIS_DEADZONE:
            m |= 1 << JOYPAD["LEFT"]
        elif x > AXIS_DEADZONE:
            m |= 1 << JOYPAD["RIGHT"]
        if y < -AXIS_DEADZONE:
            m |= 1 << JOYPAD["UP"]
        elif y > AXIS_DEADZONE:
            m |= 1 << JOYPAD["DOWN"]
        return m

    def masks(self, keyboard_enabled: bool, ports: int = 2) -> list[int]:
        """One joypad bitmask per port: keyboard + first controller on port 0, next controllers after."""
        out = [0] * ports
        if keyboard_enabled:
            keys = sdl2.SDL_GetKeyboardState(None)
            for scancode, button in KEYBOARD.items():
                if keys[scancode]:
                    out[0] |= 1 << JOYPAD[button]
        for port, pad in enumerate(self._controllers.values()):
            if port < ports:
                out[port] |= self._pad_mask(pad)
        return out

    def mask(self, keyboard_enabled: bool) -> int:
        return self.masks(keyboard_enabled, 1)[0]
