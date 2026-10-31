"""Unscored F-off ordinary CLI recheck with a real inherited GNU linker search directory."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import traceback

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "branch-return-pmu")]
import bindings as b
import worker as original
import file_trace
import records
from records import need, save, file_id

OUT = b.OUT
WORK = b.WORK
TREE = original.kit.TREE
CARGO = original.CARGO
LOG = "cargo::compiler=info,cargo::compiler::fingerprint=trace"
BRANCH = "charlie/qa-branch-return-native-recheck-20261031"
FROZEN = "2f80a7368927af35813b90c67e42cf9df6af8224"


def frozen_inputs():
    trees = {
        "scripts/branch-return-pmu": "2235ee1eb52f0e098a0cf3c160c5279ef99475f4",
        "scripts/ohm-packed-ruff": "d9fd6c8e4152d468a3a40d600ee1c6ebda13e5f2",
    }
    need(
        b.git(HERE, "rev-parse", "HEAD") == os.environ["GITHUB_SHA"] == os.environ["REVIEWED_HEAD"],
        "QA checkout",
    )
    need(
        all(
            b.git(HERE.parents[1], "rev-parse", "HEAD:" + name) == tree
            for name, tree in trees.items()
        ),
        "changed original worker",
    )
    need(
        os.environ["GITHUB_REPOSITORY"] == b.REPO
        and os.environ["GITHUB_REF"] == "refs/heads/" + BRANCH
        and os.environ["GITHUB_RUN_ATTEMPT"] == "1",
        "wrong diagnostic ref",
    )
    need(
        WORK.resolve() == WORK
        and (WORK / ".owned-by-packed-study").read_text() == str(b.ROOT)
        and shutil.disk_usage(OUT).free >= 32 * 2**30,
        "fresh owned storage",
    )


def side_from(messages):
    psm = [
        m
        for m in messages
        if m.get("reason") == "build-script-executed"
        and m.get("package_id", "").split("#")[-1].split("@")[0] == "psm"
    ]
    systems = {Path(m["out_dir"]) for m in psm if m["linked_paths"] == ["native=" + m["out_dir"]]}
    need(len(systems) == 1, ("real psm native output", systems))
    side = systems.pop() / "libgcc_s.so"
    need(
        side.parent.is_relative_to(WORK / "build") and side.parent.resolve() == side.parent,
        ("psm physical directory", side),
    )
    return side


def bare(phase, branch, where, env):
    where.mkdir()
    original.checked_source(phase, branch, where)
    messages, _, native = original.invocation(where, env, "structural", 0, "Foff")
    graph, dirty = original.historical.roster(messages)
    products, files = original.native.observed(
        messages, branch, original.kit.REVS[branch], env, b.ROOT, TREE, WORK, where
    )
    need(
        len(graph) == 375 and len(dirty) == (375 if phase.startswith("cold-") else 20),
        ("historical baseline dirty set", phase, len(dirty)),
    )
    obs = dict(
        phase=phase,
        branch=branch,
        typed=original.historical.commit(graph),
        dirty=len(dirty),
        cli=products["cli"]["whole"],
        reader=products["reader"]["whole"],
        diagnostic=products["typed"],
        psm=str(side_from(messages)),
    )
    save(where / "observation.json", obs)
    return obs, native, files


def unchanged_source():
    need(
        original.kit.git("rev-parse", "HEAD") == original.kit.REVS["B"]
        and original.kit.git("rev-parse", "HEAD^{tree}") == original.kit.TREES["B"]
        and not original.kit.git("status", "--porcelain"),
        "source B changed",
    )
    paths = ["HEAD", "refs/heads/" + original.kit.NAMES["B"]]
    return {p: [file_id(TREE / ".git" / p), b.sha(TREE / ".git" / p)] for p in paths}


def put(side, body, prior=None):
    if prior is None:
        need(not os.path.lexists(side), "provider already present")
        with side.open("xb") as f:
            f.write(body)
    else:
        need(
            side.is_file()
            and not side.is_symlink()
            and side.read_bytes() == prior
            and len(body) == len(prior),
            "unexpected provider before in-place rewrite",
        )
        st = side.stat()
        with side.open("r+b") as f:
            f.write(body)
            f.flush()
            os.fsync(f.fileno())
        os.utime(side, ns=(st.st_atime_ns, st.st_mtime_ns))
        need(
            file_id(side)[:4] == [st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns],
            "changed held native identity",
        )
    need(side.read_bytes() == body, "provider write readback")


def fingerprint(stderr):
    rows = stderr.decode(errors="strict").splitlines()
    dirty = [s for s in rows if "fingerprint dirty for " in s]
    reason = [s for s in rows if "dirty: " in s]
    cached = [s for s in rows if "relink-only: reusing cached codegen for " in s]
    need(
        len(dirty) == len(reason) == len(cached) == 1
        and "fingerprint dirty for ruff v0.16.7" in dirty[0]
        and ('dirty: FsStatusOutdated(StaleItem(MissingFile { path: "' + records.MARK + '" }))')
        in reason[0]
        and "relink-only: reusing cached codegen for ruff v0.16.7" in cached[0],
        ("distinct root-only native fingerprint/reuse", dirty, reason, cached),
    )
    return {"dirty_unit": dirty[0], "dirty_reason": reason[0], "cached_native": cached[0]}


def driver(where, env, tag, side, origins, expected, full, healthy, calls):
    where.mkdir()
    before = unchanged_source()
    sd = [file_id(side), b.sha(side)] if side.exists() else None
    r, native, io = file_trace.record(
        where, CARGO, env | {"CARGO_LOG": LOG}, TREE, original.processes, origins, side, calls
    )
    need(native["cargos"][0]["argv"][1:] == CARGO[2:], "actual Cargo command")
    messages = [json.loads(x) for x in r.stdout.splitlines()]
    need(
        messages[-1] == {"reason": "build-finished", "success": expected != 101}
        and r.returncode == (101 if expected == 101 else 0),
        ("ordinary exit", tag, r.returncode),
    )
    rustcs = [(o["crate"], o["mode"]) for o in native["rustcs"]]
    need(
        len(rustcs) == 1 and rustcs[0][0] == "ruff" and native["wild"] == 1,
        ("ordinary native roster", tag, rustcs, native["wild"]),
    )
    if full is not None:
        need(rustcs[0][1] == ("full" if full else "link-only"), ("cached/forced", tag, rustcs))
    wild = native["wild_processes"][0]
    need(
        Path(wild["output"]).name == "ruff"
        and "-lgcc_s" in wild["argv"]
        and "-L" + str(side.parent) in wild["argv"],
        ("wrong native search", tag),
    )
    resolved = {}
    for entry in io["wild_libgcc_reads"]:
        path = Path(entry["path"])
        if str(path) not in resolved:
            resolved[str(path)] = {"identity": file_id(path), "sha256": b.sha(path)}
    save(where / "native-provider-files.json", resolved)
    if side.exists():
        need(io["wild_opens"], ("real Wild did not open the provider", tag, side))
    else:
        need(
            io["wild_missing"] and any(Path(name).name == "libgcc_s.so" for name in resolved),
            ("missing Wild search or selected system provider", tag, side),
        )
    if tag == "unchanged-B":
        save(where / "fingerprint.json", fingerprint(r.stderr))
        need(
            {r["path"] for r in io["cargo_records"]}
            & {k for k, v in origins.items() if v["chain"]},
            "no authenticated marked producer opened by physical Cargo",
        )
    if expected == 101:
        text = r.stdout + r.stderr
        need(
            b"libgcc_s.so" in text
            and (b"linking with" in text or b"linker command failed" in text),
            ("not a genuine link failure", tag),
        )
        result = {"status": 101, "cli": None}
    else:
        graph, dirty = original.historical.roster(messages)
        need(
            len(graph) == 375 and [o["name"] for o in dirty] == ["ruff"],
            ("not 374 fresh", tag, dirty),
        )
        exe = WORK / "target/debug/ruff"
        run = subprocess.run([exe, "--version"], env=env, cwd=TREE, capture_output=True, timeout=45)
        for n, d in (("stdout", run.stdout), ("stderr", run.stderr)):
            (where / ("version." + n)).write_bytes(d)
        need(
            run.returncode == expected,
            ("linked Ruff runtime", tag, run.returncode, expected, run.stdout[:250]),
        )
        data = b.sha(exe)
        need(
            (data == healthy) == (expected == 0), ("native image did not match runtime change", tag)
        )
        if expected == 0:
            need(run.stdout == b"ruff 0.16.7\n", "wrong Ruff version")
            detail = subprocess.check_output(
                [exe, "version", "--output-format", "json"], env=env, cwd=TREE
            )
            (where / "version-detail.json").write_bytes(detail)
            need(
                json.loads(detail)["commit_info"]["commit_hash"] == original.kit.REVS["B"],
                "wrong Ruff incarnation",
            )
        result = {
            "status": 0,
            "cli": data,
            "runtime": run.returncode,
            "typed": original.historical.commit(graph),
            "fresh": 374,
        }
    need(before == unchanged_source(), "unchanged Ruff Git bytes or timestamps moved")
    save(where / "result.json", dict(**result, rustcs=rustcs, wild=1, provider=sd, git=before))
    return result


def force_root(native, dest):
    wild = native["wild_processes"]
    root = next(Path(row["output"]) for row in reversed(wild) if Path(row["output"]).name == "ruff")
    cache = root.with_suffix(".rlink")
    need(
        cache.parent.is_relative_to(WORK / "target") and cache.is_file() and not cache.is_symlink(),
        ("active root-only codegen recipe missing", cache),
    )
    info = file_id(cache)
    cache.rename(dest)
    return {"from": str(cache), "sha256": b.sha(dest), "before": info}


def main(source):
    frozen_inputs()
    save(
        OUT / "registration.json",
        dict(
            ref=os.environ["GITHUB_SHA"],
            plan=b.sha(HERE / "PLAN.md"),
            source=b.spec(),
            cargo=b.CARGO,
            run=os.environ["GITHUB_RUN_ID"],
            earlier_run=41200174886,
            earlier_head=FROZEN,
            boot=Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        ),
    )
    shutil.copy2(HERE / "PLAN.md", OUT / "PLAN.md")
    calls = file_trace.receiver(source / "scripts/branch-return-source/native_trace.py")
    registry = b.acquire(source)
    from selftest import from_original

    save(
        OUT / "qualified-source-receiver.json",
        from_original(b.ROOT / "source-transfer/branch-return-source-observations.zip", calls),
    )
    start = OUT / "active"
    start.mkdir()
    env = b.activate("Foff", registry, start)
    b.fresh_outputs()
    b.prepare_inputs(original.kit, env)
    history = OUT / "history"
    history.mkdir()
    states = {}
    for phase, branch in (("cold-A", "A"), ("first-B", "B"), ("return-A", "A"), ("return-B", "B")):
        states[phase], active, _ = bare(phase, branch, history / phase, env)
        if phase == "cold-A":
            cold = active
    need(
        states["cold-A"]["cli"] == states["return-A"]["cli"]
        and states["first-B"]["cli"] == states["return-B"]["cli"] != states["return-A"]["cli"],
        "branch identity",
    )
    origins = records.collect((WORK / "target", WORK / "build"), cold, OUT / "blocking-records")
    side = Path(states["return-B"]["psm"])
    original_healthy = states["return-B"]["cli"]
    first = driver(
        history / "unchanged-B",
        env,
        "unchanged-B",
        side,
        origins,
        0,
        False,
        original_healthy,
        calls,
    )
    need(first["typed"] == states["return-B"]["typed"], "different 375-unit graph")
    save(history / "unchanged-B" / "post-positive-readback.json", records.unchanged(origins))
    held = b.ROOT / "same-path-reference"
    held.mkdir()

    def preserve_cli():
        current = WORK / "target/debug/ruff"
        digest = b.sha(current)
        original.native.preserve(
            current, {"whole": digest, "size": current.stat().st_size}, held, OUT / "native-bodies"
        )
        return held / digest

    healthy_image = preserve_cli()
    probe = held / "exit83.o"
    subprocess.run(["as", "--64", HERE / "provider.S", "-o", probe], check=True)
    gcc = Path(
        subprocess.check_output(["gcc", "-print-file-name=libgcc_s.so"], text=True).strip()
    ).resolve(strict=True)
    good = f"INPUT ( {probe} {gcc} )\n".encode()
    bad = (b"OHM_INVALID_NATIVE (!\n").ljust(len(good), b" ")
    save(
        OUT / "provider.json",
        dict(
            path=str(side),
            good=good.decode(),
            bad=bad.decode(),
            object=b.sha(probe),
            assembler_source=b.sha(HERE / "provider.S"),
            system_libgcc=str(gcc),
            system_sha=b.sha(gcc),
        ),
    )
    results = {}
    put(side, good)
    results["valid"] = driver(
        history / "valid", env, "valid", side, origins, 83, False, original_healthy, calls
    )
    altered_image = preserve_cli()
    put(side, bad, good)
    results["bad"] = driver(
        history / "bad", env, "bad", side, origins, 101, False, original_healthy, calls
    )
    put(side, good, bad)
    results["repair"] = driver(
        history / "repair", env, "repair", side, origins, 83, None, original_healthy, calls
    )
    need(
        subprocess.run(["cmp", "-s", WORK / "target/debug/ruff", altered_image]).returncode == 0,
        "repaired provider ELF mismatch",
    )
    need(side.read_bytes() == good, "wrong provider removal")
    side.unlink()
    results["remove"] = driver(
        history / "remove", env, "remove", side, origins, 0, None, original_healthy, calls
    )
    need(
        subprocess.run(["cmp", "-s", WORK / "target/debug/ruff", healthy_image]).returncode == 0,
        "removed provider ELF mismatch",
    )

    b.fresh_outputs()
    empty = OUT / "independent-empty-B"
    ref, independent, _ = bare("cold-B", "B", empty, env)
    need(
        ref["typed"] == first["typed"]
        and ref["reader"] == states["return-B"]["reader"]
        and subprocess.run(["cmp", "-s", WORK / "target/debug/ruff", healthy_image]).returncode == 0
        and str(side) == ref["psm"],
        "independent same-path empty B differed",
    )
    controls = OUT / "independent-full-root"
    controls.mkdir()
    parked_recipes = WORK / "parked-native-recheck-recipes"
    parked_recipes.mkdir()
    put(side, good)
    for label, expected in (("valid", 83), ("bad", 101)):
        if label == "bad":
            put(side, bad, good)
        parked = parked_recipes / ("forced-" + label + ".rlink")
        proof = force_root(independent, parked)
        save(controls / (label + "-parked.json"), proof)
        measured = driver(
            controls / label, env, label, side, {}, expected, True, original_healthy, calls
        )
        need(
            measured == results[label], ("warm versus forced root", label, measured, results[label])
        )
        if expected == 83:
            need(
                subprocess.run(["cmp", "-s", WORK / "target/debug/ruff", altered_image]).returncode
                == 0,
                "forced native ELF differs",
            )
    need(side.read_bytes() == bad, "wrong final provider")
    side.unlink()
    b.verify_physical(b.SDK, registry["F"])
    save(
        OUT / "complete.json",
        dict(
            status="unscored",
            source_manifest=b.spec()["manifest"],
            states=states,
            first=first,
            empty=ref,
            provider_results=results,
            emitted_records=len(origins),
            naturally_reachable_markers={k: v["chain"] for k, v in origins.items() if v["chain"]},
        ),
    )


if __name__ == "__main__":
    try:
        main(Path(sys.argv[1]))
    except BaseException:
        if OUT.is_dir():
            (OUT / "failure.txt").write_text(traceback.format_exc())
        raise
