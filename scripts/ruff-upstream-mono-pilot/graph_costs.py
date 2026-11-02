"""Read a finalized rustc graph's size and kind counts with a bounded number of bytes."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import stat
import struct

SCHEMA_SHA256 = 'bd5f062d2aa380b65e995865c259d4340089a4efa9dc16986db1ec93e99b4969'
END = b'rust-end-file'
INDEX_MAGIC = b'OHMIDX01'

def require(ok, message):
    if not ok:
        raise ValueError(message)

_data = Path(__file__).with_name('graph-kinds.json').read_bytes()
require(hashlib.sha256(_data).hexdigest() == SCHEMA_SHA256, 'different source schema')
SCHEMAS = json.loads(_data)

def identity(st):
    return (st.st_dev, st.st_ino, st.st_size, st.st_blocks, st.st_mtime_ns, st.st_ctime_ns)

@contextmanager
def enrolled_file(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        snapshot = os.fstat(fd)
        require(stat.S_ISREG(snapshot.st_mode), f'expected regular file: {path}')
        read_bytes = 0
        def read(offset, length):
            nonlocal read_bytes
            require(0 <= offset <= offset + length <= snapshot.st_size, 'invalid read bounds')
            data = os.pread(fd, length, offset)
            require(len(data) == length, 'short read')
            read_bytes += len(data)
            return data
        out = dict(bytes=snapshot.st_size, allocated_bytes_by_stat=snapshot.st_blocks * 512,
                   dev=snapshot.st_dev, inode=snapshot.st_ino, mtime_ns=snapshot.st_mtime_ns)
        yield out, read
        require(identity(snapshot) == identity(os.fstat(fd)) == identity(path.stat(follow_symlinks=False)),
                f'file changed while collecting: {path}')
        out['bytes_read'] = read_bytes
    finally:
        os.close(fd)

def header(read, size, schema):
    magic, fmt, length = struct.unpack('<4sHB', read(0, 7))
    require(magic == b'RSIC' and fmt == schema['format'], 'different RSIC format')
    require(read(7, length) == schema['version'].encode('ascii'), 'different compiler version')
    require(size >= 7 + length + len(END) and read(size - len(END), len(END)) == END, 'missing file terminator')
    return 7 + length

def reverse_leb(data, end, bits):
    """Decode one canonical LEB ending here; its predecessor is also a LEB value."""
    start = end - 1
    require(start >= 0 and data[start] < 128, 'unterminated footer integer')
    value = data[start]
    while start > 0 and data[start - 1] >= 128:
        require(end - start < (bits + 6) // 7, 'overlong footer integer')
        start -= 1
        value = (value << 7) | (data[start] & 127)
    require(end - start == 1 or data[end-1] != 0, 'noncanonical footer integer')
    require(value < 1 << bits, 'footer integer overflow')
    return value, start

def graph_costs(path, role_commit):
    """Read the footer and its bounds. `role_commit` comes from the qualified compiler installation."""
    schema = SCHEMAS[role_commit]
    names = schema['names']
    path = Path(path)
    with enrolled_file(path) as (result, read):
        size = result['bytes']
        version_end = header(read, size, schema)
        records_start = version_end + 8
        commandline_hash = read(version_end, 8).hex()
        end = size - len(END)
        trailer = end - 48
        prefix, roots, magic, slots, nodes, edges = struct.unpack('<QQ8sQQQ', read(trailer, 48))
        require(nodes <= slots <= 0xffffffff, 'invalid node slot count')
        index = magic == INDEX_MAGIC
        histogram_end = prefix if index else end - 24
        if index:
            require(roots <= nodes and prefix + 8 * slots + 4 * roots == trailer, 'invalid seek directory')
        minimum = records_start + 38 * nodes
        require(histogram_end >= minimum + len(names) + 1, 'invalid graph length')
        # The last leading Null count is zero and has exactly one byte. Its preceding byte
        # belongs to the final node and is free to have the LEB continuation bit set.
        chunk = read(max(minimum, histogram_end - (5 * len(names) + 10)),
                     min(histogram_end - minimum, 5 * len(names) + 10))
        session, pos = reverse_leb(chunk, len(chunk), 64)
        require(session > 0, 'invalid compiler session count')
        counts = [0] * len(names)
        for k in range(len(names) - 1, 0, -1):
            counts[k], pos = reverse_leb(chunk, pos, 32)
        require(pos >= 1 and chunk[pos-1] == 0 and sum(counts) == nodes, 'incorrect per-kind node counts')
        histogram_bytes = len(chunk) - (pos - 1)
        records_bytes = histogram_end - histogram_bytes - records_start
        variable_bytes = records_bytes - 38 * nodes
        max_inline = (1 << (16 - (len(names)-1).bit_length() - 2)) - 2
        possible_spills = min(nodes, edges // (max_inline + 1))
        require(edges <= variable_bytes <= 4 * edges + 5 * possible_spills, 'inconsistent edge/record sizes')
        by_kind = dict(zip(names, counts, strict=True))
        result.update(role_commit=role_commit, role=schema['role'], rsic_format=schema['format'],
                      compiler_version=schema['version'], kind_schema_sha256=SCHEMA_SHA256,
                      commandline_hash=commandline_hash, node_slots=slots, nodes=nodes, edges=edges,
                      session_count=session, kind_nodes=by_kind,
                      upstream_nodes={k:v for k,v in by_kind.items() if k.startswith('upstream_')},
                      seek_index=index, seek_roots=roots if index else 0,
                      layout_bytes=dict(prefix=records_start, node_records=records_bytes,
                                        kind_counts_and_session=histogram_bytes,
                                        seek_index=end - 24 - histogram_end, totals=24, terminal=len(END)))
        require(sum(result['layout_bytes'].values()) == size, 'inconsistent file layout')
    return result

def session_costs(finalized_session_dir, role_commit):
    """Collect the current graph and query-cache size after Cargo, under one completed session."""
    directory = Path(finalized_session_dir)
    require(not directory.name.endswith('-working'), 'in-progress session')
    before = directory.stat(follow_symlinks=False)
    require(stat.S_ISDIR(before.st_mode), 'expected finalized session directory')
    graph = graph_costs(directory / 'dep-graph.bin', role_commit)
    with enrolled_file(directory / 'query-cache.bin') as (query_cache, read):
        header(read, query_cache['bytes'], SCHEMAS[role_commit])
    require(identity(before) == identity(directory.stat(follow_symlinks=False)), 'session changed while collecting')
    return dict(session=str(directory), dep_graph=graph, query_cache=query_cache)
