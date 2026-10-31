"""Read the five native Ruff role ZIPs. Keep clean controls, physical populations and storage independently inspectable."""

import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import json
from pathlib import Path
import stat
import zipfile

HEAD = "9e125aab30ec25c421a1c2c6e97fac34e7248517"
RUN = 41159617280
TEST_RUN = 41159614839
SUBJECTS = {
    "stage-to-candidate": (13026208945, "54d55a985f1df73b7d3eeb14e789f36e6f662b37ca349da8b7b5c2ffcb34477c"),
    "stage-to-sham": (13025909504, "c0f106cec4a76e35420d8cbedab8f21edc5c5ead1c6c236e31565d44438ee88d"),
    "signed-to-candidate": (13026447694, "9e44d39c2049a4ef347e3e7a5fb7c42256c920e6eb6d8d6c123aa7681be21d75"),
    "e2e-parent": (13027075088, "4adb181df602589e65f922fb782b5d69b9726c5a742fcf104050171918d6d287"),
    "e2e-candidate": (13025854595, "df8995f15a02fc8ce1891d1bfd56d644eb35c40c8223b779d5dff66dcd192619"),
}
CARGO = "035e681081683f4141e4c544b8cf9492b73784051e4541c12bb3cbdb73a798a4"
WILD = "0d6335808b647d499f3d74993b602e64ff0625206c809bf4913c487eea380cd5"


def need(value, what):
    if not value:
        raise ValueError(what)


def unpack(z, n):
    data = z.read(n)
    return json.loads(gzip.decompress(data) if n.endswith(".gz") else data)


def category(path, mode):
    p = Path(path)
    if stat.S_ISDIR(mode):
        return "directory"
    if p.name in ("dep-graph.bin", "query-cache.bin"):
        return p.name
    if "/incremental/" in path:
        return "other-incremental/" + (p.suffix or "no-suffix")
    if p.suffix in (".rmeta", ".rlib", ".o", ".so", ".d"):
        return p.suffix
    return "other"


def storage(raw):
    data = json.loads(raw)
    byroot = defaultdict(dict)
    ident = defaultdict(set)
    attrs = {}
    dirroots = {}
    for row in data:
        p, dev, ino, mode, links, size, blocks, mtime, ctime = row
        root = p.split("/")[0]
        k = (dev, ino)
        v = blocks * 512
        need(k not in attrs or attrs[k][:2] == (v, size), "inconsistent inode size")
        attrs.setdefault(k, (v, size, category(p, mode)))
        byroot[root][k] = v
        ident[k].add(root)
        if p == root:
            dirroots[root] = row
    grouping = defaultdict(lambda: [0, 0, 0])
    for v, size, ct in attrs.values():
        grouping[ct][0] += 1
        grouping[ct][1] += size
        grouping[ct][2] += v
    return {
        "paths": len(data),
        "unique_inodes": len(attrs),
        "allocated": sum(a[0] for a in attrs.values()),
        "by_root_allocated": {k: sum(d.values()) for k, d in byroot.items()},
        "cross_root_inode_count": sum(len(v) > 1 for v in ident.values()),
        "cross_root_allocated": sum(attrs[k][0] for k, v in ident.items() if len(v) > 1),
        "roots": dirroots,
        "categories_count_logical_allocated": dict(grouping),
        "ledger": hashlib.sha256(raw).hexdigest(),
    }


def issuer(head):
    need(head[:8] == b"rust\0\0\0\n", "unknown rmeta")
    size = 0
    for i, b in enumerate(head[16:22]):
        size |= (b & 127) << (7 * i)
        if b < 128:
            return head[17 + i : 17 + i + size].decode()
    raise ValueError("truncated metadata")


def first_header(a, b):
    offset = next((i for i, (x, y) in enumerate(zip(a, b)) if x != y), None)
    if offset is None:
        return {"first_offset": None}
    r = {"first_offset": offset, "first_1024_different_bytes": sum(x != y for x, y in zip(a, b))}
    cut = a.rfind(b"\xc1", max(0, offset - 16), offset)
    if cut >= 0 and a[: cut + 1] == b[: cut + 1] and cut + 17 <= len(a):
        s = cut - 1
        while s >= 0 and (a[s : s + 1].isalnum() or a[s : s + 1] == b"_"):
            s -= 1
        name = a[s + 1 : cut]
        if len(name) > 1 and len(name) < 64 and s >= 0 and a[s] == len(name) and offset - cut <= 16:
            r["adjacent_encoded_dependency_name"] = name.decode()
            r["following_16_bytes"] = [a[cut + 1 : cut + 17].hex(), b[cut + 1 : cut + 17].hex()]
    return r


def source_origin(source):
    if "/registry/src/" in source:
        return "registry"
    if source.startswith("crates/") or "/ruff/crates/" in source:
        return "workspace"
    return "other"


def population(z, phase, sdk):
    raw = [json.loads(l) for l in gzip.decompress(z.read(phase + "/stdout.jsonl.gz")).splitlines()]
    messages = [r for r in raw if r["reason"] == "compiler-artifact"]
    artifacts = Counter()
    for m in messages:
        artifacts[
            "/".join(
                (
                    source_origin(m["target"]["src_path"]),
                    "+".join(m["target"]["kind"]),
                    "fresh" if m["fresh"] else "rebuilt",
                )
            )
        ] += 1
    result = {
        "returned_artifact_count": len(messages),
        "cargo_artifacts": dict(artifacts),
        "terminal": raw[-1],
        "errors": [
            {
                "code": (m["message"].get("code") or {}).get("code"),
                "primary": [
                    [s["file_name"], s["line_start"], s["column_start"], [x["text"] for x in s["text"]]]
                    for s in m["message"]["spans"]
                    if s["is_primary"]
                ],
            }
            for m in raw
            if m["reason"] == "compiler-message"
            and m["message"]["level"] == "error"
            and m["message"].get("code")
        ],
    }
    if phase.startswith("trace/"):
        physical = unpack(z, phase + "/physical.json")
        slots = {v[0]: v for v in physical["compilers"]}
        events = unpack(z, phase + "/execs.json.gz")
        strata = Counter()
        roster = []
        installed = sdk["bin/rustc"]
        for pid, ident, image, args in events:
            if pid not in slots or not ("--crate-name" in args and "--out-dir" in args):
                continue
            need(ident == [installed["dev"], installed["ino"]], "different physical rustc")
            v = slots[pid]
            rust_sources = [a for a in args if a.endswith(".rs")]
            if not rust_sources and "-" in args:
                rust_sources = ["<stdin>"]
            need(len(rust_sources) == 1, (phase, pid, rust_sources))
            name = args[args.index("--crate-name") + 1]
            crate_types = [w.partition("=")[2] for w in args if w.startswith("--crate-type=")]
            if "--crate-type" in args:
                crate_types.append(args[args.index("--crate-type") + 1])
            ty = (
                "build-script"
                if name == "build_script_build"
                else (
                    "test" if "--test" in args else ("+".join(crate_types) if crate_types else "default-bin")
                )
            )
            origin = (
                "runtime-compiler-probe" if rust_sources == ["<stdin>"] else source_origin(rust_sources[0])
            )
            key = "/".join([origin, ty, v[2], "O" + v[4]["opt_level"]])
            strata[key] += 1
            roster.append([pid, name, rust_sources[0], key])
        need(len(roster) == len(slots), (phase, "unaccounted actual rustc"))
        result.update(
            {
                "physical": dict(strata),
                "physical_compiler_count": len(roster),
                "compiler_argv_census": roster,
                "wild": len(physical["wild"]),
                "returned_e2e_links": sum(v["same_returned_e2e"] for v in physical["wild"]),
                "generator": len(physical["generators"]),
            }
        )
    return result


def work(folder, role):
    aid, h = SUBJECTS[role]
    name = folder / f"mixed-ruff-{role}-{aid}.original.zip"
    with name.open("rb") as f:
        need(hashlib.file_digest(f, "sha256").hexdigest() == h, "changed original archive")
    with zipfile.ZipFile(name) as z:
        reg = unpack(z, "registration.json")
        r = unpack(z, "summary.json")
        e2e = role.startswith("e2e-")
        run = TEST_RUN if e2e else RUN
        need(
            (reg["head"], reg["run"], reg["attempt"], reg["role"]) == (HEAD, run, 1, role),
            "wrong physical worker",
        )
        result = {
            "run": run,
            "artifact": aid,
            "sha256": h,
            "issues": r["issues"],
            "install": {},
            "state": {},
            "visits": {},
            "comparisons": {},
            "unit_keys": {},
            "unit_values": {},
        }
        sdk = {}
        for label, v in r["installs"].items():
            sdk[label] = unpack(z, "installs/" + label + "/installed.json.gz")
            meta = unpack(z, "installs/" + label + "/install.json")
            stamp = issuer(z.read("installs/" + label + "/issuer.rmeta"))
            need(
                meta["rustc_vv"] == v["rustc_vv"] and stamp == v["stamp"],
                "inconsistent physical compiler identity",
            )
            bins = sdk[label]
            selected = {
                n: t
                for n, t in bins.items()
                if n in ("bin/cargo", "bin/rustc")
                or "librustc_driver" in n
                or n.endswith("wild-ld/ld.bfd")
                or ("/libstd-" in n and n.endswith(".rlib"))
            }
            need(
                selected["bin/cargo"]["sha256"] == CARGO
                and any(y["sha256"] == WILD for y in selected.values()),
                "unknown strict Cargo/Wild",
            )
            result["install"][label] = {
                "path": meta["stable_path"],
                "sysroot": meta["sysroot"],
                "members": len(bins),
                "issuer": stamp,
                "vv": meta["rustc_vv"],
                "selected": selected,
            }
        if not e2e:
            for stream in ("pmu", "trace"):
                holders = [
                    gzip.decompress(z.read(f"installs/{stream}-{side}/allocated-files.json.gz"))
                    for side in ("before", "after")
                ]
                need(holders[0] == holders[1], "private identity probe changed populated roots")
                result["state"][stream + "-at-install"] = storage(holders[0])
                old, new = (sdk[stream + "-" + s] for s in ("old", "new"))
                intersect = [
                    n for n in old.keys() & new.keys() if old[n]["link"] is None and new[n]["link"] is None
                ]
                need(
                    all((old[n]["dev"], old[n]["ino"]) != (new[n]["dev"], new[n]["ino"]) for n in intersect),
                    "sham inode held",
                )
                result["install"][stream + "-comparison"] = {
                    "overlapping_regulars": len(intersect),
                    "same_digest": sum(old[n]["sha256"] == new[n]["sha256"] for n in intersect),
                    "same_mtime": sum(old[n]["mtime_ns"] == new[n]["mtime_ns"] for n in intersect),
                    "same_ino": 0,
                    "same_rustc_vv": result["install"][stream + "-old"]["vv"]
                    == result["install"][stream + "-new"]["vv"],
                    "old_only": sorted(old.keys() - new.keys()),
                    "new_only": sorted(new.keys() - old.keys()),
                }
        refs = {}
        headers = {}
        tests = {}
        for phase, summary in r["visits"].items():
            vis = unpack(z, phase + "/visit.json")
            stream, pname = phase.split("/")
            generation = "old" if e2e or pname in ("cold", "prior-repeat") else "new"
            role_sdk = sdk[(stream if stream != "clean" else "trace") + "-" + generation]
            observed = population(z, phase, role_sdk)
            need(observed["terminal"] == vis["terminal"], "terminal drift")
            observed["status"] = vis["status"]
            raw = gzip.decompress(z.read(phase + "/allocated-files.json.gz"))
            result["state"][phase] = storage(raw)
            need(result["state"][phase]["allocated"] == summary["allocated"], "allocation mismatch")
            if vis["test"]:
                t = vis["test"]
                tests[phase] = {
                    "count": len(t["names"]),
                    "names": t["names"],
                    "sha": t["list_sha"],
                    "elf": t["elf"]["sha256"],
                    "new_cases": t["new_cases"],
                    "snapshot_control": t["runtime"],
                }
            refs[phase] = unpack(z, phase + "/workspace-rmeta.json")
            nonempty = [v for v in refs[phase].values() if v["size"]]
            for m in nonempty:
                k = m["sha256"]
                if k not in headers:
                    hd = z.read("rmeta-headers/" + k + ".bin")
                    need(issuer(hd) == m["stamp"], "incorrect captured metadata issuer")
                    headers[k] = hd
            observed["rmeta"] = {
                "all": len(refs[phase]),
                "nonempty": len(nonempty),
                "empty": len(refs[phase]) - len(nonempty),
                "issuers": dict(Counter(m["stamp"] for m in nonempty)),
                "wrong_issuer": sum(m["stamp"] != vis["active_stamp"] for m in nonempty),
            }
            observed["generated"] = vis["generated"]
            observed["logical_units_sha256"] = vis["logical_units"]
            result["visits"][phase] = observed
        if e2e:
            result["test"] = tests
            return result
        unique = sorted(set().union(*[set(v) for v in refs.values()]))
        result["unit_keys"] = [json.loads(k) for k in unique]
        result["unit_values"] = {phase: [m.get(k) for k in unique] for phase, m in refs.items()}
        compare = [("pmu/cold", "trace/cold"), ("clean/reversed", "clean/repaired")]
        for stream in ("pmu", "trace"):
            compare += [
                (stream + "/prior-repeat", stream + "/upgrade-first"),
                (stream + "/upgrade-first", stream + "/upgrade-second"),
                (stream + "/edited", stream + "/edit-repeat"),
            ]
            for name, ref in (
                ("upgrade-first", "original"),
                ("upgrade-second", "original"),
                ("edited", "reversed"),
                ("edit-repeat", "reversed"),
                ("repaired", "repaired"),
                ("restored", "original"),
                ("restore-repeat", "original"),
            ):
                compare.append((stream + "/" + name, "clean/" + ref))
        for left, right in compare:
            a, b = refs[left], refs[right]
            changed = {}
            removed = []
            added = []
            sizes = 0
            issuer_diffs = 0
            for i, k in enumerate(unique):
                if k not in a or k not in b:
                    if k in a:
                        removed.append(i)
                    if k in b:
                        added.append(i)
                    continue
                if a[k] != b[k]:
                    av, bv = a[k], b[k]
                    sizes += av["size"] != bv["size"]
                    issuer_diffs += av["stamp"] != bv["stamp"]
                    if av["size"] and bv["size"]:
                        changed[i] = first_header(headers[av["sha256"]], headers[bv["sha256"]])
                    else:
                        changed[i] = {"empty": True}
            src = [unpack(z, phase + "/source.json") for phase in (left, right)]
            result["comparisons"][left + " vs " + right] = {
                "keys_lost": removed,
                "keys_added": added,
                "same_source_bytes": {k: (v[0] if v else None) for k, v in src[0].items()}
                == {k: (v[0] if v else None) for k, v in src[1].items()},
                "different_units": changed,
                "changed_hashes": len(changed),
                "changed_sizes": sizes,
                "changed_issuer": issuer_diffs,
            }
        result["semantics_chunks"] = r["semantic_content_survey"]
        return result


def project(folder, output):
    d = {n: work(folder, n) for n in SUBJECTS}
    data = json.dumps(d, sort_keys=True, separators=(",", ":")).encode()
    output.write_bytes(gzip.compress(data, compresslevel=9, mtime=0))
    print(
        "underlying projection sha256",
        hashlib.sha256(data).hexdigest(),
        "compressed bytes",
        output.stat().st_size,
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("originals", type=Path)
    p.add_argument("output", type=Path)
    a = p.parse_args()
    project(a.originals, a.output)
