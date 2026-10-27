"""Builders for synthetic Gen 3 memory, so parsing is tested without a ROM."""

from __future__ import annotations

import struct

from retrodesk.gen3.model import _ORDERS, BATTLE_MON_SIZE, PARTY_MON_SIZE


def encode_text(text: str) -> bytes:
    out = bytearray()
    for ch in text:
        if ch.isupper():
            out.append(0xBB + ord(ch) - ord("A"))
        elif ch.islower():
            out.append(0xD5 + ord(ch) - ord("a"))
        elif ch.isdigit():
            out.append(0xA1 + int(ch))
        else:
            out.append(0x00)
    return bytes(out)


def name_field(text: str, size: int) -> bytes:
    return (encode_text(text) + b"\xFF" * size)[:size]


def party_mon(personality: int, ot_id: int, species: int, level: int, hp: int, max_hp: int,
              moves=(33, 0, 0, 0), pp=(35, 0, 0, 0), ivs=(31, 30, 29, 28, 27, 26),
              nickname: str = "TEST", corrupt: bool = False) -> bytes:
    subs = {
        "G": struct.pack("<HHIBBH", species, 0, 1000, 0, 70, 0),
        "A": struct.pack("<4H4B", *moves, *pp),
        "E": bytes(12),
        "M": struct.pack("<BBHI4x", 0, 0, 0, sum(v << (5 * i) for i, v in enumerate(ivs))),
    }
    plain = b"".join(subs[k] for k in _ORDERS[personality % 24])
    checksum = sum(struct.unpack("<24H", plain)) & 0xFFFF
    if corrupt:
        checksum ^= 1
    key = personality ^ ot_id
    enc = struct.pack("<12I", *(w ^ key for w in struct.unpack("<12I", plain)))
    raw = bytearray(PARTY_MON_SIZE)
    struct.pack_into("<II", raw, 0, personality, ot_id)
    raw[8:18] = name_field(nickname, 10)
    struct.pack_into("<H", raw, 0x1C, checksum)
    raw[0x20:0x50] = enc
    raw[0x54] = level
    struct.pack_into("<HH", raw, 0x56, hp, max_hp)
    return bytes(raw)


def battle_mon(species: int, level: int, hp: int, max_hp: int, types=(0, 0), moves=(33, 0, 0, 0),
               pp=(35, 0, 0, 0), stats=(50, 50, 50, 50, 50), personality: int = 0x12345678,
               ot_id: int = 0x0BADF00D, nickname: str = "MON") -> bytes:
    raw = bytearray(BATTLE_MON_SIZE)
    atk, dfn, spe, spa, spd = stats
    struct.pack_into("<6H", raw, 0, species, atk, dfn, spe, spa, spd)
    struct.pack_into("<4H", raw, 0x0C, *moves)
    raw[0x21], raw[0x22] = types
    struct.pack_into("<4B", raw, 0x24, *pp)
    struct.pack_into("<HBBHH", raw, 0x28, hp, level, 0, max_hp, 0)
    raw[0x30:0x3B] = name_field(nickname, 11)
    struct.pack_into("<IIII", raw, 0x48, personality, 0, 0, ot_id)
    return bytes(raw)


class FakeMemory:
    """Sparse guest address space."""

    def __init__(self) -> None:
        self._bytes: dict[int, int] = {}

    def write(self, addr: int, data: bytes) -> None:
        for i, b in enumerate(data):
            self._bytes[addr + i] = b

    def write_u32(self, addr: int, value: int) -> None:
        self.write(addr, struct.pack("<I", value))

    def read(self, addr: int, size: int) -> bytes:
        return bytes(self._bytes.get(addr + i, 0) for i in range(size))
