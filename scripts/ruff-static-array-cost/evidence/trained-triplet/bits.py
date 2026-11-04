"""Represent a DEFLATE byte stream in its physical low-bit-first order for delta coding."""
REVERSE = bytes(int(format(v, "08b")[::-1], 2) for v in range(256))


def expand(raw):
    return format(int.from_bytes(raw.translate(REVERSE), "big"), "0"+str(8*len(raw))+"b").encode("ascii")


def restore(bits, length):
    assert len(bits) == 8*length
    return int(bits, 2).to_bytes(length, "big").translate(REVERSE)
