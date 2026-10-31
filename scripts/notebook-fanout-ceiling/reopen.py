"""Reconstruct the feasibility ceiling and native input provenance from a completed receipt."""

import argparse
from functools import partial
import gzip
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tempfile
import zipfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import inputs
import heavy
import sampling
import support
import contract as c


def native(out, folder, mode):
    row = (
        inputs.load(folder / "program.json")
        if (folder / "program.json").exists()
        else inputs.load(folder / "visit.json")["test"]
    )
    names = inputs.load(folder / "actual-test-names.json")
    raw = gzip.decompress((folder / "native-list.stdout.gz").read_bytes())
    actual = sorted(s[:-6] for s in raw.decode().splitlines() if s.endswith(": test"))
    c.require(
        len(actual) == len(set(actual)) == {"original": 200, "reversed": 199}[mode]
        and actual == names == row["names"]
        and hashlib.sha256(raw).hexdigest() == row["list_sha"]
        and inputs.load(folder / "native-list.status.json") == 0
        and set(row["runtime"]) == c.CASES[mode],
        "native test-name mismatch",
    )
    for case in c.CASES[mode]:
        prefix = "native-" + case.split("::")[-1]
        log = gzip.decompress((folder / (prefix + ".stdout.gz")).read_bytes())
        c.require(
            inputs.load(folder / (prefix + ".status.json")) == 0
            and f"test {case} ... ok".encode() in log
            and b"1 passed; 0 failed" in log
            and row["runtime"][case] == {"code": 0, "one_named": True},
            "actual named case did not run",
        )
    image = inputs.load(out / row["elf"]["native_index"])
    c.require(
        image["sha256"] == row["elf"]["sha256"]
        and image["size"] == row["elf"]["size"] > 100_000_000
        and bool(image["segments"])
        and bool(image["sections"]),
        "incomplete native ELF",
    )
    return (row["elf"]["sha256"], tuple(names), row["list_sha"])


def invalid(folder):
    v = inputs.load(folder / "invocation.json")
    c.require(
        v["status"] == 101 and v["source"] == c.GUARD_FILE and v["command"] == c.CLI,
        "invalid source/exit",
    )
    msgs = [
        json.loads(x) for x in gzip.decompress((folder / "stdout.jsonl.gz").read_bytes()).splitlines()
    ]
    c.require(msgs[-1] == {"reason": "build-finished", "success": False}, "failed build terminal")
    (err,) = [
        x["message"]
        for x in msgs
        if x["reason"] == "compiler-message" and x["message"]["level"] == "error"
    ]
    (span,) = [s for s in err["spans"] if s["is_primary"]]
    c.require(
        err["code"]["code"] == "E0308"
        and span["file_name"] == c.GUARD_FILE
        and any(c.GUARD.strip().decode() in t["text"] for t in span["text"]),
        "wrong failure",
    )
    return [
        err["code"]["code"],
        err["message"],
        span["file_name"],
        span["line_start"],
        span["column_start"],
    ]


def audit_metadata(out, phase, raw, root, products, seen):
    def content(key, expected):
        if key not in seen:
            data = gzip.decompress((out / "metadata-cas" / (key + ".gz")).read_bytes())
            c.require(hashlib.sha256(data).hexdigest() == key, "corrupt CAS")
            seen[key] = (len(data), data if len(data) <= 1024 else None)
        c.require(seen[key][0] == expected, "incorrect original size")
        return seen[key][1]

    closure = inputs.load(phase / "work-products.json.gz")
    c.require(
        len({(o["dev"], o["ino"]) for g in closure.values() for o in g["objects"].values()})
        == sum(c.EIGHT.values()),
        "aliased native object names",
    )
    for n, group in closure.items():
        c.require(n in c.EIGHT and len(group["objects"]) == c.EIGHT[n], "wrong CGU owner")
        m = group["meta"]
        expected = {
            "cargo",
            "metadata.rmeta",
            "ohm-build-metadata.rmeta",
            "metadata-prefix-v3.ohm-prefix-v3",
            "ohm-build-metadata-prefix-v3.ohm-prefix-v3",
        }
        c.require(
            set(m) == expected
            and m["cargo"]["path"] == str(Path(products[n]).relative_to(root / "slot")),
            "wrong typed carrier",
        )
        session = PurePosixPath(group["session"])
        c.require(
            session.name.startswith("s-")
            and session.parts[:3] == ("target", "debug", "incremental")
            and session.parent.name.startswith(n + "-")
            and not session.name.endswith("-working"),
            "wrong incremental owner",
        )
        for label, r in m.items():
            c.require(
                label == "cargo" or PurePosixPath(r["path"]) == session / label,
                "wrong work product path",
            )
            content(r["sha256"], r["size"])
        for keys in [
            ("cargo", "metadata.rmeta", "ohm-build-metadata.rmeta"),
            ("metadata-prefix-v3.ohm-prefix-v3", "ohm-build-metadata-prefix-v3.ohm-prefix-v3"),
        ]:
            c.require(
                len({(m[k]["dev"], m[k]["ino"], m[k]["sha256"], m[k]["size"]) for k in keys}) == 1,
                "wrong hardlink-group identity",
            )
        c.require(
            all(
                PurePosixPath(o["path"]) == session / name and len(o["sha256"]) == 64 and o["size"] > 0
                for name, o in group["objects"].items()
            ),
            "native members",
        )
    if (phase / "workspace-headers.json.gz").exists():
        all_headers = inputs.load(phase / "workspace-headers.json.gz")
        declared = {}
        for a in map(json.loads, raw.splitlines()):
            if a["reason"] != "compiler-artifact" or not Path(a["target"]["src_path"]).is_relative_to(
                root / "ruff/crates"
            ):
                continue
            for file in a["filenames"]:
                if file.endswith(".rmeta"):
                    declared[str(Path(file).relative_to(root / "slot"))] = (
                        a["target"]["name"],
                        str(Path(a["target"]["src_path"]).relative_to(root / "ruff")),
                    )
        c.require(
            all_headers.keys() == declared.keys(), "incomplete Cargo-returned header witness set"
        )
        for key, v in all_headers.items():
            c.require((v["target"], v["source"]) == declared[key], ("wrong header owner", key))
            if not v["size"]:
                continue
            head = content(v["header_sha256"], v["header_bytes"])
            chunk = content(v["root_sha256"], v["root_bytes"])
            c.require(
                head[:8] == b"rust\0\0\0\n"
                and int.from_bytes(head[8:16], "little") == v["root_offset"]
                and v["root_bytes"] == min(384, v["size"] - v["root_offset"])
                and head.endswith(v["issuer"].encode())
                and "c79998a5c" in v["issuer"],
                "wrong Rust metadata header",
            )
            if v["target"] in c.EIGHT:
                parent = closure[v["target"]]["meta"]["cargo"]
                c.require(
                    (v["dev"], v["ino"], v["size"], v["sha256"])
                    == (parent["dev"], parent["ino"], parent["size"], parent["sha256"]),
                    "header/full mismatch",
                )
                with gzip.open(out / "metadata-cas" / (v["sha256"] + ".gz"), "rb") as f:
                    c.require(f.read(len(head)) == head, "original header bytes")
                    f.seek(v["root_offset"])
                    c.require(f.read(v["root_bytes"]) == chunk, "original root bytes")
    return closure


def run(out, feature, collector, required_run=None, required_sha=None):
    rec = inputs.load(out / "registration.json")
    ss = inputs.load(out / "selectors.json")
    read = inputs.load
    c.require(
        not (out / "refusal.json").exists()
        and rec["attempt"] == 1
        and rec["head"] == rec["reviewed_head"]
        and rec["orders"] == ["S1", "T", "S2"]
        and rec["argv"] == c.CLI
        and rec["baseline_only"]
        and rec["inputs"] == read(HERE / "sources.json")
        and rec["release_source"] == c.FEATURELESS
        and rec["collector"] == c.COLLECTOR
        and rec["diagnostic_plan"] == inputs.sha(HERE / "PLAN.md")
        and (required_run is None or rec["run"] == required_run)
        and (required_sha is None or rec["head"] == required_sha),
        "unqualified or unexpected registration",
    )
    root = Path(read(out / "environment.json")["cwd"]).parent
    c.require(root.is_absolute() and root.name == "ohm-featureless-e2e", "canonical SDK path")
    c.require(read(out / "graph.json") == sorted(read(out / "graph.json")), "entered graph")
    sdk = read(out / "sdk/actual-installed.json.gz")
    signed = read(out / "sdk/complete-release.json.gz")
    c.signed_closure(signed)
    c.require(
        len(sdk) == len(signed) == 149
        and sdk.keys() == signed.keys()
        and [k for k in sdk if sdk[k] != signed[k]] == ["bin/cargo"]
        and sdk["bin/cargo"]["sha256"]
        == "035e681081683f4141e4c544b8cf9492b73784051e4541c12bb3cbdb73a798a4"
        and sdk["bin/rustc"]["sha256"]
        == "f7663fb7dec7e5c7ea613a85ff1d6e4c00bf97b8c50534f17e5c95cd599712b9"
        and signed["bin/cargo"]["sha256"]
        == "4695ab8e260ba4d6363e42b785c8f410dd79d9255f0313dab6c19e978878f43e",
        "wrong complete signed or strict tools",
    )
    ver = read(out / "sdk/versions.json")
    c.require(
        c.CARGO in ver["cargo"] and c.RUST in ver["rustc"] and c.RUST in ver["rustdoc"],
        "wrong versions",
    )
    c.require(
        ss["rustc"][:2] == [sdk["bin/rustc"][k] for k in ("dev", "ino")], "wrong rustc device/inode"
    )
    wild_name = "lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld/ld.bfd"
    c.require(
        ss["wild"][:2] == [sdk[wild_name][k] for k in ("dev", "ino")]
        and sdk[wild_name]["sha256"]
        == "0d6335808b647d499f3d74993b602e64ff0625206c809bf4913c487eea380cd5",
        "wrong physical signed Wild",
    )
    c.require(
        len({tuple(q[:2]) for q in ss.values()}) == 4
        and set(ss) == {"rustc", "cc", "collect2", "wild"},
        "overlapping selectors",
    )
    refs = {k: native(out, out / "clean" / k, k) for k in ("original", "reversed")}
    seen = {}
    costs = {}
    edges = {}
    programs = {}
    c.require(
        set(refs["original"][1]) - set(refs["reversed"][1]) == {"notebook::cells_after_cell_magic"}
        and set(refs["reversed"][1]) < set(refs["original"][1])
        and refs["original"][0] != refs["reversed"][0],
        "bad clean reference",
    )
    allcases = {}
    enrollment = read(out / "sampling-enrollment.json")
    c.require(enrollment == {"admitted": True}, "missing calibrated native sampling")
    sampling.verify_calibration(out)
    with tempfile.TemporaryDirectory() as tmp:
        study, pmu, topology = support.load_modules(feature, collector, Path(tmp) / "original-ledger")
        pmu.calibration(out / "counter-programs", out, replay=True)
        for lane in ("S1", "T", "S2"):
            prev = None
            mode = "tree" if lane == "T" else "plain"
            for phase, state in c.STATES.items():
                loc = out / lane / phase
                label = lane + "/" + phase
                call = read(loc / "invocation.json")
                c.require(
                    call["argv"] == c.CLI
                    and call["status"] == 0
                    and call["native"][2:] == [mode, *[ss[n][2] for n in topology.ROLES], *c.CLI],
                    "nonregistered command",
                )
                blobs = read(loc / "source.json")
                exp = study.ENROLL["e2e"]["reverse" if state == "reversed" else "original"]
                c.require(
                    {k: None if v is None else v["git"] for k, v in blobs.items()} == exp,
                    "other source edit",
                )
                raw = gzip.decompress((loc / "stdout.gz").read_bytes())
                graph, products = c.typed(raw, root)
                c.require(graph == read(out / "graph.json"), "different typed product graph")
                changed = phase in ("edited", "restored")
                cb = partial(c.classify, root, products, changed)
                x = topology.read(loc / "trace", ss, mode, component=cb)
                if mode == "tree":
                    c.activation_boundaries(loc / "trace", x)
                c.require(x == read(loc / "counts.json"), "reported scope mismatch")
                sampled = enrollment["admitted"] and lane == "T" and changed
                c.require((loc / "sampling-summary.json").exists() == sampled, "partial or unexpected profile")
                if sampled:
                    sampling.verify(loc, x)
                prog = native(out, loc, state)
                c.require(prog == refs[state], "stale or inconsistent native program")
                snap = audit_metadata(out, loc, raw, root, products, seen)
                if prev is not None:
                    edges[label] = inputs.compare(prev, snap, changed)
                prev = snap
                costs[label] = x
                programs[label] = prog[0]
                c.require(
                    (loc / "workspace-headers.json.gz").exists() == (lane == "T"),
                    "missing receiver input header captures",
                )
        for n in ("populated", "empty"):
            c.require(
                native(out, out / "repair" / n, "original") == refs["original"], "failed source repair"
            )
        es = {n: invalid(out / "invalid" / n) for n in ("populated", "empty")}
        c.require(es["populated"] == es["empty"], "different E0308")
        sem = read(out / "semantics.json")
        c.require(
            sem["edges"] == edges and sem["invalid"] == es and not sem["behavior_failures"],
            "bad semantic projection",
        )
    for k in ("edited", "restored"):
        x = costs["T/" + k]
        allcases[k] = c.ceiling(
            x["whole"], costs["S1/" + k]["whole"], costs["S2/" + k]["whole"], x["eight_inclusive"]
        )
    result = read(out / "result.json")
    verdict = (
        "below-2x"
        if any(x["outcome"] == "below-2x" for x in allcases.values())
        else "room-for-investigation"
        if all(x["outcome"] == "room-for-investigation" for x in allcases.values())
        else "unresolved"
    )
    c.require(
        result
        == {
            "baseline_instruction_ceiling": allcases,
            "boot": rec["boot"],
            "diagnostic_verdict": verdict,
            "product_speedup": None,
        },
        "reported outcome mismatch",
    )
    c.require(
        {p.name for p in (out / "metadata-cas").iterdir()} == {h + ".gz" for h in seen},
        "unwitnessed CAS file",
    )
    for key in {r[0] for r in refs.values()}:
        path = out / "native-programs" / (key + ".zst")
        with subprocess.Popen(["zstd", "-qdc", path], stdout=subprocess.PIPE) as proc:
            h = hashlib.file_digest(proc.stdout, "sha256").hexdigest()
            c.require(proc.wait() == 0 and h == key, "incomplete archived ELF")
    products = heavy.reopen(out)
    c.require(products == read(out / "heavy-result.json"), "heavy object histories differ from originals")
    return {
        "qualified_baseline_feasibility": True,
        "run": rec["run"],
        "head": rec["head"],
        "boot": rec["boot"],
        "cargo_visits_with_pmu": len(costs),
        "native_members_per_edit": sum(c.EIGHT.values()),
        "cas_members": len(seen),
        "outcome": result,
        "heavy_products": products,
        "native_sample_enrollment": enrollment,
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("receipt", type=Path)
    for n in ("feature", "collector"):
        ap.add_argument("--" + n, type=Path, required=True)
    ap.add_argument("--zip-sha256")
    ap.add_argument("--run", type=int)
    ap.add_argument("--head")
    a = ap.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        out = a.receipt.resolve()
        if out.is_file():
            c.require(
                a.run and a.head and a.zip_sha256 and inputs.sha(out) == a.zip_sha256,
                "original ZIP identity required",
            )
            with zipfile.ZipFile(out) as z:
                members = z.infolist()
                c.require(
                    len(members) == len(set(z.namelist()))
                    and sum(f.file_size for f in members) < 1800 * 2**20
                    and all(
                        not PurePosixPath(f.filename).is_absolute()
                        and ".." not in PurePosixPath(f.filename).parts
                        for f in members
                    ),
                    "unsafe ZIP members",
                )
                z.extractall(tmp)
            out = Path(tmp)
        print(
            json.dumps(
                run(out, a.feature.resolve(), a.collector.resolve(), a.run, a.head),
                indent=2,
                sort_keys=True,
            )
        )
