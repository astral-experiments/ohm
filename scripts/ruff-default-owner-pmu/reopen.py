"""Rebuild the default-mode first-A instruction ledger from the retained original."""

import argparse
from functools import partial
import gzip
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import zipfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "branch-storage-e-confirmation/review"))
import replay_elf
import replay_metrics
import replay_native
import acquire
import common as c
import instrument
import ownership


class Directory:
    def __init__(self, path):
        self.path = path.resolve(strict=True)

    def open(self, name):
        p = self.path / name
        c.need(p.resolve(strict=True) == p and p.is_relative_to(self.path), "untrusted path")
        return p.open("rb")

    def read(self, name):
        with self.open(name) as f:
            return f.read()

    def namelist(self):
        return [str(p.relative_to(self.path)) for p in self.path.rglob("*") if p.is_file()]


def record(z, name):
    data = z.read(name)
    return json.loads(gzip.decompress(data) if name.endswith(".gz") else data)


def source_state(state, branch, bad):
    c.need(
        state["branch"] == branch
        and state["rev"] == c.EXPECTED[branch]
        and state["tree"] == c.TREES[branch]
        and state["invalid"] is bad
        and state["parser"] == c.PARSER_SHAS[bad],
        "unregistered source or parser",
    )
    ref = ".git/refs/heads/" + c.BRANCHES[branch]
    expected = {".git/HEAD": "ref: refs/heads/" + c.BRANCHES[branch], ref: c.EXPECTED[branch]}
    c.need(set(state["watched"]) == set(expected), "missing watched Git input")
    for key, string in expected.items():
        digest, ino, mtime, ctime = state["watched"][key]
        c.need(
            digest == hashlib.sha256((string + "\n").encode()).hexdigest() and min(ino, mtime, ctime) > 0,
            "wrong physical watched Git input",
        )


def read_subject(z, head, previous):
    en = record(z, "enrollment.json")
    cat = record(z, "catalog.json")
    env = dict(
        GITHUB_RUN_ID=str(en["run"]),
        GITHUB_REPOSITORY=c.REPO,
        GITHUB_REF="refs/heads/" + c.BRANCH,
        GITHUB_SHA=head,
        REVIEWED_HEAD=head,
        GITHUB_RUN_ATTEMPT="1",
        GITHUB_JOB="diagnostic",
        RUNNER_NAME=en["runner"],
    )
    c.need(
        (previous is None or cat["excluded"] == previous)
        and acquire.enrollment(
            cat["prior"],
            cat["jobs"],
            cat["artifacts"],
            cat["excluded"],
            cat["current"],
            cat["this_jobs"],
            env,
            en["boot"],
        )
        == en,
        "source/host enrollment",
    )
    return (en, *read_product(z))


def read_product(z):
    c.need(record(z, "asset.json") == c.SDK["asset"], "wrong published release")
    sdk = record(z, "sdk.json")
    c.need(
        sdk == record(z, "sdk-after.json") and set(sdk) == set(c.SDK["members"]) and len(sdk) == 79,
        "changed or incomplete native package",
    )
    for name, (_, mode, size, digest) in c.SDK["members"].items():
        v = sdk[name]
        c.need(
            len(v) == 7 and v[0] == digest and v[3:5] == [mode, size] and min(v[1], v[2], v[5], v[6]) > 0,
            "wrong installed SDK member",
        )
    observed = record(z, "execution-environment.json")
    e = observed["env"]
    work = Path(e["CARGO_TARGET_DIR"]).parent
    root = work.parent
    c.need(
        work.is_absolute()
        and work.name == "work"
        and root.name == "ohm-branch-object-qa"
        and ".." not in root.parts,
        "wrong canonical subject root",
    )
    home = root / "home"
    sysroot = home / ".rustup/toolchains/ohm"
    expected_env = dict(
        HOME=str(home),
        PATH=str(home / ".cargo/bin") + ":/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        RUSTUP_HOME=str(home / ".rustup"),
        RUSTUP_AUTO_INSTALL="0",
        CARGO_HOME=str(home / ".cargo"),
        CARGO_TARGET_DIR=str(work / "target"),
        CARGO_BUILD_BUILD_DIR=str(work / "build"),
        CARGO_NET_OFFLINE="true",
        CARGO_CACHE_AUTO_CLEAN_FREQUENCY="never",
        CARGO_TERM_COLOR="never",
        LC_ALL="C",
        LD_LIBRARY_PATH=str(sysroot / "lib"),
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL="/dev/null",
    )
    c.need(e == expected_env, "different compiler option or build namespace")
    for tool, commit in (("cargo", c.SDK["cargo"]), ("rustc", c.SDK["rust"]), ("rustdoc", c.SDK["rust"])):
        c.need(
            commit in observed["versions"][tool] and "ohm-1.99.0-22" in observed["versions"][tool],
            "wrong signed release version",
        )
    (driver,) = [name for name in sdk if name.startswith("lib/librustc_driver")]
    loaders = [
        s.split(" => ")[1].split()[0]
        for s in observed["ldd"].splitlines()
        if "librustc_driver" in s and " => " in s
    ]
    c.need(
        observed["driver"] == driver
        and len(loaders) == 1
        and os.path.normpath(loaders[0]) == str(sysroot / driver),
        "wrong dynamic driver",
    )
    physical = record(z, "cpu-selection.json")
    c.need(
        len({tuple(key) for key, _ in physical}) == len({cpu for _, cpu in physical}) == 4
        and sorted(cpu for _, cpu in physical) == observed["cpus"],
        "four physical cores",
    )
    selectors = record(z, "selectors.json")
    hashes = record(z, "selector-sha.json")
    c.need(
        set(selectors) == set(hashes) == {"rustc", "cc", "collect2", "wild"}
        and len({tuple(v[:2]) for v in selectors.values()}) == 4,
        "physical role selectors",
    )
    (wild,) = [n for n in sdk if n.endswith("/wild-ld/ld.bfd")]
    for role, name in (("rustc", "bin/rustc"), ("wild", wild)):
        c.need(
            selectors[role] == [*sdk[name][1:3], str(sysroot / name)] and hashes[role] == sdk[name][0],
            "different physical signed tool",
        )
    c.need(
        all(len(x) == 64 for x in hashes.values()) and all(Path(v[2]).is_absolute() for v in selectors.values()),
        "native tool identity",
    )
    inputs = record(z, "ruff-inputs.json")
    changed = inputs["changed"]
    c.need(
        inputs["commits"] == c.EXPECTED
        and inputs["trees"] == c.TREES
        and len(changed) == 169
        and len(inputs["archives"]) == 505
        and hashlib.sha256(
            (json.dumps(inputs["archives"], sort_keys=True, separators=(",", ":")) + "\n").encode()
        ).hexdigest()
        == "cd586cd0fe2b3b6b6529b6c8d8f157164073edc3b4e24f09b0ac5be88897193c"
        and inputs["lock"] == "839edc8250480bb523619b8d24bd57176a6e1f57c152cca85c5adc61ea5f94eb"
        and hashlib.sha256(("\n".join(changed) + "\n").encode()).hexdigest()
        == "6d3a6f54cd364cb62a12fdcaa65f7aea6f45639ec4c75f2660a6663decf8b84d",
        "Ruff source edit or registry input",
    )
    guard = record(z, "resource/resources.json")
    c.need(
        guard["refusal"] is None
        and guard["exit"] == 0
        and guard["minimum"]["effective"] >= 8 << 30
        and guard["minimum"]["work"] >= 4 << 30
        and guard["minimum"]["receipts"] >= 6 << 30,
        "resource refusal",
    )
    return root, work, selectors, sdk, changed


def actual_externs(z, where, products, root):
    deps = []
    for name in ("ruff_python_ast", "ruff_python_parser"):
        (path,) = [
            f
            for p in products
            if p["target"]["name"] == name and p["target"]["kind"] == ["lib"]
            for f in p["filenames"]
            if f.endswith(".rlib")
        ]
        deps.append(name + "=" + path)
    for role in ("reader-compile", "layout-64", "layout-56"):
        args = record(z, f"{where}/{role}.json.gz")["argv"]
        c.need(
            args[:2] == ["rustc", "+ohm"] and [v for k, v in zip(args, args[1:]) if k == "--extern"] == deps,
            "foreign typed-client dependency",
        )
        if role == "reader-compile":
            c.need(args[-2:] == ["-o", str(root / "full-cli-reader/reader")], "different consumer output")
    c.need(
        record(z, f"{where}/reader-run.json.gz")["argv"] == [str(root / "full-cli-reader/reader")],
        "different consumer executed",
    )


def bounded_files(z, target):
    total = 0
    selected = 0
    for name in z.namelist():
        if not name.startswith(("calibration/", "counter-programs/", "attributed/A/trace/")) or name.endswith("/"):
            continue
        leaf = Path(name)
        c.need(not leaf.is_absolute() and ".." not in leaf.parts and str(leaf) == name, "unsafe counter member")
        p = target / leaf
        p.parent.mkdir(parents=True, exist_ok=True)
        with z.open(name) as src, p.open("xb") as out:
            data = src.read((4 << 20) + 1)
            c.need(0 < len(data) <= 4 << 20, "counter file length")
            total += len(data)
            selected += 1
            c.need(total <= 32 << 20 and selected <= 1800, "counter evidence bound")
            out.write(data)


def thresholds(whole, spend):
    c.need(
        len(whole) == 3 and min(whole) > 0 and 50 * (max(whole) - min(whole)) <= min(whole),
        "ordinary/attribution whole drift exceeds 2%",
    )
    return {
        k: {
            "instructions": v,
            "budget": (
                "below half of every observed denominator"
                if 2 * v < min(whole)
                else "at least half of every observed denominator" if 2 * v >= max(whole) else "straddles half"
            ),
        }
        for k, v in spend.items()
    }


def replay(z, temp, head, previous, collector, contract):
    en, root, work, selectors, sdk, changed = read_subject(z, head, previous)
    c.need(
        record(z, "collection.json")
        == {
            "histories": {k: list(v) for k, v in c.PHASES.items()},
            "known_unrelated_native_bug": True,
            "hardware_scope": "first-A only",
        },
        "refused or incomplete cohort",
    )
    c.need(
        "refusal.txt" not in z.namelist() and "attribution-refusal.txt" not in z.namelist(),
        "a native or counting refusal was archived",
    )
    topo, pmu = instrument.compile_sources(collector, contract, temp / "source")
    bounded_files(z, temp)
    cal = pmu.calibration(temp / "counter-programs", temp, replay=True)
    results = {}
    refs = {}
    errors = []
    dirties = []
    clocks = []
    bodies = {}
    bytes_at = {}
    sources = {}
    for lane, phases in c.PHASES.items():
        for phase in phases:
            w = f"{lane}/{phase}"
            branch = "B" if phase == "B" else "A"
            bad = phase == "invalid"
            if phase == "B" or lane == "reference" or (lane == "empty-invalid" and bad):
                nodes = record(z, w + "/empty-roots.json")
                c.need(
                    set(nodes) == {str(work / "target"), str(work / "build")}
                    and all(len(n) == 3 and n[0] > 0 and n[1] > 0 and n[2] == [] for n in nodes.values())
                    and len({tuple(n[:2]) for n in nodes.values()}) == 2,
                    "independent starting roots were not empty",
                )
            before = record(z, w + "/source-before.json")
            after = record(z, w + "/source-after.json")
            source_state(before, branch, bad)
            c.need(before == after, "source changed during measurement")
            if phase == "unchanged":
                c.need(sources["attributed/A"] == before, "unchanged source/refs differed")
            sources[w] = before
            inv = record(z, w + "/invocation.json")
            cmd = list(c.CMD)
            mode = "ordinary"
            if phase == "A" and lane.startswith("plain-"):
                mode = "plain"
                cmd = [str(root / "counter-kit/bin/plain"), str(root / "logs" / w / "clock.json"), *cmd]
            elif phase == "A" and lane == "attributed":
                mode = "tree"
                cmd = [
                    str(root / "counter-kit/bin/tree"),
                    str(root / "logs" / w / "trace"),
                    "tree",
                    *[selectors[k][2] for k in topo.ROLES],
                    *cmd,
                ]
            c.need(
                inv
                == {
                    "argv": cmd,
                    "cargo": c.CMD,
                    "cwd": str(root / "ruff"),
                    "expected": 101 if bad else 0,
                    "exit": 101 if bad else 0,
                },
                "different actual ordinary command",
            )
            rows = [json.loads(line) for line in gzip.decompress(z.read(w + "/cargo.stdout.gz")).splitlines()]
            z.read(w + "/cargo.stderr.gz")
            ownership.check_roots(rows, work)
            diag = ownership.typed(rows, bad)
            v = record(z, w + "/visit.json")
            c.need(
                v["branch"] == branch
                and v["source"] == c.EXPECTED[branch]
                and v["mode"] == mode
                and v["phase"] == phase
                and diag == record(z, w + "/diagnostic.json") == v["diagnostic"],
                "changed real diagnostic or visit",
            )
            ledger = record(z, w + "/path-inodes.json.gz")
            store = record(z, w + "/storage.json")
            bytes_at[w] = replay_metrics.allocation(ledger, store, record(z, w + "/allocation-readers.json"))
            if bad:
                c.need(
                    set(record(z, w + "/failed.json")) == set(store["failed_sessions"]),
                    "unaccounted abandoned session",
                )
                errors.append(diag)
                continue
            c.need(not store["failed_sessions"], "working session on success")
            if phase == "repair":
                grace = record(z, w + "/grace.json")
                c.need(
                    grace["sessions"] == record(z, lane + "/invalid/failed.json")
                    and grace["ready_ns"] >= grace["cutoff_ns"]
                    and grace["rustc_gc_grace_ns"] == 10_000_000_000,
                    "different repair roots",
                )
            graph, products = ownership.graph(rows)
            c.need(graph == record(z, w + "/roster.json.gz"), "different Cargo graph")
            desc = replay_native.native_verdict(z, w, branch)
            actual_externs(z, w, products, root)
            dirty = sorted(
                (p["package_id"], p["target"]["src_path"], p["target"]["name"], p["target"]["kind"], p["features"])
                for p in products
                if not p["fresh"]
            )
            c.need(
                v["cli"] == desc["cli"]["whole"]
                and v["reader"] == desc["reader"]["whole"]
                and v["dirty"] == len(dirty),
                "fresh counts or native file",
            )
            if lane == "reference" or phase == "B":
                c.need(len(dirty) == 375, "clean reference not an empty compile")
            if lane == "reference":
                refs[branch] = (graph, desc)
                # Reopen every complete executable and its mapped bytes independently.
                for role in ("cli", "reader"):
                    e = desc[role]
                    bodies[branch + "/" + role] = replay_elf.verify(
                        z,
                        "native-bodies/" + e["whole"] + ".zst",
                        e,
                        "ruff" if role == "cli" else "ohm_branch_reader",
                    )
            else:
                c.need((graph, desc) == refs[branch], "full clean ELF, diagnostic or graph differs")
            if phase != "A" or lane == "reference":
                continue
            dirties.append(dirty)
            if mode == "tree":
                trace = temp / "attributed/A/trace"
                ownership.signed_cargo_images(
                    trace, root / "home/.rustup/toolchains/ohm/bin/cargo", sdk["bin/cargo"][1:3]
                )
                results = topo.read(
                    trace,
                    selectors,
                    "tree",
                    component=partial(ownership.classify, root / "ruff", work, products, ledger),
                )
                ownership.early_children(trace, results)
                c.need(results == record(z, w + "/owner-raw.json"), "changed owner ledger")
                clock = results["whole"]
            else:
                clock = instrument.clock_value(record(z, w + "/clock.json"))
            c.need(clock == v.get("whole"), "different hardware read")
            clocks.append(clock)
    c.need(
        len(errors) == 2
        and errors[0] == errors[1]
        and len(dirties) == 3
        and dirties[0] == dirties[1] == dirties[2],
        "different error, repaired consumer or physical first-A work",
    )
    c.need(len({b["whole"] for b in bodies.values()}) == 4, "independent branches or native clients collapsed")
    changed_crates = {p.split("/")[1] for row in changed for p in row.split("\t")[1:] if p.startswith("crates/")}
    owners = results["owners"]
    eligible = []
    for owner in owners:
        path = Path(owner["src"])
        if path.is_relative_to(root / "ruff/crates"):
            crate = path.relative_to(root / "ruff/crates").parts[0]
            if crate not in changed_crates:
                eligible.append(owner)
    server = [o for o in owners if o["target"] == "ruff_server" and o["kind"] == ["lib"]]
    c.need(
        len(server) <= 1
        and len([t for t in map(json.loads, refs["A"][0]) if t[1:3] == ["ruff_server", ["lib"]]]) == 1,
        "missing or ambiguous server unit",
    )
    spend = {
        "ruff_server_outside_native_cc": sum(o["outside_cc"] for o in server),
        "all_source_directory_unchanged_workspace_rustcs_outside_native_cc": sum(o["outside_cc"] for o in eligible),
        "all_stock_wild_subtrees": sum(o["wild"] for o in owners),
    }
    return {
        "enrollment": en,
        "source": c.EXPECTED,
        "plain_before_attributed_plain_after": clocks,
        "instruction_budgets": thresholds(clocks, spend),
        "outside_all_selected_rustc": results["outside_rustcs"],
        "owners": owners,
        "native_references": bodies,
        "boundary_allocated_bytes": bytes_at,
        "calibrated_whole_windows": sum(len(v[0]) for v in cal["whole28"].values()),
        "calibrated_nested_windows": sum(len(v["whole"]["values"]) for v in cal["nested"].values()),
        "causal_speedup_measured": False,
    }


def official(value, zpath, head):
    run, job, a = (value[k] for k in ("run", "job", "artifact"))
    c.need(
        run["head_sha"] == head
        and run["head_branch"] == c.BRANCH
        and run["run_attempt"] == 1
        and run["event"] == "workflow_dispatch"
        and run["conclusion"] == "success"
        and run["status"] == "completed"
        and run["repository"]["full_name"] == c.REPO
        and run["path"] == ".github/workflows/ci.yml",
        "unqualified official run",
    )
    c.need(
        job["run_id"] == run["id"]
        and job["conclusion"] == "success"
        and job["name"] == "Signed GNU Ruff first-A instruction owners"
        and {s["name"] for s in job["steps"] if s["conclusion"] == "success"}
        >= {
            "Install the published GNU release",
            "Run three first-A histories",
            "Reopen original counters and native products",
        },
        "unqualified official job",
    )
    c.need(
        a["workflow_run"]["id"] == run["id"]
        and a["name"] == "signed-gnu-ruff-default-first-a-owners"
        and zpath.stat().st_size == a["size_in_bytes"]
        and a["digest"] == "sha256:" + c.sha(zpath),
        "incorrect official ZIP identity",
    )
    return run["id"], job["id"]


def main():
    arg = argparse.ArgumentParser(description=__doc__)
    src = arg.add_mutually_exclusive_group(required=True)
    src.add_argument("--directory", type=Path)
    src.add_argument("--zip", type=Path)
    arg.add_argument("--catalog", type=Path, help="trusted post-terminal official run, job and artifact JSON")
    arg.add_argument(
        "--excluded", type=Path, help="independently authenticated six prior boot descriptors, in position order"
    )
    arg.add_argument("--collector", type=Path, required=True)
    arg.add_argument("--contract", type=Path, required=True)
    arg.add_argument("--head", required=True)
    a = arg.parse_args()
    collector = a.collector.resolve()
    contract = a.contract.resolve()
    c.need(c.git(HERE, "rev-parse", "HEAD").decode().strip() == a.head, "wrong QA receiver revision")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp)
        if a.zip:
            c.need(a.catalog and a.excluded, "official archive needs independent enrollment")
            run, job = official(c.read(a.catalog), a.zip, a.head)
            with zipfile.ZipFile(a.zip) as z:
                names = z.namelist()
                c.need(
                    len(set(names)) == len(names) < 6000
                    and sum(i.file_size for i in z.infolist()) < 768 << 20
                    and all(
                        not Path(n).is_absolute()
                        and ".." not in Path(n).parts
                        and not stat.S_ISLNK(i.external_attr >> 16)
                        for n, i in zip(names, z.infolist(), strict=True)
                    ),
                    "unbounded official archive",
                )
                value = replay(z, path, a.head, c.read(a.excluded), collector, contract)
                c.need(value == record(z, "accepted.json"), "terminal replay differs from original worker result")
                c.need(
                    (run, job) == (value["enrollment"]["run"], value["enrollment"]["job"]),
                    "mixed official original",
                )
        else:
            value = replay(Directory(a.directory), path, a.head, None, collector, contract)
    print(json.dumps(value, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
