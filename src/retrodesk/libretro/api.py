"""ctypes declarations for the subset of libretro.h that retrodesk uses."""

from __future__ import annotations

import ctypes as C

API_VERSION = 1

ENV_EXPERIMENTAL = 0x10000
ENV_GET_CAN_DUPE = 3
ENV_SET_PERFORMANCE_LEVEL = 8
ENV_GET_SYSTEM_DIRECTORY = 9
ENV_SET_PIXEL_FORMAT = 10
ENV_SET_INPUT_DESCRIPTORS = 11
ENV_GET_VARIABLE = 15
ENV_SET_VARIABLES = 16
ENV_GET_VARIABLE_UPDATE = 17
ENV_SET_SUPPORT_NO_GAME = 18
ENV_GET_LOG_INTERFACE = 27
ENV_GET_SAVE_DIRECTORY = 31
ENV_SET_SYSTEM_AV_INFO = 32
ENV_SET_CONTROLLER_INFO = 35
ENV_SET_MEMORY_MAPS = 36 | ENV_EXPERIMENTAL
ENV_SET_GEOMETRY = 37
ENV_GET_LANGUAGE = 39
ENV_GET_AUDIO_VIDEO_ENABLE = 47 | ENV_EXPERIMENTAL
ENV_GET_INPUT_BITMASKS = 51 | ENV_EXPERIMENTAL
ENV_GET_CORE_OPTIONS_VERSION = 52
ENV_SET_MESSAGE = 6
ENV_SHUTDOWN = 7
ENV_SET_HW_RENDER = 14
ENV_GET_RUMBLE_INTERFACE = 23
ENV_GET_INPUT_DEVICE_CAPABILITIES = 24
ENV_GET_PERF_INTERFACE = 28
ENV_GET_CORE_ASSETS_DIRECTORY = 30
ENV_SET_PROC_ADDRESS_CALLBACK = 33
ENV_SET_SUBSYSTEM_INFO = 34
ENV_GET_USERNAME = 38
ENV_SET_SERIALIZATION_QUIRKS = 44
ENV_GET_VFS_INTERFACE = 45 | ENV_EXPERIMENTAL
ENV_GET_LED_INTERFACE = 46 | ENV_EXPERIMENTAL
ENV_GET_FASTFORWARDING = 49 | ENV_EXPERIMENTAL
ENV_SET_CORE_OPTIONS = 53
ENV_SET_CORE_OPTIONS_INTL = 54
ENV_SET_CORE_OPTIONS_DISPLAY = 55
ENV_GET_PREFERRED_HW_RENDER = 56
ENV_GET_DISK_CONTROL_INTERFACE_VERSION = 57
ENV_SET_DISK_CONTROL_EXT_INTERFACE = 58
ENV_GET_MESSAGE_INTERFACE_VERSION = 59
ENV_SET_MESSAGE_EXT = 60
ENV_GET_INPUT_MAX_USERS = 61
ENV_SET_AUDIO_BUFFER_STATUS_CALLBACK = 62
ENV_SET_MINIMUM_AUDIO_LATENCY = 63
ENV_SET_FASTFORWARDING_OVERRIDE = 64
ENV_SET_CONTENT_INFO_OVERRIDE = 65
ENV_GET_GAME_INFO_EXT = 66
ENV_SET_CORE_OPTIONS_V2 = 67
ENV_SET_CORE_OPTIONS_V2_INTL = 68
ENV_SET_CORE_OPTIONS_UPDATE_DISPLAY_CALLBACK = 69
ENV_SET_VARIABLE = 70
ENV_GET_THROTTLE_STATE = 71 | ENV_EXPERIMENTAL
ENV_GET_SAVESTATE_CONTEXT = 72 | ENV_EXPERIMENTAL

PIXEL_0RGB1555 = 0
PIXEL_XRGB8888 = 1
PIXEL_RGB565 = 2

DEVICE_NONE = 0
DEVICE_JOYPAD = 1
DEVICE_MOUSE = 2
DEVICE_KEYBOARD = 3
DEVICE_LIGHTGUN = 4
DEVICE_ANALOG = 5
DEVICE_POINTER = 6
MAX_PORTS = 2
DEVICE_TYPE_MASK = 0xFF  # devices may be subclassed: ((id + 1) << 8) | base

DEVICE_ID_POINTER_X = 0
DEVICE_ID_POINTER_Y = 1
DEVICE_ID_POINTER_PRESSED = 2
DEVICE_ID_POINTER_COUNT = 3
POINTER_MAX = 0x7FFF
DEVICE_ID_JOYPAD_MASK = 256

MEMORY_SAVE_RAM = 0
MEMORY_RTC = 1
MEMORY_SYSTEM_RAM = 2
MEMORY_VIDEO_RAM = 3

# RETRO_DEVICE_ID_JOYPAD_* bit positions.
JOYPAD = {
    "B": 0, "Y": 1, "SELECT": 2, "START": 3, "UP": 4, "DOWN": 5, "LEFT": 6, "RIGHT": 7,
    "A": 8, "X": 9, "L": 10, "R": 11, "L2": 12, "R2": 13, "L3": 14, "R3": 15,
}


class SystemInfo(C.Structure):
    _fields_ = [
        ("library_name", C.c_char_p),
        ("library_version", C.c_char_p),
        ("valid_extensions", C.c_char_p),
        ("need_fullpath", C.c_bool),
        ("block_extract", C.c_bool),
    ]


class GameGeometry(C.Structure):
    _fields_ = [
        ("base_width", C.c_uint),
        ("base_height", C.c_uint),
        ("max_width", C.c_uint),
        ("max_height", C.c_uint),
        ("aspect_ratio", C.c_float),
    ]


class SystemTiming(C.Structure):
    _fields_ = [("fps", C.c_double), ("sample_rate", C.c_double)]


class SystemAvInfo(C.Structure):
    _fields_ = [("geometry", GameGeometry), ("timing", SystemTiming)]


class GameInfo(C.Structure):
    _fields_ = [
        ("path", C.c_char_p),
        ("data", C.c_void_p),
        ("size", C.c_size_t),
        ("meta", C.c_char_p),
    ]


class Variable(C.Structure):
    _fields_ = [("key", C.c_char_p), ("value", C.c_char_p)]


NUM_CORE_OPTION_VALUES_MAX = 128


class CoreOptionValue(C.Structure):
    _fields_ = [("value", C.c_char_p), ("label", C.c_char_p)]


class CoreOptionDefinition(C.Structure):
    _fields_ = [
        ("key", C.c_char_p),
        ("desc", C.c_char_p),
        ("info", C.c_char_p),
        ("values", CoreOptionValue * NUM_CORE_OPTION_VALUES_MAX),
        ("default_value", C.c_char_p),
    ]


class CoreOptionsIntl(C.Structure):
    _fields_ = [("us", C.POINTER(CoreOptionDefinition)), ("local", C.POINTER(CoreOptionDefinition))]


class CoreOptionV2Category(C.Structure):
    _fields_ = [("key", C.c_char_p), ("desc", C.c_char_p), ("info", C.c_char_p)]


class CoreOptionV2Definition(C.Structure):
    _fields_ = [
        ("key", C.c_char_p),
        ("desc", C.c_char_p),
        ("desc_categorized", C.c_char_p),
        ("info", C.c_char_p),
        ("info_categorized", C.c_char_p),
        ("category_key", C.c_char_p),
        ("values", CoreOptionValue * NUM_CORE_OPTION_VALUES_MAX),
        ("default_value", C.c_char_p),
    ]


class CoreOptionsV2(C.Structure):
    _fields_ = [("categories", C.POINTER(CoreOptionV2Category)),
                ("definitions", C.POINTER(CoreOptionV2Definition))]


class CoreOptionsV2Intl(C.Structure):
    _fields_ = [("us", C.POINTER(CoreOptionsV2)), ("local", C.POINTER(CoreOptionsV2))]


class Message(C.Structure):
    _fields_ = [("msg", C.c_char_p), ("frames", C.c_uint)]


class MessageExt(C.Structure):
    _fields_ = [("msg", C.c_char_p), ("duration", C.c_uint), ("priority", C.c_uint),
                ("level", C.c_int), ("target", C.c_int), ("type", C.c_int), ("progress", C.c_int8)]


class MemoryDescriptor(C.Structure):
    _fields_ = [
        ("flags", C.c_uint64),
        ("ptr", C.c_void_p),
        ("offset", C.c_size_t),
        ("start", C.c_size_t),
        ("select", C.c_size_t),
        ("disconnect", C.c_size_t),
        ("len", C.c_size_t),
        ("addrspace", C.c_char_p),
    ]


class MemoryMap(C.Structure):
    _fields_ = [("descriptors", C.POINTER(MemoryDescriptor)), ("num_descriptors", C.c_uint)]


EnvironmentCb = C.CFUNCTYPE(C.c_bool, C.c_uint, C.c_void_p)
VideoRefreshCb = C.CFUNCTYPE(None, C.c_void_p, C.c_uint, C.c_uint, C.c_size_t)
AudioSampleCb = C.CFUNCTYPE(None, C.c_int16, C.c_int16)
AudioSampleBatchCb = C.CFUNCTYPE(C.c_size_t, C.POINTER(C.c_int16), C.c_size_t)
InputPollCb = C.CFUNCTYPE(None)
InputStateCb = C.CFUNCTYPE(C.c_int16, C.c_uint, C.c_uint, C.c_uint, C.c_uint)


def declare(lib: C.CDLL) -> None:
    """Attach argument/return types to the core's exported functions."""
    sig = {
        "retro_api_version": (C.c_uint, []),
        "retro_init": (None, []),
        "retro_deinit": (None, []),
        "retro_get_system_info": (None, [C.POINTER(SystemInfo)]),
        "retro_get_system_av_info": (None, [C.POINTER(SystemAvInfo)]),
        "retro_set_environment": (None, [EnvironmentCb]),
        "retro_set_video_refresh": (None, [VideoRefreshCb]),
        "retro_set_audio_sample": (None, [AudioSampleCb]),
        "retro_set_audio_sample_batch": (None, [AudioSampleBatchCb]),
        "retro_set_input_poll": (None, [InputPollCb]),
        "retro_set_input_state": (None, [InputStateCb]),
        "retro_set_controller_port_device": (None, [C.c_uint, C.c_uint]),
        "retro_reset": (None, []),
        "retro_run": (None, []),
        "retro_serialize_size": (C.c_size_t, []),
        "retro_serialize": (C.c_bool, [C.c_void_p, C.c_size_t]),
        "retro_unserialize": (C.c_bool, [C.c_void_p, C.c_size_t]),
        "retro_load_game": (C.c_bool, [C.POINTER(GameInfo)]),
        "retro_unload_game": (None, []),
        "retro_get_memory_data": (C.c_void_p, [C.c_uint]),
        "retro_get_memory_size": (C.c_size_t, [C.c_uint]),
    }
    for name, (restype, argtypes) in sig.items():
        fn = getattr(lib, name)
        fn.restype = restype
        fn.argtypes = argtypes
