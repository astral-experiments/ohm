"""Emit rustc's DefPathHash->DefIndex wire format for its locked odht 0.3.1 configuration."""
import struct

GROUP = 16
FACTOR = 87 * 65535 // 100


def slots_for(entries):
    required = (65535 * entries + FACTOR - 1) // FACTOR
    return max(GROUP, 1 << (required - 1).bit_length())


def def_path_hash_map(keys):
    if any(not isinstance(k,bytes) or len(k)!=8 for k in keys) or len(set(keys))!=len(keys):
        raise ValueError("expected unique little-endian Hash64 keys")
    slots = [None] * slots_for(12)

    def insert(table, key, value):
        # UnHashFn takes the last four bytes. The default table always probes 16
        # consecutive slots, then advances by successive 16-slot strides.
        h = int.from_bytes(key[4:], "little")
        mask = len(table) - 1
        start, stride = h & mask, 0
        for _ in range(len(table)//GROUP):
            for i in range(GROUP):
                ix = (start+i) & mask
                if table[ix] is None:
                    table[ix] = (key,value)
                    return
            stride += GROUP
            start = (start+stride) & mask
        raise ValueError("full DefPathHash table")

    for index,key in enumerate(keys):
        if index == (len(slots)*FACTOR >> 16):
            larger = [None] * slots_for(2*index)
            for existing in slots:
                if existing is not None:
                    insert(larger,*existing)
            slots = larger
        insert(slots,key,index)
    data = bytearray(12*len(slots))
    control = bytearray([255])*len(slots)
    for i,pair in enumerate(slots):
        if pair is not None:
            key, index = pair
            struct.pack_into("<8sI", data, 12*i, key, index)
            control[i] = int.from_bytes(key[4:],"little") >> 25
    head = struct.pack("<4sBBBBQQ4sH2x",b"ODHT",1,8,4,32,len(keys),len(slots),b"\0\0\0\2",FACTOR)
    return bytes(head + data + control + control[:GROUP])
