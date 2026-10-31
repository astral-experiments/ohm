"""Verify two newly acquired official positions; only then reveal the three test-build ratios."""

import argparse
import ast
import collections
import gzip
import io
import json
import re
from fractions import Fraction
from pathlib import Path
import statistics
import subprocess
import sys
import tarfile
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support as q


def clock(row):
    q.require(
        row["code"] == row["event_errno"] == 0
        and row["instructions"] > 0
        and row["stop"] > row["start"]
        and row["user_us"] + row["system_us"] > 0
        and 0 < row["running"] <= row["enabled"]
        and 1000 * row["running"] >= 995 * row["enabled"],
        "invalid inherited counter",
    )
    return row["instructions"]


def calibration(read):
    summary = json.loads(read("summary.json"))
    shapes = [
        ("0", "1"),
        ("1", "1"),
        ("2", "1"),
        ("2", "2"),
        ("exec", "1"),
        ("thread", "1"),
        ("thread", "2"),
    ]
    q.require(
        summary["whole_tree_hw"] is True and len(summary["rows"]) == 28 and len(summary["checks"]) == 7,
        "incomplete inheritance calibration",
    )
    for i, (depth, copies) in enumerate(shapes):
        x = []
        for j, it in enumerate([0, 80_000_000, 0, 80_000_000]):
            n = 4 * i + j
            raw = read(f"{n}.json")
            x.append(clock(json.loads(raw)))
            q.require(
                summary["rows"][n]
                == {
                    "depth": depth,
                    "copies": copies,
                    "iters": it,
                    "receipt": q.digest(raw),
                    "hardware": True,
                },
                "calibration row",
            )
        delta = statistics.median(x[1::2]) - statistics.median(x[0::2])
        expected = 160_000_000 * int(copies)
        q.require(
            0.98 * expected < delta < 1.02 * expected and summary["checks"][i]["delta"] == delta,
            "calibration response",
        )


def paired_ratios(records):
    q.require(
        len(records) == 2
        and {r["position"] for r in records} == {1, 2}
        and len({r["boot"] for r in records}) == 2
        and all(r["host"] and r["runner"] for r in records)
        and len({r["host"] for r in records}) == 2
        and len({r["runner"] for r in records}) == 2
        and len({(r["run"], r["head"]) for r in records}) == 1,
        "distinct new paired hosts from one authorized dispatch",
    )
    rows = []
    for r in sorted(records, key=lambda x: x["position"]):
        q.require(
            r["order"] == q.REG["screen"]["position_" + str(r["position"])]
            and r["boot"] not in q.REG["screen"]["excluded_boot_ids"],
            "position/boot",
        )
        arm = {
            g: {**r["counts"][g], "edit+repeat": sum(r["counts"][g][p] for p in ("edit", "repeat"))}
            for g in "PC"
        }
        q.require(all(all(v > 0 for v in a.values()) for a in arm.values()), "positive complete counts")
        ratio = {p: Fraction(arm["P"][p], arm["C"][p]) for p in ("edit", "repeat", "edit+repeat")}
        rows.append(
            {
                "position": r["position"],
                "order": r["order"],
                "boot": r["boot"],
                "host": r["host"],
                "runner": r["runner"],
                "counts": arm,
                "ratios": {p: {"exact": str(v), "decimal": float(v)} for p, v in ratio.items()},
            }
        )
    return {
        "primary": "repeat",
        "eligible_to_propose_larger_confirmation": all(
            Fraction(x["ratios"]["repeat"]["exact"]) >= Fraction(9, 5) for x in rows
        ),
        "positions": rows,
    }


def native_trace(raw, kernel, witness, role, phase):
    seen = []
    parents = {}
    threads = {}
    exits = {}
    opaque = set()
    drivers = collections.defaultdict(set)
    subject = witness["physical_subject"]
    driver = subject["driver"]
    q.require(driver["sha256"] == q.REG["roles"]["driver"][role][0], "wrong loaded driver provenance")
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r|gz") as archive:
        tids = set()
        for member in archive:
            m = re.fullmatch(r"pid\.(\d+)", member.name)
            q.require(member.isfile() and m, "raw process file")
            tid = int(m[1])
            q.require(tid not in tids, "duplicate TID")
            tids.add(tid)
            pending = {}
            lines = archive.extractfile(member).read().decode().splitlines()
            for i, line in enumerate(lines):
                stamp, l = line.split(" ", 1)
                q.require(re.fullmatch(r"[0-9]+\.[0-9]+", stamp), "kernel time")
                if l == "???( <unfinished ...>":
                    q.require(
                        i + 2 == len(lines)
                        and lines[-1].endswith(" +++ exited with 0 +++")
                        and not pending,
                        "unclassified native worker",
                    )
                    opaque.add(tid)
                    continue
                q.require(not l.startswith("???("), "unknown detach")
                if l.endswith("<unfinished ...>"):
                    name = l.partition("(")[0]
                    q.require(name not in pending, "double partial")
                    pending[name] = l.removesuffix("<unfinished ...>")
                    continue
                if l.startswith("<... "):
                    name, tail = l[5:].split(" resumed>", 1)
                    l = pending.pop(name) + tail
                m = re.fullmatch(r"(?:clone3?|fork|vfork)\((.*)\)\s+= ([1-9][0-9]*)", l)
                if m:
                    child = int(m[2])
                    q.require(parents.setdefault(child, tid) == tid, "ambiguous physical parent")
                    if "CLONE_THREAD" in m[1]:
                        threads[child] = tid
                if m := re.fullmatch(r"\+\+\+ exited with (\d+) \+\+\+", l):
                    exits[tid] = int(m[1])
                if l.startswith(("execve(", "execveat(")) and re.search(r"\)\s+= 0$", l):
                    m = re.search(r'("(?:[^"\\]|\\.)*"), (\[.*\]), (?:0x[0-9a-f]+|NULL)\b', l)
                    q.require(m, "successful exec syntax")
                    seen.append((tid, ast.literal_eval(m[1]), ast.literal_eval(m[2])))
                if l.startswith(("openat(", "openat2(")) and (
                    m := re.search(r"\)\s+= \d+<([^>]+)>$", l)
                ):
                    if Path(m[1]).name.startswith("librustc_driver-"):
                        drivers[tid].add(m[1])
            q.require(not pending, "unclosed callable")
    triples = lambda rows: collections.Counter((pid, image, tuple(argv)) for pid, image, argv in rows)
    q.require(
        triples(seen) == triples((e["pid"], e["image"], e["argv"]) for e in kernel["all_exec"]),
        "raw complete execs vs returned kernel",
    )
    q.require(
        set(opaque) == {r[0] for r in kernel["opaque_rustc_thread_exits"]},
        "actual unknown-terminal set",
    )

    def in_chain(pid, mapping, end):
        checked = set()
        while pid not in end and pid in mapping:
            q.require(pid not in checked, "cycle")
            checked.add(pid)
            pid = mapping[pid]
        return pid in end

    cargo = {kernel["cargo"]["pid"]}
    compiler = set()
    work = [[], []]
    all_ld = []
    q.require(
        [tid for tid, image, _ in seen if image == subject["cargo"]["path"]] == [kernel["cargo"]["pid"]]
        and exits[kernel["cargo"]["pid"]] == 0,
        "actual successful root Cargo",
    )
    for tid, image, a in seen:
        if (
            image == subject["rustc"]["path"]
            and "--crate-name" in a
            and "--print" not in a
            and any(x.startswith("--emit") for x in a)
        ):
            nm = a[a.index("--crate-name") + 1]
            only = any(x in ("-Zlink-only", "-Zlink-only=yes", "link-only", "link-only=yes") for x in a)
            q.require(
                a[a.index("--target") + 1] == "x86_64-unknown-linux-musl"
                and (nm != "ruff_python_ast" or "--test" in a)
                and in_chain(tid, parents, cargo)
                and exits[tid] == 0
                and driver["path"] in drivers[tid],
                "real target compiler/driver",
            )
            work[int(only)].append(nm)
            compiler.add(tid)
        if (
            re.fullmatch(
                r"(?:[\w-]+-)?ld(?:\.(?:bfd|lld|gold|mold))?|rust-lld|wild(?:-ld)?|mold",
                Path(image).name,
            )
            and "-o" in a
        ):
            all_ld.append((tid, image, a))
    expected = (
        (["compact_str", "ruff_python_ast", "zmij"], [])
        if role == "P"
        else ((["ruff_python_ast"], []) if phase == "edit" else ([], ["ruff_python_ast"]))
    )
    q.require(
        tuple(sorted(x) for x in work) == expected and len(all_ld) == 1, "real expected work vs role"
    )
    pid, image, a = all_ld[0]
    tools = witness["tools"]
    q.require(
        set(tools) == {"cc", "collect2", "ld"} and tools["ld"]["path"] == "/usr/bin/ld",
        "GNU musl output linker",
    )
    physical = dict((key, {p for p, image, _ in seen if image == tools[key]["path"]}) for key in tools)
    q.require(
        all(len(ids) == 1 and exits[next(iter(ids))] == 0 for ids in physical.values())
        and in_chain(pid, parents, physical["collect2"])
        and in_chain(next(iter(physical["collect2"])), parents, physical["cc"])
        and in_chain(next(iter(physical["cc"])), parents, compiler),
        "real cc/collect2/ld descendants",
    )
    q.require(
        image == tools["ld"]["path"]
        and in_chain(pid, parents, compiler)
        and exits.get(pid) == 0
        and re.fullmatch(r"ruff_python_ast(?:-[a-f0-9]+)?", Path(a[a.index("-o") + 1]).name),
        "real descendant target ld",
    )
    for tid in opaque:
        q.require(
            tid not in {i for i, _, _ in seen}
            and tid in threads
            and in_chain(tid, threads, compiler)
            and exits[tid] == 0,
            "unexplained terminal attach",
        )


def allocated(rows):
    """Rebuild the physical payload and duplicate counts from both output trees."""
    unique = {}
    filenames = set()
    kinds, owners = collections.Counter(), collections.Counter()
    digests = collections.Counter()
    for path, device, inode, mode, size, blocks, kind, content in rows:
        q.require(
            path.split("/", 1)[0] in {"target", "shared"} and path not in filenames, "output scope"
        )
        filenames.add(path)
        key = (device, inode)
        identity = (mode, size, blocks, kind, content)
        if key in unique:
            q.require(unique[key] == identity, "inconsistent alias")
            continue
        unique[key] = identity
        if kind is None:
            continue
        q.require(
            kind in {".o", ".rlib", ".rmeta", ".rlink", ".so", "ELF-executable"} and len(content) == 64,
            "unexpected physical product",
        )
        kinds[kind] += 1
        owner = re.sub(r"-[a-f0-9]{16}(?=\.|$)", "-<metadata>", Path(path).name)
        owner = re.sub(r"\.[0-9a-z]{7}(?=\.rcgu\.o$)", ".<invocation>", owner)
        owners[kind + ":" + owner] += 1
        digests[kind + ":" + content] += 1
    return {
        "allocated_unique": sum(value[2] * 512 for value in unique.values()),
        "physical_payloads": dict(kinds),
        "physical_payloads_by_filename": dict(owners),
        "exact_duplicate_payloads": {k: v for k, v in digests.items() if v > 1},
    }


def verified_position(path, sha, prior):
    q.require(q.file_sha(path) == sha, "official ZIP")
    with zipfile.ZipFile(path) as z:
        q.require(z.testzip() is None, "ZIP CRC")
        names = {n for n in z.namelist() if not n.endswith("/")}
        q.require(len(names) == sum(not p.is_dir() for p in z.infolist()), "duplicate ZIP names")

        def one(suffix):
            hit = [n for n in names if n == suffix or n.endswith("/" + suffix)]
            q.require(len(hit) == 1, ("ambiguous/missing", suffix))
            return z.read(hit[0])

        def doc(s):
            return json.loads(one(s))

        raw_manifest = one("POSITION.sha256")
        listed = dict(l.split("  ", 1)[::-1] for l in raw_manifest.decode().splitlines())
        q.require(
            len(listed) == len(names) - 1 and all(q.digest(one(n)) == h for n, h in listed.items()),
            "complete physical packet",
        )
        pair = doc("counts/pair.json")
        host = doc("counts/host.json")
        q.require(
            pair["registration"] == q.REG_SHA
            and pair["argv"] == q.REG["ordinary_argv"]
            and pair["boot_id"] == host["boot_id"]
            and pair["head"] == host["github"]["GITHUB_SHA"]
            and pair["workflow"] == host["github"]["GITHUB_RUN_ID"]
            and int(host["github"]["GITHUB_RUN_ATTEMPT"]) == 1
            and host["github"]["GITHUB_REF_NAME"] == q.REG["ref"],
            "position subject",
        )
        q.require(
            q.AUTHORIZED_CLEARANCE_SHA256
            and pair["clearance"]
            == q.AUTHORIZED_CLEARANCE_SHA256
            == q.digest(one("counts/clearance.json")),
            "unreleased admission",
        )
        calibration(lambda n: one("counts/calibration/" + n))
        values = {}
        native_raw = {}
        common = {}
        allocations = {"warm": {}, "empty": {}}
        fixed = None
        partial = doc("flanks/partial.json")
        q.require(
            partial["role_identity"]["P"]["182_common_inode_map_sha"]
            == partial["role_identity"]["C"]["182_common_inode_map_sha"],
            "common physical SDK",
        )
        for arm in "PC":
            p = f"counts/{arm}/"
            term = doc(p + "terminal.json")
            q.require(
                q.digest(one(p + "terminal.json")) == pair["native_terminal"][arm]
                and term["role"] == arm,
                "complete native arm",
            )
            values[arm] = {}
            clocks = []
            for phase in ("edit", "repeat"):
                base = p + phase + "/"
                v = doc(base + "clock.json")
                values[arm][phase] = clock(v)
                clocks.append(v)
                stdout = one(base + "stdout.raw")
                stderr = one(base + "stderr.raw")
                streams = doc(base + "streams.json")
                q.require(
                    streams
                    == {
                        k: {"bytes": len(s), "sha256": q.digest(s)}
                        for k, s in [("stdout", stdout), ("stderr", stderr)]
                    },
                    "raw clocked streams",
                )
                sig, _ = q.typed(stdout)
                q.require(sig == term["typed"][phase] == prior[arm][phase], "scored typed work")
                mirror = term["native"][phase]
                kernel = doc(p + "kernel-" + phase + "/kernel.json")
                actual = {
                    **mirror["tools"],
                    "rustc": mirror["physical_subject"]["rustc"],
                    "cargo": mirror["physical_subject"]["cargo"],
                }
                q.require(
                    all(v["bytes"] > 0 and v["device"] >= 0 and v["inode"] > 0 for v in actual.values())
                    and actual["ld"]["sha256"] == q.MUSL_LD_SHA256
                    and (fixed is None or fixed == actual),
                    "same physical GCC/collect2/GNU ld/rustc/Cargo",
                )
                fixed = actual
                q.require(
                    q.digest(one(p + "kernel-" + phase + "/kernel.json")) == mirror["kernel_sha256"]
                    and q.digest(one(p + "kernel-" + phase + "/processes.tar.gz"))
                    == mirror["process_tar"]
                    and mirror["typed"] == sig
                    and q.typed(one(p + "kernel-" + phase + "/stdout.raw"))[0] == sig
                    and mirror["elf"] == term["body"]["edit"]
                    and len(kernel["linkers"]) == 1
                    and kernel["linkers"][0]["exit"] == 0
                    and kernel["linkers"][0]["pid"] == mirror["target_ld_pid"]
                    and kernel["status"] == 0,
                    "real mirror/target linker",
                )
                native_trace(
                    one(p + "kernel-" + phase + "/processes.tar.gz"), kernel, mirror, arm, phase
                )
            q.require(clocks[0]["stop"] <= clocks[1]["start"], "overlapping measured programs")
            q.require(
                doc(p + "clocked-commands.json")["argv"] == pair["argv"], "different measured CLI"
            )
            role_cases = {}
            for visit in (
                "old",
                "edit",
                "unchanged",
                "settled",
                "wrong",
                "invalid",
                "repair",
                "empty-new",
                "empty-old",
                "empty-wrong",
                "empty-invalid",
            ):
                base = f"flanks/{arm}/{visit}/"
                v = doc(base + "visit.json")
                revision = q.REG["ruff"]["old" if v["state"] == "old" else "new"]
                empty = visit == "old" or visit.startswith("empty-")
                q.require(
                    v["git_tree"] == revision["tree"]
                    and v["lock_sha"] == revision["cargo_lock_sha256"]
                    and v["source_sha"] == q.CONTROL_SOURCE.get(v["state"], revision["file_sha256"])
                    and v["shared_present"] == v["target_present"] == (not empty),
                    "genuine source and incoming empty state",
                )
                q.require(
                    v["argv"] == pair["argv"]
                    and all(
                        q.digest(gzip.decompress(one(base + t + ".gz"))) == v[t]
                        for t in ("exec", "stdout", "stderr")
                    ),
                    "raw native flank",
                )
                if "program" in v:
                    program = v["program"]
                    state = v["state"]
                    key = {"old": "old", "new": "edit", "wrong": "wrong"}[state]
                    h = program["sha256"]
                    q.require(
                        h == term["body"][key]
                        and program["all"]["exit"] == (101 if state == "wrong" else 0),
                        "whole native behavior",
                    )
                    if h not in native_raw:
                        raw = subprocess.check_output(
                            ["zstd", "-qdc"], input=one("flanks/elf/" + h + ".zst")
                        )
                        q.require(q.digest(raw) == h and len(raw) == program["bytes"], "full ELF bytes")
                        native_raw[h] = len(raw)
                    q.require(
                        q.digest(gzip.decompress(one(base + "native-list.stdout.gz")))
                        == q.REG["source_ordinary_tests"][key],
                        "full inventory",
                    )
                    full = gzip.decompress(one(base + "native-full.stdout.gz"))
                    want = {"old": [49, 0], "edit": [53, 0], "wrong": [52, 1]}[key]
                    q.require(
                        q.digest(full) == program["all"]["stdout"]
                        and re.search(
                            rb"^test result: (?:ok|FAILED)\. %d passed; %d failed;" % tuple(want),
                            full,
                            re.M,
                        ),
                        "full native verdict",
                    )
                    for i, n in enumerate(
                        [
                            "helpers::tests::any_over_stmt_type_alias",
                            *sorted(
                                k
                                for k in program["individual"]
                                if k != "helpers::tests::any_over_stmt_type_alias"
                            ),
                        ]
                    ):
                        raw = gzip.decompress(one(base + f"native-{i}.stdout.gz"))
                        tested = program["individual"][n]
                        selected = int(key != "old" or n == "helpers::tests::any_over_stmt_type_alias")
                        failed = int(
                            key == "wrong"
                            and n == "script::tests::last_closing_delimiter_discards_following_comments"
                        )
                        q.require(
                            q.digest(raw) == tested["stdout"]
                            and [tested["selected"], tested["failed"], tested["exit"]]
                            == [selected, failed, 101 if failed else 0]
                            and re.search(
                                rb"^test result: (?:ok|FAILED)\. %d passed; %d failed;"
                                % (selected - failed, failed),
                                raw,
                                re.M,
                            ),
                            "one exact real test",
                        )
                    role_cases[visit] = h
                else:
                    msgs = [
                        json.loads(l) for l in gzip.decompress(one(base + "stdout.gz")).splitlines()
                    ]
                    [d] = [
                        e["message"]
                        for e in msgs
                        if e["reason"] == "compiler-message"
                        and (e["message"].get("code") or {}).get("code") == "E0308"
                    ]
                    [sp] = [s for s in d["spans"] if s["is_primary"]]
                    q.require(
                        v["exit"] == 101
                        and v["diagnostic"] == term["body"]["E0308"]
                        and d["rendered"] == v["diagnostic"]["rendered"]
                        and msgs[-1] == {"reason": "build-finished", "success": False}
                        and [sp["file_name"], sp["line_start"], sp["byte_start"], sp["byte_end"]]
                        == ["crates/ruff_python_ast/src/script.rs", 300, 9295, 9317],
                        "genuine bad compile",
                    )
            q.require(
                term["body"]["edit"] == term["measured_final"] and len(set(role_cases.values())) == 3,
                "observed changed whole test",
            )
            for label, pref in [("warm", p + "measured-final/"), ("empty", f"flanks/{arm}/empty-new/")]:
                alloc = term["storage"][label]
                raw = one(pref + "allocated-inodes.json.gz")
                records = json.loads(gzip.decompress(raw))
                physical = allocated(records)
                allocations[label][arm] = physical
                q.require(
                    q.digest(raw) == alloc["raw_gzip_sha256"]
                    and q.digest(gzip.decompress(raw)) == alloc["raw_sha256"]
                    and all(physical[k] == alloc[k] for k in physical),
                    "physical allocated storage",
                )
            common[arm] = term["body"]
        for label, arms in allocations.items():
            p, c = arms["P"], arms["C"]
            pcount, ccount = p["physical_payloads"], c["physical_payloads"]
            growth = {k: ccount.get(k, 0) - pcount.get(k, 0) for k in set(pcount) | set(ccount)}
            q.require(
                pair["storage"][label]
                == {
                    "P": p["allocated_unique"],
                    "C": c["allocated_unique"],
                    "physical_payload_count_delta": growth,
                }
                and all(x <= 0 for x in growth.values())
                and all(
                    value <= max(1, p["physical_payloads_by_filename"].get(k, 0))
                    for k, value in c["physical_payloads_by_filename"].items()
                )
                and all(
                    value <= p["exact_duplicate_payloads"].get(k, 1)
                    for k, value in c["exact_duplicate_payloads"].items()
                ),
                "extra physical payload against own empty or warm control",
            )
        q.require(common["P"] == common["C"] and len(native_raw) == 3, "cross-arm native equivalence")
        return {
            "position": pair["position"],
            "order": pair["order"],
            "boot": pair["boot_id"],
            "host": host["host"],
            "runner": host["github"]["RUNNER_NAME"],
            "head": pair["head"],
            "run": pair["workflow"],
            "counts": values,
        }


if __name__ == "__main__":
    a = argparse.ArgumentParser(description=__doc__)
    a.add_argument("--structural-zip", required=True, type=Path)
    a.add_argument("position1", type=Path)
    a.add_argument("official_sha256_1")
    a.add_argument("position2", type=Path)
    a.add_argument("official_sha256_2")
    v = a.parse_args()
    prior = q.archive_oracle(v.structural_zip)
    rows = [
        verified_position(v.position1, v.official_sha256_1, prior),
        verified_position(v.position2, v.official_sha256_2, prior),
    ]
    print(json.dumps(paired_ratios(rows), indent=2, sort_keys=True))
