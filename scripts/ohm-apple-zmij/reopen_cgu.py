"""Reopen Apple compiler-object evidence from the compressed native qualification archive.

The observed-link and untraced saved-recipe paths deliberately use separate sources.
"""
import argparse
import gzip
import json
from pathlib import Path
import struct
from zipfile import ZipFile

from cgu_inputs import modules
from macho_paths import canonical
from study import digest, need


def json_body(z, name):
    return json.loads(z.read(name))


def packed(z, name):
    return gzip.decompress(z.read(name))


def link_output(argv):
    outputs = [b for a, b in zip(argv, argv[1:]) if a == "-o"]
    need(len(outputs) == 1, "ambiguous native output")
    return outputs[0]


def observed_ld(z, phase, *, argv_sha=None, output=None, pid=None):
    events = json.loads(packed(z, phase + "/exec.json.gz"))
    result = []
    for event in events:
        if Path(event["path"]).name not in {"ld", "ld-classic", "ld-prime", "ld64"}:
            continue
        argv = event["argv"]
        actual = digest(json.dumps(argv, separators=(",", ":")).encode())
        if (argv_sha is None or argv_sha == actual) and (pid is None or pid == event["pid"]):
            if output is None or link_output(argv) == output:
                result.append((actual, event))
    need(len(result) == 1, "missing or duplicated observed linker")
    return result[0][1]


def original_provider(z, entries):
    """Associate a no-link return only with a preceding warm image from this same case."""
    previous = {}
    for phase in entries:
        row = json_body(z, phase + "/verified.json")
        if not row["image"]:
            yield phase, None
            continue
        key = row["image"]["raw"]
        kind = phase.rsplit("/", 1)[1]
        if row["final_links"]:
            cert, = row["final_links"]
            event = observed_ld(z, phase, argv_sha=cert["argv_sha"], output=cert["output"], pid=cert["pid"])
            need(cert["output_sha"] in (None, key) and event["cdhash"] == cert["cdhash"],
                 "physical linker identity or returned image differs")
            body = packed(z, "edge-images/" + key + ".macho.gz")
            need(digest(body) == key, "wrong archived executable")
            answer = body, cert["output"], event["argv"]
            if kind == "warm":
                previous[key] = answer
        else:
            need(kind == "warm" and key in previous, "the returned program has no own earlier observed linker")
            answer = previous[key]
        yield phase, answer


def program(z, raw):
    for bucket in ("crc-programs", "edge-images", "bundled-programs"):
        suffix = ".macho.gz" if bucket == "edge-images" else ".gz"
        try:
            body = packed(z, bucket + "/" + raw + suffix)
        except KeyError:
            continue
        need(digest(body) == raw, "archived image has the wrong digest")
        return body
    raise RuntimeError("missing physical program")


def verify(z, phase):
    q = json_body(z, phase + "/cgu-proof.json")
    exe = q["output"]
    raw = program(z, q["raw"])
    recipe = packed(z, "cgu-inputs/recipes/" + q["recipe"] + ".gz")
    need(digest(recipe) == q["recipe"], "altered .rlink")
    version, rows = modules(recipe)
    need(version == q["version"], "wrong compiled-module version")
    lookup = {}
    directory = Path(exe).with_suffix(".rlink-objects")
    for row in rows:
        file = row["object"]
        v = q["physical"][file]
        need(Path(file).parent == directory and row["name"] == v["module"] and row["kind"] == v["kind"],
             "physical object is not an owned module")
        obj = packed(z, "cgu-inputs/objects/" + v["sha256"] + ".gz")
        need(digest(obj) == v["sha256"] and len(obj) == v["bytes"] and
             obj[:8] == bytes.fromhex("cffaedfe0c000001") and struct.unpack_from("<I", obj, 12)[0] == 1,
             "missing or changed ARM64 MH_OBJECT")
        lookup[row["name"]] = v["sha256"]
    need(lookup == q["modules"] and set(q["physical"]) == {r["object"] for r in rows},
         "unstated or duplicated compiled module")
    operands = list(q["physical"])
    if q["source"] == "kernel-xcode-ld+rustc-recipe":
        event = observed_ld(z, phase, argv_sha=q["linker_argv"], output=exe)
        argv = event["argv"]
        actual = [p for p in argv if Path(p).parent == directory and p.endswith(".o")]
        need(len(actual) == len(set(actual)) and set(operands) == set(actual), "actual linker inputs differ")
        data, record = canonical(raw, exe, argv, incremental=True)
        need(digest(data) == q["cross_path_image"] and record["paths"] == q["debug_paths"], "cross-path mismatch")
    else:
        need(q["source"] == "saved-rustc-recipe" and phase + "/exec.json.gz" not in z.namelist(),
             "untraced scope does not agree")
        argv = [*operands, "-o", exe]
    data, record = canonical(raw, exe, argv, incremental=True, namespace=False)
    need(digest(data) == q["same_path_image"] and record["nonce_objects"] == q["nonce_objects"] and
         record["code_pages"] == q["code_pages"], "whole signed image differs")
    return {"phase": phase, "raw": q["raw"], "scope": q["source"], "objects": len(lookup),
            "signed_pages": record["code_pages"], "normalized": q["same_path_image"]}


if __name__ == "__main__":
    a = argparse.ArgumentParser(description=__doc__)
    a.add_argument("archive", type=Path)
    a.add_argument("phase", nargs="*")
    ns = a.parse_args()
    with ZipFile(ns.archive) as z:
        phases = ns.phase or sorted(n.rsplit("/", 1)[0] for n in z.namelist() if n.endswith("/cgu-proof.json"))
        need(phases, "no enrolled physical root objects")
        for phase in phases:
            print(json.dumps(verify(z, phase), sort_keys=True))
