"""Run one signed baseline on one fresh boot. Counter denial or a semantic mismatch stops admission."""

import argparse
from functools import partial
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import traceback
import uuid

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import contract as c
import heavy
import inputs
import sampling
import support


def bad_input(root, label, clean, study):
    d = root / "receipts" / label
    d.mkdir(parents=True)
    src = root / "ruff" / c.GUARD_FILE
    original = src.read_bytes()
    c.require(
        subprocess.check_output(["git", "-C", root / "ruff", "show", "HEAD:" + c.GUARD_FILE])
        == original,
        "starting ruff_db source changed",
    )
    try:
        src.write_bytes(original + c.GUARD)
        if clean:
            study.s.fresh(root, registry=True)
        run = subprocess.run(
            c.CLI, env=study.s.env(root), cwd=root / "ruff", capture_output=True, timeout=3900
        )
        for name, data in [("stdout.jsonl.gz", run.stdout), ("stderr.gz", run.stderr)]:
            study.s.payload(d / name, data)
        inputs.save(
            d / "invocation.json",
            {
                "status": run.returncode,
                "command": c.CLI,
                "source": c.GUARD_FILE,
                "broken_sha256": inputs.sha(src),
            },
        )
        msgs = [json.loads(r) for r in run.stdout.splitlines()]
        errors = [
            r for r in msgs if r["reason"] == "compiler-message" and r["message"]["level"] == "error"
        ]
        c.require(
            run.returncode == 101
            and msgs[-1] == {"reason": "build-finished", "success": False}
            and len(errors) == 1,
            (label, "not an actual single Cargo error", run.returncode, len(errors)),
        )
        err = errors[0]["message"]
        (p,) = [s for s in err["spans"] if s["is_primary"]]
        c.require(
            err["code"]["code"] == "E0308"
            and p["file_name"] == c.GUARD_FILE
            and any(c.GUARD.strip().decode() in v["text"] for v in p["text"])
            and not any(
                v in (run.stdout + run.stderr).lower()
                for v in (b"internal compiler error", b"unexpectedly panicked")
            ),
            "unrelated invalid-unit or compiler failure",
        )
        return [
            err["code"]["code"],
            err["message"],
            p["file_name"],
            p["line_start"],
            p["column_start"],
        ]
    finally:
        src.write_bytes(original)
        c.require(src.read_bytes() == original, "guard repair failed")


def check_program(row, mode):
    t = row["test"]
    c.require(
        row["status"] == 0
        and not row["issues"]
        and t
        and t["valid_inventory"]
        and len(t["names"]) == {"original": 200, "reversed": 199}[mode]
        and set(t["runtime"]) == c.CASES[mode]
        and all(r == {"code": 0, "one_named": True} for r in t["runtime"].values()),
        ("test oracle", mode, row.get("issues")),
    )
    return t


def selectors(root, study, topology):
    enrolled = study.census(root, "trace/cold")
    grouped = study.s.env(root)
    raw = inputs.load(root / "receipts/trace/cold/execs.json.gz")
    gcc = Path(enrolled["paths"][4])
    collect = Path(
        subprocess.check_output([gcc, "-print-prog-name=collect2"], env=grouped, text=True).strip()
    ).resolve(strict=True)
    c.require(
        collect.is_absolute()
        and any(
            Path(e[2]) == collect and "-o" in e[3] and c.option(e[3], "-o") == enrolled["paths"][3]
            for e in raw
        ),
        "missing actual system collect2 on native e2e cold link",
    )
    paths = dict(
        rustc=enrolled["paths"][0], cc=str(gcc), collect2=str(collect), wild=enrolled["paths"][1]
    )
    return paths, {n: topology.location(Path(p)) for n, p in paths.items()}


def compare_oracle(actual, ref):
    return (actual["names"], actual["runtime"], actual["list_sha"], actual["elf"]["sha256"]) == (
        ref["names"],
        ref["runtime"],
        ref["list_sha"],
        ref["elf"]["sha256"],
    )


def sources(root, study, state):
    expected = study.ENROLL["e2e"]["reverse" if state == "reversed" else "original"]
    rows = {}
    for rel, oid in expected.items():
        p = root / "ruff" / rel
        if oid is None:
            c.require(not p.exists(), ("unexpected source file", rel))
            rows[rel] = None
        else:
            data = p.read_bytes()
            git = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
            c.require(git == oid, (rel, "historical blob bytes"))
            rows[rel] = {"sha256": hashlib.sha256(data).hexdigest(), "git": git, "bytes": len(data)}
    return rows


def preserve_vault(root):
    vault = root / "image-vault"
    if not vault.exists():
        return
    archive = root / "receipts/native-programs"
    archive.mkdir(exist_ok=True)
    for obj in vault.iterdir():
        dest = archive / (obj.name + ".zst")
        if not dest.exists():
            c.require(inputs.sha(obj) == obj.name, "native image race")
            subprocess.run(["zstd", "-q", "-3", "-T4", "-o", dest, obj], check=True)


def run_all(workspace, incoming, root):
    base, collector = workspace / "feature", workspace / "collector"
    c.require(
        os.environ["GITHUB_REPOSITORY"] == "astral-experiments/ohm"
        and os.environ["GITHUB_RUN_ATTEMPT"] == "1"
        and os.environ["GITHUB_REF"]
        == "refs/heads/charlie/qa-signed21-notebook-heavy-compiler-samples-20261031"
        and support.git(HERE, "rev-parse", "HEAD")
        == os.environ["GITHUB_SHA"]
        == os.environ["REVIEWED_HEAD"],
        "wrong registered ref, head or attempt",
    )
    # Never touch the registries/target of any other installation.
    c.require(
        root == Path(os.environ["RUNNER_TEMP"]) / "ohm-featureless-e2e" and not root.exists(),
        "canonical fresh root required",
    )
    private = Path(os.environ["RUNNER_TEMP"]) / "notebook-fanout-collector"
    study, pmu, topology = support.load_modules(base, collector, private)
    s = study.s
    study.s.unit_dir(root)
    out = root / "receipts"
    cas = out / "metadata-cas"
    cas.mkdir()
    boot_path = Path("/proc/sys/kernel/random/boot_id")
    boot = str(uuid.UUID(boot_path.read_text().strip()))
    start = {
        "run": int(os.environ["GITHUB_RUN_ID"]),
        "head": os.environ["GITHUB_SHA"],
        "reviewed_head": os.environ["REVIEWED_HEAD"],
        "attempt": 1,
        "boot": boot,
        "baseline_only": True,
        "orders": ["S1", "T", "S2"],
        "argv": c.CLI,
        "diagnostic_plan": inputs.sha(HERE / "PLAN.md"),
        "inputs": inputs.load(HERE / "sources.json"),
        "collector": c.COLLECTOR,
        "release_source": c.FEATURELESS,
    }
    inputs.save(out / "registration.json", start)
    tools = pmu.compilers(root)
    shutil.copytree(tools, out / "counter-programs")
    pmu.calibration(tools, out)
    try:
        perf = sampling.prepare(root, tools, out)
    except Exception as err:
        # Continue with the independent native-output experiment if this host cannot sample PMIs.
        perf = None
        inputs.save(out / "sampling-enrollment.json", {"admitted": False, "reason": repr(err)})
    else:
        inputs.save(out / "sampling-enrollment.json", {"admitted": True})
    s.source(root)
    inputs.save(
        out / "environment.json",
        {
            "cwd": str(root / "ruff"),
            "env": s.env(root),
            "eight_directories": {
                n: support.git(root / "ruff", "rev-parse", "HEAD:crates/" + n) for n in c.EIGHT
            },
        },
    )
    study.acquire(root, workspace, incoming / "selected", incoming / "signed", "strict")
    c.signed_closure(inputs.load(out / "sdk/complete-release.json.gz"))
    s.seed_registry(root)
    (out / "sdk/issuer").mkdir()
    stamp = study.observe.issuer(root, "sdk/issuer")
    s.fresh(root, registry=True)
    cold = study.panel.visit(root, study.PANEL, "trace", "cold", "original", stamp)
    check_program(cold, "original")
    paths, physical = selectors(root, study, topology)
    inputs.save(out / "selectors.json", physical)
    names, first_products = c.typed(
        gzip.decompress((out / "trace/cold/stdout.jsonl.gz").read_bytes()), root
    )
    inputs.save(out / "graph.json", names)
    history = {}
    comparisons = {}
    references = {}
    errors = {}
    for lane in ("S1", "T", "S2"):
        c.require(
            shutil.disk_usage(root).free > 5 * 2**30
            and str(uuid.UUID(boot_path.read_text().strip())) == boot,
            "changed boot or disk reserve",
        )
        if lane != "S1":
            s.fresh(root, registry=True)
            fresh = study.panel.visit(root, study.PANEL, lane, "cold", "original", stamp)
            check_program(fresh, "original")
        mode = "tree" if lane == "T" else "plain"
        prev = None
        for phase, state in c.STATES.items():
            s.state(root, "e2e", state)
            before = sources(root, study, state)
            folder = out / lane / phase
            folder.parent.mkdir(exist_ok=True)
            c.require(
                all(topology.location(Path(p)) == physical[n] for n, p in paths.items()),
                "native selectors changed",
            )
            sampled = perf is not None and lane == "T" and phase in ("edited", "restored")
            if sampled:
                raw = sampling.record(folder, tools, paths, c.CLI, root / "ruff", s.env(root), perf)
            else:
                raw = pmu.record(folder, tools, mode, paths, c.CLI, root / "ruff", s.env(root))
            inventory, products = c.typed(raw, root)
            c.require(
                inventory == names and products == first_products,
                "different graph or physical output path",
            )
            changed = phase in ("edited", "restored")
            callback = partial(c.classify, root, products, changed)
            counted = topology.read(folder / "trace", physical, mode, component=callback)
            if mode == "tree":
                c.activation_boundaries(folder / "trace", counted)
            inputs.save(folder / "counts.json", counted)
            # Everything below is outside the command and kernel PMU lifetime on each lane.
            if sampled:
                sampling.summarize(folder, counted, perf)
            if f"{lane}/{phase}" in heavy.STATES:
                heavy.capture(root, folder, products, out / "heavy-cas")
            actual = study.observe.native_reader(root, f"{lane}/{phase}", Path(products["e2e"]), state)
            check_program({"status": 0, "issues": [], "test": actual}, state)
            inputs.save(folder / "program.json", actual)
            snap = inputs.collect(root, products, folder / "work-products.json.gz", cas)
            if lane == "T":
                inputs.header_witnesses(raw, root, folder / "workspace-headers.json.gz", cas)
            if prev is not None:
                comparisons[lane + "/" + phase] = inputs.compare(prev, snap, changed)
            prev = snap
            history[lane + "/" + phase] = {
                "state": state,
                "whole": counted["whole"],
                "eight_inclusive": counted.get("eight_inclusive"),
                "sha256": actual["elf"]["sha256"],
            }
            c.require(before == sources(root, study, state), "working source changed during the visit")
            inputs.save(folder / "source.json", before)
        if lane == "T":
            errors["populated"] = bad_input(root, "invalid/populated", False, study)
            repaired = study.panel.visit(root, study.PANEL, "repair", "populated", "original", stamp)
            check_program(repaired, "original")
            history["repair/populated"] = {
                "state": "original",
                "sha256": repaired["test"]["elf"]["sha256"],
            }
    for state in ("reversed", "original"):
        s.fresh(root, registry=True)
        row = study.panel.visit(root, study.PANEL, "clean", state, state, stamp)
        references[state] = check_program(row, state)
        folder = out / "clean" / state
        graph, clean_products = c.typed(gzip.decompress((folder / "stdout.jsonl.gz").read_bytes()), root)
        c.require(graph == names and clean_products == first_products, "clean product identities changed")
        heavy.capture(root, folder, clean_products, out / "heavy-cas")
    errors["empty"] = bad_input(root, "invalid/empty", True, study)
    c.require(errors["empty"] == errors["populated"], "independent invalid diagnostic differs")
    repaired = study.panel.visit(root, study.PANEL, "repair", "empty", "original", stamp)
    check_program(repaired, "original")
    history["repair/empty"] = {"state": "original", "sha256": repaired["test"]["elf"]["sha256"]}
    issues = []
    for key, row in history.items():
        program = (
            inputs.load(out / key / "program.json")
            if not key.startswith("repair/")
            else inputs.load(out / key / "visit.json")["test"]
        )
        if not compare_oracle(program, references[row["state"]]):
            issues.append(key)
    c.require(
        set(references["original"]["names"]) - set(references["reversed"]["names"])
        == {"notebook::cells_after_cell_magic"}
        and not (set(references["reversed"]["names"]) - set(references["original"]["names"]))
        and references["original"]["elf"]["sha256"] != references["reversed"]["elf"]["sha256"],
        "ineffective historical edit",
    )
    preserve_vault(root)
    inputs.save(
        out / "semantics.json",
        {
            "historical": history,
            "edges": comparisons,
            "clean": {k: v["elf"] for k, v in references.items()},
            "invalid": errors,
            "behavior_failures": issues,
        },
    )
    c.require(not issues, (issues, "native images or verdicts differ from empty controls"))
    inputs.save(out / "heavy-result.json", heavy.reopen(out))
    result = {}
    for key in ("edited", "restored"):
        tsp = history["T/" + key]
        result[key] = c.ceiling(
            tsp["whole"],
            history["S1/" + key]["whole"],
            history["S2/" + key]["whole"],
            tsp["eight_inclusive"],
        )
    verdict = (
        "below-2x"
        if any(v["outcome"] == "below-2x" for v in result.values())
        else "room-for-investigation"
        if all(v["outcome"] == "room-for-investigation" for v in result.values())
        else "unresolved"
    )
    inputs.save(
        out / "result.json",
        {
            "baseline_instruction_ceiling": result,
            "diagnostic_verdict": verdict,
            "boot": boot,
            "product_speedup": None,
        },
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("workspace", "incoming", "root"):
        parser.add_argument("--" + key, type=Path, required=True)
    args = parser.parse_args()
    try:
        run_all(args.workspace, args.incoming, args.root)
    except Exception as e:
        if (args.root / "receipts").is_dir():
            inputs.save(
                args.root / "receipts/refusal.json",
                {"error": repr(e), "traceback": traceback.format_exc(), "qualified": False},
            )
            preserve_vault(args.root)
        raise
