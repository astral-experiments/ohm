"""Reopen the compact attribution controls and optionally all five original consumer graphs."""
import argparse
import gzip
import hashlib
import json
import re
import statistics
import shutil
import struct
import subprocess
import tarfile
import zipfile
from bisect import bisect_right
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
PACKET = 'd5a6fdacd47cab931ebf17f75d7a7d8e50c1b1beb2ec9dd322c78a88689ddbdb'
ORIGINAL = '51839d2cca8ddee61a88c356b4950a5b0702a2b3bdeaee1a6abcfcba7ef4ad3d'
PRODUCER = '7aeabc1e479283f6'
TAGS = ('O', 'O2', 'N', 'N2', 'N3')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read_packet():
    path = HERE / 'raw-controls.tar.gz'
    require(sha(path.read_bytes()) == PACKET, 'compact archive SHA-256 differs')
    with tarfile.open(path) as archive:
        return {member.name: archive.extractfile(member).read() for member in archive if member.isfile()}


def actor(program, argv):
    name = Path(program).name
    if program.endswith('/reopened/defer/bin/rustc'):
        require('--crate-name' in argv, 'unrecognized compiler invocation')
        return 'rustc:' + argv[argv.index('--crate-name') + 1]
    if program.endswith('/reopened/defer/bin/cargo'):
        return 'cargo'
    if program.endswith('/wild-ld/ld.bfd'):
        return 'Wild'
    if name in ('watch', 'count-exec'):
        return 'instrumentation'
    if re.fullmatch(r'(?:x86_64-linux-gnu-)?(?:gcc(?:-\d+)?|cc|ld|collect2)', name):
        return 'link driver'
    require(name == 'rustup', f'unrecognized executable {name}')
    return name


def exact_processes(packet):
    roles = {}
    for filename, data in packet.items():
        if filename.startswith('exec/') and filename.endswith('.nul'):
            parts = data.decode().split('\0')
            require(parts.pop() == '', 'incomplete argv')
            pid, _, _, program, *argv = parts
            roles[int(Path(filename).stem)] = (int(pid), actor(program, argv))
    epochs = defaultdict(list)
    disjoint = Counter()
    tids = set()
    monitor = None
    for line in packet['exec/epochs.tsv'].decode().splitlines():
        tag, *fields = line.split()
        if tag == 'M':
            monitor = int(fields[0])
            continue
        image, pid, tid = map(int, fields[:3])
        image_pid, role = roles[image]
        require(image_pid == pid, 'counter epoch belongs to another executable')
        if tag == 'I':
            epochs[pid].append((int(fields[3]), role))
        else:
            require(tag == 'C', 'unknown epoch')
            count, enabled, running = map(int, fields[3:])
            require(enabled == running, 'multiplexed per-task counter')
            disjoint[role] += count
            tids.add(tid)
    clocks = {name: json.loads(packet[f'clocks/{name}.json']) for name in ('ordinary', 'profiled')}
    require(all(c['enabled'] == c['running'] > 0 and not c['event_errno'] for c in clocks.values()), 'inherited counter failed')
    foreground = sum(value for key, value in disjoint.items() if key != 'instrumentation')
    require(foreground == clocks['profiled']['instructions'], 'process counters disagree with inherited hardware event')
    require(disjoint == json.loads(packet['pmu/processes.json']) and len(tids) == 376 and monitor, 'checkout attribution changed')
    return epochs, monitor, disjoint, {name: c['instructions'] for name, c in clocks.items()}


def kernel_samples(packet):
    compressed = packet['pmu/perf.data.zst']
    stored = json.loads(packet['pmu/perf-data.json'])
    require(sha(compressed) == stored['compressed_sha256'], 'compressed Linux perf file changed')
    raw = subprocess.check_output(['zstd', '-qd', '-c'], input=compressed)
    require(sha(raw) == stored['raw_sha256'] and len(raw) == stored['bytes'], 'Linux perf file changed')
    magic, header_size, attr_size, attr, attr_len, data, size, _, _ = struct.unpack_from('<9Q', raw)
    require(magic == int.from_bytes(b'PERFILE2', 'little') and header_size <= attr and attr_size == attr_len, 'invalid perf header')
    kind, attr_size, config, period, fields, _, flags = struct.unpack_from('<IIQQQQQ', raw, attr)
    require((kind, config, period, fields) == (0, 1, 1000003, 0x127) and attr_size >= 64, 'different sample event or layout')
    require(flags & 32 and flags & 64 and not flags & 16, 'event must count only user instructions')
    records = Counter()
    samples = {}
    stop = data + size
    while data < stop:
        event, mode, width = struct.unpack_from('<IHH', raw, data)
        require(width >= 8 and data + width <= stop, 'truncated kernel record')
        records[event] += 1
        if event == 9:
            ip, pid, tid, stamp, actual, depth = struct.unpack_from('<QIIQQQ', raw, data + 8)
            key = (pid, tid, stamp, actual, ip)
            require(actual == period and depth <= 64 and 48 + 8 * depth <= width, 'invalid sampled record')
            require(mode & 7 in (1, 2) and key not in samples, 'ambiguous sample')
            samples[key] = mode & 7
        data += width
    require(data == stop and not any(records[k] for k in (2, 5, 6, 13)), 'lost or throttled records')
    require(records[9] == json.loads(packet['pmu/record-counts.json'])['PERF_RECORD_SAMPLE'], 'sample inventory differs')
    return samples


def sampled_subsystems(packet, epochs, monitor):
    raw = kernel_samples(packet)
    labels = json.loads(packet['pmu/frame-groups.json'])
    framed = {}
    actor_samples = Counter()
    grouped = defaultdict(Counter)
    seen = set()
    for line in gzip.decompress(packet['pmu/samples.ndjson.gz']).splitlines():
        row = json.loads(line)
        if row[0] == 'f':
            _, idx, dso, symbol = row
            require(idx not in framed and labels[str(idx)][:2] == [dso, symbol], 'frame census differs')
            framed[idx] = labels[str(idx)][2]
            continue
        _, event, pid, tid, stamp, period, leaf, stack = row
        key = (pid, tid, stamp, period, leaf[1])
        require(event == 'instructions:u' and key in raw and key not in seen, 'symbolizer changed an actual sampled PC')
        require(all(frame[0] in framed for frame in [leaf, *stack]), 'unresolved frame index')
        seen.add(key)
        seq = epochs.get(pid, [])
        i = bisect_right(seq, (stamp, '\U0010ffff'))
        role = seq[i - 1][1] if i else ('instrumentation' if pid == monitor else 'unattributed startup')
        actor_samples[role] += 1
        if role.startswith('rustc:'):
            label = framed[leaf[0]] if raw[key] == 2 else 'kernel skid'
            grouped[label][role] += 1
    require(seen == raw.keys() and actor_samples == json.loads(packet['pmu/samples.json'])['by_role'], 'raw sample or process mismatch')
    require(dict(grouped) == json.loads(packet['pmu/partition.json']), 'subsystem reports do not reconcile')
    require(Counter(raw.values()) == {2: 6303, 1: 31}, 'user/kernel leaf census changed')
    return actor_samples, grouped


def sparse_rows(blob, locator):
    encoding, count, pos = locator
    width = encoding & 127
    require(0 < width <= 17 and 0 <= count < 5000, 'invalid metadata table shape')
    populated = []
    if encoding & 128:
        buckets = (count + 63) // 64
        for group in range(buckets):
            bits, rank = struct.unpack_from('<QI', blob, pos + group * 12)
            require(rank == len(populated) and bits.bit_length() <= min(64, count - group * 64), 'invalid sparse rank')
            populated.extend(group * 64 + bit for bit in range(64) if bits >> bit & 1)
        pos += buckets * 12
    else:
        populated = range(count)
    rows = {}
    for index in populated:
        value = blob[pos:pos + width]
        require(len(value) == width, 'truncated metadata row')
        if any(value):
            rows[index] = value
        pos += width
    return rows, pos


def decoded_counts(blob, root):
    # The pinned CrateRoot and CrateHeader fields leading up to exported_generic_symbols.
    pos = root

    def unsigned():
        nonlocal pos
        value, pos = leb(blob, pos)
        return value

    def string():
        nonlocal pos
        length = unsigned()
        data = blob[pos:pos + length]
        pos += length
        require(blob[pos] == 193, 'unterminated Rust metadata string')
        pos += 1
        return data

    def array_len():
        n = unsigned()
        if n:
            unsigned()  # Relative pointer into the metadata.
        return n

    require(unsigned() == 0 and string() == b'x86_64-unknown-linux-gnu', 'wrong metadata target')
    pos += 32  # CrateHashes
    require(unsigned() == 0 and string() == b'annotate_snippets', 'wrong crate symbol')
    require(unsigned() == unsigned() == 0 and string() == b'-505afd119b4de8d0', 'unexpected crate flags')
    require(int.from_bytes(blob[pos:pos + 8], 'little') == int(PRODUCER, 16), 'wrong stable crate ID')
    pos += 8
    require([unsigned() for _ in range(7)] == [0, 0, 3, 0, 0, 0, 0], 'unexpected panic/edition/allocator flags')
    prior = [array_len() for _ in range(13)]  # EII, dependencies, lang items, native libraries, traits.
    require(prior[1] == 22 and unsigned() == 1, 'different dependency or trait-impl representation')
    array_len()  # EncodedTraitImpls::DefPathHash
    array_len()  # incoherent_impls
    alloc = array_len()
    require(unsigned() == 0, 'unexpected ProcMacroData')
    remaining = [array_len() for _ in range(5)]  # debugger, exportable, impl order, non-generic, generic
    return alloc, remaining[-1]


def metadata_domains(packet):
    locations = json.loads(packet['rmeta/locators.json'])
    rdr = {}
    expanded = {}
    for tag, item in locations.items():
        blob = packet['rmeta/' + item['binding'] + '.bin']
        dump = packet['rmeta/' + item['binding'] + '.ls']
        require(sha(blob) == item['blob_sha'] and sha(dump) == item['ls_sha'], 'compiler-decoded metadata changed')
        require(blob.startswith(b'rust\0\0\0\n') and blob.endswith(b'rust-end-file'), 'wrong Rust metadata format')
        require(struct.unpack_from('<Q', blob, 8)[0] == item['root'] and blob[-29:-13].hex() == item['public_global'], 'metadata root or global hash differs')
        require(decoded_counts(blob, item['root']) == (item['n_alloc'], item['n_exported']), 'different root array lengths')
        defs, _ = sparse_rows(blob, item['def_path_hashes'])
        local, local_end = sparse_rows(blob, item['rdr_local'])
        expn, expn_end = sparse_rows(blob, item['rdr_expn'])
        require(local_end == item['rdr_expn'][2] and expn_end == item['root'], 'unexpected final metadata table boundary')
        require(all(len(v) == 17 and v[0] == 1 for rows in (local, expn) for v in rows.values()), 'invalid reachable fingerprint')
        rdr[tag] = {f'{int.from_bytes(defs[i], "little"):016x}': v[1:].hex() for i, v in local.items()}
        expanded[tag] = expn
        require(rdr[tag][PRODUCER] == item['root_scc'], 'crate-root SCC differs from physical table')
    old, new = rdr['O'], rdr['N']
    require(old == rdr['O2'] and new == rdr['N2'] == rdr['N3'] and old.keys() == new.keys(), 'unstable same-source local results')
    require(expanded['O'] == expanded['O2'] and expanded['N'] == expanded['N2'] == expanded['N3'], 'unstable same-source expansion results')
    changed = {key for key in new if old[key] != new[key]}
    require(len(new) == 1099 and len(changed) == 771 and PRODUCER in changed, 'different reachable local footprint')
    require(locations['O']['n_exported'] == 1019 and all(locations[t]['n_exported'] == 1028 for t in ('N', 'N2', 'N3')), 'different exported generic counts')
    require(locations['N']['blob_sha'] != locations['N3']['blob_sha'] and locations['N']['ls_sha'] == locations['N3']['ls_sha'], 'independent clean difference lost')
    return set(new), changed


def query_witnesses(packet, identities, changed):
    graphs = json.loads(packet['rsic/observations.json'])
    keyed, direct = {}, {}
    for tag, graph in graphs.items():
        keyed[tag], direct[tag] = {}, {}
        require(not graph['domain_kind_counts'], 'direct RDR query kinds unexpectedly present')
        for kind, key, value, index, count, reads_marker in graph['rows']:
            require(key.startswith(PRODUCER) and (kind, key) not in keyed[tag], 'ambiguous external query row')
            keyed[tag][kind, key] = value
            if reads_marker:
                require(count and index != graph['marker'], 'bad marker edge')
                direct[tag][kind, key] = value
    for rows in (keyed, direct):
        require(rows['O'] == rows['O2'] and rows['N'] == rows['N2'] == rows['N3'], 'same-source query witness differs')
        require(rows['O'].keys() == rows['N'].keys(), 'query inventory changed')
    pairs = [k for k in keyed['O'] if k[1][16:] in identities]
    different = {k[0] for k in pairs if keyed['O'][k] != keyed['N'][k]}
    require(len(keyed['N']) == 1487 and len(pairs) == 1485 and len({k[0] for k in pairs}) == 73, 'wrong external query population')
    require(different == {'crate_hash', 'external_metadata_input_hash', 'exported_generic_symbols'}, 'a different external query changed')
    require(sum(keyed['O'][k] == keyed['N'][k] != '0'*32 for k in pairs) == 1481, 'unexpected stable nonzero query count')
    require(sum(k[1][16:] in changed for k in pairs) == 1469, 'different queried-definition footprint')
    require(len(direct['O']) == 1210 and {k[0] for k in direct['O'] if direct['O'][k] != direct['N'][k]} == {'exported_generic_symbols'}, 'different direct dependents of coarse metadata')
    return graphs


def native_controls(packet):
    builds = json.loads(packet['native/builds.json'])
    reference = json.loads(packet['native/source.json'])
    comp = json.loads(packet['native/archive-comparisons.json'])
    require(reference['whole_archive_gate_passed'] is False and comp['retained_raw_archive_rejection'], 'original worker refusal missing')
    for tag, build in builds.items():
        native = build['native']
        require(build['n_output'] == 171 and build['registry_entries'] == 123 and build['shared'] == 114, 'wrong source topology')
        require(build['tests_sha'] == sha(packet['native/tests.list']) and len(packet['native/tests.list'].splitlines()) == 126, 'wrong libtest list')
        require(sorted(native['tests'].values()) == [0, 0] and len(build['consumer']) == 216 and len(build['renderer']) == 118, 'incomplete native controls')
        for name, _, _, payload_sha in build['native_members']:
            if name.endswith('.rcgu.o'):
                require(build['renderer'][name.split('.')[1]] == payload_sha, 'misidentified renderer codegen unit')
    for old, edit in [('O', 'N'), ('O2', 'N2')]:
        before, after = builds[old]['consumer'], builds[edit]['consumer']
        require(before.keys() == after.keys() and all(before[k][:2] == after[k][:2] and after[k][2] for k in before), 'exact old donor was replaced')
    for key in ('renderer', 'allocated_shape_sha', 'registry_roster_sha'):
        require(builds['N'][key] == builds['N2'][key] == builds['N3'][key], f'New {key} differs')
    for key in ('elf', 'client', 'oracle'):
        require(builds['N']['native'][key] == builds['N2']['native'][key] == builds['N3']['native'][key], f'New {key} differs')
    digests = lambda tag: {k: v[0] for k, v in builds[tag]['consumer'].items()}
    require(digests('N') == digests('N2') == digests('N3') and builds['N']['native']['elf'] != builds['O']['native']['elf'], 'unexpected clean/changed final product')
    require(builds['N']['dirty'] == builds['N2']['dirty'] == ['annotate_snippets', 'ruff_db'] and builds['N']['cargo_roster_sha'] == builds['N2']['cargo_roster_sha'], 'profiled Cargo work differs')
    require(len({b['raw_ar'] for b in builds.values()}) == 5 and builds['N']['allocated_sections'] == 3199, 'archive envelope or allocated-section census differs')
    return builds


def leb(raw, pos):
    result = 0
    for shift in range(0, 35, 7):
        byte = raw[pos]
        pos += 1
        result |= (byte & 127) << shift
        if byte < 128:
            return result, pos
    raise ValueError('overlong integer')


def verify_rsic(raw, schema, expected):
    require(sha(raw) == expected['sha256'] and raw.startswith(b'RSIC') and raw.endswith(b'rust-end-file'), 'different compiler graph')
    require(struct.unpack_from('<H', raw, 4)[0] == schema['format'] and raw[7:7 + raw[6]] == b'1.99.0-dev', 'unexpected graph format')
    names = schema['names']
    bits = (len(names) - 1).bit_length()
    end = len(raw) - 13
    slots, nodes, edges = struct.unpack_from('<QQQ', raw, end - 24)
    require(nodes == expected['nodes'] <= slots and edges == expected['edges'], 'different graph footer')
    limit = struct.unpack_from('<Q', raw, end - 48)[0] if raw[end-32:end-24] == b'OHMIDX01' else end-24
    pos = 7 + raw[6] + 8
    visited = [0] * len(names)
    edge_count = 0
    observed = []
    for _ in range(nodes):
        tag, index = struct.unpack_from('<HI', raw, pos)
        kind = tag & ((1 << bits) - 1)
        width = ((tag >> bits) & 3) + 1
        count = (tag >> (bits + 2)) - 1
        key_a, key_b, value_a, value_b = struct.unpack_from('<QQQQ', raw, pos + 6)
        pos += 38
        if count < 0:
            count, pos = leb(raw, pos)
        visited[kind] += 1
        if key_a == int(PRODUCER, 16):
            children = (int.from_bytes(raw[off:off+width], 'little') for off in range(pos, pos + count*width, width))
            observed.append([names[kind], f'{key_a:016x}{key_b:016x}', f'{value_a:016x}{value_b:016x}', index, count, expected['marker'] in children])
        pos += count * width
        edge_count += count
        require(pos <= limit and index < slots, 'malformed sparse graph')
    for count in visited:
        actual, pos = leb(raw, pos)
        require(actual == count, 'node records do not reproduce the kind histogram')
    _, pos = leb(raw, pos)
    require(observed == expected['rows'] and pos == limit and edge_count == edges, 'raw graph does not reproduce selected evidence')
    for label in ('extern_def_public_hash', 'extern_expn_public_hash', 'public_global_hash'):
        require(not visited[names.index(label)], 'unexpected direct RDR query')


def verify_rlib(raw, build):
    require(raw[:8] == b'!<arch>\n', 'wrong rlib magic')
    pos = 8
    long_names = b''
    rows = []
    allocated = 0
    while pos < len(raw):
        at = pos
        header = raw[pos:pos+60]
        require(len(header) == 60 and header[58:] == b'`\n', 'invalid archive header')
        name = header[:16].decode().strip()
        length = int(header[48:58].strip())
        pos += 60
        body = raw[pos:pos+length]
        require(len(body) == length, 'truncated archive member')
        if name == '//':
            long_names = body
        elif re.fullmatch(r'/\d+', name):
            start = int(name[1:])
            name = long_names[start:long_names.index(b'/\n', start)].decode()
        elif name != '/':
            name = name.rstrip('/')
        rows.append([name, at, length, sha(body)])
        if name.endswith('.rcgu.o'):
            require(body[:6] == b'\x7fELF\x02\x01' and struct.unpack_from('<H', body, 18)[0] == 62, 'wrong native object')
            shoff = struct.unpack_from('<Q', body, 40)[0]
            size, count = struct.unpack_from('<HH', body, 58)
            allocated += sum(bool(struct.unpack_from('<Q', body, shoff + n * size + 8)[0] & 2) for n in range(count))
        pos += length + length % 2
    require(pos == len(raw) and rows == build['native_members'] and allocated == build['allocated_sections'], 'native archive members or ELF section count changed')


def verify_original(path, packet, builds, graphs):
    with path.open('rb') as file:
        require(hashlib.file_digest(file, 'sha256').hexdigest() == ORIGINAL, 'different GitHub artifact')
    origin = json.loads(packet['provenance.json'])
    schema = json.loads(packet['rsic/kinds.json'])
    graph_paths = {f"receipt/{r['stage']}/graph.bin.gz": tag for tag, r in origin['role_receipts'].items()}
    archive_tags = {v['raw_ar']: tag for tag, v in builds.items()}
    expected_bodies = {body for tag in TAGS for body, _, _ in builds[tag]['consumer'].values()}
    expected_bodies.update(archive_tags)
    expected_bodies.update(builds[tag]['native'][key] for tag in TAGS for key in ('elf', 'client'))
    seen_bodies = set()
    seen_graphs = set()
    with zipfile.ZipFile(path) as outer:
        require(outer.namelist() == ['matched-heldout-proof.tar'], 'different diagnostic envelope')
        with outer.open(outer.namelist()[0]) as stream, tarfile.open(fileobj=stream, mode='r|') as tar:
            for member in tar:
                if member.name in graph_paths:
                    tag = graph_paths[member.name]
                    with gzip.GzipFile(fileobj=tar.extractfile(member)) as compressed:
                        raw = compressed.read(45_000_001)
                    require(len(raw) <= 45_000_000, 'oversized graph')
                    verify_rsic(raw, schema, graphs[tag])
                    del raw
                    seen_graphs.add(tag)
                elif member.isfile() and member.name.startswith('receipt/native/'):
                    key = Path(member.name).stem
                    require(key in expected_bodies and key not in seen_bodies, 'unexpected content-addressed product')
                    with subprocess.Popen(['zstd', '-dq', '-c'], stdin=subprocess.PIPE, stdout=subprocess.PIPE) as decoder:
                        def feed():
                            with decoder.stdin:
                                shutil.copyfileobj(tar.extractfile(member), decoder.stdin, 65536)

                        with ThreadPoolExecutor(max_workers=1) as pool:
                            writer = pool.submit(feed)
                            if key in archive_tags:
                                raw = decoder.stdout.read(50_000_001)
                                require(len(raw) <= 50_000_000 and sha(raw) == key, 'wrong or oversized renderer rlib')
                                verify_rlib(raw, builds[archive_tags[key]])
                                del raw
                            else:
                                require(hashlib.file_digest(decoder.stdout, 'sha256').hexdigest() == key, 'wrong native body')
                            writer.result()
                        require(decoder.wait() == 0, 'native decompression failed')
                    seen_bodies.add(key)
    require(seen_bodies == expected_bodies and seen_graphs == set(TAGS), 'incomplete original artifacts')
    print(f'Reopened all {len(seen_bodies)} physical native blobs and all five complete RSIC graphs.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--original', type=Path, help='optional GitHub ZIP artifact 13143119648')
    args = parser.parse_args()
    packet = read_packet()
    builds = native_controls(packet)
    identities, changed = metadata_domains(packet)
    graphs = query_witnesses(packet, identities, changed)
    epochs, monitor, actors, clocks = exact_processes(packet)
    samples, groups = sampled_subsystems(packet, epochs, monitor)
    target = json.loads(packet['pmu/target.json'])
    require(statistics.median(target['six_boot_gaps']) == target['gap'] == 726845557, 'different prior six-boot denominator')
    print('Registered whole-rlib comparison failed. Edited native, test and independently clean controls passed.')
    print('Whole-command user instructions', clocks)
    print('Exact disjoint processes', dict(actors.most_common()))
    print('Kernel sample census', dict(samples.most_common()))
    print('Consumer and producer rustc samples')
    for group, counts in sorted(groups.items(), key=lambda item: -sum(item[1].values())):
        print(f"{group}: {counts['rustc:ruff_db']} / {counts['rustc:annotate_snippets']}")
    print('Exported generics 1019 → 1028. Changed saved public SCC fingerprints 771 / 1099.')
    print('1485 paired public-definition query keys: 1481 equal nonzero, 1 equal zero, 3 changed.')
    if args.original:
        verify_original(args.original, packet, builds, graphs)


if __name__ == '__main__':
    main()
