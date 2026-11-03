"""Pinned zero-key stable SipHash-1-3 with 128-bit output."""

import struct

MASK = 2**64 - 1


def sip(data):
    """LLVM is uninvolved: rustc-stable-hash 0.1.2's zero-key SipHash-1-3 with 128-bit output."""
    a, b, c, d = (
        0x736F6D6570736575,
        0x646F72616E646F6D ^ 0xEE,
        0x6C7967656E657261,
        0x7465646279746573,
    )

    def rot(x, n):
        return ((x << n) | (x >> (64 - n))) & MASK

    def run(a, b, c, d):
        a = (a + b) & MASK
        b = rot(b, 13) ^ a
        a = rot(a, 32)
        c = (c + d) & MASK
        d = rot(d, 16) ^ c
        a = (a + d) & MASK
        d = rot(d, 21) ^ a
        c = (c + b) & MASK
        b = rot(b, 17) ^ c
        c = rot(c, 32)
        return a, b, c, d

    end = len(data) // 8 * 8
    tail = data[end:]
    words = [w[0] for w in struct.iter_unpack("<Q", data[:end])] + [
        int.from_bytes(tail, "little") | ((len(data) & 255) << 56)
    ]
    for w in words:
        a, b, c, d = run(a, b, c, d ^ w)
        a ^= w
    c ^= 0xEE
    for _ in range(3):
        a, b, c, d = run(a, b, c, d)
    low = a ^ b ^ c ^ d
    b ^= 0xDD
    for _ in range(3):
        a, b, c, d = run(a, b, c, d)
    return f"{low:016x}{a ^ b ^ c ^ d:016x}"
