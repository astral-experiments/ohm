"""Measure identical, complete Cargo histories with the packed cache disabled and enabled."""

import json
import os
import shutil
import subprocess
import sys
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
PILOT = HERE.parent / "branch-return-pmu"
sys.path.insert(0, str(PILOT))
import worker
from bindings import OUT, ROOT, WORK, need, save, sha
from extra_provider import exercise

b = worker.b
PLAN = "4b3674feca534b2622cb4c33efdbd2f778099573f1cf964a96fad69697f0a7b6"
BRANCH = "charlie/qa-branch-cache-three-arm-attribution-20261031"
ORDERS = {"01": ("Foff", "Fon", "Kon"), "02": ("Kon", "Fon", "Foff")}
PREVIOUS_BOOTS = {
    "78a866b0-afbc-4843-a44c-17a8d5bf8e1a",
    "efc22aa1-dd29-4916-985b-d7a54f481433",
    "0f45fd59-1c8c-4474-8ab8-e9886ad48fda",
    "12c3aea9-28c1-4831-a481-1b614286b3b4",
    "198293fe-416e-48d0-aef9-0611a36675a0",
    "27b66717-98d6-4021-8c18-fbf15299251f",
    "3060b886-0ac1-46a3-a1c1-a3c34b9073b6",
    "30cd5b79-aac9-4ce4-b006-c3bf6d60734c",
    "3b0e4081-536a-4f6a-a945-674825be2329",
    "6b0543d0-2fd6-4b60-9dbd-0d90c66b9973",
    "701225ea-feee-4195-82a3-9a1f70d39c46",
    "cf938e9c-a8d2-4a0d-8260-fb5f89d89d65",
    "eb13685b-610e-43dd-a65e-72a6b88482f1",
}


def compare_clean(refs):
    for branch in ("A", "B"):
        reference = refs["Foff", branch]
        for arm in ("Fon", "Kon"):
            other = refs[arm, branch]
            need(
                reference["typed"] == other["typed"]
                and reference["graph"] == other["graph"],
                ("clean typed graph", arm, branch),
            )
            need(
                worker.same_products(reference["products"], other["products"]),
                ("clean behavior", arm, branch),
            )
            for binary in ("cli", "reader"):
                for key in ("executable", "loads"):
                    need(
                        reference["products"][binary][key]
                        == other["products"][binary][key],
                        ("clean ELF", arm, branch, binary, key),
                    )


def compare_histories(records):
    for phase, _ in worker.PHASES:
        for arm in ORDERS["01"]:
            ordinary, measured = (
                records[lane, arm][phase] for lane in ("ordinary", "measured")
            )
            need(
                {
                    k: v
                    for k, v in ordinary.items()
                    if k not in ("instructions", "allocated")
                }
                == {
                    k: v
                    for k, v in measured.items()
                    if k not in ("instructions", "allocated")
                },
                ("ordinary/metered behavior", arm, phase),
            )
            need(
                ordinary["instructions"] is None and measured["instructions"] > 0,
                ("only the calibrated command can carry counts", arm, phase),
            )
        rows = [records["ordinary", arm][phase] for arm in ORDERS["01"]]
        for key in ("source", "status", "graph", "dirty_digest"):
            need(
                all(row.get(key) == rows[0].get(key) for row in rows),
                ("matched arms", phase, key),
            )


def main(position, source, calibrator, observers, provider):
    order = ORDERS[position]
    head = os.environ["GITHUB_SHA"]
    need(
        os.environ["GITHUB_REPOSITORY"] == b.REPO
        and os.environ["GITHUB_REF"] == "refs/heads/" + BRANCH
        and os.environ["GITHUB_RUN_ATTEMPT"] == "1"
        and head == os.environ["REVIEWED_HEAD"] == b.git(HERE, "rev-parse", "HEAD")
        and sha(HERE / "ATTRIBUTION.md") == PLAN,
        "attribution identity",
    )
    trees = b.git(
        HERE,
        "rev-parse",
        "HEAD:scripts/branch-return-pmu",
        "HEAD:scripts/ohm-packed-ruff",
    )
    need(
        trees.splitlines()
        == [
            "8036cb549845a905ab83882f5b01766229e0e636",
            "d9fd6c8e4152d468a3a40d600ee1c6ebda13e5f2",
        ],
        "historical readers",
    )
    oracle = json.loads((PILOT / "historical-sources.json").read_bytes())
    need(
        all(
            sha(HERE.parents[1] / name) == wanted
            for name, wanted in oracle["files"].items()
        ),
        "missing historical source or reader",
    )
    need(
        ROOT.resolve() == ROOT
        and (WORK / ".owned-by-packed-study").read_text() == str(ROOT)
        and shutil.disk_usage(OUT).free >= 32 * 2**30,
        "fresh runner capacity",
    )
    for name in ("clean", "ordinary", "measured", "providers", "initial"):
        (OUT / name).mkdir()
    shutil.copy2(HERE / "ATTRIBUTION.md", OUT / "PLAN.md")
    shutil.copy2(b.RUNTIME, OUT / "source-kit.json")
    worker.link_diagnostic.acquire()
    subprocess.run(
        [sys.executable, "-IB", PILOT / "meter.py", calibrator, observers], check=True
    )
    ready = json.loads((OUT / "meter-ready.json").read_bytes())
    os.sched_setaffinity(0, ready["affinity"])
    need(
        ready["boot"] not in PREVIOUS_BOOTS
        and sorted(os.sched_getaffinity(0)) == ready["affinity"],
        "reused boot or wrong affinity",
    )
    save(
        OUT / "enrollment.json",
        dict(
            position=position,
            order=order,
            head=head,
            attempt=1,
            boot=ready["boot"],
            run=int(os.environ["GITHUB_RUN_ID"]),
            runner=os.environ["RUNNER_NAME"],
            source=b.spec(),
            plan=PLAN,
            command=worker.CARGO,
        ),
    )
    registry = b.acquire(source)
    env = b.activate(order[0], registry, OUT / "initial")
    b.fresh_outputs()
    b.prepare_inputs(worker.kit, env)
    worker.historical.calibration()
    refs = {}
    for arm in order:
        worker.install(arm, "clean", registry, refs, OUT / "clean" / arm)
    compare_clean(refs)
    exercise(registry, provider, order)
    records = {}
    for lane in ("ordinary", "measured"):
        for arm in order:
            records[lane, arm] = worker.install(
                arm, lane, registry, refs, OUT / lane / arm
            )
    compare_histories(records)
    archives = {
        p.name: sha(p) for p in (b.HOME / ".cargo/registry/cache").glob("*/*.crate")
    }
    need(
        len(archives) == 505
        and archives == json.loads((OUT / "ruff-inputs.json").read_bytes())["archives"],
        "changed Ruff registry",
    )
    for role, expected in registry.items():
        path = b.PARK / role
        need(
            b.inventory(path if path.exists() else b.SDK) == expected,
            ("changed SDK", role),
        )
    save(
        OUT / "sdk" / "terminal.json",
        dict(
            both_complete_byte_and_inode_inventories_unchanged=True,
            registry=worker.historical.commit(archives),
        ),
    )
    save(
        OUT / "complete.json",
        dict(
            host_complete=True,
            arms=order,
            phases=[p for p, _ in worker.PHASES],
            raw_counts_unscaled=True,
            requires_independent_cross_host_replay=True,
        ),
    )


if __name__ == "__main__":
    try:
        main(sys.argv[1], *map(Path, sys.argv[2:]))
    except BaseException:
        if OUT.exists():
            (OUT / "failure.txt").write_text(traceback.format_exc())
        raise
