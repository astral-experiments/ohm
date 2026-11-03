"""Challenge an actual Ruff incremental session with the other physical compiler's authentic record."""

from collections import Counter
from contextlib import ExitStack
import gzip
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import stock_scope as scope
import stock_artifacts
import stock_gate
import migrate_index
from stock_runtime import StockRuntime
import artifacts as guarded_artifacts
import durable
import worker

acquire, tracking = worker.acquire, worker.tracking
study, pilot, replay = acquire.study, acquire.pilot, acquire.replay
need, save, sha = scope.base.need, scope.base.save, scope.base.sha


def rustc_traces(names, kernel, sdk):
    parents = {int(k): int(v) for k, v in kernel["tree"]["parents"].items()}
    compilers = {x["pid"]: x for x in kernel["compilers"] if x["kind"] == "full"}
    executions = {
        x["pid"] for x in kernel["tree"]["processes"] if x["path"] != str(Path(sdk) / "bin/rustc")
    }
    owners = []
    for name in sorted(names):
        owner = tracking.identity(int(Path(name).suffix[1:]), parents, compilers, executions)
        if (
            owner
            and owner["name"] == "ruff_workspace"
            and owner["exec"] == str(Path(sdk) / "bin/rustc")
        ):
            owners.append(name)
    need(owners, "the historical real Ruff compiler has no enrolled kernel trace")
    return owners


def extract_donor(archive, dest, version, wanted):
    dest.mkdir()
    with zipfile.ZipFile(archive) as z:
        infos = z.infolist()
        need(len({i.filename for i in infos}) == len(infos), "duplicate donor member")

        def read(name, cap):
            info = z.getinfo(name)
            need(0 < info.file_size <= cap, "unbounded donor input")
            return z.read(info)

        case = "physical/durability/object-corrupt/"
        raw = gzip.decompress(read(case + "original-work-products.bin.gz", 32 << 20))
        obj = gzip.decompress(read(case + "original-old-object.o.gz", 32 << 20))
        need(len(raw) < 64 << 20 and len(obj) < 64 << 20, "excess native donor")
        proof = json.loads(read(case + "old/durability.json", 2 << 20))["old_object_mutation"]
        need(proof["cgu"] == wanted, "different actual captured native victim")
        slot, _, body = migrate_index.open_entry(raw, version, obj, slot=proof["record"]["slot"])
        need(
            body[-32:].hex() == proof["record"]["bound_blake3"]
            and sha256(raw).hexdigest() == proof["record"]["index"],
            "incorrect original deep seal",
        )
        (dest / "work-products.bin.gz").write_bytes(gzip.compress(raw, mtime=0))
        (dest / "old-object.o.gz").write_bytes(gzip.compress(obj, mtime=0))
        phases = json.loads(read("physical/option/acquired.json", 4 << 20))["C"]
        reference = {}
        for stage, key in (("old", "old"), ("new", "clean-new")):
            owner = phases[key]["owner_archive"]["sha256"]
            zbody = read("physical/owner-archives/" + owner + ".gz", 512 << 20)
            parsed = durable.member_map(gzip.decompress(zbody))
            need(
                parsed["raw_sha256"] == owner and len(parsed["objects"]) == 125,
                "not an actual independently clean Ruff 125-CGU archive",
            )
            path = dest / (stage + "-owner.rlib.gz")
            path.write_bytes(zbody)
            reference[stage] = {"elf": phases[key]["elf"], "archive": parsed}
        physical = json.loads(read("physical/physical-roles.json", 1 << 20))
        receipt = {
            "version": version,
            "victim": wanted,
            "slot": slot,
            "sha256": sha256(obj).hexdigest(),
            "kit": {k: v["sha"] for k, v in physical["kits"]["C"].items()},
            "index": sha256(raw).hexdigest(),
            "reference": reference,
        }
        save(dest / "verified.json", receipt)
        return obj, raw, receipt


def donor_sources(folder, enrollment):
    ref = enrollment["admissions"]["C3b_native"]
    run = int(os.environ["GITHUB_RUN_ID"])
    head = os.environ["GITHUB_SHA"]
    prior_path, new_path = folder / "C3b.zip", folder / "Stock4.zip"
    previous = guarded_artifacts.receive(
        ref["run"], ref["qa"], "admit", 1, "raw", prior_path, 2 << 30, previous=True
    )
    need(previous == ref["option_raw"], "not the immutable prior C3b native admission")
    current = stock_artifacts.receive(run, head, "admit", 1, "raw", new_path, 2 << 30)
    return {"C3b": (prior_path, previous, 3), "Stock4": (new_path, current, 4)}


def run(source):
    enrollment = scope.bind()
    ref = enrollment["admissions"]["C3b_native"]
    run_dir, evidence, _ = worker.census.paths()
    run_dir.mkdir()
    evidence.mkdir()
    out = evidence / "physical"
    out.mkdir()
    native = out / "migration"
    native.mkdir()
    admission = stock_gate.check(
        int(os.environ["GITHUB_RUN_ID"]),
        os.environ["GITHUB_SHA"],
        native / "prior-native.json",
        previous=False,
        migration=False,
    )
    for n in ("native-bodies", "owner-archives", "workproduct-indices"):
        (out / n).mkdir()
    inputs = Path(os.environ["RUNNER_TEMP"]) / "placement-qualified-sdks"
    older = inputs.with_name("placement-previous-sdks")
    root = run_dir / "actual-ruff"
    root.mkdir()
    downloads = run_dir / "real-native-inputs"
    downloads.mkdir()
    donors = donor_sources(downloads, enrollment)
    models = {}
    for name, (path, receipt, version) in donors.items():
        models[name] = extract_donor(path, native / ("donor-" + name), version, ref["cross_victim"])
        save(native / ("origin-" + name + ".json"), receipt)
    need(
        models["Stock4"][0] == models["C3b"][0],
        "physically different complete prior native objects",
    )
    with scope.product("Stock4"), ExitStack() as stack:
        stack.enter_context(patch.object(worker.transport, "BRANCH", scope.BRANCH))
        stack.enter_context(
            patch.object(
                worker.runtime, "Runtime", lambda w, i, o, t: StockRuntime(w, i, o, t, older)
            )
        )
        cpus, kit = worker.setup(root, out, inputs)
        current_boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        need(
            current_boot not in {x["boot"] for x in admission["admissions"].values()}
            and all(
                {k: v["sha"] for k, v in kit.refs[scope.INTERNAL[r]].items()} == models[r][2]["kit"]
                for r in ("Stock4", "C3b")
            ),
            "wrong or reused native migration environment",
        )
        project = root / "workflow-option"
        project.mkdir()
        repo, work, client, donor = [
            project / n for n in ("ruff", "work", "consumer", "registry-donor")
        ]
        work.mkdir()
        client.mkdir()
        donor.mkdir()
        command = acquire.source_entry(source, "option")["command"]
        pilot.new_tree(source, repo, study.OLD)
        shutil.copyfile(
            scope.HERE.parent / "ruff-workspace-option-edit/client.rs", client / "option-client.rs"
        )
        (client / "bad-option-client.rs").write_bytes(study.BAD_CLIENT)
        gold = study.source_pair(source)
        env = kit.base | {
            "CARGO_HOME": str(work / "cargo-home"),
            "CARGO_TARGET_DIR": str(work / "target"),
            "CARGO_BUILD_BUILD_DIR": str(work / "build"),
        }
        registry = {
            r["name"] + "-" + r["version"] + ".crate": r["checksum"]
            for r in tomllib.loads((source / "Cargo.lock").read_text())["package"]
            if "checksum" in r
        }
        subprocess.run(
            ["cargo", "+ohm", "fetch", "--locked"],
            env=kit.base | {"CARGO_HOME": str(donor)},
            cwd=source,
            check=True,
        )
        need(pilot.registry(donor) == registry, "changed locked registry")
        observed = {}
        for foreign, dest in (("C3b", "Stock4"), ("Stock4", "C3b")):
            kit.select(scope.INTERNAL[dest])
            where = native / (foreign + "-to-" + dest)
            where.mkdir()
            own = models[dest][2]
            fobj, fraw, fd = models[foreign]
            victim = ref["cross_victim"]
            expected_hits = set(ref["hit"]["new"]) - {victim}
            before = study.write_source(repo, study.OLD, False)
            worker.guards.admit(worker.guards.resources(work, where), entry=True)
            phases = {}
            with replay.empty_roots(work, where):
                target_home = work / "cargo-home/registry"
                target_home.mkdir(parents=True)
                for n in ("index", "cache"):
                    subprocess.run(
                        ["cp", "-a", "--reflink=auto", donor / "registry" / n, target_home / n],
                        check=True,
                    )
                subprocess.run(
                    ["cargo", "+ohm", "fetch", "--locked", "--offline"],
                    env=env,
                    cwd=repo,
                    check=True,
                )
                need(pilot.registry(work / "cargo-home") == registry, "different fresh registry")
                graph = pilot.unit_graph(command, env, repo, where, "option")
                witness = where / "original-inode.o"
                for phase, rev in (("old", study.OLD), ("new", study.NEW)):
                    loc = where / phase
                    signature = study.write_source(repo, rev, False)
                    with patch.object(
                        tracking, "EXTRA", (*tracking.EXTRA, "link", "linkat")
                    ), tracking.add_file_calls(worker.guards, loc):
                        _, roster, _, _, _, _ = worker.runtime.visit(
                            kit,
                            loc,
                            work,
                            repo,
                            env,
                            command,
                            0,
                            score=False,
                            cold=phase == "old",
                            observe=phase == "new",
                        )
                    need(
                        signature == study.source_state(repo, rev, False),
                        "historical source changed during Cargo",
                    )
                    lines = replay.cargo_rows((loc / "outer.stdout").read_bytes())
                    products = study.results(lines, True)
                    ids = [
                        acquire.e2e.artifact_key(
                            v["package_id"], v["target"], v["features"], v["profile"]["test"]
                        )
                        for v in products
                    ]
                    need(
                        Counter(ids) == graph[0]
                        and (
                            all(not v["fresh"] for v in products)
                            if phase == "old"
                            else roster == {"rustc": [["full", "ruff_workspace", 1]], "linkers": []}
                        ),
                        "different native tasks",
                    )
                    check = pilot.native.client(
                        loc, lines, products, client, work, env, gold[rev], out / "native-bodies"
                    )
                    owner = study.artifact(products, study.OWNER)
                    kept = worker.support.physical.keep(owner, out / "owner-archives", b"!<arch>\n")
                    parsed = durable.member_map(owner.read_bytes())
                    need(
                        check["sha256"] == own["reference"][phase]["elf"]
                        and parsed["objects"] == own["reference"][phase]["archive"]["objects"]
                        and kept["sha256"] == parsed["raw_sha256"],
                        "different native clean objects or executable",
                    )
                    selected = tracking.read(loc, kit.sdk)
                    save(loc / "source-selection.json", selected)
                    names = lambda rows: sorted(
                        x["cgu"] for x in rows if x["owner"] == "ruff_workspace"
                    )
                    hits = names(selected["renames"])
                    emitted = names(selected["ordinary_native_object_writes"])
                    if phase == "old":
                        need(not hits, "nonempty initial compilation")
                        obj = durable.object_dict(tracking.inc_root(loc, "ruff_workspace"))[victim]
                        os.link(obj, witness)
                        need(
                            witness.samefile(obj)
                            and obj.read_bytes() == fobj
                            and parsed["objects"][victim] == sha(obj),
                            "source, incumbent and archived old ELF differ",
                        )
                        path = obj.parent / "work-products.bin"
                        original = path.read_bytes()
                        after, proof = migrate_index.swap(
                            original, own["version"], fobj, fraw, fd["version"], fd["slot"]
                        )
                        (where / "before.bin.gz").write_bytes(gzip.compress(original, mtime=0))
                        (where / "after.bin.gz").write_bytes(gzip.compress(after, mtime=0))
                        durable.detached_replace(path, after, where / "physical-index-change.json")
                        need(
                            path.read_bytes() == after and witness.samefile(obj),
                            "incorrectly published private challenge",
                        )
                        save(where / "challenge.json", proof)
                    else:
                        need(
                            set(hits) == expected_hits
                            and victim in emitted
                            and not (set(hits) & set(emitted))
                            and len(set(hits) | set(emitted)) == ref["dirty_total"]
                            and witness.read_bytes() == fobj,
                            "incompatible record accepted or other native work changed",
                        )
                        with ExitStack() as files:
                            owned = rustc_traces(
                                (loc / "trace").glob("exec.*"),
                                json.loads((loc / "kernel.json").read_bytes()),
                                kit.sdk,
                            )
                            traces = [(p.name, files.enter_context(p.open("rb"))) for p in owned]
                            index_read = migrate_index.kernel_read(traces, str(path))
                        save(
                            where / "kernel-read.json",
                            {"original": str(path), "path_to_successful_open": index_read},
                        )
                    phases[phase] = {
                        "source": rev,
                        "selection": sha(loc / "source-selection.json"),
                        "hits": hits,
                        "emitted": emitted,
                        "archive": kept["sha256"],
                        "reader": check["sha256"],
                        "real_roster": roster,
                    }
            observed[foreign + "-to-" + dest] = phases
        kit.finish()
        save(
            native / "complete.json",
            {
                "schema": "selected-genuine-cross-index-1",
                "run": int(os.environ["GITHUB_RUN_ID"]),
                "qa": os.environ["GITHUB_SHA"],
                "boot": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
                "source": enrollment["source"],
                "cpus": cpus,
                "counter_samples": 0,
                "true_directions": observed,
                "physical_roles": sha(out / "physical-roles.json"),
                "study": sha(scope.HERE / "selected-study.json"),
            },
        )


if __name__ == "__main__":
    run(Path(sys.argv[1]).resolve(strict=True))
