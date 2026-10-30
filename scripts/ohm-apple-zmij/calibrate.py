import argparse
import json
import re
import statistics
import subprocess
import sys
from pathlib import Path

from study import check_host, digest, need, run, save, sha

BURN = r"""
#include <stdio.h>
#include <stdlib.h>
#include <sys/wait.h>
#include <unistd.h>
int main(int argc, char **argv) {
    if (argc != 3) return 10;
    int d = atoi(argv[1]); unsigned long long n = strtoull(argv[2], 0, 10);
    if (d) {
        pid_t c = fork(); int status; char depth[16];
        if (c < 0) return 11;
        if (!c) {
            snprintf(depth, sizeof(depth), "%d", d-1);
            execl(argv[0], argv[0], depth, argv[2], NULL); _exit(12);
        }
        if (waitpid(c, &status, 0) != c || !WIFEXITED(status)) return 13;
        return WEXITSTATUS(status);
    }
#if defined(__aarch64__)
    if (n) __asm__ volatile("1: subs %0, %0, #1\nb.ne 1b" : "+r"(n) : : "cc");
#else
    return 14;
#endif
    return 0;
}
"""


def fields(output):
    result = {}
    lines = output.splitlines()
    for line in lines:
        if m := re.fullmatch(r"\s*(\d+)\s+instructions retired\s*", line):
            result["instructions"] = int(m[1])
        if m := re.fullmatch(r"\s*([\d.]+) real\s+([\d.]+) user\s+([\d.]+) sys\s*", line):
            result.update(wall=float(m[1]), user=float(m[2]), system=float(m[3]))
        if m := re.fullmatch(r"\s*(real|user|sys)\s+([\d.]+)\s*", line):
            result[{"real": "wall", "user": "user", "sys": "system"}[m[1]]] = float(m[2])
    need("user" in result and "system" in result, "unknown Darwin /usr/bin/time output")
    return result


def classify(rows, iters):
    deltas, cpu = {}, {}
    for depth in range(3):
        bucket = [r for r in rows if r["depth"] == depth]

        def diff(k):
            if any(k not in r for r in bucket):
                return None
            return statistics.median(r[k] for r in bucket if r["iters"]) - statistics.median(
                r[k] for r in bucket if not r["iters"]
            )

        deltas[str(depth)] = diff("instructions")
        cpu[str(depth)] = diff("user")
    expected = 2 * iters
    plausible = lambda value: value is not None and 0.90 * expected <= value <= 1.1 * expected
    all_levels = all(plausible(d) for d in deltas.values())
    parent_only = plausible(deltas["0"]) and all(
        v is not None and abs(v) <= expected * 0.05 for v in (deltas["1"], deltas["2"])
    )
    status = (
        "whole-tree-calibrated"
        if all_levels
        else ("direct-process-only" if parent_only else "unavailable-or-inconclusive")
    )
    cpu_ok = cpu["0"] is not None and cpu["0"] >= 0.01 and all(v >= cpu["0"] * 0.45 for v in cpu.values())
    return {
        "retired_instruction_scope": status,
        "tree_CPU_calibrated": cpu_ok,
        "expected_delta": expected,
        "retired_deltas": deltas,
        "user_seconds_deltas": cpu,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("out", type=Path)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True)
    host = check_host(out)
    code = out / "burn.c"
    code.write_text(BURN)
    exe = out / "burn"
    run(["xcrun", "clang", "-O2", str(code), "-o", str(exe)])
    iters = 200_000_000
    rows = []
    for rep, counts in enumerate(([0, iters], [iters, 0], [0, iters])):
        for depth in (0, 1, 2) if rep != 1 else (2, 1, 0):
            for n in counts:
                log = out / f"time-{rep}-{depth}-{n}.txt"
                run(["/usr/bin/time", "-l", "-o", str(log), str(exe), str(depth), str(n)])
                rows.append(dict(depth=depth, iters=n, rep=rep, time_raw=sha(log), **fields(log.read_text())))
    result = {
        "host": host,
        "toy": sha(exe),
        "source": digest(BURN.encode()),
        "rows": rows,
        **classify(rows, iters),
    }
    save(out / "result.json", result)
    print(
        json.dumps(
            {k: result[k] for k in ("retired_instruction_scope", "tree_CPU_calibrated", "retired_deltas")}
        )
    )


if __name__ == "__main__":
    main()
