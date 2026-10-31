"""Rebuild both original archives, including rustc's ten source-bound opaque receiver captures."""
import gzip
import json
from pathlib import Path
import struct

from clocked import require, sha
import member_readback
import opaque_metadata
import products

OWNER = "ruff_python_ast"
STATE = {
    "old": "old", "replay-old": "old",
    "measured-final": "new", "replay-edit": "new", "repair": "new", "empty": "new",
}


def body(store, digest):
    data = gzip.decompress((store / (digest + ".gz")).read_bytes())
    require(sha(data) == digest, "bad retained native bytes")
    return data


def rebuild(manifest, read):
    result = bytearray(b"!<arch>\n")
    for name, header, digest, length, padding in manifest["entries"]:
        data = read(digest)
        require(len(data) == length and sha(data) == digest, ("invalid retained ar member", name))
        result.extend(bytes.fromhex(header) + data + bytes.fromhex(padding))
    raw = bytes(result)
    require(len(raw) == manifest["bytes"] and sha(raw) == manifest["sha256"], "whole ar replay")
    return raw


def rmeta_offset(elf, metadata):
    require(elf[:7] == b"\x7fELF\x02\x01\x01", "inner metadata is not a native 64-bit little-endian ELF")
    hdr = struct.unpack_from("<16sHHIQQQIHHHHHH", elf)
    require(hdr[1:3] == (1, 62) and hdr[-3] == 64 and 0 < hdr[-1] < hdr[-2], "wrong ELF object and table")
    sht = [struct.unpack_from("<IIQQQQIIQQ", elf, hdr[6] + n * hdr[-3]) for n in range(hdr[-2])]
    string_table = sht[hdr[-1]]
    require(string_table[1] == 3, "not a section-name table")
    names = elf[string_table[4]:string_table[4]+string_table[5]]
    matches = [row for row in sht if names[row[0]:].split(b"\0", 1)[0] == b".rmeta"]
    require(len(matches) == 1, "ambiguous real ELF metadata section")
    region = matches[0]
    require(region[1] == 1 and region[5] == len(metadata) and elf.count(metadata) == 1
            and elf[region[4]:region[4]+region[5]] == metadata, "separate metadata is not the exact ELF section")
    return region[4]


def witness(manifest, read):
    raw = rebuild(manifest, read)
    meta = read(manifest["separate_rmeta"])
    require(sha(meta) == manifest["separate_rmeta"], "separate rustc rmeta SHA")
    summary = products.normalized_archive(raw)
    require(len(summary["ordered_objects"]) == 95, "changed native CGU count")
    start = 8
    offset = None
    for name, header, part in member_readback.archive(raw):
        require(raw[start:start + 60] == header, "ar header")
        if name == "lib.rmeta":
            require(offset is None, "duplicate embedded metadata object")
            offset = start + 60 + rmeta_offset(part, meta)
        start += 60 + len(part) + len(part) % 2
    require(start == len(raw) and offset is not None and raw[offset:offset+len(meta)] == meta, "ar boundaries")
    return raw, meta, offset, summary


def compare(left_state, right_state, left, right, left_witness, right_witness):
    require(left_state in STATE and right_state in STATE and STATE[left_state] == STATE[right_state], "source-state mismatch")
    excluded = {"canonical_rlib", "rmeta", "embedded_metadata"}
    independent = ("roster", "elf", "elf_bytes", "reader_link", "result", "objects", "object_count", "symbols")
    require(all(left[k] == right[k] for k in independent), "native output, symbols, roster or observed behavior changed")
    differences = {n: [left[n], right[n]] for n in sorted(excluded) if left[n] != right[n]}
    for state, physical in ((left,left_witness),(right,right_witness)):
        raw, meta, _, summary = physical
        require(
            state["rlib"] == summary["raw"] == sha(raw)
            and state["rmeta"] == sha(meta) and state["symbols"] == summary["symbols"]
            and state["embedded_metadata"] == summary["embedded_metadata"]
            and state["canonical_rlib"] == summary["complete_canonical_sha256"]
            and state["objects"] == sha(json.dumps(summary["ordered_objects"],separators=(",",":")).encode())
            and state["object_count"] == len(summary["ordered_objects"]),
            "physical originals do not match their declarations",
        )

    def direction(a, b):
        raw, meta, at, summary = a
        target, other_meta, other_at, other_summary = b
        require(len(raw)==len(target) and len(meta)==len(other_meta) and at == other_at, "fixed archive or metadata width")
        if meta == other_meta:
            proof = {"byte_identical_rmeta": True, "sha256": sha(meta)}
        else:
            proof = opaque_metadata.prove_permutation(meta,other_meta)
            require(proof["reencoded_sha256"] == proof["destination_sha256"] == sha(other_meta), "rmeta reconstruction")
            require(opaque_metadata.canonical(meta) == opaque_metadata.canonical(other_meta), "source-bound canonical metadata")
        # Only the previously validated rustc invocation suffix and the verified ELF section can move.
        salt = summary["salt"].encode()
        other_salt = other_summary["salt"].encode()
        require(salt not in other_meta and other_salt not in meta, "CGU suffix occurs inside metadata")
        rebuilt = (raw[:at] + other_meta + raw[at+len(meta):]).replace(salt, other_salt)
        require(rebuilt == target, "unexplained byte in complete archive")
        return {"separate_rmeta":proof,"source_ar":sha(raw),"reencoded_ar":sha(rebuilt),"destination_ar":sha(target),
                "source_salt":summary["salt"],"destination_salt":other_summary["salt"],
                "rmeta_section_in_ar":at,"rmeta_bytes":len(meta)}
    return {"left":left_state,"right":right_state,"strict_differences":differences,
            "forward":direction(left_witness,right_witness),"reverse":direction(right_witness,left_witness)}


def from_paths(proof, states, a, b):
    def get(n):
        manifest = json.loads((proof/n/"ar-replay.json").read_bytes())
        return witness(manifest, lambda h: body(proof/"ar-content",h))
    return compare(a,b,states[a],states[b],get(a),get(b))
