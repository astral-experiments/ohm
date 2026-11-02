"""Read the concrete GNU sdk graph node identities and verify every reflected offset and count."""
from collections import Counter
import struct

END = b"rust-end-file"


def leb(data, offset):
    value = 0
    for shift in range(0, 64, 7):
        byte = data[offset]
        offset += 1
        value |= (byte & 127) << shift
        if byte < 128:
            return value, offset
    raise AssertionError("oversized variable-width integer")


class Graph:
    def __init__(self, data, kinds, epoch, version=b'1.99.0-dev'):
        self.by_id = {}
        self.edges = {}
        header = b"RSIC" + epoch.to_bytes(2, "little") + bytes([len(version)]) + version
        assert len(header) + 32 < len(data) < 16 << 20 and data.startswith(header) and data.endswith(END)
        offset = len(header) + 8
        footer = len(data) - len(END) - 24
        maximum, count, edges = struct.unpack_from("<3Q", data, footer)
        assert 0 < count <= maximum <= 100000
        indexed = data[footer-8:footer] == b"OHMIDX01"
        stop = footer
        if indexed:
            stop, roots = struct.unpack_from("<2Q", data, footer - 24)
            assert roots <= count and stop + 8 * maximum + 4 * roots == footer - 24
        assert offset + count * 38 <= stop
        offsets = [0] * maximum
        by_kind = Counter()
        seen_edges = 0
        for _ in range(count):
            flags, i = struct.unpack_from("<HI", data, offset)
            assert i < maximum and not offsets[i]
            offsets[i] = offset
            kind = flags & 511
            assert 0 < kind < len(kinds)
            self.by_id[i] = (kinds[kind], data[offset+6:offset+22].hex())
            by_kind[kind] += 1
            width = 1 + ((flags >> 9) & 3)
            n = (flags >> 11) - 1
            offset += 38
            if n < 0:
                n, offset = leb(data, offset)
            self.edges[i] = [int.from_bytes(data[j:j+width], 'little') for j in range(offset, offset+n*width, width)]
            offset += n * width
            seen_edges += n
            assert offset <= stop
        for k in range(len(kinds)):
            n, offset = leb(data, offset)
            assert n == by_kind[k]
        self.session, offset = leb(data, offset)
        assert offset == stop and seen_edges == edges and self.session > 0
        if indexed:
            assert all(value == stored for value, (stored,) in zip(
                offsets, struct.iter_unpack("<Q", memoryview(data)[stop:stop+8*maximum]), strict=True))
