"""Independently authenticate native bits, hardware observations and actual test membership in one original no-run ZIP."""

import argparse, collections, hashlib, json, os, re, subprocess as sp, tempfile, threading, zipfile
from pathlib import Path

ROOTS = {
    "src/lib.rs",
    "src/main.rs",
    "tests/analyze_graph.rs",
    "tests/cli/main.rs",
    "tests/config.rs",
    "tests/direxist_guard.rs",
    "tests/integration_test.rs",
    "tests/resolve_files.rs",
}
PHASES = (
    "cold-old",
    "old-unchanged",
    "edit",
    "new-unchanged",
    "repair",
    "empty-new",
    "second-cold-old",
    "observed-old-unchanged",
    "observed-edit",
    "observed-new-unchanged",
)
STATE = dict.fromkeys(PHASES, "NEW") | dict.fromkeys(
    ("cold-old", "old-unchanged", "second-cold-old", "observed-old-unchanged"), "OLD"
)
HEX = re.compile("[0-9a-f]{64}")


def need(ok, text):
    if not ok:
        raise ValueError(text)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def hf(path):
    with path.open("rb") as src:
        return hashlib.file_digest(src, "sha256").hexdigest()


def reopen(z, work, live, partial, strict_checkpoint_sum=False):
    names = z.namelist()
    need(
        len(names) == len(set(names)) < 30000
        and all(not Path(n).is_absolute() and ".." not in Path(n).parts for n in names),
        "invalid ZIP directory",
    )

    def raw(n):
        need(z.getinfo(n).file_size < 48 << 20, ("large control", n))
        return z.read(n)

    def j(n):
        return json.loads(raw(n))

    reg = j("registration.json")
    if "confirmation.json" in names:
        conf = j("confirmation.json")
        slot = conf["slot"]
        plan = conf["plan"]
        order = plan["orders"][slot]
        need(
            plan["orders"] == ["PC", "CP", "CP", "PC", "PC", "CP"]
            and plan["excluded_pilot"] == 41756383381
            and conf["pilot_excluded"]
            and 0 <= slot < 6
            and reg["plan"]["confirmation_slot"] == slot
            and order == conf["order"],
            "wrong paired assignment",
        )
    else:
        conf = None
        order = "PC"
    need(
        reg["plan"]["order"] == order
        and reg["plan"]["ordinary"]
        == ["cargo", "+ohm", "test", "--no-run", "-p", "ruff"]
        and reg["plan"]["source"]
        == [
            "f3280423f6c535690287e8169c25929f8d6433ce",
            "d136bd8d002a648de5f344df602e492658306f1e",
        ]
        and len(reg["boot"]) == 36
        and len(reg["factory"]) == 2,
        "wrong genuine study",
    )
    temporary = Path(tempfile.mkdtemp(dir=work))
    table = {
        "run_input": reg,
        "confirmation": conf,
        "roles": {},
        "refusals": {
            n: j(n) for n in names if n.startswith("refusal-") and n.endswith(".json")
        },
    }
    try:
        restored = set()

        def materialize(role, desc):
            digest = desc["sha256"]
            size = desc["bytes"]
            need(
                HEX.fullmatch(digest) and 64 <= size < 1024 << 20,
                ("bad native identity", role, digest, size),
            )
            out = temporary / (role + "-" + digest)
            key = f"{role}/native-bodies/{digest}.zst"
            if key not in restored:
                with z.open(key) as compressed, out.open("xb") as body:
                    proc = sp.Popen(["zstd", "-dcq"], stdin=sp.PIPE, stdout=sp.PIPE)
                    errors = []

                    def input_stream():
                        try:
                            with proc.stdin:
                                while part := compressed.read(1 << 20):
                                    proc.stdin.write(part)
                        except Exception as exc:
                            errors.append(repr(exc))

                    thread = threading.Thread(target=input_stream)
                    thread.start()
                    h = hashlib.sha256()
                    total = 0
                    first = b""
                    with proc.stdout:
                        while part := proc.stdout.read(1 << 20):
                            total += len(part)
                            need(total <= size, "oversized reconstructed ELF")
                            h.update(part)
                            body.write(part)
                            if not first:
                                first = part[:64]
                    thread.join()
                    need(
                        not errors
                        and proc.wait() == 0
                        and total == size
                        and h.hexdigest() == digest,
                        "native body differs from original SHA/length",
                    )
                    need(
                        first[:6] == b"\x7fELF\x02\x01"
                        and int.from_bytes(first[16:18], "little") in (2, 3)
                        and first[18:20] == b">\x00",
                        "wrong physical executable",
                    )
                out.chmod(0o700)
                restored.add(key)
            return out

        for role in "PC":
            row = table["roles"][role] = {"phases": {}}
            hw = {}
            known = {}
            for phase in PHASES:
                base = f"{role}/{phase}/"
                if base + "counter.json" in names:
                    v = j(base + "counter.json")
                    need(
                        v["enabled"] == v["running"] > 0
                        and v["instructions"] > 0
                        and v["status"] == 0,
                        "bad original PMU",
                    )
                    hw[phase] = v["instructions"]
                if base + "native.json" not in names:
                    if partial:
                        continue
                    raise ValueError(("missing native phase", base))
                out = j(base + "native.json")
                need(set(out["roots"]) == ROOTS, "wrong named native witnesses")
                tokens = []
                lines = raw(base + "stderr").decode().splitlines()
                for line in lines:
                    m = re.fullmatch(r"\s*Executable (.+?) \((.+)\)", line)
                    if m:
                        tokens.append((m[1], m[2]))
                need(
                    len(tokens) == 8
                    and len(set(path for desc, path in tokens)) == 8
                    and all(sum(t[0].endswith(n) for t in tokens) == 1 for n in ROOTS),
                    "missing physical Cargo test roots",
                )
                phase_row = {"roots": {}, "cli": out["cli"]}
                cli = materialize(role, out["cli"])
                for n, meta in sorted(out["roots"].items()):
                    tag = n.replace("/", "_")
                    roster = raw(base + "out-of-counter/" + tag + ".list")
                    parsed = roster.decode().splitlines()
                    need(
                        len(parsed) == len(set(parsed)) == meta["inventory_count"]
                        and sha(roster) == meta["inventory"]
                        and not raw(base + "out-of-counter/" + tag + ".stderr"),
                        "different actual test roster",
                    )
                    materialize(role, meta)
                    phase_row["roots"][n] = [
                        meta["sha256"],
                        meta["bytes"],
                        len(parsed),
                        meta["inventory"],
                    ]
                    for sample in {
                        "tests/config.rs": ["lint_select", "lint_select_json"],
                        "tests/integration_test.rs": ["stdin_success"],
                    }.get(n, []):
                        answer = raw(
                            base + "out-of-counter/" + tag + "-" + sample + ".stdout"
                        )
                        need(
                            sample + ": test" in parsed
                            and ("test " + sample + " ... ok").encode() in answer
                            and b"1 passed; 0 failed" in answer,
                            ("wrong native test result", role, phase, sample),
                        )
                for label, obs in out["verdict"]["cases"].items():
                    stem = base + "out-of-counter/" + label
                    need(
                        sha(raw(stem + ".stdout")) == obs["out"]
                        and sha(raw(stem + ".stderr")) == obs["err"],
                        ("text digest", label),
                    )
                if live and STATE[phase] not in known:
                    # Independent argv, executable location, and temp namespace, outside any timing.
                    help_ = sp.run(
                        [cli, "check", "--help"],
                        capture_output=True,
                        env=os.environ
                        | {
                            "COLUMNS": "240",
                            "NO_COLOR": "1",
                            "TERM": "dumb",
                            "LC_ALL": "C",
                        },
                    )
                    env = os.environ | {
                        "CARGO_MANIFEST_DIR": str(live / "crates/ruff"),
                        "CARGO_BIN_EXE_ruff": str(cli),
                        "RUFF_NO_CACHE": "true",
                        "INSTA_UPDATE": "no",
                        "COLUMNS": "240",
                        "NO_COLOR": "1",
                        "TERM": "dumb",
                        "LC_ALL": "C",
                    }
                    need(
                        help_.returncode == 0 and not help_.stderr, "native help failed"
                    )
                    old = STATE[phase] == "OLD"
                    allhelp = b" ".join(
                        (
                            p.stdout
                            for p in [
                                help_,
                                sp.run([cli, "--help"], capture_output=True, env=env),
                                sp.run(
                                    [cli, "format", "--help"],
                                    capture_output=True,
                                    env=env,
                                ),
                            ]
                        )
                    )
                    joined = b" ".join(allhelp.split())
                    expected = (
                        b"lint.line-length = 100" if old else b"line-length = 100"
                    )
                    need(
                        b'--config "' + expected + b'"' in joined
                        and (old or b"lint.line-length = 100" not in joined),
                        ("stale off-clock help", role, phase),
                    )
                    # insta_cmd can derive the companion CLI from the test binary path; preserve Cargo's layout as well as its env.
                    d = temporary / (role + "-" + STATE[phase]) / "debug"
                    (d / "deps").mkdir(parents=True)
                    os.link(cli, d / "ruff")
                    executed = {}
                    for n, meta in out["roots"].items():
                        tag = n.replace("/", "_")
                        logical = d / "deps" / tag
                        os.link(materialize(role, meta), logical)
                        new = sp.run(
                            [logical, "--list", "--format", "terse"],
                            cwd=live / "crates/ruff",
                            env=env,
                            capture_output=True,
                            timeout=60,
                        )
                        need(
                            new.returncode == 0
                            and sha(new.stdout) == meta["inventory"]
                            and not new.stderr,
                            ("independent physical test list", n),
                        )
                        for sample in {
                            "tests/config.rs": ["lint_select", "lint_select_json"],
                            "tests/integration_test.rs": ["stdin_success"],
                        }.get(n, []):
                            ran = sp.run(
                                [logical, "--exact", sample, "--test-threads=1"],
                                cwd=live / "crates/ruff",
                                env=env,
                                capture_output=True,
                                timeout=90,
                            )
                            need(
                                ran.returncode == 0
                                and b"1 passed; 0 failed" in ran.stdout
                                and ("test " + sample + " ... ok").encode()
                                in ran.stdout,
                                (
                                    "independent initialized test",
                                    n,
                                    sample,
                                    ran.stdout[-250:],
                                    ran.stderr[-250:],
                                ),
                            )
                            executed[sample] = ran.returncode
                    phase_row["independent_native"] = {
                        "all_eight_inventories": True,
                        "three_real_tests": executed,
                        "expected_help": expected.decode(),
                    }
                known.setdefault(STATE[phase], out)
                if not partial:
                    need(
                        known[STATE[phase]] == out,
                        ("different clean/repair native trial", role, phase),
                    )
                row["phases"][phase] = phase_row
            row["whole_user_instructions"] = hw
            if partial:
                continue
            for bad in ("invalid", "invalid-unchanged"):
                msg = raw(f"{role}/{bad}/stderr")
                need(
                    b"error[E0308]" in msg and b"owner_cgu_invalid_test_build" in msg,
                    "bad real invalid verdict",
                )
            need(
                len(known) == 2
                and known["OLD"]["cli"] != known["NEW"]["cli"]
                and len(hw) == 10,
                "incomplete ordinary roles",
            )
            tasks = {}
            for phase in (
                "observed-old-unchanged",
                "observed-edit",
                "observed-new-unchanged",
            ):
                base = f"{role}/{phase}/"
                proc_rows = j(base + "task-instructions.json")
                tsv = raw(base + "kernel-execs/epochs.tsv").decode().splitlines()
                raw_r = {}
                images = {}
                for line in tsv:
                    f = line.split()
                    if f[0] == "I":
                        ids = raw(base + f"kernel-execs/{int(f[1]):05}.nul").split(
                            b"\0"
                        )
                        need(
                            ids.pop() == b"" and int(ids[0]) == int(f[2]),
                            "invalid exec trace record",
                        )
                        images[int(f[1])] = [os.fsdecode(v) for v in ids[4:]]
                    if f[0] == "R":
                        i, pid, ir, en, run, status = map(int, f[1:])
                        need(
                            status == 0 and ir > 0 and en == run > 0,
                            "bad direct task event",
                        )
                        raw_r[pid] = [ir, images[i]]
                sums = collections.defaultdict(int)
                for r in proc_rows:
                    need(
                        raw_r[r["pid"]] == [r["instructions"], r["argv"]],
                        "task proof or argv differs",
                    )
                    name = (
                        r["kind"]
                        + ":"
                        + r.get("source", "")
                        + (":link-only" if r.get("link_only") else "")
                    )
                    sums[name] += r["instructions"]
                unpriced = {
                    pid: data
                    for pid, data in raw_r.items()
                    if pid not in {r["pid"] for r in proc_rows}
                }
                for pid, (ir, argv) in unpriced.items():
                    need(
                        "--crate-name" not in argv
                        and not any(
                            "link-only" in w or w.endswith(".rlink") for w in argv
                        )
                        and any(
                            w in ("-vV", "-V", "--version", "--print")
                            or w.startswith("--print=")
                            for w in argv
                        ),
                        ("unclassified native compiler or linker lifetime", pid, argv),
                    )
                    sums["untyped-tool-inquiry"] += ir
                if phase != "observed-edit":
                    need(
                        not proc_rows,
                        "unexpected physical compilation/link in settled control",
                    )
                # These original task counters also account for linker children created by fork,
                # whose full instruction costs are deliberately outside the exec-root-only lifetime event.
                full = collections.Counter()
                by_link = collections.Counter()
                image_meta = {}
                initial = None
                pre_exec = 0
                whole = -1
                link_bindings = {}
                linker_images = set()
                for ln in tsv:
                    fs = ln.split()
                    if fs[0] != "R":
                        continue
                    fields = raw(base + f"kernel-execs/{int(fs[1]):05}.nul").split(
                        b"\0"
                    )
                    path = os.fsdecode(fields[3])
                    if path.endswith(
                        "/dist/sdk/lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld/ld.bfd"
                    ):
                        linker_images.add((int(fields[1]), int(fields[2])))
                need(
                    len(linker_images) == (1 if phase == "observed-edit" else 0),
                    "physical signed linker identity",
                )
                for line in tsv:
                    f = line.split()
                    if f[0] == "I":
                        i = int(f[1])
                        parts = raw(base + f"kernel-execs/{i:05}.nul").split(b"\0")
                        ident = (int(parts[1]), int(parts[2]))
                        image_meta[i] = [
                            os.fsdecode(parts[3]),
                            list(map(os.fsdecode, parts[4:-1])),
                            ident,
                            f[5],
                        ]
                        if initial is None:
                            initial = i
                            need(f[5] == "first", "unexpected initial process")
                    elif f[0] == "C":
                        i, pid, tid, ir, en, run = map(int, f[1:])
                        need(ir >= 0 and en == run >= 0, "multiplexed task checkpoint")
                        path, argv, ident, origin = image_meta[i]
                        kind = Path(path).name
                        full[kind] += ir
                        if i == initial:
                            pre_exec += ir
                        if kind == "ld.bfd":
                            need(
                                argv.count("-o") == 1, "ambiguous physical link output"
                            )
                            need(
                                ident in linker_images
                                and path.endswith(
                                    "/dist/sdk/lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld/ld.bfd"
                                ),
                                "unbound forked linker",
                            )
                            dst = Path(argv[argv.index("-o") + 1]).name
                            by_link[dst] += ir
                            val = {
                                "ruff_archive": [
                                    Path(w).name
                                    for w in argv
                                    if re.fullmatch(
                                        r"libruff(?:-[a-z0-9_]+)?\.rlib", Path(w).name
                                    )
                                ],
                                "archives": sum(w.endswith(".rlib") for w in argv),
                                "rsp": sum(w.startswith("@") for w in argv),
                            }
                            need(
                                dst not in link_bindings or link_bindings[dst] == val,
                                "changed link arguments after fork",
                            )
                            link_bindings[dst] = val
                    elif f[0] == "W":
                        whole, en, run, status = map(int, f[1:])
                        need(
                            en == run > 0 and status == 0,
                            "invalid original inherited event",
                        )
                diff = sum(full.values()) - pre_exec - whole
                need(whole > 0, "missing whole inherited event")
                closes = abs(diff) <= max(1000, whole // 1000000)
                if strict_checkpoint_sum and not closes:
                    raise ValueError(("native task counters do not close", role, phase, diff))
                section = "separate_all_task_breakdown" if closes else "refused_all_task_breakdown"
                row.setdefault(section, {})[phase] = {
                    "whole": whole,
                    "all_tasks": dict(sorted(full.items())),
                    "link_outputs": dict(sorted(by_link.items())),
                    "link_inputs": link_bindings,
                    "pre_exec": pre_exec,
                    "closure_difference": diff,
                }
                tasks[phase] = dict(sorted(sums.items()))

            def sessions(phase):
                return {
                    Path(k).parent.as_posix(): v
                    for k, v in j(f"{role}/{phase}/cgu-bodies.json").items()
                }

            was = sessions("cold-old")
            now = sessions("edit")
            row["cgu_donors"] = {}
            for key, units in sorted(now.items()):
                previous = was.get(key, {})
                same = sum(
                    name in previous and part == previous[name]
                    for name, part in units.items()
                )
                changed = sum(
                    part[3]
                    for name, part in units.items()
                    if name not in previous or part != previous[name]
                )
                need(
                    all(
                        len(part) == 5 and HEX.fullmatch(part[4])
                        for part in units.values()
                    ),
                    "native ledger",
                )
                row["cgu_donors"][Path(key).name] = [len(units), same, changed]
            row["real_tasks"] = tasks
            row["allocations"] = {
                phase: j(f"{role}/{phase}/footprint.json")
                for phase in ("cold-old", "edit", "empty-new")
            }
            ok = j(role + "/complete.json")
            need(
                ok["all_controls"] and ok["ordinary"] == reg["plan"]["ordinary"],
                "missing terminal role",
            )
        if not partial:
            need(
                j("terminal.json")["all_cases"] and not table["refusals"],
                "terminal or final guard refused",
            )
            pc = table["roles"]
            table["paired_reduction_percent"] = {
                k: 100 * (1 - pc["C"]["whole_user_instructions"][k] / v)
                for k, v in pc["P"]["whole_user_instructions"].items()
            }
            for phase in PHASES:
                a = pc["P"]["phases"][phase]["roots"]
                b = pc["C"]["phases"][phase]["roots"]
                need(
                    {n: v[2:] for n, v in a.items()}
                    == {n: v[2:] for n, v in b.items()},
                    "physical cross-compiler inventory",
                )
        table["physical_native_bodies"] = len(restored)
        return table
    finally:
        import shutil

        shutil.rmtree(temporary)


def main():
    cli = argparse.ArgumentParser()
    cli.add_argument("--zip", type=Path, required=True)
    cli.add_argument("--sha256", required=True)
    cli.add_argument("--work", type=Path, required=True)
    cli.add_argument("--ruff", type=Path)
    cli.add_argument("--out", type=Path, required=True)
    cli.add_argument("--partial", action="store_true")
    cli.add_argument("--strict-checkpoint-sum", action="store_true")
    a = cli.parse_args()
    need(
        HEX.fullmatch(a.sha256) and hf(a.zip) == a.sha256,
        "wrong authenticated original ZIP",
    )
    import shutil

    need(
        shutil.disk_usage(a.work).free > 15 * 2**30 + 3 * a.zip.stat().st_size,
        "physical reader disk reserve",
    )
    a.out.parent.mkdir(exist_ok=True, parents=True)
    with zipfile.ZipFile(a.zip) as z:
        data = reopen(z, a.work, a.ruff, a.partial, a.strict_checkpoint_sum)
    data["original"] = {"sha256": a.sha256, "bytes": a.zip.stat().st_size}
    a.out.write_text(json.dumps(data, sort_keys=True, indent=2) + "\n")
    print(
        "native bodies",
        data["physical_native_bodies"],
        "whole primary",
        data.get("paired_reduction_percent", {}).get("edit"),
        "original",
        a.sha256,
    )


if __name__ == "__main__":
    main()
