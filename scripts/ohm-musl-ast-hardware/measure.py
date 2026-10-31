"""Acquire one registered paired whole-Cargo exposure on a fresh private Linux worker."""

import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import clocked as c
import products
from clocked import require, save, file_sha, sha

EXPECTED_ENV = {
    "HOME",
    "PATH",
    "RUSTUP_HOME",
    "RUSTUP_AUTO_INSTALL",
    "CARGO_HOME",
    "CARGO_TARGET_DIR",
    "CARGO_BUILD_BUILD_DIR",
    "CARGO_TERM_COLOR",
    "CARGO_CACHE_AUTO_CLEAN_FREQUENCY",
    "GIT_CONFIG_NOSYSTEM",
    "GIT_CONFIG_GLOBAL",
    "LC_ALL",
    "TZ",
    "CARGO_NET_OFFLINE",
}
LEAVES = {"zmij", "compact_str", "ruff_python_ast"}


def host():
    cpu = Path("/proc/cpuinfo").read_text().split("\n\n")[0]
    boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    require(
        platform.system() == "Linux" and platform.machine() == "x86_64" and len(boot) == 36, "wrong hardware"
    )
    return {
        "host": platform.node(),
        "boot_id": boot,
        "kernel": platform.release(),
        "cpuinfo": cpu,
        "allowed_cpus": sorted(os.sched_getaffinity(0)),
        "github": {
            k: os.environ[k]
            for k in (
                "GITHUB_RUN_ID",
                "GITHUB_SHA",
                "GITHUB_RUN_ATTEMPT",
                "GITHUB_JOB",
                "GITHUB_REPOSITORY",
                "GITHUB_REF_NAME",
                "RUNNER_NAME",
                "RUNNER_ARCH",
                "RUNNER_OS",
            )
        },
    }


def source(r, env, state):
    names = r.call(["git", "diff", "--name-only"], env).decode().splitlines()
    require(
        sorted(names) == (sorted(r.FILES) if state == "old" else []), ("worktree source mismatch", state, names)
    )
    require(
        r.call(["git", "rev-parse", "HEAD"], env).decode().strip() == r.REV
        and r.call(["git", "rev-parse", "HEAD^{tree}"], env).decode().strip() == r.TREE
        and file_sha(r.R / "Cargo.lock") == r.LOCK,
        "Ruff source custody",
    )
    return {n: [file_sha(r.R / n), (r.R / n).stat().st_mtime_ns] for n in r.FILES}


def apply(r, env, state):
    cmd = ["git", "apply"] + (["--reverse"] if state == "old" else [])
    r.call([*cmd, "--check", r.PATCH], env)
    r.call([*cmd, r.PATCH], env)
    return source(r, env, state)


def stat_for(paths):
    def row(p):
        st = p.stat()
        return {
            "path": str(p),
            "dev": st.st_dev,
            "ino": st.st_ino,
            "ctime_ns": st.st_ctime_ns,
            "mtime_ns": st.st_mtime_ns,
            "bytes": st.st_size,
            "sha256": file_sha(p),
        }

    return {k: row(p) for k, p in paths.items()}


def activate(restore, role, hand, dest):
    sdk = restore.SDK
    driver = sdk / restore.q.DRIVER
    backing = Path(hand["drivers"][role]["path"])
    require(
        file_sha(backing) == hand["drivers"][role]["sha256"]
        and not driver.is_symlink()
        and not backing.is_symlink(),
        role,
    )
    if not driver.samefile(backing):
        staging = driver.with_suffix(".installing")
        require(not staging.exists(), staging)
        os.link(backing, staging)
        staging.replace(driver)
    identity = json.loads((restore.TMP / "identity.json").read_bytes())
    expected = identity["base"].copy()
    if role == "C":
        expected[restore.q.DRIVER] = identity["candidate_driver"]
    actual = restore.q.inventory(sdk)
    require(
        len(actual) == 183 and actual == expected and driver.samefile(backing),
        "full actual SDK physical identity",
    )
    tools = {n: sdk / f"bin/{n}" for n in ("rustc", "rustdoc", "cargo")}
    tools["driver"] = driver
    (wild,) = [s for s in actual if s.endswith("/wild-ld/ld.bfd")]
    tools["wild"] = sdk / wild
    require(
        (sdk / "bin/cargo").samefile(hand["aware_cargo"]["path"])
        and hand["aware_cargo"]["source"] == restore.q.AWARE,
        "wrong Cargo reader",
    )
    all_inodes = {}
    for name in sorted(expected):
        st = (sdk / name).lstat()
        all_inodes[name] = [st.st_dev, st.st_ino, st.st_ctime_ns, st.st_mtime_ns]
    save(
        dest / "role.json",
        {
            "role": role,
            "source": hand["drivers"][role]["source"],
            "cargo": hand["aware_cargo"]["source"],
            "sdk": str(sdk),
            "physical": stat_for(tools),
            "all_sdk_files": actual,
            "all_sdk_inodes": all_inodes,
        },
    )
    return tools


def park(r, role, name):
    dest = r.W / "closed" / role / name
    dest.mkdir(parents=True)
    for item in ("target", "shared"):
        p = r.W / item
        require(p.is_dir() and not p.is_symlink() and p.parent == r.W, p)
        p.rename(dest / item)


def empty(r):
    require(
        not any((r.W / n).exists() for n in ("target", "shared")),
        "cache roots shared between independent starts",
    )


def registry(root):
    return {p.name: file_sha(p) for p in (root / "registry/cache").glob("*/*.crate")}


def terminal_native(k):
    require(
        len(k["cargo"]) == 1
        and k["cargo"][0]["terminal"] == [0]
        and all(row["terminal"] == [0] for key in ("rustcs", "link_tools") for row in k[key]),
        "nonterminal Cargo/rustc/linker",
    )
    full = [row for row in k["rustcs"] if not row["link_only"]]
    return {
        "full_rustcs": sorted(x["crate"] for x in full),
        "host_full": sorted(x["crate"] for x in full if "--target" not in x["argv"]),
        "target_full": sorted(x["crate"] for x in full if "--target" in x["argv"]),
        "link_only_rustcs": sorted(x["crate"] for x in k["rustcs"] if x["link_only"]),
        "link_tools": [str(x["path"]) for x in k["link_tools"]],
    }


def depfiles(r, k, dest):
    roots = (r.W / "target", r.W / "shared")
    rows = {}
    for x in k["rustcs"]:
        a = x["argv"]
        name = x["crate"]
        if name not in LEAVES or x["link_only"] or list(r.census.flags(a, "--target")) != [r.T]:
            continue
        (directory,) = r.census.flags(a, "--out-dir")
        (postfix,) = [v.split("=", 1)[1] for v in r.census.flags(a, "-C") if v.startswith("extra-filename=")]
        path = Path(directory) / (name + postfix + ".d")
        require(
            name not in rows and path.is_file() and any(path.resolve().is_relative_to(root) for root in roots),
            name,
        )
        raw = path.read_bytes()
        digest = sha(raw)
        r.census.blob(dest / "depfiles" / (digest + ".gz"), raw)
        rows[name] = {
            "file": str(path),
            "sha256": digest,
            "marker": r.census.marker(raw),
            "pid": x["pid"],
            "argv": a,
        }
    save(dest / "depfiles.json", rows)
    return {n: row["marker"] for n, row in rows.items()}


def validate_cold(r, k, messages, dest, expected):
    graph, _ = products.product(messages)
    native = terminal_native(k)
    require(
        len(graph["dirty"]) == graph["count"] == len(native["full_rustcs"]) == 39
        and not native["link_only_rustcs"],
        ("independent cold", native),
    )
    require(depfiles(r, k, dest) == expected, "wrong known actual target artifact marker")
    return r.training(k["rustcs"]), native


def ensure_invalid(r, env, store, trace):
    path = r.R / r.FILES[0]
    before = file_sha(path)
    with path.open("a") as f:
        f.write("\nconst _: usize = " + r.BAD + ";\n")
    bad = file_sha(path)
    require(bad != before, "unmodified invalid control")
    dest, messages, k = r.census.trace_build("invalid", trace, store, r.R, env, c.CMD, 101)
    products.complete_execs(dest / "execs.tar.gz")
    errors = [m for m in messages if m.get("reason") == "compiler-message" and m["message"]["level"] == "error"]
    require(
        any(
            m["target"]["name"] == r.N
            and (m["message"].get("code") or {}).get("code") == "E0425"
            and r.BAD in (m["message"].get("rendered") or "")
            and any(str(r.FILES[0]) in s["file_name"] for s in m["message"]["spans"])
            for m in errors
        ),
        "invalid visitor has wrong source/emitter/error",
    )
    require(
        any(x["crate"] == r.N and x["terminal"] != [0] for x in k["rustcs"]),
        "error not produced by an actual bad AST compilation",
    )
    save(
        dest / "control.json",
        {
            "invalid_sha256": bad,
            "corrected_sha256": before,
            "emitter": r.N,
            "code": "E0425",
            "identifier": r.BAD,
        },
    )
    r.call(["git", "restore", "--worktree", "--", r.FILES[0]], env)
    require(file_sha(path) == before and source(r, env, "new"), "incorrect repair")


def run_arm(r, restore, role, hand, env, out, watch, seed, registry_expected):
    arm = out / role
    arm.mkdir()
    tools = activate(restore, role, hand, arm)
    before = stat_for(tools)
    h = Path(env["CARGO_HOME"])
    require(not h.exists(), "role Cargo home already used")
    shutil.copytree(seed, h, symlinks=True)
    require(registry(h) == registry_expected, "changed per-role Cargo registry archive inventory")
    proof = arm / "proof"
    proof.mkdir()
    trace = r.W / ("trace-" + role)
    trace.mkdir()
    expected = hand["qualification"][role]
    states = {}
    visits = {}
    physical = {}

    def traced(name):
        d, messages, k = r.census.trace_build(name, trace, proof, r.R, env, c.CMD)
        products.complete_execs(d / "execs.tar.gz")
        return d, messages, k

    def cold(name, state):
        empty(r)
        d, msg, k = traced(name)
        training, visits[name] = validate_cold(r, k, msg, d, expected["markers"])
        from collections import Counter

        counts = Counter(Path(x["path"]) for x in k["link_tools"])
        wild = tools["wild"]
        require(
            len(counts) == 3
            and counts[wild] == 8
            and sum(counts.values()) == 24
            and {p.name for p in counts} == {"cc", "collect2", "ld.bfd"},
            "physical user Cargo host tool links",
        )
        visits[name]["cold_link_tools"] = {str(p): [v, file_sha(p)] for p, v in counts.items()}
        states[name] = products.checked_reader(r, training, msg, d, env, state)
        require(
            states[name]["result"] == expected["behavior"]["old" if state == "old" else "empty"]["stdout"]
            and states[name]["elf"] == expected["behavior"]["old" if state == "old" else "empty"]["reader"],
            "independent previous host complete ELF/visitor mismatch",
        )
        return training

    empty(r)
    old = apply(r, env, "old")
    training = cold("old", "old")
    new = apply(r, env, "new")
    save(
        arm / "source.json",
        {"revision": r.REV, "tree": r.TREE, "lock": r.LOCK, "patch": file_sha(r.PATCH), "old": old, "new": new},
    )
    values = c.consecutive(watch, arm, env, r.R)
    msgs = {p: [json.loads(line) for line in values[p]["stdout"].splitlines()] for p in c.PHASES}
    for phase in c.PHASES:
        graph, _ = products.product(msgs[phase])
        require(
            graph == expected["typed"][phase],
            ("unexpected measured typed artifacts", role, phase, graph, expected),
        )
        visits[phase] = graph
    d = proof / "measured-final"
    d.mkdir()
    states["measured-final"] = products.checked_reader(r, training, msgs["repeat"], d, env, "new")
    physical["warm"] = products.ledger(r.W, d)
    park(r, role, "warm")
    cold("empty", "new")
    physical["empty"] = products.ledger(r.W, proof / "empty")
    products.equal_state(states["empty"], states["measured-final"])
    park(r, role, "empty")
    old_again = apply(r, env, "old")
    require({n: h[0] for n, h in old_again.items()} == {n: h[0] for n, h in old.items()}, "old source replay")
    cold("replay-old", "old")
    products.equal_state(states["old"], states["replay-old"])
    apply(r, env, "new")
    d = proof / "replay-edit"
    msg, k = products.observed_edit(r, env, tools["driver"], d)
    visits["replay-edit"] = terminal_native(k)
    require(
        visits["replay-edit"]["full_rustcs"] == expected["native"]["edit"]
        and visits["replay-edit"]["link_only_rustcs"] == expected["link_only_native"]["edit"]
        and not visits["replay-edit"]["link_tools"],
        "kernel full roster on actual edit",
    )
    states["replay-edit"] = products.checked_reader(r, r.training(k["rustcs"]), msg, d, env, "new")
    products.equal_state(states["replay-edit"], states["empty"])
    d, msg, k = traced("replay-repeat")
    visits["replay-repeat"] = terminal_native(k)
    require(
        visits["replay-repeat"]["full_rustcs"] == expected["native"]["repeat"]
        and visits["replay-repeat"]["link_only_rustcs"] == expected["link_only_native"]["repeat"]
        and not visits["replay-repeat"]["link_tools"],
        "kernel full roster on real repeat",
    )
    ensure_invalid(r, env, proof, trace)
    d, msg, k = traced("repair")
    visits["repair"] = terminal_native(k)
    require(r.N in visits["repair"]["full_rustcs"], "real repaired AST not recompiled")
    states["repair"] = products.checked_reader(r, r.training(k["rustcs"]), msg, d, env, "new")
    products.equal_state(states["repair"], states["empty"])
    require(
        states["old"]["result"] != states["empty"]["result"] and states["old"]["elf"] != states["empty"]["elf"],
        "source edit not visible to linked native visitor",
    )
    require(
        registry(h) == registry_expected and stat_for(tools) == before,
        "tool/registry identity changed within arm",
    )
    park(r, role, "validation")
    h.rename(r.W / "closed" / role / "cargo-home")
    record = {
        "role": role,
        "usual_source": str(r.R),
        "sdk": str(restore.SDK),
        "target": env["CARGO_TARGET_DIR"],
        "shared": env["CARGO_BUILD_BUILD_DIR"],
        "source_heads": {k: {n: v[0] for n, v in rec.items()} for k, rec in [("old", old), ("new", new)]},
        "artifacts": states,
        "visits": visits,
        "storage": physical,
        "driver": before["driver"],
        "typed_roster": states["old"]["roster"],
    }
    save(arm / "terminal.json", record)
    return record


def storage_gate(records):
    summary = {}
    for state in ("warm", "empty"):
        p = records["P"]["storage"][state]
        q = records["C"]["storage"][state]
        kinds = set(p["physical_payloads"]) | set(q["physical_payloads"])
        growth = {n: q["physical_payloads"].get(n, 0) - p["physical_payloads"].get(n, 0) for n in kinds}
        require(
            all(v <= 0 for v in growth.values()), ("extra physical codegen or linked payload", state, growth)
        )
        owner_delta = {
            n: v - max(1, p["physical_payloads_by_filename"].get(n, 0))
            for n, v in q["physical_payloads_by_filename"].items()
        }
        require(
            not any(v > 0 for v in owner_delta.values()),
            ("another stored codegen/logical product", state, {k: v for k, v in owner_delta.items() if v > 0}),
        )
        new_copies = {
            n: v
            for n, v in q["exact_duplicate_payloads"].items()
            if v > p["exact_duplicate_payloads"].get(n, 1)
        }
        require(not new_copies, ("new separately allocated identical code or product", state, new_copies))
        summary[state] = {
            "P": p["allocated_unique"],
            "C": q["allocated_unique"],
            "physical_payload_count_delta": growth,
        }
    return summary


def calibration_process(dest):
    src = HERE.parent / "ohm-gnu-syscall"
    sys.path.insert(0, str(src))
    import paired

    env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "LC_ALL": "C"}
    return c.calibrate(src, paired, dest, env)


def main(phase, pos):
    tmp = Path(os.environ["RUNNER_TEMP"]).resolve(strict=True)
    require(
        os.environ["GITHUB_RUN_ATTEMPT"] == "1" and os.environ["GITHUB_REPOSITORY"] == "astral-experiments/ohm",
        "wrong hardware run",
    )
    seq = c.assignment(HERE, phase)
    require(1 <= pos <= len(seq), pos)
    order = seq[pos - 1]
    hand = json.loads((tmp / "musl-hardware-handoff.json").read_bytes())
    require(
        (hand["phase"], hand["position"], hand["order"], hand["workflow_sha"])
        == (phase, pos, order, os.environ["GITHUB_SHA"]),
        "unauthenticated SDK handoff",
    )
    require(
        not os.environ.get("GH_TOKEN") and not os.environ.get("GITHUB_TOKEN"),
        "credentials in measurement process",
    )
    out = tmp / "musl-measurements"
    out.mkdir()
    save(out / "admission.json", hand)
    products.storage_calibration(out, tmp)
    platform_info = host()
    save(out / "host.json", platform_info)
    require(
        platform_info["boot_id"] not in hand["admitted"].get("boot_ids", []),
        "reused worker from a prior cohort",
    )
    require(
        shutil.disk_usage(tmp).free >= 8 * 2**30, "not enough space for six independent archived private states"
    )
    subprocess.run([sys.executable, "-IB", HERE / "measure.py", "calibrate", str(out)], check=True)
    watch = out / "tools/watch"
    sys.path.insert(0, str(HERE.parent / "ohm-musl-ast-pair"))
    import restore

    sys.path.insert(0, str(HERE.parent / "ohm-musl-ast"))
    import ruff_loop as r

    require(
        file_sha(r.LOG / "sdk.json") == hand["sdk_receipt"]
        and file_sha(r.LOG / "guard-subjects.json") == hand["guard_subjects"],
        "altered physical source receipt",
    )
    r.census.qualify.rt.SDK = restore.SDK
    require(restore.SDK == Path(hand["sdk"]) and r.s.rt.SDK == restore.SDK, "different SDK paths")
    env = r.prepare()
    require(
        set(env) == EXPECTED_ENV
        and env["CARGO_NET_OFFLINE"] == "true"
        and env["RUSTUP_AUTO_INSTALL"] == "0"
        and (env["CARGO_TARGET_DIR"], env["CARGO_BUILD_BUILD_DIR"])
        == (str(r.W / "target"), str(r.W / "shared")),
        "ordinary allowlist",
    )
    eligible = json.loads((r.LOG / "subjects.json").read_bytes())
    require(
        eligible["source"] == r.REV and eligible["tree"] == r.TREE and eligible["lock"] == r.LOCK, "source data"
    )
    save(out / "ordinary-environment.json", {"values": env, "eligible": eligible, "command": c.CMD})
    before = Path(env["CARGO_HOME"])
    seed = r.W / "prefetched-registry"
    require(registry(before) == eligible["registry"] and not seed.exists(), "registry custody")
    before.rename(seed)
    for path in seed.rglob("*"):
        if path.is_symlink():
            require(
                not Path(os.readlink(path)).is_absolute() and path.resolve(strict=True).is_relative_to(seed),
                "shared registry symlink",
            )
    records = {}
    for role in order:
        records[role] = run_arm(r, restore, role, hand, env, out, watch, seed, eligible["registry"])
    p, q = records["P"], records["C"]
    manifests = [json.loads((out / n / "role.json").read_bytes()) for n in "PC"]
    all_files = [m["all_sdk_files"] for m in manifests]
    all_inodes = [m["all_sdk_inodes"] for m in manifests]
    require(
        {name for name in all_files[0] if all_files[0][name] != all_files[1][name]} == {restore.q.DRIVER}
        and {name for name in all_inodes[0] if all_inodes[0][name] != all_inodes[1][name]}
        == {restore.q.DRIVER},
        "the same 182 files and inodes must accompany both different compiler drivers",
    )
    require(
        all(p[k] == q[k] for k in ("usual_source", "sdk", "target", "shared", "source_heads", "typed_roster")),
        "role inputs differ",
    )
    for name in ("old", "empty", "replay-edit", "measured-final", "repair"):
        require(
            all(
                p["artifacts"][name][k] == q["artifacts"][name][k]
                for k in ("elf", "elf_bytes", "result", "reader_link")
            ),
            ("cross-compiler complete linked output differs", name),
        )
    saved = storage_gate(records)
    host_id = platform_info["boot_id"]
    result = {
        "hardware": True,
        "position": pos,
        "order": order,
        "phase": phase,
        "boot_id": host_id,
        "source_run": hand["transfer"]["SOURCE_RUN"],
        "source_head": hand["transfer"]["SOURCE_HEAD"],
        "provider_run": hand["transfer"]["PROVIDER_RUN"],
        "provider_head": hand["transfer"]["PROVIDER_HEAD"],
        "workflow_sha": hand["workflow_sha"],
        "workflow_run": int(os.environ["GITHUB_RUN_ID"]),
        "whole_command": c.CMD,
        "plan_sha256": c.PLAN_SHA,
        "position_sha256": c.POSITIONS_SHA,
        "storage": saved,
        "terminals": {role: file_sha(out / role / "terminal.json") for role in order},
        "coverage": "all threads and descendants on whole ordinary command; separate native structural replay",
    }
    save(out / "pair.json", result)
    packed = c.pack(out, pos)
    save(out / "packet.json", {"file": packed.name, "bytes": packed.stat().st_size, "sha256": file_sha(packed)})
    print("Completed registered pair", phase, pos, order, packed.name, file_sha(packed), flush=True)


if __name__ == "__main__":
    if sys.argv[1] == "calibrate":
        calibration_process(Path(sys.argv[2]))
    else:
        main(sys.argv[1], int(sys.argv[2]))
