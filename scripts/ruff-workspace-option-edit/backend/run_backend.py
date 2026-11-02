"""Independently price LLVM IR optimization and machine emission after the ordinary Ruff study."""

import argparse
import gzip
import hashlib
import json
import os
import re
import struct
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
LIB = "lib/libLLVM.so.23.1-rust-1.99.0-beta"
LIB_SHA = "43bac9749e539cd5988a4d5452b64582cf07ac9e7c059fde29c7bee76e106c51"
ARMS = ("normal", "lean", "fast", "both")
MIB = 1 << 20


def sha(data):
    return hashlib.sha256(data).hexdigest()


def digest(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def save(path, data):
    with path.open("xb") as f:
        f.write(data)


def put(path, obj):
    save(path, (json.dumps(obj, indent=2, sort_keys=True) + "\n").encode())


def get(path):
    return json.loads(path.read_bytes())


def require(ok, message):
    if not ok:
        raise ValueError(message)


def elf(data):
    require(
        data[:7] == b"\x7fELF\x02\x01\x01"
        and struct.unpack_from("<H", data, 18)[0] == 62,
        "expected GNU x86-64 object",
    )
    off = struct.unpack_from("<Q", data, 40)[0]
    ent, n, strings = struct.unpack_from("<HHH", data, 58)
    require(
        ent == 64 and 0 < strings < n and off + n * ent <= len(data),
        "invalid section table",
    )

    def header(i):
        return struct.unpack_from("<IIQQQQIIQQ", data, off + i * ent)

    st = header(strings)
    names = data[st[4] : st[4] + st[5]]
    sections = []
    for i in range(n):
        s = header(i)
        name = names[s[0] : names.index(b"\0", s[0])].decode()
        require(s[1] == 8 or s[4] + s[5] <= len(data), "section exceeds object")
        sections.append([name, s[2], s[5]])
    return {
        "sha256": sha(data),
        "bytes": len(data),
        "text": sum(size for _, flags, size in sections if flags & 4),
        "debug": sum(size for name, _, size in sections if name.startswith(".debug")),
        "sections": sections,
    }


def select(old, warm, empty, accepted):
    require(
        set(warm) == set(accepted["warm_rebuilt_keys"]) and warm,
        "missing admitted Ruff compile",
    )
    pool = {}
    for key, value in warm.items():
        d = value["sha256"]
        size = value["stat"][2]
        require(
            re.fullmatch("[a-f0-9]{64}", d) and isinstance(size, int) and size > 0,
            "invalid input descriptor",
        )
        if key not in empty or empty[key]["sha256"] != d:
            continue
        if size > 6 * MIB:
            continue
        kind = "changed" if key not in old or old[key]["sha256"] != d else "same"
        pool.setdefault(kind, []).append((size, key))
    output = {}
    for kind, members in sorted(pool.items()):
        v = sorted(members)
        for label, rank in (
            ("smallest", 0),
            ("median", (len(v) - 1) // 2),
            ("largest", -1),
        ):
            size, key = v[rank]
            if key not in output:
                output[key] = {
                    "reason": kind + "-" + label,
                    "old": old.get(key),
                    "warm": warm[key],
                    "empty": empty[key],
                }
    require(
        bool(output) and len(output) <= 6,
        "no agreed warm/empty LLVM inputs within the size cap",
    )
    return output


def subprocess_ok(cmd, env=None):
    proc = subprocess.run(
        cmd,
        env=env,
        capture_output=True,
        stdin=subprocess.DEVNULL,
        timeout=100,
        check=False,
    )
    if proc.returncode:
        raise ValueError((list(map(str, cmd)), proc.returncode, proc.stderr[-2000:]))
    return proc.stdout, proc.stderr


CONTROL_RUST = b"""#![no_std]
#[unsafe(no_mangle)]
pub extern "C" fn ohm_fold(mut value: u64, mut n: u64) -> u64 {
    while n != 0 {
        value = if value & 1 == 0 { value.rotate_left(7).wrapping_add(n) }
                else { value.wrapping_mul(0x9e3779b1).rotate_right(3) };
        n = n.wrapping_sub(1);
    }
    value
}
"""
CONTROL_C = b"""#include <stdint.h>
#include <inttypes.h>
#include <stdio.h>
extern uint64_t ohm_fold(uint64_t,uint64_t);
int main(void) {
  uint64_t x[]={0,1,2,0xfedcba9876543210ULL,~0ULL};
  uint64_t n[]={0,1,2,7,29,91};
  for(unsigned i=0;i<5;i++)for(unsigned j=0;j<6;j++)
    printf("%016" PRIx64 "\\n",ohm_fold(x[i],n[j]));
  return 0;
}
"""


def oracle():
    mask = (1 << 64) - 1

    def value(x, n):
        while n:
            if x & 1:
                x = x * 0x9E3779B1 & mask
                x = (x >> 3) | (x << 61) & mask
            else:
                x = (((x << 7) & mask) | (x >> 57)) + n & mask
            n -= 1
        return x

    return "".join(
        f"{value(x, n):016x}\n"
        for x in (0, 1, 2, 0xFEDCBA9876543210, mask)
        for n in (0, 1, 2, 7, 29, 91)
    ).encode()


def size_checked(desc, directory, out):
    size = desc["stat"][2]
    key = desc["sha256"]
    with gzip.open(directory / (key + ".gz"), "rb") as f:
        raw = f.read(size + 1)
    require(
        len(raw) == size and raw.startswith(b"BC\xc0\xde") and sha(raw) == key,
        "wrong raw Ruff bitcode",
    )
    save(out, raw)


def study(base, work, results):
    logs = base / "logs"
    accepted = get(logs / "accepted.json")
    require(accepted["new_compiler_treatments"] == 0, "ordinary receipt required")

    def emitted(location):
        return get(logs / location / "cgus.json")["ruff_workspace"]["emitted"]

    selected = select(
        emitted("capture/old"),
        emitted("capture/new"),
        emitted("capture-empty/new"),
        accepted,
    )
    work.mkdir()
    results.mkdir()
    lib = base / "home/.rustup/toolchains/ohm" / LIB
    require(digest(lib) == LIB_SHA, "unexpected LLVM DSO")
    version = (logs / "rustc.version").read_text()
    require(
        "008a21ac0d750dc9a1c18b7959d7e7984c03d887" in version,
        "unexpected packaged compiler",
    )
    cpus = sorted(os.sched_getaffinity(0))
    require(cpus, "missing allowed CPUs")
    os.sched_setaffinity(0, {cpus[len(cpus) // 2]})
    paths = {}
    enrolled = {}
    for index, (key, desc) in enumerate(sorted(selected.items())):
        token = f"ruff-{index:02d}"
        p = work / (token + ".bc")
        size_checked(desc["warm"], logs / "cgu-originals", p)
        paths[token] = p
        enrolled[token] = {"module": key, **desc}
    env = get(logs / "environment.json")
    src = work / "control.rs"
    cc = work / "control.c"
    bc = work / "control.bc"
    save(src, CONTROL_RUST)
    save(cc, CONTROL_C)
    subprocess_ok(
        [
            "rustc",
            "+ohm",
            "--edition=2024",
            "--crate-name",
            "ohm_control",
            "--crate-type=lib",
            "-Copt-level=1",
            "-Cdebuginfo=line-tables-only",
            "-Cpanic=abort",
            "-Cno-prepopulate-passes",
            "--emit",
            "llvm-bc",
            "-o",
            bc,
            src,
        ],
        env,
    )
    paths["control"] = bc
    probe = work / "measure"
    subprocess_ok(
        [
            "cc",
            "-std=c11",
            "-O2",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-DNATIVE_PMU",
            HERE / "probe.c",
            "-ldl",
            "-o",
            probe,
        ]
    )
    first = [
        (token, arm, phase)
        for token in ("control", *sorted(enrolled))
        for arm in ARMS
        for phase in ("ir", "obj")
    ]
    order = [
        ("control", "normal", "sham"),
        ("control", "normal", "cal"),
        *first,
        *first[::-1],
        ("control", "normal", "cal"),
        ("control", "normal", "sham"),
    ]
    registration = {
        "source": digest(HERE / "probe.c"),
        "receiver": digest(Path(__file__)),
        "probe": digest(probe),
        "llvm": LIB_SHA,
        "accepted": digest(logs / "accepted.json"),
        "source_version": version,
        "cpu": list(os.sched_getaffinity(0)),
        "selected": enrolled,
        "control_bc": digest(bc),
        "control_rust": sha(CONTROL_RUST),
        "control_c": sha(CONTROL_C),
        "control_output": sha(oracle()),
        "order": order,
        "initial_input_sha": {k: digest(p) for k, p in paths.items()},
    }
    put(results / "registered.json", registration)
    put(
        results / "source-files.json",
        {
            "probe.c": (HERE / "probe.c").read_text(),
            "run_backend.py": Path(__file__).read_text(),
        },
    )
    store = results / "objects"
    store.mkdir()
    rows = []
    seen_objs = {}
    for i, (token, arm, phase) in enumerate(order):
        out = work / "last.o"
        tag = str(i)
        proc, err = subprocess_ok([probe, lib, paths[token], out, arm, phase, tag])
        require(not err, ("unexpected LLVM diagnostics", token, arm, err[:300]))
        count = re.fullmatch(
            rb"PMU instructions (\d+) enabled (\d+) running (\d+)\nLLVM inode (\d+)/(\d+) object (\d+) input (\d+) calibration (\d+) tag (\d+)\n",
            proc,
        )
        require(count is not None, "missing physical clocks")
        ir, enabled, running, dev, ino, sz, insz, cal, ix = map(int, count.groups())
        require(
            (dev, ino) == (lib.stat().st_dev, lib.stat().st_ino)
            and ix == i
            and insz == paths[token].stat().st_size,
            "mismatched native actor",
        )
        require(
            running == enabled > 0 and cal == (5000050000 if phase == "cal" else 0),
            "partial counter or failed calibration",
        )
        info = elf(out.read_bytes())
        require(sz == info["bytes"], "wrong output size")
        if phase == "sham":
            require(ir < 500, "counter not idle")
        elif phase == "cal":
            require(300000 < ir < 1500000, "counter sensitivity")
        else:
            require(ir > 2000, "empty compiler interval")
        native = seen_objs.setdefault((token, arm), info["sha256"])
        require(native == info["sha256"], "same module/arm emitted a different object")
        raw = store / (native + ".gz")
        if not raw.exists():
            compressed = gzip.compress(out.read_bytes(), compresslevel=2, mtime=0)
            require(
                sum(f.stat().st_size for f in store.iterdir()) + len(compressed)
                <= 70 * MIB,
                "native original cap",
            )
            save(raw, compressed)
        execute = None
        if token == "control":
            exe = work / "oracle-native"
            subprocess_ok(["cc", "-O2", cc, out, "-o", exe])
            body, stderr = subprocess_ok([exe])
            require(
                not stderr and body == oracle(),
                "wrong native arithmetic or control flow",
            )
            execute = {"output": sha(body), "elf": digest(exe), "cases": 30}
        row = {
            "index": i,
            "input": token,
            "arm": arm,
            "stage": phase,
            "instructions": ir,
            "enabled": enabled,
            "running": running,
            "object": info,
            "native": execute,
            "stdout": proc.decode(),
            "stderr": err.decode(),
        }
        rows.append(row)
        put(results / (f"row-{i:03}.json"), row)
    require(
        digest(logs / "accepted.json") == registration["accepted"],
        "ordinary result changed",
    )
    summary = {}
    for token in paths:
        summary[token] = {}
        for arm in ARMS:
            pair = {
                stage: [
                    r["instructions"]
                    for r in rows
                    if (r["input"], r["arm"], r["stage"]) == (token, arm, stage)
                ]
                for stage in ("ir", "obj")
            }
            require(all(len(v) == 2 for v in pair.values()), "missing reversal")
            summary[token][arm] = pair
    put(
        results / "result.json",
        {
            "registration": digest(results / "registered.json"),
            "stages": summary,
            "whole_cargo_treatment_runs": 0,
        },
    )
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("base", type=Path)
    ap.add_argument("work", type=Path)
    ap.add_argument("results", type=Path)
    a = ap.parse_args()
    study(a.base, a.work, a.results)
