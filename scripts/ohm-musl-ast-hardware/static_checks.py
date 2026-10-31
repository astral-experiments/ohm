"""Exercise window boundaries, native archive/diagnostic/storage integrity and parent reader without acquiring PMU."""

import argparse
import gzip
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
from types import SimpleNamespace
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import clocked as c, measure, products, ingress, reopen
from clocked import require, sha, file_sha


def rejects(fn):
    try:
        fn()
    except (RuntimeError, ValueError, AssertionError, FileNotFoundError, KeyError):
        return
    raise AssertionError("negative control accepted")


def observations(signed, archive_results):
    original = json.loads(archive_results.read_bytes())
    signed_input = original["inputs"]
    states = {}
    graph = {}
    for phase in ("old-cold", "edited", "first", "settled"):
        msg = [
            json.loads(x)
            for x in gzip.decompress((signed / "raw" / f"{phase}.stdout.gz").read_bytes()).splitlines()
        ]
        graph[phase] = products.product(msg)[0]
        stale = {"reason": "compiler-message", "message": {"level": "error"}}
        rejects(lambda: products.product([*msg[:-1], stale, msg[-1]]))
        rejects(lambda: products.product(msg[:-1]))
        if phase == "first":
            continue
        raw = gzip.decompress((signed / "data" / (signed_input[phase]["sha256"] + ".gz")).read_bytes())
        require(sha(raw) == signed_input[phase]["sha256"], phase)
        rec = products.normalized_archive(raw)
        require(len(rec["ordered_objects"]) == original["retained"][phase]["members"] - 4, phase)
        states[phase] = rec
        if phase == "edited":
            source = json.loads((signed / "result.json").read_bytes())["rows"]["edited"]["client"]
            m = gzip.decompress((signed / "data" / (source["input_rmeta"]["sha256"] + ".gz")).read_bytes())
            images = {}

            def memory_body(_, data):
                digest = sha(data)
                images[digest] = data
                return digest

            with tempfile.TemporaryDirectory() as fixture:
                dest = Path(fixture) / "visit"
                dest.mkdir()
                with mock.patch.object(products, "store_body", memory_body):
                    products.preserve_archive(raw, dest, m)
                manifest = json.loads((dest / "ar-replay.json").read_bytes())
                require(
                    reopen.archive_bytes(manifest, images.__getitem__) == raw
                    and images[manifest["separate_rmeta"]] == m,
                    "portable raw archive and independent physical rmeta",
                )
                rejects(lambda: reopen.archive_bytes(manifest, lambda d: images[d] + b"corruption"))
            name, head, obj = next(r for r in products.member_readback.archive(raw) if r[0].endswith(".rcgu.o"))
            start = raw.index(obj)
            mutant = bytearray(raw)
            mutant[start + 74] ^= 1
            corrupt = products.normalized_archive(bytes(mutant))
            require(
                corrupt["complete_canonical_sha256"] != rec["complete_canonical_sha256"]
                and [q for q, p in zip(corrupt["ordered_objects"], rec["ordered_objects"]) if q != p],
                "modified native code accepted",
            )
            salt = rec["salt"].encode()
            rejects(lambda: products.normalized_archive(raw.replace(salt, b".zzzzzzz.rcgu.o", 1)))
    old = states["old-cold"]
    edited = states["edited"]
    repeat = states["settled"]
    require(
        old["complete_canonical_sha256"]
        != edited["complete_canonical_sha256"]
        == repeat["complete_canonical_sha256"]
        and edited["raw"] != repeat["raw"]
        and sum(l != r for l, r in zip(old["ordered_objects"], edited["ordered_objects"])) == 2,
        "wrong old/edited/settled separation",
    )
    return {
        "typed": {p: [v["count"], len(v["dirty"])] for p, v in graph.items()},
        "old_edited_native_objects_changed": 2,
        "same_source_objects": len(edited["ordered_objects"]),
        "portable_entire_edited_archive_and_separate_rmeta": True,
        "original_archive_hashes": {p: s["raw"] for p, s in states.items()},
        "entire_archive_canonical": {p: s["complete_canonical_sha256"] for p, s in states.items()},
    }


def own_fs(d):
    target = d / "target"
    shared = d / "shared"
    for n in (target, shared):
        n.mkdir()
    data = target / "one.o"
    data.write_bytes(b"private object")
    os.link(data, shared / "alias.o")
    (shared / "duplicate.o").write_bytes(data.read_bytes())
    (shared / "link.o").symlink_to("alias.o")
    with (shared / "sparse").open("xb") as f:
        f.seek(1024 * 1024)
        f.write(b"!")
    stored = products.ledger(d, d)
    require(
        stored["hardlink_aliases"] == 1
        and stored["physical_payloads"] == {".o": 2}
        and list(stored["exact_duplicate_payloads"].values()) == [2]
        and stored["allocated_unique"] < 128 * 1024,
        "physical ledger control",
    )
    rows = json.loads(gzip.decompress((d / "allocated-inodes.json.gz").read_bytes()))
    require(
        len(rows) == 7
        and {r[0] for r in rows}
        == {
            "target",
            "shared",
            "target/one.o",
            "shared/alias.o",
            "shared/duplicate.o",
            "shared/link.o",
            "shared/sparse",
        },
        rows,
    )
    rec = {role: {"storage": {k: stored.copy() for k in ("warm", "empty")}} for role in "PC"}
    measure.storage_gate(rec)
    rec["C"]["storage"]["warm"]["physical_payloads"] = {".o": 3}
    rejects(lambda: measure.storage_gate(rec))
    return {
        k: stored[k]
        for k in (
            "allocated_unique",
            "unique_inodes",
            "hardlink_aliases",
            "physical_payloads",
            "exact_duplicate_payloads",
        )
    }


def saved_counter(d, sources):
    # This calibration was actually acquired by a prior Linux x86_64 PMU study; the synthetic artifact command is only used to
    # exercise ordering/formatting and is never hardware evidence about a musl build.
    def add(relative, raw):
        out = d / relative
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(raw)

    with subprocess.Popen(["zstd", "-qdc", sources], stdout=subprocess.PIPE) as proc:
        with tarfile.open(fileobj=proc.stdout, mode="r|") as ar:
            count = 0
            for m in ar:
                if not m.isfile() or "/calibration/" not in m.name:
                    continue
                rest = m.name.split("/calibration/", 1)[1]
                if rest not in {"summary.json", *(f"{i}.json" for i in range(28))}:
                    continue
                add("calibration/" + rest, ar.extractfile(m).read())
                count += 1
        require(proc.wait() == 0 and count == 29, "missing original calibration")
    return {p.name: file_sha(p) for p in (d / "calibration").iterdir()}


def window(d, role, fail_at=None):
    arm = d / role
    arm.mkdir()
    numer = 0

    def invoke(cmd, cwd, env, stdout, stderr, timeout):
        nonlocal numer
        n = numer
        numer += 1
        require(n == 0 or n == 1, "extra call")
        phase = c.PHASES[n]
        require(
            Path(cmd[1]) == arm / phase / "clock.json"
            and cmd[2:] == c.CMD
            and str(cmd[0]) == "/not-a-real-perf-tracer",
            "ordinary argv changed",
        )
        require(
            stdout.name == str(arm / phase / "stdout.raw") and stderr.name == str(arm / phase / "stderr.raw"),
            "stream paths",
        )
        require(
            (arm / "repeat" / "stderr.raw").exists() and (arm / "repeat" / "stdout.raw").exists(),
            "next streams were not preopened",
        )
        require(
            not (arm / "clocked-commands.json").exists() and not (arm / "edit/streams.json").exists(),
            "interposed parse",
        )
        if n == 0:
            guarded.__enter__()
        else:
            guarded.__exit__(None, None, None)
        if n == fail_at:
            stdout.write(b"deliberate invalid command\n")
            return SimpleNamespace(returncode=101)
        ticks = {
            "event_errno": 0,
            "code": 0,
            "instructions": 1000001 + n,
            "running": 9999,
            "enabled": 10000,
            "start": 10000 * n + 1,
            "stop": 10000 * n + 11,
            "user_us": 5,
            "system_us": 1,
        }
        c.save(arm / phase / "clock.json", ticks)
        stdout.write(b'{"synthetic":1}\n')
        stderr.write(b"ordinary simulator stderr\n")
        return SimpleNamespace(returncode=0)

    guarded = mock.patch.object(
        Path, "read_bytes", side_effect=RuntimeError("reading any bytes between commands")
    )
    if fail_at == 0:
        try:
            rejects(lambda: c.consecutive(Path("/not-a-real-perf-tracer"), arm, {}, d, runner=invoke))
        finally:
            guarded.__exit__(None, None, None)
        require(numer == 1, "ran a repeat after failed edit")
        return
    out = c.consecutive(Path("/not-a-real-perf-tracer"), arm, {}, d, runner=invoke)
    require(numer == 2 and list(out) == list(c.PHASES), "command count")
    for phase in c.PHASES:
        for mutation in ({"running": 900}, {"event_errno": 1}, {"code": 101}, {"instructions": 0}):
            rejects(lambda: c.check_clock(out[phase]["clock"] | mutation))


def trace_cases(d):
    path = d / "traces.gz"

    def archive(line):
        with tarfile.open(path, "w:gz") as ar:
            hd = tarfile.TarInfo("proc.37")
            hd.size = len(line)
            ar.addfile(hd, io.BytesIO(line))

    archive(b'execve("/known/cargo", ["cargo"], 0) = 0\n+++ exited with 0 +++\n')
    products.complete_execs(path)
    for bad in (b'execve("/known/rustc", [], 0 <unfinished ...>\n', b"<... execve resumed>) = 0\n"):
        archive(bad)
        rejects(lambda: products.complete_execs(path))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("signed", type=Path)
    parser.add_argument("archives", type=Path)
    parser.add_argument("historical_counter", type=Path)
    parser.add_argument("root_reader", type=Path)
    a = parser.parse_args()
    from importlib.util import spec_from_file_location, module_from_spec

    spec = spec_from_file_location("readonly_root_analyzer", a.root_reader)
    reader = module_from_spec(spec)
    spec.loader.exec_module(reader)
    summary = {
        "evidence": "offline controls only. No new compiler, native instruction, or timing measurement.",
        "signed": observations(a.signed, a.archives),
        "historical_counter_artifact": file_sha(a.historical_counter),
    }
    with tempfile.TemporaryDirectory() as t:
        root = Path(t)
        f = root / "ledger"
        f.mkdir()
        summary["storage_fixture"] = own_fs(f)
        trace_cases(root)
        fail = root / "invalid-prefix"
        fail.mkdir()
        window(fail, "P", 0)
        for pos, order in enumerate(c.assignment(HERE, "screen"), 1):
            where = root / order
            where.mkdir()
            chrono = saved_counter(where, a.historical_counter)
            reader.calibration(lambda p: (where / p).read_text())
            for role in order:
                window(where, role)
                for key in ("terminal", "role"):
                    c.save(where / role / (key + ".json"), {"synthetic": True})
            c.save(where / "pair.json", {"position": pos, "order": order, "hardware": False, "synthetic": True})
            for filename in ("host.json", "admission.json", "tools/identity.json"):
                c.save(where / filename, {"synthetic": True})
            packed = c.pack(where, pos)
            envelope = json.loads(subprocess.check_output(["zstd", "-qdc", packed]))
            read = lambda p: envelope["musl-measurements/" + p]
            reader.calibration(read)
            for role in order:
                for phase in c.PHASES:
                    require(reader.hw(json.loads(read(f"{role}/{phase}/clock.json"))) > 0, "root reader format")
                    s = json.loads(read(f"{role}/{phase}/streams.json"))
                    require(
                        s["stdout"]["sha256"] == sha(read(f"{role}/{phase}/stdout.raw").encode()), "lossy pack"
                    )
            require(len(chrono) == 29, "missing calibration")
        for phase in ("screen", "primary", "independent"):
            if ingress.FROZEN[phase] is None:
                rejects(lambda: ingress.admitted(HERE, phase))
            else:
                enrollment, certificate = ingress.admitted(HERE, phase)
                require(enrollment[phase] and certificate["passed"], "admitted phase must reopen")
    summary["synthetic_windows"] = [
        "PC",
        "CP",
        "failed edit suppresses repeat",
        "no intermediate reads",
        "raw bytes reconstructed",
    ]
    summary["real_prior_calibration"] = {
        "originals": 28,
        "direct_child_grandchild_exec_thread": True,
        "root_reader_sha256": file_sha(a.root_reader),
    }
    print(json.dumps(summary, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
