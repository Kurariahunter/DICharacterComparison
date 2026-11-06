"""Pure format helpers extracted from project research; no game I/O at import."""

from pathlib import Path

import struct

def hash32(text):
    raw = text.lower().encode('utf-8')
    mask = 0xffffffff
    def rot(x, n): return ((x << n) | (x >> (32-n))) & mask
    def mix(x): return rot(x * 0xcc9e2d51 & mask, 15) * 0x1b873593 & mask
    h = 1000
    end = len(raw) // 4 * 4
    for at in range(0, end, 4):
        h = (rot(h ^ mix(int.from_bytes(raw[at:at+4], 'little')), 13) * 5 + 0xe6546b64) & mask
    if end < len(raw): h ^= mix(int.from_bytes(raw[end:], 'little'))
    h ^= len(raw)
    h ^= h >> 16
    h = h * 0x85ebca6b & mask
    h ^= h >> 13
    h = h * 0xc2b2ae35 & mask
    return h ^ (h >> 16)

def route(logical):
    parts = logical.split('/')
    return Path(*(f'{hash32("/".join(parts[:i+1])):08x}' for i in range(len(parts))))
