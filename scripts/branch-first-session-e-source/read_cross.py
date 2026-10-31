"""Reopen native table bytes, owned compiler reads and executable verdicts from the original ZIP."""

import gzip
import hashlib
import json
from pathlib import Path
import re
import tempfile
import zlib

import cross_reader as cross
from registration import need


def h(data):
    return hashlib.sha256(data).hexdigest()


def table(raw, record, name, mode):
    need(len(raw) == record["bytes"] and h(raw) == record["sha256"], "actual stored table")
    data = raw
    if mode == "packed":
        dec = zlib.decompressobj()
        decoded = dec.decompress(raw, (16 << 20) + 4096)
        need(dec.eof and not dec.unconsumed_tail and not dec.unused_data, "partial packed table")
        header, sep, data = decoded[11:].partition(b"\0")
        tag = b"G" if name == cross.NAMES[0] else b"Q"
        need(decoded[:2] == b"\x01" + tag and decoded[2] & 1 and decoded[2] < 8
             and int.from_bytes(decoded[3:11], "little") == len(data) and sep
             and header.decode() == Path(record["path"]).parent.name.rsplit("-", 1)[0],
             "foreign packed producer")
    need(data.startswith(b"RSIC") and len(data) == record["decoded_bytes"]
         and h(data) == record["decoded_sha256"], "different native table payload")


def replay(archive, read, case, record, manifest, donor):
    base = "E/cross-readers/" + case + "/"
    source = Path(record["source"])
    current = Path(record["returned_marker"]).parent
    driver = manifest["driver"]
    for role in ("K", "E"):
        expected = donor["driver"] if role == "K" else manifest["files"][driver]
        need(record["images"][role][driver][0] == expected[0], "wrong active compiler identity")
    for sub, key, mode in (("", "source_tables", record["representation"]),
                           ("cold-A/", "cold_tables", record["cold_representation"])):
        need(set(record[key]) == set(cross.NAMES), "missing one table")
        for name in cross.NAMES:
            row = record[key][name]
            expected = ("ohm-packed-" if mode == "packed" else "") + name
            need(Path(row["path"]).name == expected, "table polarity")
            table(gzip.decompress(read(base + sub + expected + ".gz")), row, name, mode)
    need(h((case + " " + str(source) + "\n").encode()) == record["marker_sha256"]
         and record["marker"] == record["returned_marker_identity"], "foreign origin sentinel")
    visits = [("consumer-return-A", "loaded", 17), ("consumer-empty-A", "not-loaded", 17),
              ("cold-A", "not-loaded", 17),
              ("consumer-first-B" if record["immediate_cold_read"] else "first-B", "loaded", 29)]
    for phase, assertion, value in visits:
        loc = base + phase + "/"
        cmd = json.loads(read(loc + "compiler/command.json"))
        need(cmd["code"] == 0 and "-Zassert-incr-state=" + assertion in cmd["argv"]
             and "incremental=" + str(source.parents[1]) in cmd["argv"], "wrong compiler command")
        for witness, status in (("right", 0), ("wrong", 19)):
            need(json.loads(read(loc + witness + "/command.json"))["code"] == status
                 and read(loc + witness + "/stdout") == f"{value}\n".encode(),
                 "wrong executed native result")
    miss = base + "empty-refuses-loaded/compiler/"
    need(json.loads(read(miss + "command.json"))["code"] == 1 and cross.DENIAL in read(miss + "stderr"),
         "missing genuine empty-state rejection")
    prefix = base + "consumer-return-A/kernel."
    paths = [n for n in archive.namelist() if n.startswith(prefix)]
    need(0 < len(paths) <= 256 and all(re.fullmatch(r"[0-9]+\.gz", n[len(prefix):]) for n in paths),
         "invalid native trace members")
    with tempfile.TemporaryDirectory() as scratch:
        place = Path(scratch)
        for name in paths:
            (place / Path(name).name).write_bytes(read(name))
        facts = cross.kernel(place, place / "kernel", source.parents[3] / "operational" / driver,
                             record["representation"], record["source_tables"], current,
                             source / "cross-reader-origin", reopen=True)
    need(facts == record["actual"], "raw trace does not reproduce physical selected inputs")
    for name in ("return_elf", "first_B"):
        digest = record[name]
        native = gzip.decompress(read("E/cross-readers/elf/" + digest + ".gz"))
        need(native[:4] == b"\x7fELF" and native[18:20] == b"\x3e\0" and h(native) == digest,
             "wrong independently preserved Linux image")
